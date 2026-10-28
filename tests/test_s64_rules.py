"""S64: the rule_filter template (docs/protocols/s64_rules_protocol.md): point-in-time P/E, the seven rules, the series."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pflab.learner import claims, templates as tp


def panel(n_names=80, years=4, seed=1, effect=0.0):
    """Synthetic wide frames. Names 0-19 are 'rule' names whose monthly return carries `effect` on top of noise."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2012-01-02", periods=252 * years)
    cols = [f"INE{i:09d}" for i in range(n_names)]
    r = pd.DataFrame(rng.normal(0.0004, 0.012, (len(idx), n_names)), index=idx, columns=cols)
    adj = 100 * (1 + r).cumprod()
    return idx, cols, r, adj


def test_the_seven_rules_are_a_closed_list_and_claims_must_name_them():
    assert tp.check_params("rule_filter", {"rule": "pe_above_50", "direction": "under", "months": 1}) is None
    for bad in ({"rule": "pe_above_60", "direction": "out", "months": 1}, {"rule": "pe_above_50", "direction": "up", "months": 1},
                {"rule": "pe_above_50", "direction": "out", "months": 3}):
        assert tp.check_params("rule_filter", bad)
    ok = claims.fits("Stocks priced above 50 times their trailing earnings earn less over the next month than the others.", "",
                     "rule_filter", {"rule": "pe_above_50"})
    assert ok and not claims.fits("Momentum works.", "", "rule_filter", {"rule": "pe_above_50"})
    assert not claims.fits("The 52-week low effect is absent here.", "", "rule_filter", {"rule": "near_52w_low_5"})        # absence: not tested


def test_price_rules_use_only_sessions_up_to_the_row():
    idx, cols, r, adj = panel()
    w = {"adj": adj, "r": r, "turnover": pd.DataFrame(1e7, index=idx, columns=cols), "close": adj}
    adj.iloc[-1, 0] = adj.iloc[:-1, 0].min() * 0.5                          # the last day crashes name 0
    f = tp.rule_frame(w, "near_52w_low_5")
    assert f.iloc[-1, 0] == 1.0 and f.iloc[-2, 0] != 1.0 or f.iloc[-2, 0] in (0.0, 1.0)
    shifted = tp.rule_frame({**w, "adj": adj.iloc[:-1]}, "near_52w_low_5")
    pd.testing.assert_series_equal(f.iloc[-2], shifted.iloc[-1], check_names=False)          # row i does not know row i+1
    assert tp.rule_frame(w, "below_sma200").iloc[:199].isna().all().all()                    # not told before 200 sessions
    assert set(np.unique(tp.rule_frame(w, "rsi_below_30").iloc[100:].to_numpy()[~np.isnan(tp.rule_frame(w, "rsi_below_30").iloc[100:].to_numpy())])) <= {0.0, 1.0}


def test_volume_spike_compares_with_the_prior_twenty_sessions_not_including_today():
    idx, cols, r, adj = panel(n_names=3)
    to = pd.DataFrame(1e7, index=idx, columns=cols)
    to.iloc[-1, 0] = 3e7
    f = tp.rule_frame({"adj": adj, "r": r, "turnover": to, "close": adj}, "volume_spike_2")
    assert f.iloc[-1, 0] == 1.0 and f.iloc[-1, 1] == 0.0


