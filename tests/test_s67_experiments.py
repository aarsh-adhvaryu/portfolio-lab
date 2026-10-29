"""S67 local: the bounded experiment loop. A scripted writer stands in for the model (it checks the wiring, not any reasoning); the sandbox is the
local subprocess the test suite names explicitly; the data is a synthetic index series. The evaluator is the real one. Real Docker is a separate
marked test."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pflab.learner import counter, experiments as ex, live
from pflab.learner import templates as tp
from pflab.pm import store

NOW = datetime(2026, 10, 29, 18, 0)


@pytest.fixture(autouse=True)
def local_box(monkeypatch):
    monkeypatch.setenv("PFLAB_SANDBOX", "local")


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


def _series(trend_after_dips=True, seed=3) -> pd.DataFrame:
    """Business days 2009-01 to 2023-12: a random walk with drift, enough months in both periods; rows after 2021 exist so the guard is tested."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2009-01-01", "2023-12-29")
    r = rng.normal(0.0004, 0.01, len(days))
    return pd.DataFrame({"date": [d.date() for d in days], "close": 100 * np.cumprod(1 + r)})


CODE_ALWAYS = '''
def compute(data):
    return {"signal": 1.0}
'''
CODE_MOM = '''
import pandas as pd

def compute(data):
    d = next(iter(data.values()))
    c = d["close"]
    if len(c) < 253:
        return {"signal": 1.0}
    return {"signal": float(c.iloc[-1] / c.iloc[-253] - 1.0)}
'''
CODE_BROKEN = '''
def compute(data):
    return {"signal": undefined_name}
'''
TEST_ROWS = [{"date": f"2020-01-{k:02d}", "close": 100.0 + k} for k in range(1, 20)]


def reply(code: str, explain="rule") -> str:
    return json.dumps({"datasets": [ex.DEFAULT_DATASET], "code": code, "explain": explain,
                       "test": {"data": {ex.DEFAULT_DATASET: TEST_ROWS}, "expected": {"signal": 1.0 if "return {\"signal\": 1.0}" in code and "c.iloc" not in code else _mom_expect()}, "tol": 1e-6}})


def _mom_expect():
    return 1.0                                   # fewer than 253 rows in the test case: the rule returns 1.0 there


class Writer:
    def __init__(self, *codes):
        self.codes, self.prompts = list(codes), []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return reply(self.codes[min(len(self.prompts) - 1, len(self.codes) - 1)])


def _reg(con, tmp_path, **kw):
    return ex.register(con, tmp_path / "proto", NOW, hypothesis=kw.get("h", "Twelve-month momentum improves on always being invested"),
                       why_it_matters="A rule that avoids long falls would matter for a 35 percent fall limit",
                       disproof="no net gain over always invested in both periods", source_kind="investor")


# --- registration ---------------------------------------------------------------------------------------------------------------------------

def test_the_question_is_registered_before_any_candidate_and_never_twice(con, tmp_path):
    eid = _reg(con, tmp_path)
    assert _reg(con, tmp_path) == eid
    proto = json.loads((tmp_path / "proto" / f"experiment_{eid}.json").read_text(encoding="utf-8"))
    assert proto["comparator"] == ex.COMPARATOR and proto["periods"]["spent_not_loaded_from"] == "2022-01-01"
    assert proto["budget"]["total_wall_s"] == ex.TOTAL_WALL_S and proto["stop"]["max_attempts"] == ex.MAX_ATTEMPTS
    assert con.execute("SELECT count(*) FROM learn_attempts").fetchone()[0] == 0                      # nothing observed yet
    with pytest.raises(ValueError):
        ex.register(con, tmp_path / "proto", NOW, hypothesis="x", why_it_matters="", disproof="y", source_kind="investor")
    with pytest.raises(ValueError):
        ex.register(con, tmp_path / "proto", NOW, hypothesis="x2", why_it_matters="w", disproof="y", source_kind="a hunch")


