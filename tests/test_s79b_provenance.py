"""S79b item 18C: decision provenance. A paper decision stores the sources behind it (two cited tool calls, a forecast in force, a bear warning, the team and the
model); when the decision is scored the outcome is credited back to every source with the right sign; the scorecard shows a count only under 20; re-scoring adds
nothing; a store without the tables, a failing recorder or the switch off never blocks a decision. Synthetic."""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pandas as pd

from pflab.paper import manager, provenance as pv
from tests.test_s68_autonomy import rt  # noqa: F401  (the fixture)
from tests.test_s76_paper import AAA, DAYS, _mission, _review, _seed, con  # noqa: F401  (the fixtures and helpers)

NOW = datetime(2026, 11, 2, 10, 0)


def _idx():
    return pd.Series([1000.0 + 10 * i for i in range(len(DAYS))], index=pd.to_datetime(DAYS))      # the market rises; AAA is flat


def _world(con, cid):
    """Two tool calls (cited), one uncited, in the quant's pass of the mission; hedge + two forecasters + a tiny one; a bear warning on AAA; a debate."""
    con.execute("INSERT INTO hq_tasks (task_id, created_at, from_agent, to_agent, text, status, hops, case_id, role) VALUES (9001, ?, 'coord', 'quant', 't', 'done', 0, ?, 'quant')", [NOW, cid])
    con.execute("INSERT INTO hq_tasks (task_id, created_at, from_agent, to_agent, text, status, hops, case_id, role) VALUES (9002, ?, 'coord', 'research', 't', 'done', 0, ?, 'research')", [NOW, cid])
    con.execute("INSERT INTO hq_passes VALUES (501, ?, 'task:9001', '[]', 'claude-sonnet-x', 'quant', false, 'done', '', '[]', 0, NULL, NULL)", [NOW])
    con.execute("INSERT INTO hq_passes VALUES (502, ?, 'task:9002', '[]', 'claude-sonnet-x', 'research', false, 'done', '', '[]', 0, NULL, NULL)", [NOW])
    for no, tool, args in ((11, "decompose_move", {"symbol": "AAA"}), (12, "trajectory", {"symbol": "AAA"}), (13, "breadth", {}), (14, "decompose_move", {"symbol": "ZZZ"})):
        con.execute("INSERT INTO hq_tool_calls VALUES (?,501,?,1,?, 'read', ?, 'ran', '{}', 5)", [no, NOW, tool, json.dumps(args)])
    q = lambda r: json.dumps({"0.05": r - 0.05, "0.5": r, "0.95": r + 0.05})
    for fid, name, r, meta in ((1, "hedge", 0.01, {"weights": {"momentum": 0.6, "meanrev": 0.39, "tiny": 0.01}}), (2, "momentum", 0.02, {}), (3, "meanrev", -0.02, {}), (4, "tiny", 0.03, {})):
        con.execute("INSERT INTO forecasts_s79 VALUES (?, 'IN', 'live', ?, ?, 'AAA', 20, ?, ?, 100.0, ?, ?, ?)", [fid, DAYS[4], AAA, name, q(r), DAYS[20], json.dumps(meta), NOW])
    con.execute("INSERT INTO bear_warnings_s79 (warning_id, debate_id, market, symbol, isin, claim, direction, horizon_sessions, benchmark, ref_date, ref_close, made_at, due_date) "
                "VALUES (7, 3, 'IN', 'AAA', ?, 'AAA falls more than 5%', 'fall', 5, 'NIFTY 500', ?, 100.0, ?, ?)", [AAA, DAYS[4], datetime(2026, 11, 1, 9, 0), DAYS[10]])
    con.execute("INSERT INTO debates_s79 (debate_id, market, subject, symbol, created_at, status) VALUES (3, 'IN', 'AAA', 'AAA', ?, 'done')", [datetime(2026, 11, 1, 9, 0)])


def _decide(con, cid, action="HOLD", extra=None):
    a = {"action": action, "symbol": "AAA", "reason": "the business is intact after the results, price flat [call 11] [call 12]", "alternatives": "sell; reduce", "review_condition": "the next results",
         "_prov": {"pass_id": 501, "task_id": 9001, "role": "quant", "model": "claude-sonnet-x"}}
    a.update(extra or {})
    out = manager.decide(con, NOW, cid, a, _idx())
    assert out["stored"], out
    return out["decision_id"]


