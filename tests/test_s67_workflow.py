"""S67 the ongoing-records workflow is one recoverable thing: mail ingestion is idempotent and survives a failing message, a gap is explicit and
counted, a question about a difference closes itself when the difference is gone, readiness reads the stores (so it resumes after a missing step
is done), and market history fills itself in bounded steps that can be stopped anywhere. Synthetic; fakes at the boundaries; no network."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from pflab.agents import tradecheck as tc
from pflab.app import inbox as ib
from pflab.app import readiness as rd
from pflab.app import runtime, system
from pflab.ingest import gmail, sniff
from pflab.ledger.events import Event, EventLog, save
from pflab.pm import store
from tests.test_s65_gmail import FakeGmail, LEDGER, TRADEBOOK  # noqa: F401

NOW = datetime(2026, 11, 4, 21, 0)
AAA = "INE000A01011"


@pytest.fixture
def rt(tmp_path, monkeypatch):
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(ib, "_start", lambda rt, iid: None)
    monkeypatch.setattr(sniff, "passwords_from_secrets", lambda: [])
    monkeypatch.setattr(system, "_ollama", lambda: {"up": True, "models": ["qwen3:8b-q8_0", "nomic-embed-text:latest"]})
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


MAILS = {"m1": (("Console", "Mon"), [("tb.csv", TRADEBOOK, False)]), "m2": (("bank", "Tue"), [("ledger.xlsx", LEDGER, False)]),
         "m3": (("Console", "Wed"), [("tb2.csv", TRADEBOOK + b"DEF,INE1,2026-10-28,buy,2,3,4\n", False)])}


def test_repeat_input_creates_no_duplicates_and_a_new_message_adds_only_itself(rt):
    g = FakeGmail(dict(list(MAILS.items())[:2]))
    a = gmail.fetch(rt, g, now=NOW)
    assert a["kept"] == 2 and a["errors"] == 0
    g2 = FakeGmail(dict(MAILS))
    b = gmail.fetch(rt, g2, now=NOW)
    assert b["messages"] == 1 and b["kept"] == 1                                 # only the new one; the first two were seen
    again = gmail.fetch(rt, FakeGmail(dict(MAILS)), now=NOW)
    assert again["messages"] == 0
    con = rt.cursor()
    assert con.execute("SELECT count(*) FROM inbox_items").fetchone()[0] == 3
    assert con.execute("SELECT count(*) - count(DISTINCT sha) FROM inbox_items").fetchone()[0] == 0     # no file twice
    # the same attachment arriving in a second message is the same file, not a second one
    dup = FakeGmail({"m9": (("Console", "Thu"), [("tb-copy.csv", TRADEBOOK, False)])})
    gmail.fetch(rt, dup, now=NOW)
    assert con.execute("SELECT count(*) FROM inbox_items").fetchone()[0] == 3


def test_a_message_that_cannot_be_stored_is_a_counted_gap_and_the_others_still_arrive(rt, monkeypatch):
    real = ib.receive

    def flaky(rt_, name, data, *a, **k):
        if name == "ledger.xlsx":
            raise OSError("disk is full")
        return real(rt_, name, data, *a, **k)
    monkeypatch.setattr(ib, "receive", flaky)
    g = FakeGmail(dict(MAILS))
    out = gmail.fetch(rt, g, now=NOW)
    assert out["errors"] == 1 and out["kept"] == 2                               # m1 and m3 arrived; m2 did not stop them
    con = rt.cursor()
    assert [x["key"] for x in rd.gaps(con, "mail")] == ["mail:msg:m2"] and "disk is full" in rd.gaps(con)[0]["detail"]
    assert con.execute("SELECT count(*) FROM mail_seen WHERE msg_id='m2'").fetchone()[0] == 0     # not marked seen: it is retried
    monkeypatch.setattr(ib, "receive", real)                                      # the disk has room again
    out = gmail.fetch(rt, g, now=NOW)
    assert out["kept"] == 1 and out["errors"] == 0 and rd.gaps(con, "mail") == []   # the retry stored it and closed the gap
    monkeypatch.setattr(ib, "receive", flaky)
    g4 = FakeGmail({"m4": (("bank", "Fri"), [("ledger.xlsx", LEDGER + b"x", False)])})
    for _ in range(rd.GAP_TRIES + 2):
        gmail.fetch(rt, g4, now=NOW)
    gp = rd.gaps(con, "mail")
    assert gp and gp[0]["attempts"] == rd.GAP_TRIES                              # three tries, then left visible and no longer retried


def test_a_failing_fetch_listing_fails_the_mail_job_not_silently(rt, monkeypatch):
    class Down(FakeGmail):
        def get(self, url, params=None, timeout=None):
            return SimpleNamespace(status_code=401, json=lambda: {})
    with pytest.raises(gmail.MailError, match="401"):
        gmail.fetch(rt, Down({}), now=NOW)


# --- questions about differences close themselves ----------------------------------------------------------------------------------------------

def _store_with_ledger(tmp_path):
    con = store.connect(tmp_path / "t.duckdb")
    con.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha (synthetic)')")
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                   VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, 'AAA', 'Aaa Limited', 'synthetic', now())""", [AAA])
    save(con, EventLog([Event("deposit", "ZER", date(2026, 10, 1), amount=100_000.0),
                        Event("buy", "ZER", date(2026, 10, 1), isin=AAA, qty=10, price=100.0, ref="T1")]))
    return con