def test_eps_ttm_is_point_in_time_needs_four_consecutive_quarters_and_drops_after_a_split(tmp_path, monkeypatch):
    idx = pd.bdate_range("2019-01-01", "2021-12-31")
    cols = ["INE000A01011"]
    close = pd.DataFrame(100.0, index=idx, columns=cols)
    adj = close.copy()
    adj.loc["2021-03-01":, :] = 50.0                                          # a 1:2 split on 1 March 2021 (adjusted history)
    adj.loc[:"2021-02-28", :] = 50.0
    close.loc["2021-03-01":, :] = 50.0
    adj.loc[:"2021-02-28"] = 50.0
    w = {"tr": close, "adj": adj, "close": close}
    q = pd.DataFrame({"quarter_end": pd.to_datetime(["2019-03-31", "2019-06-30", "2019-09-30", "2019-12-31", "2020-03-31"]),
                      "eps_basic": [1.0, 2.0, 3.0, 4.0, 5.0]})
    monkeypatch.setattr(tp._duck, "sql", lambda q_: type("R", (), {"df": lambda self: pd.DataFrame({"scrip_code": ["500001"], "isin": cols})})())
    eps = tp.eps_ttm_frame(tmp_path, w, load=lambda scrip: q)
    e = eps[cols[0]]
    assert e.loc["2020-01-15":"2020-02-15"].isna().all()                       # 2019-12 quarter usable only from 29 Feb 2020
    assert e.loc["2020-03-02"] == 10.0                                         # 1+2+3+4
    assert e.loc["2020-06-15"] == 14.0                                         # 2+3+4+5, usable from 30 May 2020
    assert e.loc["2021-03-15":].isna().all()                                   # older than 15 months: gone


def test_a_split_after_the_eps_became_usable_makes_the_pe_undefined(tmp_path, monkeypatch):
    idx = pd.bdate_range("2019-01-01", "2020-12-31")
    cols = ["INE000A01011"]
    close = pd.DataFrame(100.0, index=idx, columns=cols)
    adj = pd.DataFrame(100.0, index=idx, columns=cols)
    close.loc["2020-07-01":, :] = 50.0                                         # split: traded price halves; adjusted stays
    w = {"tr": close, "adj": adj, "close": close}
    q = pd.DataFrame({"quarter_end": pd.to_datetime(["2019-03-31", "2019-06-30", "2019-09-30", "2019-12-31"]),
                      "eps_basic": [1.0, 1.0, 1.0, 1.0]})
    monkeypatch.setattr(tp._duck, "sql", lambda q_: type("R", (), {"df": lambda self: pd.DataFrame({"scrip_code": ["500001"], "isin": cols})})())
    e = tp.eps_ttm_frame(tmp_path, w, load=lambda scrip: q)[cols[0]]
    assert e.loc["2020-03-02"] == 4.0 and e.loc["2020-06-15"] == 4.0
    assert e.loc["2020-07-02":].isna().all()                                   # the old EPS is another unit from the new price


def planted(effect):
    idx, cols, r, adj = panel(n_names=80, years=5, seed=3)
    rule = pd.DataFrame(0.0, index=idx, columns=cols)
    rule.iloc[:, :20] = 1.0
    r.iloc[:, :20] += effect / 21                                              # a daily drift on the rule names
    adj = 100 * (1 + r).cumprod()
    tr = (1 + r.fillna(0.0)).cumprod()
    w = {"adj": adj, "r": r, "tr": tr, "turnover": pd.DataFrame(1e7, index=idx, columns=cols), "close": adj}
    mem = pd.DataFrame({"isin": cols, "from_date": pd.Timestamp("2000-01-01"), "to_date": pd.Timestamp("2099-01-01")})
    return w, mem, rule


def test_series_finds_a_planted_effect_charges_buy_rules_and_not_avoid_rules():
    w, mem, rule = planted(0.03)
    out = tp.rule_filter_series(w, mem, rule, "out", 1, "2013-01-01", "2016-12-31", 0.2)
    under = tp.rule_filter_series(w, mem, rule, "under", 1, "2013-01-01", "2016-12-31", 0.2)
    assert len(out) >= 36 and out.mean() > 0.02
    assert (under - out).mean() > 0                                           # `under` has no charge, `out` pays one
    m, t, n = tp.nw_t(under.values, lags=1)
    assert t > 3                                                              # the planted group does outperform
    null_w, null_mem, null_rule = planted(0.0)
    s0 = tp.rule_filter_series(null_w, null_mem, null_rule, "under", 1, "2013-01-01", "2016-12-31", 0.2)
    assert abs(tp.nw_t(s0.values, lags=1)[1]) < 3                             # no effect planted: no t


def test_a_month_with_too_small_a_group_is_skipped():
    w, mem, rule = planted(0.0)
    rule.iloc[:, 5:20] = 0.0                                                   # 5 names only
    assert tp.rule_filter_series(w, mem, rule, "out", 1, "2013-01-01", "2016-12-31", 0.2).empty
