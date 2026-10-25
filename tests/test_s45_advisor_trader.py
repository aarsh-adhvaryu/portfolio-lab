"""S45: split / limit study functions, advisor allocation, trader tickets. SYNTHETIC."""
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pflab.plan import advisor, trader
from pflab.quant import execution_study as es


def test_plan_prices_by_hand():
    # prev close 100; sessions: open/low/close
    o, lo, c = [101, 99.7, 98, 100, 100], [100.2, 99.4, 97.5, 99, 99], [100, 99.8, 98.5, 100, 101]
    p = es.plan_prices(100.0, o, lo, c)
    assert p["A"] == 100 and p["B5"] == pytest.approx(np.mean(c))
    assert p["L0.5"] == pytest.approx(99.5)            # low 99.4 on session 2 reaches 99.5
    assert p["L1"] == pytest.approx(98.0)              # session 3 opens at 98, already below 99: filled at the open
    assert p["L2"] == pytest.approx(98.0)              # low 97.5 reaches 98 on session 3 (open 98 not below 98)
    never = es.plan_prices(100.0, [100] * 5, [99.9] * 5, [100, 101, 102, 103, 104])
    assert never["L1"] == 104                          # never filled: all at the close of session 5


def test_savings_and_decision_on_a_synthetic_panel():
    days = pd.bdate_range("2015-01-01", "2015-03-31")
    rows = []
    for isin in ("A", "B"):
        for k, d in enumerate(days):
            px = 100 + 0.1 * k
            rows.append({"date": d, "isin": isin, "open": px, "low": px * 0.985, "close": px, "adj_factor": 1.0})
    panel = pd.DataFrame(rows)
    mem = pd.DataFrame({"isin": ["A", "B"], "from_date": pd.Timestamp("2010-01-01"), "to_date": pd.Timestamp("2099-01-01")})
    sv = es.savings(panel, mem, pd.date_range("2015-01-01", "2015-03-01", freq="MS"))
    assert len(sv) == 4 and (sv["L1"] > 0).all()        # January has no prior close; a 1% limit fills at 1.5%-deep lows
    s = es.summarise(sv)
    assert s["L1"]["mean_bps"] > 50 and s["B5"]["mean_bps"] < 0      # rising prices: splitting costs
    d = es.decide(s, s)
    assert d["chosen_on_dev"] in ("L0.5", "L1") and d["adopted"] == d["chosen_on_dev"]
    weak = {k: {**v, "t": 1.0} for k, v in s.items()}
    assert es.decide(s, weak)["adopted"] is None


def test_advisor_fills_underweights_within_caps():
    alloc = advisor.allocate(100.0, {"X": 0.0, "Y": 50.0, "Z": 200.0}, target_each=100.0, cap_value=80.0)
    assert alloc == pytest.approx({"X": 100 * 80 / 110, "Y": 100 * 30 / 110, "Z": 0.0})
    cands = [{"symbol": "X", "isin": "IX"}, {"symbol": "Y", "isin": "IY"}]
    adv = advisor.advise(1000.0, cands, {"Y": 300.0}, {"X": 90.0, "Y": 45.0}, bucket_target_value=1400.0,
                         investable=10_000.0, asof=date(2026, 10, 17), skipped=["Z (fail)"])
    # share 700 each (under the 800 cap); shortfalls 700 and 400 share Rs 1,000: 636.4 -> 7 x 90, 363.6 -> 8 x 45
    q = {b.symbol: b.qty for b in adv.buys}
    assert q == {"X": 7, "Y": 8} and adv.unspent == pytest.approx(1000 - 7 * 90 - 8 * 45)
    assert advisor.advise(500.0, [], {}, {}, 1000.0, 10_000.0, date(2026, 10, 17)).unspent == 500.0
    assert "Z (fail)" in advisor.render(adv)


def test_trader_tickets_follow_the_study(tmp_path):
    assert trader.decision(tmp_path) is None
    assert "has not run yet" in trader.tickets("X", 10, 101.37, None)[0]
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "split_study.json").write_text(json.dumps({"decision": {"adopted": "L1"}}))
    assert trader.decision(tmp_path) == "L1"
    t = trader.tickets("X", 10, 101.37, "L1")[0]
    assert "LIMIT 100.35" in t and "5 sessions" in t                        # 101.37 x 0.99 = 100.356 -> tick 100.35
    assert "[2, 2, 2, 2, 2]" in trader.tickets("X", 10, 100.0, "B5")[0]
    (tmp_path / "research" / "split_study.json").write_text(json.dumps({"decision": {"adopted": None}}))
    assert trader.decision(tmp_path) == "" and "no reliably cheaper" in trader.tickets("X", 1, 50.0, "")[0]