def test_a_question_about_a_holding_difference_closes_when_the_difference_is_gone_and_is_not_asked_twice(tmp_path):
    from tests.test_agents_s43 import FakeKite
    con = _store_with_ledger(tmp_path)
    r1 = tc.check(con, FakeKite(holdings=12.0, cash=99_000.0), date(2026, 10, 17), now=NOW)
    r1b = tc.check(con, FakeKite(holdings=12.0, cash=99_000.0), date(2026, 10, 17), now=NOW)
    assert len(r1.asked) == 1 and r1b.asked == []                                # asked once
    assert con.execute("SELECT count(*) FROM questions WHERE status='open' AND subject_key LIKE 'holding:%'").fetchone()[0] == 1
    tc.check(con, FakeKite(holdings=10.0, cash=99_000.0), date(2026, 10, 18), now=NOW + timedelta(days=1))   # the statement came: they agree
    assert con.execute("SELECT count(*) FROM questions WHERE status='open' AND subject_key LIKE 'holding:%'").fetchone()[0] == 0
    tc.check(con, FakeKite(holdings=13.0, cash=99_000.0), date(2026, 10, 19), now=NOW + timedelta(days=2))   # a new difference: one question
    tc.check(con, FakeKite(holdings=14.0, cash=99_000.0), date(2026, 10, 20), now=NOW + timedelta(days=3))   # it grew: the old one is replaced
    assert con.execute("SELECT count(*) FROM questions WHERE status='open' AND subject_key LIKE 'holding:%'").fetchone()[0] == 1


# --- readiness reads the stores ---------------------------------------------------------------------------------------------------------------------

def test_readiness_reflects_reconciled_coverage_and_resumes_after_a_missing_step(rt, monkeypatch):
    con = rt.cursor()
    r = rd.assess(rt, NOW)
    st = {s["key"]: s for s in r["stages"]}
    assert not r["ready"] and st["record"]["state"] == rd.TODO and st["reconciled"]["state"] == rd.TODO and st["history"]["state"] == rd.TODO
    assert any("Drop your statements" in t for t in r["remaining"])
    con.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha')")
    save(con, EventLog([Event("deposit", "ZER", date(2026, 10, 1), amount=1000.0)]))
    st = {s["key"]: s for s in rd.assess(rt, NOW)["stages"]}
    assert st["record"]["state"] == rd.PARTIAL and any("Approve the accounts" in t for t in st["record"]["todo"])
    (rt.pm_dir / "sources.toml").write_text("[sources]\n", encoding="utf-8")                  # the missing step is done
    con.execute("INSERT INTO questions (q_id, created_at, agent, subject_key, text, status) VALUES (1, ?, 'mail', 'mail:locked:NSDL', 't', 'open')", [NOW])
    st = {s["key"]: s for s in rd.assess(rt, NOW)["stages"]}
    assert st["record"]["state"] == rd.PARTIAL and "password" in st["record"]["todo"][0]
    con.execute("UPDATE questions SET status='dropped' WHERE q_id=1")
    assert {s["key"]: s for s in rd.assess(rt, NOW)["stages"]}["record"]["state"] == rd.DONE
    # a successful job run is not the same as reconciled: breaks in the latest successful check keep it partial
    con.execute("INSERT INTO kite_snapshots (snap_id, taken_at, account_id, kind, amount) VALUES (1, ?, 'ZER', 'cash', 1)", [NOW - timedelta(hours=1)])
    con.execute("INSERT INTO job_runs (run_id, job, started_at, finished_at, status, detail) VALUES (1, 'tradecheck', ?, ?, 'ok', ?)",
                [NOW - timedelta(minutes=30), NOW, json.dumps({"breaks": 2, "pending": 1, "asked": 2})])
    s = {s["key"]: s for s in rd.assess(rt, NOW)["stages"]}["reconciled"]
    assert s["state"] == rd.PARTIAL and "2 holding(s) differ" in s["todo"][0] and "1 Kite trade(s)" in s["todo"][1]
    con.execute("INSERT INTO job_runs (run_id, job, started_at, finished_at, status, detail) VALUES (2, 'tradecheck', ?, ?, 'ok', ?)",
                [NOW - timedelta(minutes=10), NOW, json.dumps({"breaks": 0, "pending": 0, "asked": 0})])
    assert {s["key"]: s for s in rd.assess(rt, NOW)["stages"]}["reconciled"]["state"] == rd.DONE


