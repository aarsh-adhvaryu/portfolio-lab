"""S76 learner families (docs/protocols/s76_learner_protocol.md) on synthetic data: the fall group with its confirmation window, the gold series across its ISIN
change and unit split, the rebalancing paths with charges and tax, the worst-fall guard, and the twelve claims registered once with words that fit their tests."""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from pflab.learner import claims, s76
from pflab.learner import templates as tp
from pflab.pm import store


def test_the_fall_group_needs_the_fall_to_have_lasted_the_whole_window():
    idx = pd.bdate_range("2015-01-01", periods=400)
    a = np.r_[np.full(300, 100.0), np.full(100, 60.0)]                       # 40% down from session 300 on
    b = np.r_[np.full(300, 100.0), np.full(10, 60.0), np.full(90, 100.0)]    # down for ten sessions only
    w = {"adj": pd.DataFrame({"A": a, "B": b}, index=idx)}
    f0, f20 = tp.fall_frame(w, 30, 0), tp.fall_frame(w, 30, 20)
    assert f0["A"].iloc[300] == 1.0 and f20["A"].iloc[300] == 0.0 and f20["A"].iloc[320] == 1.0
    assert f0["B"].iloc[305] == 1.0 and f20["B"].iloc[315] == 0.0                # ten sessions are not a confirmed fall
    assert np.isnan(f0["A"].iloc[100])                                          # under 200 sessions of history: cannot tell


def test_the_gold_series_removes_the_unit_split_and_joins_the_two_isins(monkeypatch):
    frames = {"INF732E01102": pd.DataFrame({"date": pd.to_datetime(["2019-12-17", "2019-12-18", "2019-12-19"]), "close": [3350.0, 3360.0, 33.6]}),
              "INF204KB17I5": pd.DataFrame({"date": pd.to_datetime(["2019-12-20", "2019-12-23"]), "close": [33.7, 34.0]})}

    class Q:
        def __init__(self, q):
            self.q = q

        def df(self):
            return next(v for k, v in frames.items() if k in self.q).copy()
    monkeypatch.setattr(tp._duck, "sql", lambda q: Q(q))
    g = tp.gold_series(tp.Path("x"))
    assert g.iloc[-1] / g.iloc[0] == pytest.approx(34.0 * 100 / 3350.0) and (g.pct_change().abs().dropna() < 0.02).all()      # returns run through the change


def _assets(n=2400, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2010-01-01", periods=n)
    eq = pd.Series(100 * np.cumprod(1 + rng.normal(0.0005, 0.011, n)), index=idx)
    gd = pd.Series(100 * np.cumprod(1 + rng.normal(0.0003, 0.009, n)), index=idx)
    return eq, gd


def test_rebalancing_pays_charges_and_tax_and_never_touching_pays_none():
    eq, gd = _assets()
    never = tp.rebalance_path(eq, gd, "60_20_20", "never")
    monthly = tp.rebalance_path(eq, gd, "60_20_20", "monthly")
    cash = 20 * (1 + tp.REB_CASH_PA) ** (len(eq) / 252)
    expect_never = 60 * eq.iloc[-1] / eq.iloc[0] + 20 * gd.iloc[-1] / gd.iloc[0] + cash
    assert never.iloc[-1] == pytest.approx(expect_never, rel=1e-6)
    assert len(monthly) == len(never) and monthly.iloc[-1] != pytest.approx(never.iloc[-1])
    flat = pd.Series(100.0, index=eq.index)
    assert tp.rebalance_path(flat, flat, "70_30_0", "band", 5, "daily").iloc[-1] == pytest.approx(100.0)   # nothing drifts: nothing is traded


def test_the_band_test_passes_or_fails_by_the_rule_and_the_worst_fall_guard():
    eq, gd = _assets(n=3200)
    out = tp.rebalance_bands(tp.Path("x"), "60_20_20", 10, "never", "month_end", periods=(("2010-01-01", "2017-12-31"), ("2018-01-01", "2022-04-30")),
                             eq=eq, gold=gd)
    assert out["decision"] in ("pass", "fail") and out["development"]["n"] >= 36 and "worst_fall_pct" in out["validation"]
    assert "_returns" in out["development"]


def test_twelve_claims_are_registered_once_and_their_words_fit_their_tests(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    now = datetime(2026, 11, 2, 22, 0)
    out = s76.register_all(con, tmp_path / "proto", now)
    assert len(out) == 12 and all("registered" in v for v in out.values())
    assert len(s76.register_all(con, tmp_path / "proto", now)) == 12
    assert con.execute("SELECT count(*) FROM learn_claims").fetchone()[0] == 12
    for c, q, t, p in con.execute("SELECT claim, quote, template, params_json FROM learn_claims").fetchall():
        assert claims.fits(c, q, t, __import__("json").loads(p)), c
        assert tp.check_params(t, __import__("json").loads(p)) is None
