"""S67 local: the fresh start archives the old profile as opaque bytes, verifies it, begins a new EMPTY profile that waits for the icon,
keeps only the test counter and a reduced spend record, and restores only into a separate folder. Synthetic folders; no real data."""
from __future__ import annotations

import json
from datetime import date, datetime

import duckdb
import pytest

from pflab import activation
from pflab.pm import fresh, store

TODAY = date(2026, 10, 29)
CANARY = "PORTFOLIO-CANARY-12345"


@pytest.fixture
def old(tmp_path):
    pm = tmp_path / "app" / "pm"
    pm.mkdir(parents=True)
    con = store.connect(pm / "ledger.duckdb")
    con.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha (synthetic)')")
    con.execute("INSERT INTO learn_tests (test_id, ran_at, family, origin, template, passed, note) VALUES (1, now(), 'fam', 'seed', 't', FALSE, 'n')")
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, question, request_sha, request_json, status, cost_inr) "
                f"VALUES (1, now(), 'live', 'm', 'q about {CANARY}', 'sha', '{CANARY} holdings', 'done', 42.5)")
    con.close()
    (pm / "notes").mkdir()
    (pm / "notes" / "decision_PAN1234.txt").write_text("his decision", encoding="utf-8")
    stm = tmp_path / "app" / "statements"
    stm.mkdir()
    (stm / "account_987654321.pdf").write_bytes(b"%PDF opaque statement bytes")
    return pm, stm, tmp_path / "archives"


def test_nothing_changes_without_the_confirmation_word(old):
    pm, stm, arch = old
    r = fresh.fresh(pm, arch, TODAY)
    assert r["done"] is False and "--confirm" in r["note"] and (pm / "ledger.duckdb").exists() and not arch.exists()


def test_the_old_profile_is_archived_verified_and_moved_and_the_new_one_is_empty_and_dormant(old):
    pm, stm, arch = old
    r = fresh.fresh(pm, arch, TODAY, confirm=fresh.CONFIRM, extra={"statements": stm})
    assert r["done"] and r["verified"] >= 3 and fresh.verify_archive(r["archive"])["ok"]
    assert pm.exists() and (pm / "ledger.duckdb").exists() and "profile_20261029" in r["archive"]
    new = duckdb.connect(str(pm / "ledger.duckdb"), read_only=True)
    for t in ("accounts", "events", "instruments", "prices", "hq_cases", "hq_suggestions", "kg_docs", "known_gaps"):
        assert new.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0, t               # no personal or company state carried
    assert new.execute("SELECT count(*) FROM learn_tests").fetchone()[0] == 1                 # the counter survives: no spent test is reopened
    assert new.execute("SELECT cost_inr FROM api_calls").fetchall() == [(42.5,)]               # and so does what was spent
    assert CANARY not in str(new.execute("SELECT * FROM api_calls").fetchall())        # but not what was asked
    new.close()
    assert activation.is_pending(pm) and not (pm / "notes").exists()
    assert (r["moved_to"] and (fresh.Path(r["moved_to"]) / "notes" / "decision_PAN1234.txt").exists())   # the old one is moved aside, not deleted


def test_the_manifest_holds_hashes_and_sizes_but_no_file_names(old):
    pm, stm, arch = old
    r = fresh.fresh(pm, arch, TODAY, confirm=fresh.CONFIRM, extra={"statements": stm})
    text = open(r["manifest"], encoding="utf-8").read()
    assert "987654321" not in text and "PAN1234" not in text and "sha256" in text
    assert json.loads(text)["folders"]["statements"]["files"] == 1


def test_restore_goes_only_into_an_empty_separate_folder_and_a_damaged_archive_is_refused(old, tmp_path):
    pm, stm, arch = old
    r = fresh.fresh(pm, arch, TODAY, confirm=fresh.CONFIRM, extra={"statements": stm})
    out = tmp_path / "restored"
    res = fresh.restore(r["archive"], out)
    assert res["restored"] >= 3 and (out / "notes" / "decision_PAN1234.txt").read_text(encoding="utf-8") == "his decision"
    with pytest.raises(FileExistsError):
        fresh.restore(r["archive"], out)                                                       # never over something
    victim = next((fresh.Path(r["archive"]) / "statements").iterdir())
    victim.write_bytes(b"tampered")
    assert fresh.verify_archive(r["archive"])["ok"] is False
    with pytest.raises(RuntimeError):
        fresh.restore(r["archive"], tmp_path / "again")


def test_an_archive_inside_the_profile_is_refused_and_an_existing_archive_is_never_overwritten(old, tmp_path):
    pm, stm, arch = old
    with pytest.raises(ValueError):
        fresh.archive(pm, pm / "inside")
    first = fresh.archive(pm, tmp_path / "a1")
    assert first["folders"]["pm"]["files"] >= 2
    with pytest.raises(FileExistsError):
        fresh.archive(pm, tmp_path / "a1")


def test_a_failed_archive_leaves_the_old_profile_where_it_was(old, monkeypatch):
    pm, stm, arch = old
    monkeypatch.setattr(fresh, "verify_archive", lambda d: {"ok": False, "files": 0, "problems": ["x"]})
    with pytest.raises(RuntimeError):
        fresh.fresh(pm, arch, TODAY, confirm=fresh.CONFIRM)
    assert (pm / "ledger.duckdb").exists() and not activation.path(pm).exists()
