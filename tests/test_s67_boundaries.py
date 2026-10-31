"""S67 local: the boundaries of the research workspace, shown by behaviour. The installed application investigates, calculates and experiments by
itself and chat shares the same tools and durable state; a wish becomes explicit objectives and risks; the runtime can propose software changes
but never makes them; a new market grants no trading; an interrupted experiment continues from what was recorded. Synthetic data, no network."""
from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from pflab.hq import board, brain, cases, egress, governor as gv, objectives, tools as tl
from pflab.hq.desk import Desk
from pflab.learner import counter, experiments as ex
from pflab.pm import store

NOW = datetime(2026, 10, 29, 20, 0)
CFG = {"model": "claude-opus-5-5", "cap": 2500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True, "tijori_to_analyst": True}


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


@pytest.fixture
def ctx(con, tmp_path, monkeypatch):
    monkeypatch.setattr(tl.Ctx, "book", lambda self: None)
    from pflab.agents import analyst as an
    monkeypatch.setattr(an, "config", lambda: CFG)
    (tmp_path / "pm").mkdir(exist_ok=True)
    rt = Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None, {"brain": "economy", "preset": "full"}, clock=lambda: NOW)
    cid, _ = cases.open_case(con, NOW, "Is an AI-related downturn a buying chance?", subject="AI")
    cases.start_pass(con, [cid], 1, NOW)
    c = tl.Ctx(rt, 1, gv.OPUS, False, {}, egress.Gate(), NOW, case_ids=[cid])
    c.cid = cid
    return c


GOOD = {
    "objectives": [{"measure": "annualised return net of tax", "target": 12.0, "horizon_months": 60, "comparator": "the Nifty 50 total return"}],
    "acceptable_risk": {"max_fall_pct": 30, "cash_floor_months": 12},
    "competing_explanations": [
        {"explanation": "a temporary sentiment fall: earnings are intact", "supported_by": "estimates stay flat while prices fall", "refuted_by": "estimates are cut"},
        {"explanation": "deteriorating fundamentals: the growth story is breaking", "supported_by": "cuts to revenue guidance", "refuted_by": "guidance is kept or raised"}],
    "would_change_my_view": ["two quarters of estimate cuts", "the fall limit being reached in simulation"],
}


# --- a wish becomes an objective ----------------------------------------------------------------------------------------------------------

def test_higher_returns_alone_is_a_draft_with_one_grouped_question_and_nothing_is_tested_against_it(con):
    r = objectives.store(con, NOW, "higher returns", {})
    assert r["status"] == "draft" and r["vague"] and r["question_id"]
    objectives.store(con, NOW, "Higher returns.", {})                                                   # the same wish again: no second question
    q = con.execute("SELECT text FROM questions WHERE subject_key LIKE 'objective:%'").fetchall()
    assert len(q) == 1 and "how much a year" in q[0][0] and "fall from a peak" in q[0][0] and "months of expenses" in q[0][0]     # asked together, once
    assert objectives.testable(con) == []


def test_a_complete_frame_is_stored_as_framed_with_competing_explanations_and_what_would_change_the_view(con):
    r = objectives.store(con, NOW, "I want higher returns", GOOD)
    assert r["status"] == "framed" and r["problems"] == [] and r["max_fall_applied_pct"] == 30
    assert [o["id"] for o in objectives.testable(con)] == [r["objective_id"]]


@pytest.mark.parametrize("break_it,needle", [
    (lambda f: f.update(competing_explanations=GOOD["competing_explanations"][:1]), "two competing explanations"),
    (lambda f: f.update(would_change_my_view=[]), "what evidence would change"),
    (lambda f: f["objectives"][0].pop("target"), "no number for the target"),
    (lambda f: f["objectives"][0].update(measure="vibes"), "the measure must be"),
    (lambda f: f["objectives"][0].pop("comparator"), "nothing to compare"),
])
def test_each_missing_part_is_named_and_the_frame_stays_a_draft(con, break_it, needle):
    f = json.loads(json.dumps(GOOD))
    break_it(f)
    r = objectives.store(con, NOW, "grow faster", f)
    assert r["status"] == "draft" and any(needle in p for p in r["problems"])