def _sources(con, did):
    return {(r[0], r[1]): r[2:] for r in con.execute("SELECT source_kind, source_id, role, weight, direction, supports FROM decision_provenance_s79 WHERE decision_id=?", [did]).fetchall()}


def _scored(con, cid, did):
    _review(con, cid, "approve")
    manager.execute(con, datetime(2026, 11, 2, 12, 0), cid)
    assert manager.score_due(con, datetime(2026, 12, 3, 21, 0), _idx()) >= 1


def test_the_decision_stores_the_sources_behind_it(con, rt):
    _seed(con)
    cid = _mission(con, rt)
    _world(con, cid)
    did = _decide(con, cid)
    s = _sources(con, did)
    assert s[("tool:decompose_move", "11")][:2] == ("cited", 1.0) and s[("tool:trajectory", "12")][:2] == ("cited", 1.0)
    assert s[("tool:breadth", "13")][1] == 0.0                                       # run in the pass, not cited: listed, no credit
    assert ("tool:decompose_move", "14") not in s                                    # a call about another name is not this decision's evidence
    assert s[("bear_warning", "7")][:4] == ("warning", 1.0, -1, False)               # a HOLD wants up: the bear stood against it
    assert s[("forecaster:momentum", "2")][2:] == (1, True) and s[("forecaster:meanrev", "3")][2:] == (-1, False)
    assert s[("forecaster:hedge", "1")][1] == 1.0 and s[("forecaster:tiny", "4")][1] == 0.01
    assert s[("agent:quant", "9001")][0] == "deciding" and s[("agent:research", "9002")][1] == 0.5 and s[("model:claude-sonnet-x", "501")][0] == "speaker"
    assert ("debate", "3") in s


def test_the_outcome_is_credited_with_the_right_sign_and_once(con, rt):
    _seed(con)
    cid = _mission(con, rt)
    _world(con, cid)
    did = _decide(con, cid)
    _scored(con, cid, did)
    cr = {r[0]: r[1:] for r in con.execute("SELECT source_kind, outcome, hit, contribution, gain_pct FROM source_credit_s79 WHERE decision_id=? AND horizon_days=28", [did]).fetchall()}
    assert cr["bear_warning"][0] == "bad" and cr["bear_warning"][1] is True and cr["bear_warning"][2] > 0           # the HOLD lagged: the bear was right
    assert cr["forecaster:meanrev"][1] is True and cr["forecaster:momentum"][1] is False and cr["forecaster:momentum"][2] < 0
    assert cr["tool:decompose_move"][1] is False and cr["agent:quant"][1] is False and "tool:breadth" not in cr      # backed a decision that failed; weight-0 rows not credited
    assert "forecaster:tiny" not in cr and cr["forecaster:hedge"][1] is False
    assert abs(cr["bear_warning"][2] + cr["forecaster:momentum"][2]) < 1e-9 and cr["bear_warning"][3] == cr["forecaster:momentum"][3] < 0     # same gain, opposite sign of credit
    n = con.execute("SELECT count(*) FROM source_credit_s79").fetchone()[0]
    again = pv.credit_scored(con, datetime(2026, 12, 4, 9, 0))
    manager.score_due(con, datetime(2026, 12, 4, 9, 0), _idx())
    assert again["credited"] == 0 and con.execute("SELECT count(*) FROM source_credit_s79").fetchone()[0] == n          # re-scoring adds nothing
    sc = {(r[0], r[1]): r[2:] for r in con.execute("SELECT source_kind, decision_kind, n, hits FROM source_scorecard_s79 WHERE horizon_days=28").fetchall()}
    assert sc[("bear_warning", "all")] == (1, 1)
    assert sc[("bear_warning", "hold")] == (1, 1) and sc[("forecaster:momentum", "hold")] == (1, 0)


