"""S85 replay3: a MARKET/MACRO case is scored on its index's path (think/score.py proxy_closes), and the three replays' drills (tools/replays_s85.py) pass."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from pflab.think import cases, score, watch

from tests.test_s84_integration import (CLOSE_AT, DAY, _world, con, extend, open_case_on, orders)  # noqa: F401  (the fixtures)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))


def _index(days, level0=1000.0, daily=0.001):
    return pd.Series([level0 * (1 + daily) ** k for k in range(len(days))], index=pd.to_datetime(days))


def _market_case_with_decision(con, isin, sym, option, kind="market"):
    cid = open_case_on(con, isin, sym, kind=kind, signal="market_down_20d", value=-0.12, exposure=500000.0)
    now = CLOSE_AT + timedelta(minutes=40)
    cases.add_step(con, cid, now, "answer_ok", payload={"answer": {"choices": [{"symbol": sym, "option": option, "reason": "scripted"}], "class": "market_fear",
                                                                  "likelihood": {"worst": "unlikely", "likely": "likely", "best": "unlikely"}}})
    cases.add_option(con, cid, now, track="rule", isin=isin, symbol=sym, option=option, worst_inr=-30000.0, likely_inr=2000.0, best_inr=40000.0, expected_inr=3000.0, worst_pct_book=0.01, size_inr=0.0, chosen=True)
    cases.add_option(con, cid, now, track="model", isin=isin, symbol=sym, option=option, worst_inr=-30000.0, likely_inr=2000.0, best_inr=40000.0, expected_inr=3000.0, worst_pct_book=0.01, size_inr=0.0, chosen=True)
    cases.add_option(con, cid, now, track="alt", isin=isin, symbol=sym, option="buy_in_parts", worst_inr=-60000.0, likely_inr=5000.0, best_inr=90000.0, expected_inr=6000.0, worst_pct_book=0.02, size_inr=0.0)
    cases.record_decision(con, cid, DAY, isin=isin, symbol=sym, rule_option=option, model_option=option, acted_option=option, reason="scripted")
    return cid


def test_proxy_closes_reads_the_index_the_pseudo_name_stands_for_and_nothing_after_the_day(con, monkeypatch):
    days = [d.date() for d in pd.bdate_range("2026-01-01", periods=80)]
    monkeypatch.setattr(watch, "_index", lambda market, root=None: _index(days) if market == "IN" else None)
    s = score.proxy_closes(con, "MARKET:IN", "Nifty 500", days[40])
    assert len(s) == 41 and s.index[-1] == pd.Timestamp(days[40])                    # point in time
    assert score.proxy_closes(con, "MARKET:US", "S&P 500", days[40]).empty             # no stored series: empty, never an error
    assert score.proxy_closes(con, "INE000B01012", "BBB", days[40]).empty             # not a pseudo-name


def test_a_market_case_is_scored_at_5_and_20_sessions_on_the_index_path(con, monkeypatch):
    days = extend(con, 25)
    allday = [d for d in pd.bdate_range("2026-09-01", days[-1])]
    ix = pd.Series([1000.0] * len(allday), index=allday)
    ix[ix.index > pd.Timestamp(DAY)] = [1000.0 * 1.004 ** k for k in range(1, int((ix.index > pd.Timestamp(DAY)).sum()) + 1)]     # the index recovers after the decision day
    monkeypatch.setattr(watch, "_index", lambda market, root=None: ix if market == "IN" else None)
    cid = _market_case_with_decision(con, "MARKET:IN", "Nifty 500", "wait")
    assert score.score_due(con, days[-1]) > 0
    rows = con.execute("SELECT horizon_sessions, track, option, result_inr, vs_nothing_inr FROM think_scores_s84").fetchall()
    assert {h for h, *_ in rows} == {5, 20}
    by = {(h, t, o): (r, v) for h, t, o, r, v in rows}
    assert by[(20, "rule", "wait")][1] == pytest.approx(0.0, abs=1e-6)                 # waiting is the baseline
    assert by[(20, "alt", "buy_in_parts")][1] > 0                                       # the index rose: buying would have beaten waiting
    n = len(rows)
    score.score_due(con, days[-1])
    assert con.execute("SELECT count(*) FROM think_scores_s84").fetchone()[0] == n     # once only
    assert cid


def test_a_macro_case_is_scored_on_its_stored_series(con, monkeypatch):
    days = extend(con, 12)
    allday = pd.bdate_range("2026-09-01", days[-1])
    ser = pd.Series([80.0 + 0.2 * k for k in range(len(allday))], index=allday)
    from pflab.story import series
    monkeypatch.setattr(series, "load", lambda key, root=None: ser if key == "USDINR" else None)
    cid = _market_case_with_decision(con, "MACRO:USDINR", "the dollar-rupee", "nothing", kind="overnight")
    score.score_due(con, days[-1])
    rows = con.execute("SELECT horizon_sessions, track, option FROM think_scores_s84").fetchall()
    assert (5, "rule", "nothing") in rows and cid


def test_without_a_stored_series_a_market_case_is_not_scored_and_nothing_breaks(con, monkeypatch):
    days = extend(con, 12)
    monkeypatch.setattr(watch, "_index", lambda market, root=None: None)
    _market_case_with_decision(con, "MARKET:IN", "Nifty 500", "wait")
    assert score.score_due(con, days[-1]) == 0
