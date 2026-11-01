"""S68 P5: with no chat message, a new material filing on a held name and a due review each start or resume an investigation that leaves artifacts; the
reason it was chosen and what would justify revisiting are kept; an unchanged signal is not adopted twice; a day's starts are bounded; Pause stops it.
A scripted model stands in for the API (development test); synthetic data only."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from pflab.agents import analyst as an
from pflab.app import assistant, chat
from pflab.hq import board, cases, egress, governor as gv, missions, roster, service
from pflab.hq.desk import Desk
from pflab.pm import store
from tests.test_s68_missions import Model, PLAN, _fake_calc, _happy_scripts, _say, _use

NOW = datetime(2026, 10, 31, 15, 0)
AAA = "INE000A01011"
CFG = {"model": an.MODEL, "cap": 2500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True, "tijori_to_analyst": True}
REPRO = {"reproduced": True, "basis": "original", "label": "x", "same_as_kept": True, "differences": [], "problems": [], "result": {}, "kept": {}}


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    c.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                 VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, 'AAA', 'AAA Limited', 'synthetic', now())""", [AAA])
    return c


@pytest.fixture
def rt(con, tmp_path, monkeypatch):
    monkeypatch.setattr(an, "config", lambda: CFG)
    monkeypatch.setattr(service, "gate", lambda r: egress.Gate())
    monkeypatch.setattr(service, "names", lambda r: ([AAA], []))
    monkeypatch.setattr(cases, "reproduce", lambda *a, **k: REPRO)
    (tmp_path / "pm" / "app").mkdir(parents=True)
    return Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None, {"brain": "normal", "preset": "full", "telegram_send": False}, clock=lambda: NOW)