def test_a_risk_above_his_fall_limit_is_a_proposal_and_the_limit_stands(con):
    f = json.loads(json.dumps(GOOD))
    f["acceptable_risk"]["max_fall_pct"] = 50
    r = objectives.store(con, NOW, "much higher returns", f)
    assert r["max_fall_applied_pct"] == 35.0 and any("above your limit of 35 percent" in p for p in r["proposals"])
    kept = objectives.current(con)[0]["frame"]["acceptable_risk"]
    assert kept["max_fall_pct"] == 35.0 and kept["requested_max_fall_pct"] == 50                    # his request is on record; the limit is unchanged


def test_the_tool_links_the_explanations_to_the_case_and_chat_sees_the_same_state(ctx, con):
    text, err = tl.run(ctx, "frame_objective", {"wish": "higher returns from the AI dip", "frame_json": json.dumps(GOOD), "case_id": ctx.cid}, 1)
    assert not err and json.loads(text)["status"] == "framed"
    ev = [e["text"] for e in cases.evidence(con, ctx.cid)]
    assert any(t.startswith("explanation to test: a temporary sentiment fall") for t in ev) and any(t.startswith("explanation to test: deteriorating") for t in ev)
    assert any(t.startswith("would change the view: two quarters of estimate cuts") for t in ev)
    assert cases.assess(con, ctx.cid, NOW)["missing"] == 0                                           # these are not gaps
    from pflab.agents import tools as at
    facts = at.research(con, NOW.date())                                                              # what the ask centre (chat) reads
    assert any(k.startswith("objective.") and v.startswith("framed") for k, v in facts.items())
    bad, err2 = tl.run(ctx, "frame_objective", {"wish": "x", "frame_json": "not json"}, 1)
    assert json.loads(bad)["stored"] is False


# --- one workspace for chat and background work ---------------------------------------------------------------------------------------------

def test_an_experiment_registered_by_the_brain_is_what_the_learner_runs_and_chat_reads(ctx, con, tmp_path):
    text, err = tl.run(ctx, "register_experiment", {"hypothesis": "A twelve-month momentum filter improves on staying invested",
                                                    "why_it_matters": "it would bear on the 35 percent fall limit", "disproof": "no net gain in either period",
                                                    "source": "case", "case_id": ctx.cid, "contract": "index_timing"}, 1)
    assert not err and json.loads(text)["carried_out"]
    assert ex.select(con) == 1
    from pflab.agents import tools as at
    f = at.research(con, NOW.date())
    assert f["experiment.1"].startswith("registered:") and f["experiments.variants_searched_in_all"] == counter.n_tests(con)
    t2, err2 = tl.run(ctx, "experiments", {}, 1)
    assert not err2 and json.loads(t2)["experiments"][0]["id"] == 1
    assert "research" in {t.name for t in at.TOOLS} and {"frame_objective", "register_experiment", "experiments", "propose_software_change"} <= set(tl.TOOLS)


def test_registering_experiments_is_capped_a_day(ctx):
    done = []
    for k in range(tl.DAILY["register_experiment"] + 2):
        text, _ = tl.run(ctx, "register_experiment", {"hypothesis": f"rule number {k}", "why_it_matters": "w", "disproof": "d", "source": "investor", "contract": "index_timing"}, 1)
        done.append(json.loads(text).get("carried_out"))
    assert done == [True, True, False, False]


def test_an_interrupted_experiment_continues_from_its_recorded_attempts_and_a_live_one_is_left_alone(con, tmp_path):
    eid = ex.register(con, tmp_path / "proto", NOW, hypothesis="a rule", why_it_matters="w", disproof="d", source_kind="investor", contract="index_timing")
    con.execute("UPDATE learn_experiments SET status='running' WHERE exp_id=?", [eid])
    ex._attempt(con, eid, 1, NOW, "candidate", "rejected", code="def compute(data):\n    return {'signal': 1}\n", result={"why": "behind"})
    with ex._LIVE_LOCK:
        ex._LIVE.add(eid)
    try:
        assert ex.reap(con, NOW) == 0                                                                  # this process is still running it
    finally:
        with ex._LIVE_LOCK:
            ex._LIVE.discard(eid)
    assert ex.reap(con, NOW) == 1                                                                      # the process that ran it died
    assert con.execute("SELECT status FROM learn_experiments WHERE exp_id=?", [eid]).fetchone()[0] == "registered"
    assert len([a for a in ex.attempts(con, eid) if a["kind"] == "candidate"]) == 1                    # what was recorded is kept