def test_sync_gaps_opens_and_closes_the_stage_gaps_without_duplicates(rt):
    rd.sync_gaps(rt, NOW)
    rd.sync_gaps(rt, NOW)
    keys = [g["key"] for g in rd.gaps(rt.cursor(), "readiness")]
    assert "stage:record" in keys and len(keys) == len(set(keys))
    rt.cursor().execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha')")
    save(rt.cursor(), EventLog([Event("deposit", "ZER", date(2026, 10, 1), amount=1000.0)]))
    (rt.pm_dir / "sources.toml").write_text("[sources]\n", encoding="utf-8")
    rd.sync_gaps(rt, NOW)
    assert "stage:record" not in [g["key"] for g in rd.gaps(rt.cursor(), "readiness")]


# --- history that fills itself ----------------------------------------------------------------------------------------------------------------------

def _fake_fetch(root: Path, holidays=(), fail=()):
    calls = []

    def fetch(d, session, root_):
        calls.append(d)
        if d in fail:
            raise ConnectionError("reset by peer")
        p = Path(root_) / "bhavcopy" / str(d.year) / f"{d.isoformat()}.parquet"
        if d in holidays:                                                          # NSE answered 404: a logged holiday, not a hole
            (Path(root_) / "bhavcopy").mkdir(parents=True, exist_ok=True)
            with open(Path(root_) / "bhavcopy" / "_log.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"date": d.isoformat(), "status": "no-file"}) + "\n")
            return None
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p
    fetch.calls = calls
    return fetch


class Ticker:
    """A clock that advances by `step` each time it is read: a budget runs out after a known number of reads."""
    def __init__(self, step=1.0):
        self.t, self.step = 0.0, step

    def __call__(self):
        self.t += self.step
        return self.t


def test_backfill_fills_holes_newest_first_in_bounded_steps_and_resumes(tmp_path):
    root = tmp_path / "data"
    start, end = date(2026, 10, 1), date(2026, 10, 30)                             # 22 weekdays
    before = rd.bhavcopy_holes(root, start, end)
    assert before["have"] == 0 and len(before["holes"]) == 22
    fetch = _fake_fetch(root, holidays={date(2026, 10, 2)})
    first = rd.backfill_step(root, NOW, start=start, end=end, budget_s=8, fetch=fetch, sleep=0, clock=Ticker(), session=object())
    assert first["fetched"] > 0 and not first["done"] and first["left"] > 0
    assert fetch.calls[0] == date(2026, 10, 30) and fetch.calls == sorted(fetch.calls, reverse=True)      # newest first
    second = rd.backfill_step(root, NOW, start=start, end=end, budget_s=1000, fetch=fetch, sleep=0, clock=Ticker(), session=object())
    assert second["done"] and second["left"] == 0
    after = rd.bhavcopy_holes(root, start, end)
    assert after["holes"] == [] and after["have"] == 21                              # the logged holiday is not a hole
    assert rd.backfill_step(root, NOW, start=start, end=end, fetch=fetch, sleep=0, session=object())["done"]


def test_a_source_that_is_down_stops_the_step_and_the_job_fails_visibly(tmp_path):
    root = tmp_path / "data"
    start, end = date(2026, 10, 1), date(2026, 10, 30)
    days = rd.bhavcopy_holes(root, start, end)["holes"]
    fetch = _fake_fetch(root, fail=set(days))
    out = rd.backfill_step(root, NOW, start=start, end=end, budget_s=1000, fetch=fetch, sleep=0, clock=Ticker(0.001), session=object())
    assert out["fetched"] == 0 and out["errors"] == 5 and not out["done"] and "reset by peer" in out["last_error"]
    assert len(fetch.calls) == 5                                                   # it did not hammer a source that is down


def test_the_backfill_job_is_enabled_only_while_there_are_holes_and_its_failure_is_the_jobs(tmp_path, monkeypatch, rt):
    from pflab.service import jobs, tasks
    ctx = jobs.Ctx(rt.cursor(), NOW, rt.pm_dir, rt.data_root, rt.repo, "python", None)
    rt.data_root.mkdir(parents=True, exist_ok=True)
    assert tasks._backfill_enabled(ctx)[0] is True                                   # no history yet: holes
    monkeypatch.setattr(rd, "bhavcopy_holes", lambda *a, **k: {"holes": [], "have": 5})
    assert tasks._backfill_enabled(ctx) == (False, "market history has no holes")
    monkeypatch.setattr(rd, "backfill_step", lambda root, now: {"fetched": 0, "left": 9, "errors": 3, "last_error": "ConnectionError: reset", "done": False})
    monkeypatch.setattr(rd, "sync_gaps", lambda r, n: {"open": 2, "ready": False})
    res = jobs.run_job(ctx, jobs.REGISTRY["backfill"]) if tasks._backfill_enabled(ctx)[0] else None
    monkeypatch.setattr(rd, "bhavcopy_holes", lambda *a, **k: {"holes": [1], "have": 5})
    res = jobs.run_job(ctx, jobs.REGISTRY["backfill"])
    assert res.status == "failed" and "reset" in res.detail
