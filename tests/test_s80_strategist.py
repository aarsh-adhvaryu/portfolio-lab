"""S80 phase 2: the strategist session, its budget rules and triggers (a scripted model stands in for Opus; no paid call)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from pflab import core
from pflab.hq import governor as gv
from pflab.lab import service, shadow, strategist, tools
from pflab.pm import store
from tests.test_s80_lab import MOMENTUM, make_data
from tests.test_s68_autonomy import CFG

NOW = datetime(2026, 11, 9, 1, 0)


def _blocks(*calls, text=None, out=1200):
    content = [SimpleNamespace(type="thinking", thinking="", signature="sig")]
    if text:
        content.append(SimpleNamespace(type="text", text=text))
    content += [SimpleNamespace(type="tool_use", id=f"tu{k}_{n}", name=n, input=i) for k, (n, i) in enumerate(calls)]
    return SimpleNamespace(content=content, stop_reason="tool_use" if calls else "end_turn", model=gv.OPUS,
                           usage=SimpleNamespace(input_tokens=9000, output_tokens=out, cache_read_input_tokens=0, cache_creation_input_tokens=0))


class Opus:
    def __init__(self, *turns):
        self.turns, self.seen = list(turns), []
        self.messages = SimpleNamespace(count_tokens=lambda **kw: SimpleNamespace(input_tokens=9000))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.seen.append(kw)
        if not self.turns:
            raise AssertionError("the strategist was asked again with nothing scripted")
        return self.turns.pop(0)


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    monkeypatch.setenv("PFLAB_SANDBOX", "local")
    monkeypatch.setattr("pflab.lab.runner.HISTORY", ("2012-06-01", "2015-12-31"))
    c = store.connect(tmp_path / "l.duckdb")
    c.execute("INSERT INTO core_policies_s80 (policy_id, status, code_hash, created_at, promoted_at) VALUES ('baseline_v1', 'champion', 'x', ?, ?)", [NOW, NOW])
    return c


@pytest.fixture(scope="module")
def data():
    return make_data()


def _session(con, tmp_path, client, data, reason="the weekly session", **kw):
    return strategist.run_session(con, tmp_path, None, NOW, reason, client=client, cfg=CFG, data=data, **kw)


HAPPY = lambda: Opus(
    _blocks(("toolkit_help", {}), text="Hypothesis: strong 12-1 momentum, sized by risk, beats the plain basket."),
    _blocks(("write_policy", {"policy_id": "mom_risk_1", "code": MOMENTUM, "hypothesis": "lean toward the strongest 12-1 momentum, sized by risk"})),
    _blocks(("run_lab", {"policy_id": "mom_risk_1", "n_shuffles": 5})),
    _blocks(("make_challenger", {"policy_id": "mom_risk_1", "params": {"n": 5}, "why": "fewest names"}), ("write_note", {"text": "Tried momentum with 5 and 10 names; 5 looked better after costs; watch it in shadow."})),
    _blocks(("finish", {"summary": "wrote one variant, ran it, kept the 5-name arm"})))


def test_a_session_writes_runs_keeps_a_challenger_and_leaves_a_note(con, tmp_path, data):
    client = HAPPY()
    out = _session(con, tmp_path, client, data)
    assert out["status"] == "done" and out["lab_runs"] == 1 and out["challengers"] == 1 and out["variants"] == 1 and out["cost_inr"] > 0
    assert service.get(con, "mom_risk_1")["status"] == "challenger"
    assert "shadow" in service.notes(con)[0]["text"]
    row = con.execute("SELECT status, lab_runs, challengers, cost_inr, finished_at FROM core_sessions_s80").fetchone()
    assert row[0] == "done" and row[1] == 1 and row[2] == 1 and row[3] > 0 and row[4] is not None
    agents = {r[0] for r in con.execute("SELECT agent FROM api_calls").fetchall()}
    assert agents == {"strategist"}
    first = client.seen[0]
    assert first["model"] == gv.OPUS and "STRATEGIST" in first["system"][0]["text"] and first["system"][0]["cache_control"] == {"type": "ephemeral"}
    sent = json.dumps(first["messages"])
    assert "BOOK CARD" in sent or "no book card yet" in sent
    assert {t["name"] for t in first["tools"]} >= {"write_policy", "run_lab", "make_challenger", "write_note", "finish", "compare"} and len(first["tools"]) <= 22


def test_the_model_never_gets_raw_output_only_small_scorecards(con, tmp_path, data):
    client = HAPPY()
    _session(con, tmp_path, client, data)
    results = [b for kw in client.seen for m in kw["messages"] if m["role"] == "user" for b in m["content"] if b.get("type") == "tool_result"]
    assert results and all(len(b["content"]) <= 9000 for b in results)
    lab = next(b for b in results if "scorecards" in b["content"])
    assert "deflated_sharpe" in lab["content"] and "shuffled_beat_it_share" in lab["content"]


def test_a_refused_policy_comes_back_with_its_reason_and_the_session_goes_on(con, tmp_path, data):
    bad = "import os\ndef decide(state, forecasts, sims, storylines, params=None):\n    return {}\n"
    client = Opus(_blocks(("write_policy", {"policy_id": "evil_one", "code": bad, "hypothesis": "tries to import the operating system module"})), _blocks(("finish", {"summary": "nothing to run"})))
    out = _session(con, tmp_path, client, data)
    res = [b for m in client.seen[1]["messages"] if m["role"] == "user" for b in m["content"] if b.get("type") == "tool_result"][0]
    assert res.get("is_error") and "not allowed" in res["content"]
    assert out["status"] == "wasted" and service.get(con, "evil_one") is None


def _throttle_on(monkeypatch):
    """S81 (A55): the halving rules are applied only from `throttle_after` (2026-12-09); these tests are about the rules themselves, so the date is moved before NOW."""
    real = core.settings
    monkeypatch.setattr(core, "settings", lambda: {**real(), "strategist": {**real()["strategist"], "throttle_after": "2026-01-01"}})


def test_a_session_with_no_lab_run_is_wasted_and_the_next_one_gets_half_the_budget_until_one_succeeds(con, tmp_path, data, monkeypatch):
    _throttle_on(monkeypatch)
    full = strategist.session_budget(con, NOW)["rupees"]
    out = _session(con, tmp_path, Opus(_blocks(("finish", {"summary": "I decided to do nothing"}))), data)
    assert out["status"] == "wasted"
    half = strategist.session_budget(con, NOW)
    assert half["rupees"] == full / 2 and any("half the budget" in w for w in half["why"])
    ok = _session(con, tmp_path, HAPPY(), data)
    assert ok["status"] == "done" and ok["budget_inr"] == full / 2
    assert strategist.session_budget(con, NOW)["rupees"] == full


def test_the_session_ends_where_the_budget_ends(con, tmp_path, data):
    client = Opus(_blocks(("toolkit_help", {}), out=40_000), _blocks(("finish", {"summary": "never reached"})))        # the first turn costs about Rs 72
    out = _session(con, tmp_path, client, data, budget_inr=50.0)
    assert out["status"] == "wasted" and out["cost_inr"] > 50                # it stopped because the money was used (and no lab run was made)
    assert len(client.seen) == 1 and len(client.turns) == 1                  # the second scripted turn was never asked for
    assert "Rs 50" in strategist._first_message(con, "x", 50.0)


def test_the_kill_switch_and_the_strategist_switch_stop_every_session(con, tmp_path, data, monkeypatch):
    real = core.settings
    monkeypatch.setattr(core, "settings", lambda: {**real(), "core": {**real()["core"], "kill": True}})
    assert "skipped" in _session(con, tmp_path, Opus(), data) and core.on() is False and core.strategist_on() is False
    assert strategist.tick(con, tmp_path, None, NOW, lambda: Opus(), data=data) == {"off": True}


def test_triggers_weekly_challenger_ready_and_nothing_to_do(con, tmp_path, data):
    assert strategist.due(con, NOW) == ["the weekly session (re-examine the allocation)"]
    _session(con, tmp_path, HAPPY(), data)
    assert strategist.due(con, NOW + timedelta(days=2)) == []                                   # not on a bare timer, nothing else to work on
    assert strategist.due(con, NOW + timedelta(days=8)) == ["the weekly session (re-examine the allocation)"]
    from tests.test_s80_lab_promotion import GOOD, BASE, _run, _shadow_days
    _run(con, "baseline_lab", "history", BASE)
    con.execute("DELETE FROM lab_runs_s80 WHERE policy_id='mom_risk_1'")
    _run(con, "mom_risk_1", "history", GOOD, params={"n": 5})
    _shadow_days(con, "mom_risk_1", 22)
    assert any("ready for the promotion check" in r for r in strategist.due(con, NOW + timedelta(days=2)))


def test_eight_weeks_without_a_win_halves_the_budget_and_tells_him(con, tmp_path, data, monkeypatch):
    _throttle_on(monkeypatch)
    told = []
    monkeypatch.setattr("pflab.app.assistant.notify", lambda con_, now, text, key: told.append(text))
    con.execute("INSERT INTO core_sessions_s80 (session_id, started_at, finished_at, reason, status, cost_inr) VALUES (1, ?, ?, 'old', 'done', 10)", [NOW - timedelta(days=70), NOW - timedelta(days=70)])
    b = strategist.session_budget(con, NOW)
    assert b["rupees"] == strategist.settings()["session_rupees"] / 2 and any("weeks" in w for w in b["why"])
    _session(con, tmp_path, Opus(_blocks(("finish", {"summary": "x"}))), data)
    assert any("without an AI-written variant" in t for t in told)


def test_spend_report_ties_money_to_outcomes(con, tmp_path, data):
    _session(con, tmp_path, HAPPY(), data)
    r = strategist.spend_report(con, NOW)
    assert r["month_rupees"]["strategist"] > 0 and r["month_rupees"]["checker"] == 0 and r["lab_runs"] >= 1 and r["challengers_added"] == 1
    assert r["lab_runs_per_100_rupees"] is not None and r["promotions"] == 0 and r["budget"]["rupees"] > 0


def test_every_tool_description_is_short_and_the_set_is_small():
    ds = tools.definitions()
    assert 10 <= len(ds) <= 22                                                  # S81: propose_allocation is the seventeenth; S83: screen_stocks and company_card ; the picks tools: propose_picks, withdraw_pick, skip_idea
    assert all(len(d["description"]) < 480 for d in ds)