def _insert_reading(con, doc="D1", isin=AAA):
    cols = [r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name='hq_readings' ORDER BY ordinal_position").fetchall()]
    vals = {"doc_id": doc, "read_at": NOW - timedelta(hours=1), "material": "yes", "isins_json": json.dumps([isin]), "summary": "AAA reported a large order loss",
            "kind": "result", "model": "m", "cost_inr": 0.0, "status": "done", "facts_json": "[]", "published_at": NOW - timedelta(hours=2)}
    use = [c for c in cols if c in vals]
    con.execute(f"INSERT INTO hq_readings ({','.join(use)}) VALUES ({','.join('?' * len(use))})", [vals[c] for c in use])


def test_a_new_material_filing_on_a_held_name_starts_an_investigation_with_no_chat_message(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    _insert_reading(con)
    assert con.execute("SELECT count(*) FROM chat_messages").fetchone()[0] == 0                # nobody has said anything
    scripts = _happy_scripts()
    scripts["coordinator"][0] = _use(("plan_mission", {"case_id": 1, "steps_json": json.dumps(PLAN), "approach": "check the filing"}), model=gv.OPUS)
    rt._hq_client = Model(scripts)
    out = missions.scan(rt)
    assert out["discovered"] == 1 and len(out["started"]) == 1
    cid = out["started"][0]
    card = missions.card(con, cid)
    assert card["origin"] == "system" and "material document" in card["why_chosen"] and "revisit when" in card["why_chosen"]
    service.drive_missions(rt)
    card = missions.card(con, cid)
    assert card["state"] == "done" and {o["kind"] for o in card["outputs"]} >= {"evidence", "calc", "review", "answer"}      # it left artifacts
    told = [m["text"] for m in chat.messages(con, assistant.thread(con, NOW)) if m["mode"].startswith("note:")]
    assert any("While you were away" in t for t in told) and any("Finished" in t for t in told)


def test_an_unchanged_signal_is_not_adopted_twice_and_a_days_starts_are_bounded(rt, con, monkeypatch):
    isins = [f"INE00{k}A0101{k}" for k in range(5)]
    for k, i in enumerate(isins):                                           # five DIFFERENT companies, five signals
        con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                       VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, ?, ?, 'synthetic', now())""", [i, f"CO{k}", f"CO{k} Limited"])
        _insert_reading(con, f"D{k}", i)
    monkeypatch.setattr(service, "names", lambda r: (isins, []))
    rt._hq_client = Model({"coordinator": [], "research": [], "quant": [], "review": []})
    first = missions.scan(rt)
    assert len(first["started"]) == missions.DAILY_NEW and first["held_back"] == len(isins) - missions.DAILY_NEW   # five signals, one start a day (S70)
    again = missions.scan(rt)
    assert again["started"] == [] and con.execute("SELECT count(*) FROM hq_missions").fetchone()[0] == missions.DAILY_NEW


def test_pause_stops_the_system_choosing_work(rt, con):
    rt.settings["scheduler"] = False
    _insert_reading(con)
    out = service.round_(rt)
    assert out.get("paused") is True and con.execute("SELECT count(*) FROM hq_missions").fetchone()[0] == 0


def test_a_due_review_reopens_the_same_investigation_which_then_updates_itself(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    rt._hq_client = Model(_happy_scripts())
    out = missions.create(con, NOW, "Compare phased buying with holding cash", pm_dir=rt.pm_dir)
    service.drive_missions(rt)
    cid = out["case_id"]
    assert missions.card(con, cid)["state"] == "done"
    later = cases.get(con, cid)["next_review"] + timedelta(minutes=1)                         # the review day comes: no message from him
    rt.clock = lambda: later
    second = _happy_scripts()
    second["coordinator"] = [_use(("plan_mission", {"case_id": cid, "steps_json": json.dumps([PLAN[0]])}), model=gv.OPUS), _say("Planned.", gv.OPUS),
                             _use(("submit_answer", {"case_id": cid, "answer": "Nothing in the new evidence changes the earlier conclusion.", "limitations": "Same assumptions.",
                                                     "monitor_next": "The next review."}), model=gv.OPUS), _say("Answer written.", gv.OPUS)]
    second["research"] = [_use(("case_evidence", {"case_id": cid, "stance": "neutral", "text": "No new filing changes the picture.", "source_kind": "observation"}),
                               ("case_evidence", {"case_id": cid, "stance": "for", "text": "Prices behaved as the scenarios assumed.", "source_kind": "observation"})), _say("Two items recorded.")]
    second["review"] = [_use(("submit_review", {"case_id": cid, "verdict": "approve", "findings": "The update is sourced.", "checks": "none needed"}), model=gv.OPUS), _say("Approved.", gv.OPUS)]
    rt._hq_client = Model(second)
    assert cases.due(con, later) == []                                                         # the brain's case pass does not take it
    assert missions.due_reviews(rt) == [cid]
    assert missions.due_reviews(rt) == []                                                       # once
    assert missions.card(con, cid)["state"] == "planning"
    service.drive_missions(rt)
    card = missions.card(con, cid)
    assert card["state"] == "done" and "Nothing in the new evidence" in card["answer"]["answer"]
    log = [e[0] for e in con.execute("SELECT event FROM hq_case_log WHERE case_id=? ORDER BY log_id", [cid]).fetchall()]
    assert "reopened" in log
    told = [m["text"] for m in chat.messages(con, assistant.thread(con, later)) if m["mode"].startswith("note:")]
    assert sum("Finished" in t for t in told) == 2 and any("scheduled review" in t for t in told)      # the second finish is told too


def test_a_failed_investigation_can_be_retried_and_resumes_where_it_stopped(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    scripts = _happy_scripts()
    scripts["quant"] = [_say("I did nothing."), _say("Still nothing."), _say("Nothing at all."), _use(("case_calculate", {"case_id": 1, "question": "worst fall"})), _say("Done.")]
    rt._hq_client = Model(scripts)
    out = missions.create(con, NOW, "Compare phased buying with holding cash", pm_dir=rt.pm_dir)
    service.drive_missions(rt)
    assert missions.card(con, out["case_id"])["state"] == "blocked"
    ev_before = con.execute("SELECT count(*) FROM hq_artifacts WHERE kind='evidence'").fetchone()[0]
    assert missions.retry(con, NOW, out["case_id"]) == {"retried": 1, "state": "working"}
    service.drive_missions(rt)
    assert missions.card(con, out["case_id"])["state"] == "done"
    assert con.execute("SELECT count(*) FROM hq_artifacts WHERE kind='evidence'").fetchone()[0] == ev_before             # the research was not repeated


def test_six_documents_about_one_companys_results_are_one_mission_not_six(rt, con):
    """Found on the first real start: six missions on six documents about the same company's quarter."""
    for k in range(6):
        _insert_reading(con, f"D{k}")
    rt._hq_client = Model({"coordinator": [], "research": [], "quant": [], "review": []})
    out = missions.scan(rt)
    assert len(out["started"]) == 1 and con.execute("SELECT count(*) FROM hq_missions").fetchone()[0] == 1
    lead = out["started"][0]
    assert "Other documents of the same kind" in missions.mission_of(con, lead)["goal"]
    st = con.execute("SELECT status, decision, decision_reason FROM hq_cases WHERE case_id <> ? ORDER BY case_id", [lead]).fetchall()
    assert len(st) == 4 and all(r[0] == "done" and r[1] == "nothing" and "folded into" in r[2] for r in st)
    _insert_reading(con, "D9")                                              # a new document the same week: covered by the one already started
    again = missions.scan(rt)
    assert again["started"] == [] and con.execute("SELECT count(*) FROM hq_missions").fetchone()[0] == 1