# --- the runtime cannot change the application --------------------------------------------------------------------------------------------

def test_a_proposed_software_change_is_only_a_record_and_the_repository_is_untouched(ctx, con):
    repo = Path(__file__).resolve().parents[1]
    before = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
    text, err = tl.run(ctx, "propose_software_change", {"kind": "missing_tool", "title": "Add a US-market data connector", "evidence": "no US prices in the store",
                                                        "repro": "ask for a US stock's chart", "proposed_patch": "def fetch_us(): ..."}, 1)
    out = json.loads(text)
    assert not err and out["applied"] is False
    assert con.execute("SELECT status, origin FROM hq_issues").fetchone() == ("proposed", "brain")
    after = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
    assert after == before                                                                             # not one file in the repo changed


def test_no_runtime_tool_can_change_code_permissions_limits_or_place_an_order():
    names = set(tl.TOOLS)
    assert not [n for n in names if any(w in n for w in ("order_placed", "place_order", "gtt", "deploy", "release", "install", "set_limit", "grant", "sudo"))]
    # the tools that touch his preferences go through his yes (a proposal), never directly
    assert tl.TOOLS["change_preference"].kind == "action" and "yes" in tl.TOOLS["change_preference"].about.lower()
    # generated code runs only through the sandbox's static check: no files, no network, no processes
    from pflab.agents import workshop as wk
    for code in ("import os\ndef compute(data):\n    return {'a': 1}\n", "import subprocess\ndef compute(data):\n    return {'a': 1}\n",
                 "def compute(data):\n    open('/etc/passwd')\n    return {'a': 1}\n", "def compute(data):\n    return {'a': __import__('os').getcwd()}\n"):
        assert wk.static_check(code), code


@pytest.mark.parametrize("exchange", ["NASDAQ", "NYSE", "NSE", "BSE", "GIFT", "NSEIX"])
def test_adding_a_market_or_an_instrument_grants_no_trading(exchange):
    from pflab.ingest import kite
    k = kite.ReadOnlyKite("key", "tok", factory=lambda **kw: SimpleNamespace(place_order=lambda **a: "order placed", place_gtt=lambda **a: "gtt"))
    for method in ("place_order", "place_gtt", "modify_order", "cancel_order", "place_mf_order"):
        with pytest.raises(kite.TradingForbidden):
            getattr(k, method)(exchange=exchange, tradingsymbol="AAPL")
    # a US instrument's pseudo-ISIN is a security key like any other; nothing in the tool registry can act on it with money
    assert not [t for t in tl.TOOLS.values() if t.kind == "action" and "order" in t.name and t.name not in ("order_research", "order_calculation")]


# --- updates keep what was learned ----------------------------------------------------------------------------------------------------------

def test_new_research_survives_a_rollback_to_the_release_that_does_not_know_the_tables(tmp_path):
    """The newer release adds experiment and objective tables. A rollback to the older schema keeps the shared tables' later rows and says which tables
    only the newer release has (they stay in the kept copy, not lost)."""
    import duckdb
    from pflab import update as up
    old = [m for m in store.MIGRATIONS if m[0] <= 42]
    bk, kept = tmp_path / "bk.duckdb", tmp_path / "kept.duckdb"
    c = duckdb.connect(str(bk))
    store.migrate(c, old)
    c.close()
    kept.write_bytes(bk.read_bytes())
    k = store.connect(kept)
    k.execute("INSERT INTO questions VALUES (9, ?, 'investigator', 'objective:1', 'newer question', 'open', NULL, NULL)", [NOW])
    ex.register(k, tmp_path / "proto", NOW, hypothesis="kept research", why_it_matters="w", disproof="d", source_kind="investor", contract="index_timing")
    k.close()
    r = up.merge_new_rows(kept, bk)
    assert r["errors"] == {} and r["added"].get("questions") == 1
    assert {"learn_experiments", "learn_attempts", "hq_objectives", "hq_issues"} <= set(r["only_in_kept"])