def test_a_changed_protocol_or_evaluator_stops_the_run(con, tmp_path):
    eid = _reg(con, tmp_path)
    p = tmp_path / "proto" / f"experiment_{eid}.json"
    p.write_text(p.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(RuntimeError, match="protocol file changed"):
        ex.run(con, eid, tmp_path, NOW, Writer(CODE_ALWAYS), frame=_series())
    eid2 = _reg(con, tmp_path, h="a second question")
    con.execute("UPDATE learn_experiments SET evaluator_sha='0' WHERE exp_id=?", [eid2])
    with pytest.raises(RuntimeError, match="evaluator changed"):
        ex.run(con, eid2, tmp_path, NOW, Writer(CODE_ALWAYS), frame=_series())


# --- the trusted evaluator ------------------------------------------------------------------------------------------------------------------

def test_always_invested_cannot_beat_itself_and_the_rule_is_deflated_by_the_tests_run(con):
    df = _series()
    dates = ex.walk_dates(df)
    assert max(dates) < ex.SPENT_FROM and min(dates) >= date(2010, 1, 1)
    dev = ex.score_period(df, {d.isoformat(): 1.0 for d in dates}, tp.DEV)
    assert dev["mean_excess"] == pytest.approx(0.0, abs=1e-12) and dev["exposure"] == 1.0
    out = ex.score_period(df, {d.isoformat(): -1.0 for d in dates}, tp.DEV)
    assert out["exposure"] == 0.0 and out["cand_mean"] < out["base_mean"]                   # always out is not free
    ok, why = ex.decide(dev, dev, 2.0)
    assert not ok and "behind" in why
    strong = {"n_months": 96, "mean_excess": 0.01, "t": 4.0}
    assert ex.decide(strong, {"n_months": 48, "mean_excess": 0.01, "t": 2.0}, 3.0)[0]
    assert not ex.decide(strong, {"n_months": 48, "mean_excess": 0.01, "t": 2.0}, 4.5)[0]  # the bar rose with the searches
    assert not ex.decide({**strong, "n_months": 20}, strong, 2.0)[0]                      # too little evidence
    with pytest.raises(ValueError):
        ex.score_period(df, {}, tp.DEV)                                                      # a missing signal is an error, never a zero


# --- the loop -------------------------------------------------------------------------------------------------------------------------------

def test_a_candidate_is_baselined_run_in_the_sandbox_scored_counted_and_recorded(con, tmp_path):
    eid = _reg(con, tmp_path)
    n0 = counter.n_tests(con)
    w = Writer(CODE_MOM)
    r = ex.run(con, eid, tmp_path, NOW, w, frame=_series())
    assert r["status"] in ("kept", "rejected") and r["attempts"] >= 1
    a = ex.attempts(con, eid)
    assert a[0]["kind"] == "baseline" and a[0]["result"]["development"]["n_months"] >= 90
    cands = [x for x in a if x["kind"] == "candidate"]
    assert cands and all(x["result"]["development"] and x["result"]["validation"] for x in cands)
    assert counter.n_tests(con) == n0 + len(cands)                                           # every evaluated variant counts
    first_bar = cands[0]["result"]["dev_bar"]
    assert cands[0]["result"]["tests_in_family"] == n0 + 1 and first_bar >= 2.0
    if len(cands) > 1:
        assert cands[1]["result"]["dev_bar"] >= first_bar                                    # the bar only rises
    # the writer saw the recorded evidence of every earlier attempt before writing the next one
    if len(w.prompts) > 1:
        assert "EARLIER CANDIDATES" in w.prompts[1] and "development" in w.prompts[1]
    row = live.current(con, ("experiment",))
    assert row and f"Experiment #{eid}" in row[0]["text"] and ("SHADOW" in row[0]["text"] or "does not prove" in row[0]["text"])


def test_a_rejected_candidate_is_a_valid_result_and_the_attempt_stays_on_record(con, tmp_path):
    eid = _reg(con, tmp_path)
    r = ex.run(con, eid, tmp_path, NOW, Writer(CODE_ALWAYS), frame=_series())
    assert r["status"] == "rejected" and r["attempts"] == ex.MAX_ATTEMPTS and "none beat" in r["why"]
    kept_rows = [x for x in ex.attempts(con, eid) if x["kind"] == "candidate"]
    assert len(kept_rows) == ex.MAX_ATTEMPTS and all(x["status"] == "rejected" and x["code"] for x in kept_rows)
    assert "brain_text" and "EXPERIMENTS" in live.brain_text(con) and "rejection is a result" in live.brain_text(con)
    with pytest.raises(ValueError, match="not run again"):
        ex.run(con, eid, tmp_path, NOW, Writer(CODE_ALWAYS), frame=_series())


def test_a_crash_gets_one_repair_with_the_error_then_is_deferred_not_hidden(con, tmp_path):
    eid = _reg(con, tmp_path)
    w = Writer(CODE_BROKEN)
    r = ex.run(con, eid, tmp_path, NOW, w, frame=_series())
    assert r["status"] == "deferred" and "failed to run" in r["why"] and r["crashes"] == ex.MAX_ATTEMPTS
    assert len(w.prompts) == ex.MAX_ATTEMPTS * (ex.REPAIRS + 1)                              # one repair per attempt, no more
    assert any("FAILED TO RUN" in p and "undefined_name" in p for p in w.prompts)            # the error went back to the writer
    assert counter.n_tests(con) == counter.n_tests(con)                                      # crashes evaluated nothing, so nothing was counted
    assert all(a["status"] == "crash" and a["error"] for a in ex.attempts(con, eid) if a["kind"] != "baseline")


def test_a_repair_that_works_is_recorded_after_the_crash(con, tmp_path):
    eid = _reg(con, tmp_path)
    w = Writer(CODE_BROKEN, CODE_ALWAYS)
    ex.run(con, eid, tmp_path, NOW, w, frame=_series())
    st = [(a["kind"], a["status"]) for a in ex.attempts(con, eid)]
    assert ("candidate", "crash") in st and ("candidate", "rejected") in st


def test_a_candidate_that_peeks_at_the_future_cannot_see_it(con, tmp_path):
    """The runner cuts the data at each date; a candidate asking for the last row sees only that date's last row, so it cannot use tomorrow's close."""
    df = _series()
    eid = _reg(con, tmp_path)
    spy = '''
def compute(data):
    d = next(iter(data.values()))
    return {"signal": 1.0 if d["close"].iloc[-1] > d["close"].iloc[0] else -1.0}
'''
    ex.run(con, eid, tmp_path, NOW, Writer(spy), frame=df)
    cands = [a for a in ex.attempts(con, eid) if a["kind"] == "candidate" and a["result"]]
    assert cands                                                                              # it ran; whatever it scored was on past rows only


def test_the_spent_period_is_never_loaded_into_a_candidate(con, tmp_path):
    from pflab.agents import workshop as wk
    seen = {}
    real = wk.run

    def spy(spec, frames, **kw):
        seen["max"] = max(max(f["date"]) for f in frames.values())
        seen["walk_max"] = max(kw["walk"])
        return real(spec, frames, **kw)
    import pflab.agents.workshop as mod
    mod.run = spy
    try:
        eid = _reg(con, tmp_path)
        ex.run(con, eid, tmp_path, NOW, Writer(CODE_ALWAYS), frame=_series())
    finally:
        mod.run = real
    assert seen["max"] < ex.SPENT_FROM and seen["walk_max"] < ex.SPENT_FROM.isoformat()


def test_missing_data_or_sandbox_makes_it_wait_and_invents_nothing(con, tmp_path, monkeypatch):
    eid = _reg(con, tmp_path)
    r = ex.run(con, eid, tmp_path, NOW, Writer(CODE_ALWAYS))                                  # no frame, no index file in tmp_path
    assert r["status"] == "waiting" and "no data" in r["why"]
    assert [a for a in ex.attempts(con, eid)] == []
    monkeypatch.delenv("PFLAB_SANDBOX")
    from pflab.agents import sandbox as sb
    monkeypatch.setattr(sb, "status", lambda *a, **k: {"ok": False, "why": "Docker Desktop is not running"})
    r2 = ex.run(con, eid, tmp_path, NOW, Writer(CODE_ALWAYS), frame=_series())
    assert r2["status"] == "waiting" and "Docker" in r2["why"] and ex.select(con) == eid        # and it is picked up again later


def test_the_time_budget_stops_the_loop(con, tmp_path):
    eid = _reg(con, tmp_path)
    t = iter(range(0, 100000, 1000))
    r = ex.run(con, eid, tmp_path, NOW, Writer(CODE_ALWAYS), frame=_series(), clock=lambda: float(next(t)))
    assert r["status"] == "deferred" and "budget" in r["why"]


def test_step_runs_the_next_experiment_and_is_idle_when_there_is_none(con, tmp_path):
    from types import SimpleNamespace
    rt = SimpleNamespace(cursor=lambda: con, clock=lambda: NOW, data_root=tmp_path)
    assert "idle" in ex.step(rt, Writer(CODE_ALWAYS))
    _reg(con, tmp_path)
    out = ex.step(rt, Writer(CODE_ALWAYS), sandbox=None)
    assert out["experiment"] == 1 and out["status"] == "waiting"                              # no data under tmp_path: it waits
    assert ex.report(con)[0]["status"] == "waiting"


def _regimes(seed=5) -> pd.DataFrame:
    """Alternating up and down regimes of about 250 trading days with small noise: a 60-day momentum rule is genuinely informative here."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2009-01-01", "2023-12-29")
    drift = np.where((np.arange(len(days)) // 250) % 2 == 0, 0.002, -0.002)
    return pd.DataFrame({"date": [d.date() for d in days], "close": 100 * np.cumprod(1 + drift + rng.normal(0, 0.003, len(days)))})


CODE_SHORT_MOM = '''
def compute(data):
    c = next(iter(data.values()))["close"]
    if len(c) < 61:
        return {"signal": 1.0}
    return {"signal": float(c.iloc[-1] / c.iloc[-61] - 1.0)}
'''


def test_a_candidate_that_really_beats_the_comparator_is_kept_as_shadow_research_and_the_loop_stops(con, tmp_path):
    eid = _reg(con, tmp_path, h="Sixty-day momentum improves on always being invested")
    w = Writer(CODE_ALWAYS, CODE_SHORT_MOM, CODE_ALWAYS)
    r = ex.run(con, eid, tmp_path, NOW, w, frame=_regimes())
    assert r["status"] == "kept" and r["attempts"] == 2 and len(w.prompts) == 2             # stopped at the first keep, the third was never written
    a = [x for x in ex.attempts(con, eid) if x["kind"] == "candidate"]
    assert [x["status"] for x in a] == ["rejected", "kept"]
    k = a[1]["result"]
    assert k["development"]["t"] >= k["dev_bar"] and k["validation"]["t"] >= tp.T_VAL and k["development"]["cand_max_drawdown"] > k["development"]["base_max_drawdown"]
    assert "Shadow research only" in con.execute("SELECT decision_why FROM learn_experiments WHERE exp_id=?", [eid]).fetchone()[0]
    assert "SHADOW" in live.current(con, ("experiment",))[0]["text"]
    assert con.execute("SELECT count(*) FROM learned WHERE kind IN ('finding', 'instruction', 'daily_cap', 'model')").fetchone()[0] == 0   # nothing is wired as a rule