def test_the_review_joins_and_is_credited_on_a_refusal(con, rt):
    _seed(con)
    cid = _mission(con, rt)
    _world(con, cid)
    did = _decide(con, cid, "WAIT", {"symbol": None, "isin": None, "reason": "valuations are high across the market today; keep cash [call 11]", "alternatives": "buy the index now"})
    _review(con, cid, "reject")
    manager.execute(con, datetime(2026, 11, 2, 12, 0), cid)
    r = con.execute("SELECT role, weight, supports FROM decision_provenance_s79 WHERE decision_id=? AND source_kind='agent:review'", [did]).fetchone()
    assert r == ("verdict", 1.0, False)                                              # the review stood against it
    manager.score_due(con, datetime(2026, 12, 3, 21, 0), _idx())
    hit = con.execute("SELECT hit FROM source_credit_s79 WHERE decision_id=? AND source_kind='agent:review' AND horizon_days=7", [did]).fetchone()[0]
    assert hit is True                                                               # the market beat cash: waiting was wrong, refusing it was right


def test_small_n_shows_the_count_only_and_the_lines_say_so(con, rt):
    _seed(con)
    cid = _mission(con, rt)
    _world(con, cid)
    did = _decide(con, cid)
    _scored(con, cid, did)
    sc = pv.scorecard(con, "IN")
    row = next(r for r in sc["rows"] if r["source_kind"] == "bear_warning" and r["decision_kind"] == "all")
    assert row["n"] == 1 and "hits" not in row and "hit_rate" not in row and "count, not a conclusion" in row["note"]
    ls = pv.lines(con, "IN")
    assert any(l.startswith("The bear stood behind 1 scored decision(s) before holds") and "too few" in l for l in ls)


def test_enough_decisions_give_rates_and_the_plain_lines(con):
    for i in range(23):                                                              # 23 credited decisions before sells: the bear right on 14; transmission right on 11
        for sk, right in (("bear_warning", i < 14), ("transmission", i < 11)):
            con.execute("INSERT INTO source_credit_s79 VALUES (?, 'IN', ?, '1', 28, 'trim', ?, true, ?, 2.0, ?, NULL, now())", [i + 1, sk, "good" if right else "bad", right, 2.0 if right else -2.0])
    pv.rebuild_scorecard(con, "IN")
    row = next(r for r in pv.scorecard(con, "IN")["rows"] if r["source_kind"] == "bear_warning" and r["decision_kind"] == "trim")
    assert row["n"] == 23 and row["hits"] == 14 and row["hit_rate"] == round(14 / 23, 3) and row["skeptical_rate"] is not None and row["mean_outcome_pct"] == round((14 * 2.0 - 9 * 2.0) / 23, 2)
    ls = pv.lines(con, "IN")
    assert "The bear was right on 14 of 23 warnings before sells." in ls
    assert "Transmission misled on 12 of 23 decisions before sells and was right on 11." in ls
    assert pv.line_for("bear_warning", "trim", 5, 3, 20).startswith("The bear stood behind 5 scored decision(s) before sells")      # under 20 no rate
    assert "managers" not in pv.dossier_text(con) and pv.dossier_text(con).startswith("WHICH SOURCES WERE RIGHT")


def test_the_credit_reaches_the_knowledge_graph_with_its_evidence(con, rt):
    _seed(con)
    cid = _mission(con, rt)
    _world(con, cid)
    did = _decide(con, cid)
    _scored(con, cid, did)
    rows = con.execute("SELECT src, rel, dst, source_kind, source_ref, attrs_json FROM kg_edges WHERE source_kind='provenance' AND rel IN ('was_right_on','misled_on')").fetchall()
    by = {(r[0], r[1]) for r in rows}
    assert ("source:bear_warning", "was_right_on") in by and ("source:forecaster:momentum", "misled_on") in by
    one = next(r for r in rows if r[0] == "source:bear_warning" and r[4].endswith(":h28"))
    assert one[2] == f"paper_decision:{did}" and json.loads(one[5])["outcome"] == "bad" and json.loads(one[5])["supported"] is False


