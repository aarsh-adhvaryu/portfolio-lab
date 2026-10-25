"""D1/D2 data repairs (E1 §15, 2026-09-27): synthetic cases for each rule."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from pflab.data import repairs

D = [date(2020, 1, 1) + timedelta(days=i) for i in range(40)]


def rows(isin, sym, dates, closes, series="EQ", prev=None):
    closes = list(closes)
    pc = prev if prev is not None else [closes[0]] + closes[:-1]
    return pd.DataFrame({"date": dates, "isin": isin, "symbol": sym, "series": series,
                         "instrument_type": "STK", "open": closes, "high": closes,
                         "low": closes, "close": closes, "prev_close": pc,
                         "volume": 1, "turnover": 1e7, "adj_factor": 1.0,
                         "adj_close": closes, "adj_open": closes, "dividend": 0.0})


def acts(*r):
    return pd.DataFrame([{"isin": i, "ex_date": e, "factor": f, "source": s,
                          "prior_close": pc, "adj_prev_close": ap} for i, e, f, s, pc, ap in r],
                        columns=["isin", "ex_date", "factor", "source", "prior_close",
                                 "adj_prev_close"])


def test_d2_drift_factor_dropped_and_be_rows_priced():
    eq = pd.concat([rows("A", "AAA", D[:10], [100.0] * 10),
                    rows("A", "AAA", D[20:30], [80.0] * 10, prev=[80.0] * 10)])
    be = rows("A", "AAA", D[10:20], np.linspace(99, 80, 10), series="BE")
    a = acts(("A", D[20], 0.8, "prevclose", 100.0, 80.0))
    p, a2, rep = repairs.apply(eq, a, be)
    assert rep["d2_factors_dropped"] == 1 and len(a2) == 0
    assert rep["d2_be_rows_inserted"] == 10
    s = p[p["isin"] == "A"].set_index("date")
    assert (s["adj_factor"] == 1.0).all()             # no action left
    assert s.loc[D[15], "series"] == "BE" and s.loc[D[15], "close"] < 100


def test_d2_rebase_when_nse_adjusted_on_return():
    eq = pd.concat([rows("A", "AAA", D[:10], [100.0] * 10),
                    rows("A", "AAA", D[20:30], [40.0] * 10, prev=[45.0] + [40.0] * 9)])
    be = rows("A", "AAA", D[10:20], [90.0] * 10, series="BE")
    a = acts(("A", D[20], 0.45, "prevclose", 100.0, 45.0))
    p, a2, rep = repairs.apply(eq, a, be)
    assert rep["d2_factors_rebased"] == 1
    r = a2.iloc[0]
    assert r["factor"] == pytest.approx(0.5) and r["prior_close"] == 90.0


def test_d2_demerger_on_entry_to_be_is_an_action():
    eq = rows("A", "AAA", D[:10], [300.0] * 10)
    be = rows("A", "AAA", D[10:20], [15.0] * 10, series="BE", prev=[300.0] + [15.0] * 9)
    p, a2, rep = repairs.apply(eq, acts(), be)
    assert rep["d2_transition_actions"] == 1
    j = a2.iloc[0]
    assert j["ex_date"] == D[10] and j["factor"] == pytest.approx(0.05)
    assert j["source"] == "prevclose"
    s = p.set_index("date")["adj_close"]
    assert s[D[9]] == pytest.approx(15.0)             # continuous adjusted series


def test_d2_normal_entry_move_is_not_an_action():
    eq = rows("A", "AAA", D[:10], [100.0] * 10)
    be = rows("A", "AAA", D[10:20], [95.0] * 10, series="BE", prev=[100.0] + [95.0] * 9)
    _, a2, rep = repairs.apply(eq, acts(), be)
    assert rep["d2_transition_actions"] == 0 and len(a2) == 0


def test_d1_rekey_pure_isin_change():
    p0 = pd.concat([rows("OLD", "X", D[:10], [100.0] * 10),
                    rows("NEW", "X", D[10:20], [100.0] * 10)])
    a = acts(("OLD", D[5], 0.5, "purpose", np.nan, np.nan))
    p, a2, rep = repairs.apply(p0, a, None)
    assert rep["d1_handovers"] == 1 and set(p["isin"]) == {"NEW"}
    assert list(a2["isin"]) == ["NEW"]
    assert p[p.date < D[5]]["adj_factor"].eq(0.5).all()


def test_d1_unrecorded_split_added_as_action():
    p0 = pd.concat([rows("OLD", "X", D[:10], [100.0] * 10),
                    rows("NEW", "X", D[10:20], [50.0] * 10, prev=[50.0] * 10)])
    p, a2, rep = repairs.apply(p0, acts(), None)
    assert rep["d1_split_factors_added"] == 1
    assert a2.iloc[0]["factor"] == 0.5 and a2.iloc[0]["ex_date"] == D[10]
    s = p.set_index("date")["adj_close"]
    assert s[D[9]] == pytest.approx(50.0)


def test_d1_non_standard_jump_rejected_and_left_alone():
    p0 = pd.concat([rows("OLD", "X", D[:10], [100.0] * 10),
                    rows("NEW", "X", D[10:20], [37.0] * 10, prev=[37.0] * 10)])
    p, _, rep = repairs.apply(p0, acts(), None)
    assert rep["d1_handovers"] == 0 and len(rep["d1_rejected"]) == 1
    assert set(p["isin"]) == {"OLD", "NEW"}


def test_d1_skips_etfs_and_overlapping_lives():
    etf = pd.concat([rows("OLD", "E", D[:10], [100.0] * 10),
                     rows("NEW", "E", D[10:20], [100.0] * 10)]).assign(instrument_type="ETF")
    assert repairs.apply(etf, acts(), None)[2]["d1_handovers"] == 0
    both = pd.concat([rows("OLD", "X", D[:15], [100.0] * 15),
                      rows("NEW", "X", D[10:20], [100.0] * 10)])
    assert repairs.apply(both, acts(), None)[2]["d1_handovers"] == 0


def test_future_prices_only_rescale_the_past():
    """A price change after T moves adj_close before T by at most a constant
    per ISIN, so no ratio a decision reads at or before T changes."""
    eq = pd.concat([rows("A", "AAA", D[:10], [100.0] * 10),
                    rows("A", "AAA", D[20:30], [80.0] * 10, prev=[80.0] * 10)])
    be = rows("A", "AAA", D[10:20], np.linspace(99, 80, 10), series="BE")
    a = acts(("A", D[20], 0.8, "prevclose", 100.0, 80.0))
    base = repairs.apply(eq, a, be)[0]
    eq2 = eq.copy()
    late = eq2["date"] >= D[25]
    eq2.loc[late, ["open", "close"]] *= 3.0
    alt = repairs.apply(eq2, a, be)[0]
    T = D[24]
    x = base[base.date <= T].set_index("date")["adj_close"]
    y = alt[alt.date <= T].set_index("date")["adj_close"]
    ratio = (x / y).round(12)
    assert ratio.nunique() == 1


def test_engine_never_buys_on_a_be_row():
    from conftest import random_walk_panel
    from test_engine_golden import _cfg, _wavy_index
    from pflab.backtest import engine
    from pflab.eval.periods import Period
    from pflab.execution.costs import CostModel
    from pflab.tax.india_lots import TaxPolicy
    sessions, _, panel = random_walk_panel(seed=11, n_names=40, start="2013-01-01",
                                           end="2016-12-31", annual_drift=0.08,
                                           sigma=0.02, tick=0.01)
    d = pd.to_datetime(panel["date"]).dt.date
    month = (d >= date(2015, 3, 1)) & (d <= date(2015, 3, 31))
    panel = panel.copy()
    panel.loc[month, "series"] = "BE"
    res = engine.run(_cfg("off"), Period("g", date(2014, 6, 1), date(2016, 12, 31)),
                     panel, _wavy_index(sessions),
                     CostModel.from_toml("configs/costs_zerodha.toml"),
                     TaxPolicy.from_toml("configs/tax_policy_in.toml"))
    buys = res.trades[res.trades.side == "BUY"]
    bd = pd.to_datetime(buys["date"]).dt.date
    assert len(buys) > 0
    assert not ((bd >= date(2015, 3, 1)) & (bd <= date(2015, 3, 31))).any()


def test_d2_dividend_inside_be_stint_is_credited():
    """2026-09-28: a dividend going ex on a BE row reaches the panel, so the
    engine credits it to a holder; one on a date with an action does not."""
    eq = pd.concat([rows("A", "AAA", D[:10], [100.0] * 10),
                    rows("A", "AAA", D[20:30], [100.0] * 10)])
    be = rows("A", "AAA", D[10:20], [100.0] * 10, series="BE")
    divs = pd.DataFrame({"isin": ["A", "A", "Z"], "ex_date": [D[14], D[16], D[14]],
                         "dividend_per_share": [2.5, 1.0, 9.0]})
    a = acts(("A", D[16], 0.5, "purpose", np.nan, np.nan))
    p, _, rep = repairs.apply(eq, a, be, None, divs)
    s = p[p["isin"] == "A"].set_index("date")["dividend"]
    assert s[D[14]] == 2.5 and s[D[16]] == 0.0 and rep["d2_be_dividends"] == 1
    assert s.drop([D[14]]).eq(0).all()


def test_d2_be_dividend_reaches_the_engine_dividend_map():
    from pflab.backtest.engine import _dividend_map
    eq = rows("A", "AAA", D[:10], [100.0] * 10)
    be = rows("A", "AAA", D[10:20], [100.0] * 10, series="BE")
    divs = pd.DataFrame({"isin": ["A"], "ex_date": [D[12]], "dividend_per_share": [3.0]})
    p, _, _ = repairs.apply(eq, acts(), be, None, divs)
    assert _dividend_map(p)[D[12]] == [("A", 3.0)]


def test_d2_stale_prev_close_on_return_to_eq_is_not_an_action():
    """GOLDTECH 2008-06-13 (2026-09-28): back in EQ, NSE's prev close is the
    last EQ close before the stint, not the last BE close. Not an action."""
    eq = pd.concat([rows("A", "AAA", D[:10], [224.8] * 10),
                    rows("A", "AAA", D[20:30], [239.3] * 10, prev=[224.8] + [239.3] * 9)])
    bc = list(np.linspace(218.0, 246.55, 10))
    be = rows("A", "AAA", D[10:20], bc, series="BE", prev=[224.8] + bc[:-1])
    _, a2, rep = repairs.apply(eq, acts(), be)
    assert rep["d2_transition_actions"] == 0 and len(a2) == 0
    # the same return with NSE's prev close at the BE close is not stale
    eq2 = pd.concat([eq.iloc[:10], rows("A", "AAA", D[20:30], [120.0] * 10,
                                        prev=[123.3] + [120.0] * 9)])
    _, a3, rep3 = repairs.apply(eq2, acts(), be)
    assert rep3["d2_transition_actions"] == 1


def test_d2_garbage_prev_close_on_entry_is_not_an_action():
    """ROHITFERRO 2008-06-13 (2026-09-28): entered BE with prev close 30.00
    against a 150.30 close and opened at 154.90. Not a 1:5 split."""
    eq = rows("A", "AAA", D[:10], [150.3] * 10)
    be = rows("A", "AAA", D[10:20], [154.9] * 10, series="BE", prev=[30.0] + [154.9] * 9)
    _, a2, rep = repairs.apply(eq, acts(), be)
    assert rep["d2_transition_actions"] == 0 and len(a2) == 0
    # an adjusted prev close the open agrees with is still an action
    be2 = rows("A", "AAA", D[10:20], [52.0] * 10, series="BE", prev=[50.1] + [52.0] * 9)
    _, a3, rep3 = repairs.apply(eq, acts(), be2)
    assert rep3["d2_transition_actions"] == 1
    assert a3.iloc[0]["factor"] == pytest.approx(50.1 / 150.3)
