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
from tests.test_s76_paper import AAA, DAYS, _review, _seed, con  # noqa: F401  (the fixtures and helpers)

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


def test_the_tool_is_off_with_the_switch(con, monkeypatch):
    from pflab.hq.tools_s79 import t_provenance as tp
    monkeypatch.setattr(pv, "settings", lambda: {**pv.DEFAULTS, "on": False})
    assert tp.provenance(SimpleNamespace(con=con, call_ref=None), {}) == {"off": True}