def test_a_store_without_the_tables_a_failing_recorder_or_the_switch_off_never_block_a_decision(con, rt, monkeypatch):
    _seed(con)
    cid = _mission(con, rt)
    con.execute("DROP TABLE decision_provenance_s79")
    assert _decide(con, cid) and pv.record(con, NOW, 1, cid) == 0                    # tables gone: nothing recorded, the decision stands
    monkeypatch.setattr(pv, "_record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    con.execute("CREATE TABLE decision_provenance_s79 (decision_id INTEGER)")
    assert _decide(con, cid, "WAIT", {"symbol": None, "isin": None, "reason": "valuations are high across the market today; keep cash", "alternatives": "buy the index now"})
    monkeypatch.setattr(pv, "settings", lambda: {**pv.DEFAULTS, "on": False})
    assert pv.record(con, NOW, 1, cid) == 0 and pv.credit_scored(con, NOW) == {"credited": 0, "decisions": 0} and pv.dossier_text(con) == ""


def test_missing_situation_forecast_and_debate_tables_are_tolerated(con, rt):
    _seed(con)
    cid = _mission(con, rt)
    for t in ("forecasts_s79", "bear_warnings_s79", "debates_s79"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    did = _decide(con, cid)
    assert not [k for k in _sources(con, did) if k[0].startswith(("forecaster", "bear"))]
    assert pv.chain(con, did)["found"] is True


def test_situation_claims_and_chains_are_read_when_present(con, rt):
    _seed(con)
    cid = _mission(con, rt)
    con.execute("INSERT INTO situation_report (report_id, market, as_of, created_at) VALUES (5, 'IN', ?, ?)", [DAYS[4], datetime(2026, 11, 1, 20, 0)])
    con.execute("INSERT INTO situation_chain (chain_id, report_id, market, as_of, chain_type, links, ok, created_at) VALUES (1, 5, 'IN', ?, 'transmission', ?, true, ?)",
                [DAYS[4], json.dumps([{"from": "oil", "to": "AAA", "direction": "down"}]), NOW])
    con.execute("INSERT INTO situation_chain (chain_id, report_id, market, as_of, chain_type, links, ok, created_at) VALUES (2, 5, 'IN', ?, 'transmission', ?, true, ?)",
                [DAYS[4], json.dumps([{"from": "oil", "to": "OTHER", "direction": "up"}]), NOW])
    con.execute("INSERT INTO situation_claim (claim_id, market, kind, subject, value, entities, as_of, created_at) VALUES (9, 'IN', 'sentiment', 'AAA tone', 0.4, 'AAA', ?, ?)",
                [DAYS[4], datetime(2026, 11, 1, 20, 0)])
    did = _decide(con, cid)
    s = _sources(con, did)
    assert s[("transmission", "1")][2:] == (-1, False) and ("transmission", "2") not in s                  # only the chain that names the stock; down vs a HOLD: against
    assert s[("claim:sentiment", "9")][2:] == (1, True) and s[("situation_report", "5")][1] == 0.0


def test_the_provenance_tool_gives_the_chain_and_the_scorecard(con, rt):
    from pflab.hq.tools_s79 import t_provenance as tp
    _seed(con)
    cid = _mission(con, rt)
    _world(con, cid)
    did = _decide(con, cid)
    _scored(con, cid, did)
    ctx = SimpleNamespace(con=con, call_ref=77)
    one = tp.provenance(ctx, {"decision_id": did})
    assert one["found"] and one["call_id"] == 77 and one["n_sources"] >= 8
    bear = next(s for s in one["sources"] if s["source_kind"] == "bear_warning")
    assert bear["supports_decision"] is False and bear["credit"][0]["source_was_right"] is True
    allx = tp.provenance(ctx, {})
    assert allx["decisions_with_provenance"] == 1 and allx["decisions_credited"] == 1 and allx["scorecard"] and allx["lines"] and allx["min_n"] == 20
    assert tp.provenance(SimpleNamespace(con=con, call_ref=1), {"horizon_days": 7})["horizon_days"] == 7
    assert tp.TOOLS[0].name == "provenance" and tp.TOOLS[0].kind == "read"


def test_the_tool_is_off_with_the_switch(con, monkeypatch):
    from pflab.hq.tools_s79 import t_provenance as tp
    monkeypatch.setattr(pv, "settings", lambda: {**pv.DEFAULTS, "on": False})
    assert tp.provenance(SimpleNamespace(con=con, call_ref=None), {}) == {"off": True}


def test_the_weekly_dossier_carries_the_block_only_once_something_is_credited(con, rt):
    _seed(con)
    cid = _mission(con, rt)
    _world(con, cid)
    assert "WHICH SOURCES WERE RIGHT" not in manager.dossier_text(con, cid, NOW)
    did = _decide(con, cid)
    _scored(con, cid, did)
    assert "WHICH SOURCES WERE RIGHT" in manager.dossier_text(con, cid, datetime(2026, 12, 4, 9, 0))
    from pflab.hq import scorecard
    assert scorecard.sources(con)["lines"]
