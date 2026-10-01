"""E5-A A5 valuation (§6(f), §14 2026-10-01): dating, TTM, restatement, store."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pflab.data import positioning as pos
from pflab.ranker import valuation as va


def test_quarter_end_ids():
    assert va.quarter_end(26) == date(2000, 6, 30)
    assert va.quarter_end(27) == date(2000, 9, 30)
    assert va.quarter_end(29) == date(2001, 3, 31)
    assert va.quarter_end(66) == date(2010, 6, 30)


def test_usable_from_rule():
    # announcement before the deadline: the deadline wins (never earlier than the law)
    assert va.usable_from(date(2012, 9, 30), pd.Timestamp("2012-10-20 10:00")) == \
        (date(2012, 11, 14), "announcement")
    # March quarter: 60 days
    assert va.usable_from(date(2012, 3, 31), None)[0] == date(2012, 6, 29)
    assert va.usable_from(date(2012, 3, 31), pd.Timestamp("2012-05-01 10:00"))[0] == date(2012, 5, 30)
    # announcement after the deadline, after 15:30: the next day
    assert va.usable_from(date(2012, 9, 30), pd.Timestamp("2012-11-20 16:00"))[0] == date(2012, 11, 21)


def test_unmatched_is_90_days():
    assert va.usable_from(date(2008, 12, 31), np.nan) == (date(2009, 3, 31), "unmatched_90")


def test_matched_announcements_window_and_category():
    rq = pd.DataFrame({"scrip_code": ["1", "1"], "quarter_end": [date(2012, 9, 30), date(2012, 12, 31)]})
    ann = pd.DataFrame({
        "scrip_code": ["1", "1", "1", "1"],
        "t": ["2012-09-15 10:00", "2012-10-05 10:00", "2012-10-25 10:00", "2013-02-01 10:00"],
        "category": [None, None, None, "Result"], "subcategory": [None, None, None, "Financial Results"],
        "headline": ["Results for June quarter", "Board meeting", "Unaudited results for September 2012",
                     "Outcome"]})
    m = va.matched_announcements(ann, rq).set_index("quarter_end")["announced"]
    assert m[date(2012, 9, 30)] == pd.Timestamp("2012-10-25 10:00")   # headline names month
    assert m[date(2012, 12, 31)] == pd.Timestamp("2013-02-01 10:00")  # category


def _dq(quarters, uf_days=50, eps=1.0, rev=100.0, np_=10.0):
    return pd.DataFrame({"scrip_code": "1", "quarter_end": quarters,
                         "revenue": rev, "net_profit": np_, "eps": eps,
                         "usable_from": [q + pd.Timedelta(days=uf_days).to_pytimedelta() for q in quarters],
                         "date_source": "announcement"})


QS = [(pd.Timestamp("2010-03-31") + pd.offsets.QuarterEnd(k)).date() for k in range(12)]


def test_ttm_needs_four_usable_quarters_and_never_substitutes():
    dq = _dq(QS)
    t = va.ttm_at(dq, date(2011, 3, 31)).iloc[0]       # latest usable: Dec 2010 (usable Feb 2011)
    assert t["quarter_end"] == date(2010, 12, 31)
    assert t["revenue_ttm"] == 400.0 and np.isnan(t["revenue_ttm_prev"])
    gap = dq.drop(index=2)                               # Sep 2010 missing
    t = va.ttm_at(gap, date(2011, 3, 31)).iloc[0]
    assert np.isnan(t["revenue_ttm"])                    # not filled from an older quarter
    t = va.ttm_at(dq, date(2012, 12, 31)).iloc[0]
    assert t["revenue_ttm"] == 400.0 and t["revenue_ttm_prev"] == 400.0


def test_pct_own_history():
    v = pd.DataFrame({"X": list(range(30)) + [np.nan] * 0})
    p = va._pct_own(v)
    assert np.isnan(p.iloc[22, 0]) and p.iloc[23, 0] == 1.0   # 24 values: highest = 1
    v.iloc[29, 0] = -1.0
    assert va._pct_own(v).iloc[29, 0] == pytest.approx(1 / 30)


def _panel(split_on=None):
    d = pd.bdate_range("2009-01-01", "2013-12-31")
    close = np.full(len(d), 100.0)
    adj = close.copy()
    if split_on is not None:                    # 2:1 split: close halves, adj history halves
        s = d.searchsorted(pd.Timestamp(split_on))
        close[s:] = 50.0
        adj[:s] = 50.0
        adj[s:] = 50.0
    return pd.DataFrame({"date": d.date, "isin": "INE1", "close": close, "adj_close": adj})


def _me(panel):
    s = pd.Series(pd.to_datetime(panel["date"]))
    return sorted(s.groupby(s.dt.to_period("M")).max().dt.date)


class _Res(pos.ScripResolver):
    def __init__(self):
        super().__init__(pd.DataFrame({"scrip_code": ["1"], "isin": ["INE1"],
                                       "valid_from": [pd.Timestamp("2000-01-01")],
                                       "valid_to": [pd.Timestamp("2030-01-01")]}))


def _store(split_on=None, divs=None):
    panel = _panel(split_on)
    mes = [m for m in _me(panel) if m.year >= 2010]
    dq = _dq(QS)
    shares = pd.DataFrame({"scrip_code": "1", "quarter_end": [date(2009, 12, 31)],
                           "usable_from": [date(2010, 1, 21)], "shares_outstanding": [1e6]})
    div = divs if divs is not None else pd.DataFrame(columns=["isin", "ex_date", "dividend_per_share"])
    f = va.a5_features(dq, div, shares, panel, {m: ["INE1"] for m in mes}, _Res())
    return f.pivot_table(index="month_end", columns="feature", values="value", aggfunc="first")


def test_store_values():
    w = _store(divs=pd.DataFrame({"isin": ["INE1"], "ex_date": [date(2011, 6, 1)],
                                  "dividend_per_share": [5.0]}))
    m = date(2011, 6, 30)
    assert w.loc[m, "ey_ttm"] == pytest.approx(4.0 / 100)
    assert w.loc[m, "sy_ttm"] == pytest.approx(400e6 / (1e6 * 100))
    assert w.loc[m, "dy_ttm"] == pytest.approx(5.0 / 100)
    assert np.isnan(w.loc[date(2011, 3, 31), "dy_ttm"])          # the feed-hole NaN window
    assert w.loc[date(2011, 4, 29), "dy_ttm"] == 0.0             # no dividend = 0
    assert va.DY_NAN[0][1] == date(2007, 12, 31)                 # thin feed before 2007
    assert w.loc[date(2012, 6, 29), "rev_ttm_yoy"] == 0.0
    assert list(w.columns.sort_values()) == sorted(va.COLUMNS) or set(w.columns) <= set(va.COLUMNS)


def test_eps_restated_through_a_split():
    w = _store(split_on="2011-05-02")
    # EPS of 1/quarter before the split is 0.5 on the new basis; close is 50
    assert w.loc[date(2011, 6, 30), "ey_ttm"] == pytest.approx(4 * 0.5 / 50)
    assert w.loc[date(2011, 6, 30), "sy_ttm"] == pytest.approx(400e6 / (2e6 * 50))


def test_values_do_not_depend_on_other_names():
    """Point in time across stores: adding a name (and its extra sessions)
    must not change another name's values."""
    base = _panel(split_on="2011-05-02")
    extra = pd.DataFrame({"date": [date(2011, 6, 25)], "isin": "INE2",       # a Saturday session
                          "close": [10.0], "adj_close": [10.0]})
    mes = [m for m in _me(base) if m.year >= 2010]
    dq = _dq(QS)
    shares = pd.DataFrame({"scrip_code": "1", "quarter_end": [date(2009, 12, 31)],
                           "usable_from": [date(2010, 1, 21)], "shares_outstanding": [1e6]})
    div = pd.DataFrame(columns=["isin", "ex_date", "dividend_per_share"])
    a = va.a5_features(dq, div, shares, base, {m: ["INE1"] for m in mes}, _Res())
    b = va.a5_features(dq, div, shares, pd.concat([base, extra]),
                       {m: ["INE1"] + (["INE2"] if m == mes[-1] else []) for m in mes}, _Res())
    b = b[b["isin"] == "INE1"].reset_index(drop=True)
    pd.testing.assert_series_equal(a["value"], b["value"])
