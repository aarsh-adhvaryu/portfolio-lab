"""S67 release safety: a new version's migrations are rehearsed on a COPY before they touch his store; a rollback keeps every row written
after the upgrade (events, journal, questions, memory), table by table, over the columns both versions know; the live store is never half
migrated. A temporary git repository and temporary DuckDB files; no network."""
from __future__ import annotations

import subprocess
from datetime import date, datetime
from pathlib import Path

import duckdb
import pytest

from pflab import release, update as up
from pflab.ledger.events import Event, EventLog, save
from pflab.pm import store

from tests.test_s65_update import SimpleNS, g, ok_install, publish  # noqa: F401

NOW = datetime(2026, 10, 29, 9, 0, 0)


def _old_store(path: Path):
    """A store at schema v42 with real tables and rows (the migrations before 43), as the installed app has it."""
    old = [m for m in store.MIGRATIONS if m[0] <= 42]
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    store.migrate(con, old)
    con.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha (synthetic)')")
    save(con, EventLog([Event("deposit", "ZER", date(2026, 10, 1), amount=1000.0), Event("buy", "ZER", date(2026, 10, 2), isin="INE000A01011", qty=1, price=10.0, ref="T1")]))
    con.execute("INSERT INTO questions VALUES (1, ?, 'x', 'k1', 'q', 'open', NULL, NULL)", [NOW])
    con.close()


def test_the_new_migrations_run_on_a_copy_and_no_table_loses_a_row(tmp_path):
    live = tmp_path / "pm" / "ledger.duckdb"
    _old_store(live)
    before = up._row_counts(live)
    copy = tmp_path / "copy.duckdb"
    copy.write_bytes(live.read_bytes())
    r = up.rehearse(copy)
    assert r["version"] == max(m[0] for m in store.MIGRATIONS) and r["lost"] == {}
    assert up._row_counts(live) == before                                                    # the live store was not opened for writing
    con = duckdb.connect(str(live), read_only=True)
    assert con.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 42      # still the old schema
    con.close()
    assert "hq_cases" in up._row_counts(copy)                                                # the copy has the new tables


def test_a_migration_that_fails_on_the_copy_stops_the_update_before_the_live_store_is_touched(tmp_path, monkeypatch):
    live = tmp_path / "pm" / "ledger.duckdb"
    _old_store(live)
    stamp = live.stat().st_mtime_ns
    calls = []

    def run(cmd, cwd):
        calls.append(cmd)
        if cmd[-3:-1] == ["pflab.update", "rehearse"]:
            return 1, "Parser Error: syntax error in migration 44"
        return 0, ""
    ok, msg = up.default_selftest(tmp_path, run, tmp_path / "pm")
    assert not ok and "migration 44" in msg
    assert live.stat().st_mtime_ns == stamp and not any(c[-2:] == ["pm", "init"] for c in calls)      # no `pm init` on the real store
    ok, msg = up.default_selftest(tmp_path, lambda cmd, cwd: (1, "ImportError: no module named x"), tmp_path / "pm")
    assert not ok and "does not start" in msg


def test_rollback_keeps_the_events_and_notes_written_after_the_upgrade(tmp_path):
    origin, work, folder = tmp_path / "origin.git", tmp_path / "work", tmp_path / "PortfolioLabApp"
    g(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    g(tmp_path, "clone", "-q", str(origin), str(work))
    g(work, "checkout", "-q", "-b", "main")
    (work / ".gitignore").write_text("release.toml\n", encoding="utf-8")
    publish(work, "one", "v2026.10.01")
    app = folder / "app"
    folder.mkdir()
    g(folder, "clone", "-q", str(origin), str(app))
    g(app, "checkout", "-q", "--detach", "v2026.10.01")
    release.write(app, folder, "v2026.10.01")
    pm = folder / "pm"
    _old_store(pm / "ledger.duckdb")
    publish(work, "two", "v2026.10.15")
    r = up.update(app, pm, install=ok_install, selftest=lambda root: (True, "ok"), now=NOW)
    assert r["updated"]
    # the app runs on the new version: it migrates the live store and records new things
    con = store.connect(pm / "ledger.duckdb")
    # a ledger rebuild: an earlier-dated statement arrives, so every id shifts, and one event is new
    con.execute("DELETE FROM events")
    save(con, EventLog([Event("deposit", "ZER", date(2026, 9, 30), amount=500.0), Event("deposit", "ZER", date(2026, 10, 1), amount=1000.0),
                        Event("buy", "ZER", date(2026, 10, 2), isin="INE000A01011", qty=1, price=10.0, ref="T1"),
                        Event("buy", "ZER", date(2026, 10, 20), isin="INE000A01011", qty=2, price=11.0, ref="T2")]))
    con.execute("INSERT INTO questions VALUES (2, ?, 'x', 'k2', 'asked after the upgrade', 'open', NULL, NULL)", [NOW])
    con.execute("UPDATE questions SET status='answered', answer='yes' WHERE q_id=1")           # an old row changed: the backup's version stands
    con.execute("INSERT INTO hq_cases (case_id, subject_key, opened_at, updated_at, origin, question, status, attempts, max_attempts, steps) "
                "VALUES (1, 'k', ?, ?, 'code', 'new table', 'queued', 0, 3, 0)", [NOW, NOW])
    con.close()
    rb = up.rollback(app, pm, install=ok_install, now=datetime(2026, 10, 30, 8, 0, 0))
    assert rb["to"] == "v2026.10.01" and rb["merged"]["added"].get("events") == 2 and rb["merged"]["added"].get("questions") == 1
    assert "hq_cases" in rb["merged"]["only_in_kept"] and "hq_cases" in rb["note"]
    live = duckdb.connect(str(pm / "ledger.duckdb"), read_only=True)
    assert live.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 42
    assert live.execute("SELECT count(*) FROM events").fetchone()[0] == 4                        # two before, two new (ids had shifted): nothing lost, nothing doubled
    assert sorted(x[0] for x in live.execute("SELECT ref FROM events WHERE ref <> ''").fetchall()) == ["T1", "T2"]
    assert live.execute("SELECT count(DISTINCT event_id) FROM events").fetchone()[0] == 4
    assert sorted(x[0] for x in live.execute("SELECT subject_key FROM questions").fetchall()) == ["k1", "k2"]
    live.close()
    kept = duckdb.connect(rb["kept"], read_only=True)
    assert kept.execute("SELECT count(*) FROM hq_cases").fetchone()[0] == 1                      # the table the old version lacks is in the kept copy
    kept.close()
    # rolling back and merging again adds nothing twice
    live = duckdb.connect(str(pm / "ledger.duckdb"))
    again = up.merge_new_rows(Path(rb["kept"]), pm / "ledger.duckdb")
    assert again["rows"] == 0
    live.close()
