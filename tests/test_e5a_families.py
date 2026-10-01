"""E5-A families A1 (issuer events, §6b) and A3 (world exposure, §6d).

Lookahead first: an event usable after M, or a factor value public after M,
cannot change M's features. Then the A1 subtype rules decided 2026-09-30
(K -> UNCLEAR; L's NOT_EVENT excluded; unread refuses), the §6 [D 6]
activation rule (inactive -> A0's decisions exactly), and that a family
changes only the columns (§3). Synthetic; nothing reads PFLAB_DATA_DIR.
"""
import copy
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from conftest import random_walk_panel
from pflab import _toml
from pflab.ranker import events as ev, exposure as ex, family, features as ft
from pflab.ranker import labels as lb, model as mdl, store, walk
from pflab.signals import shock_betas as sb

ASSIGN = {f: "K" for f in ev.FLAGS}
ASSIGN.update({"DEFAULT": "L", "FORENSIC_AUDIT": "L", "REGULATORY_ACTION": "L"})


def _mes(start="2009-01-31", n=48):
    return [d.date() for d in pd.date_range(start, periods=n, freq="ME")]


def _events(rows):
    return pd.DataFrame([{"isin": i, "scrip_code": "5000", "company": "X Ltd", "flag": f,
                          "key_dt": pd.Timestamp(u), "key_source": "DissemDT",
                          "usable_from": u, "headline": h, "category": "", "subcategory": ""}
                         for i, f, u, h in rows],
                        columns=["isin", "scrip_code", "company", "flag", "key_dt",
                                 "key_source", "usable_from", "headline", "category",
                                 "subcategory"])


SMAP = pd.DataFrame({"scrip_code": ["5000", "5001"], "isin": ["INA", "INB"],
                     "valid_from": pd.to_datetime(["2000-01-01", "2012-06-01"]),
                     "valid_to": pd.to_datetime(["2099-01-01", "2099-01-01"])})


def _a1(raw, reads, mes, end=None):
    end = end or mes[-1]
    e = ev.subtyped(raw, ASSIGN, reads, end)
    uni = {m: ["INA", "INB"] for m in mes if m <= end}
    return ft.to_wide(ev.a1_features(e, uni, mes, SMAP, ASSIGN), ev.feature_names(ASSIGN))


# -- A1 ------------------------------------------------------------------
def test_an_event_usable_after_M_cannot_change_Ms_features():
    mes = _mes()
    m = mes[30]
    base = [("INA", "FRAUD", mes[20], "a"), ("INA", "FRAUD", mes[29] + timedelta(days=3), "b")]
    late = base + [("INA", "FRAUD", m + timedelta(days=1), "c"),
                   ("INA", "INSOLVENCY", mes[40], "d")]
    a, b = _a1(_events(base), {}, mes), _a1(_events(late), {}, mes)
    pd.testing.assert_frame_equal(a.loc[(slice(None, m),), :], b.loc[(slice(None, m),), :])
    assert not a.loc[(mes[31],), :].equals(b.loc[(mes[31],), :])


def test_k_events_are_unclear_and_counted_by_window():
    mes = _mes()
    m = mes[30]
    raw = _events([("INA", "FRAUD", mes[29] + timedelta(days=5), "a"),   # in 1m
                   ("INA", "FRAUD", mes[27] + timedelta(days=1), "b"),   # in 3m
                   ("INA", "FRAUD", mes[20], "c")])                      # in 12m
    w = _a1(raw, {}, mes).loc[(m, "INA")]
    assert (w["ev_fraud_unclear_1m"], w["ev_fraud_unclear_3m"],
            w["ev_fraud_unclear_12m"], w["ev_fraud_unclear_since"]) == (1, 2, 3, 0)
    assert not any(c.startswith("ev_fraud_at_company") for c in ev.feature_names(ASSIGN))


def test_l_subtypes_not_event_excluded_and_unread_refuses():
    mes = _mes()
    when = (mes[29], mes[28], mes[27] + timedelta(days=1))     # all inside (M_-3, M]
    raw = _events([("INA", "DEFAULT", u, h) for u, h in zip(when, "xyz")])
    ids = [ev.event_id("5000", pd.Timestamp(u), "DEFAULT", h) for u, h in zip(when, "xyz")]
    with pytest.raises(ValueError, match="no reading"):
        ev.subtyped(raw, ASSIGN, {ids[0]: "AT_COMPANY"}, mes[-1])
    reads = {ids[0]: "AT_COMPANY", ids[1]: "NOT_EVENT", ids[2]: "garbage"}
    w = _a1(raw, reads, mes).loc[(mes[30], "INA")]
    assert w["ev_default_at_company_3m"] == 1
    assert w["ev_default_unclear_3m"] == 1           # an invalid reply is UNCLEAR
    assert w[[c for c in w.index if c.startswith("ev_default")
              and c.endswith("_3m")]].sum() == 2     # NOT_EVENT is not counted


def test_missing_is_not_zero_coverage_and_the_2010_window():
    mes = _mes()
    w = _a1(_events([]), {}, mes)
    col = "ev_fraud_unclear_12m"
    # INB's scrip resolves only from 2012-06-01
    assert np.isnan(w.loc[(date(2012, 5, 31), "INB"), col])
    assert w.loc[(date(2012, 6, 30), "INB"), col] == 0
    # nothing is available until the 12-month window lies after 2010-01-01
    assert np.isnan(w.loc[(date(2010, 11, 30), "INA"), col])
    assert w.loc[(date(2010, 12, 31), "INA"), col] == 0
    # no event: months-since is censored at the feed's start (a lower bound)
    assert w.loc[(date(2010, 12, 31), "INA"), "ev_fraud_unclear_since"] == 11


def test_a1_config_columns_are_the_builders():
    c = _toml.load("configs/e5a_a1.toml")
    assert c["e5a"]["a1"]["reader"] == ASSIGN
    assert family.family_features(c) == ev.feature_names(ASSIGN)
    assert len(ev.feature_names(ASSIGN)) == 6 * 4 + 3 * 4 * 4


# -- A3 ------------------------------------------------------------------
def _a3_world():
    rng = np.random.default_rng(3)
    days = pd.bdate_range("2008-01-01", "2014-12-31")
    mes = sorted({d.date() for d in pd.Series(days).groupby(days.to_period("M")).max()})
    close = pd.DataFrame(np.exp(np.cumsum(rng.normal(0, 0.01, (len(days), 3)), 0)) * 100,
                         index=[d.date() for d in days], columns=["I1", "I2", "I3"])
    ser = {k: pd.Series(np.exp(np.cumsum(rng.normal(0, 0.01, len(days)))) * 50,
                        index=[d.date() for d in days])
           for k in list(ex.FACTORS) + [ex.INDEX]}
    uni = {m: ["I1", "I2", "I3"] for m in mes if m.year >= 2010}
    return close, ser, uni, mes


def test_a3_factor_after_M_cannot_change_M():
    close, ser, uni, mes = _a3_world()
    m = date(2012, 6, 29) if date(2012, 6, 29) in mes else [x for x in mes if x.year == 2012][5]
    a = ft.to_wide(ex.a3_features(close, ser, uni, mes, mes[-1]), ex.feature_names())
    ser2 = copy.deepcopy(ser)
    for k in ("brent", "usdinr", "us10y", "fii"):           # printed after 15:30 IST
        ser2[k].loc[m] = ser2[k].loc[m] * 3                  # M's own print: usable M+1
    ser2["india_vix"].loc[[d for d in ser2["india_vix"].index if d > m]] *= 5
    b = ft.to_wide(ex.a3_features(close, ser2, uni, mes, mes[-1]), ex.feature_names())
    pd.testing.assert_frame_equal(a.loc[(slice(None, m),), :], b.loc[(slice(None, m),), :])
    assert not a.equals(b)


def test_a3_beta_is_the_ols_slope_and_needs_24_months():
    close, ser, uni, mes = _a3_world()
    w = ft.to_wide(ex.a3_features(close, ser, uni, mes, mes[-1]), ex.feature_names())
    m = mes[-1]
    rets = sb.monthly_returns(close, mes)
    f = sb.month_end_values(ex.usable(ser["india_vix"], 0, m), mes, "diff")
    y, x = rets["I1"].loc[:m].iloc[-36:], f.reindex(rets.index).loc[:m].iloc[-36:]
    ok = y.notna() & x.notna()
    want = np.polyfit(x[ok], y[ok], 1)[0]
    assert w.loc[(m, "I1"), "beta_india_vix"] == pytest.approx(want, rel=1e-9)
    first = min(k for k in uni)            # 2010-01: 24 monthly returns from 2008-02
    assert w.loc[(first, "I1")].notna().any()
    assert w.loc[(first, "I1"), "beta_india_vix_x_chg3"] == pytest.approx(
        w.loc[(first, "I1"), "beta_india_vix"] *
        ex.changes(ex.usable(ser["india_vix"], 0, first), mes, "diff", 3).loc[first])


def test_a3_config_columns_are_the_builders():
    c = _toml.load("configs/e5a_a3.toml")
    assert family.family_features(c) == ex.feature_names()
    assert (c["e5a"]["a3"]["window_months"], c["e5a"]["a3"]["min_obs"]) == (ex.WINDOW, ex.MIN_OBS)


# -- a family changes only the columns (§3) ---------------------------------
def test_family_configs_differ_from_a0_only_in_columns_and_family_blocks():
    a0 = _toml.load("configs/e5a_a0.toml")
    for p in ("configs/e5a_a1.toml", "configs/e5a_a2.toml", "configs/e5a_a3.toml"):
        c = _toml.load(p)
        base = family.base_config(c)
        assert store.identity(base) == store.identity(a0)
        strip = lambda d: {k: v for k, v in d.items() if k != "report"}
        e0 = {k: v for k, v in a0["e5a"].items() if k != "family"}
        e1 = {k: v for k, v in base["e5a"].items() if k != "family"}
        assert e0 == e1
        assert {k: v for k, v in strip(base).items() if k != "e5a"} == \
            {k: v for k, v in strip(a0).items() if k != "e5a"}
        assert walk.spec_from_config(a0).family == ()


@pytest.fixture(scope="module")
def world():
    sessions, names, panel = random_walk_panel(seed=5, n_names=30, start="2011-01-01",
                                               end="2018-12-31", tick=0.05)
    cfg = {"strategy": {"lookback_sessions": 252, "skip_sessions": 21,
                        "signal": "precomputed", "fallback_signal": "vol_scaled_6_12",
                        "score_windows": [126, 252], "score_order": "average_then_z",
                        "delist_confirm_sessions": 250, "delisting": "last_close"},
           "universe": {"series": ["EQ"], "min_sessions": 250, "top_n_by_turnover": 500,
                        "turnover_window": 126, "min_price": 10.0},
           "e5a": {"family": "A0", "features": list(ft.A0_FEATURES),
                   "horizons": [1, 3, 12], "refit": "annual", "min_cross_sections": 12,
                   "fixed": {"num_iterations": 20, "bagging_fraction": 0.8,
                             "bagging_freq": 1, "feature_fraction": 0.8},
                   "params": {"num_leaves": 4, "min_data_in_leaf": 5, "learning_rate": 0.1}}}
    uni = ft.universe_by_month(panel, cfg)
    feats = ft.a0_features(panel, cfg, uni)
    labels = lb.build_labels(panel, cfg, uni)
    # a family column available from 2014-01 on, noise
    rng = np.random.default_rng(1)
    fam = feats[feats["feature"] == "mom_1m"].copy()
    fam["feature"] = "fam_x"
    fam["value"] = rng.normal(size=len(fam))
    fam["available"] = [m >= date(2014, 1, 1) for m in fam["month_end"]]
    fam.loc[~fam["available"], "value"] = np.nan
    return {"cfg": cfg, "uni": uni, "labels": labels,
            "feats": pd.concat([feats, fam], ignore_index=True)}


def test_an_inactive_family_decides_exactly_as_a0(world):
    cols = tuple(ft.A0_FEATURES) + ("fam_x",)
    fw = ft.to_wide(world["feats"], cols)
    mes = sorted(world["uni"])
    months = [m for m in mes if m.year >= 2014]
    a0 = walk.spec_from_config(world["cfg"])
    c = copy.deepcopy(world["cfg"])
    c["e5a"]["features"] = list(cols)
    c["e5a"]["activation"] = {"min_cross_sections": 12, "min_coverage": 0.5}
    fam = walk.spec_from_config(c)
    assert fam.family == ("fam_x",)
    assert walk.a0_spec(fam) == walk.Spec(**{**a0.__dict__, "activation": fam.activation})
    w = walk.Walk(fw, world["labels"], world["uni"], mes)
    ra, rf = w.score(a0, months), w.score(fam, months)
    off = [m for m in months if not rf["info"][m].get("family_active")]
    on = [m for m in months if rf["info"][m].get("family_active")]
    assert off and on and max(off) < min(on)
    for m in off:
        if m in ra["scores"]:
            pd.testing.assert_series_equal(ra["scores"][m], rf["scores"][m])
    # active from a refit whose training set holds >= 12 covered cross-sections
    R = rf["info"][min(on)]["refit"]
    assert all(v >= 12 for v in w.family_active(fam, R)["covered_cross_sections"].values())
    # and never active when the threshold is out of reach
    never = walk.Spec(**{**fam.__dict__, "activation": (10_000, 0.5)})
    assert not any(i.get("family_active") for i in w.score(never, months)["info"].values())


# -- A2 (§6c as amended 2026-10-01) ------------------------------------------
from pflab.data import positioning as pos  # noqa: E402
from pflab.ranker import holdings as ho  # noqa: E402


def _summary(rows):
    """rows: (scrip, quarter_end, filed or None, promoter_shares, promoter_pct,
    pledged_pct_of_promoter, shares_outstanding_reported)"""
    return pd.DataFrame([{"scrip_code": s, "quarter_end": q, "status": "ok",
                          "filing_date": pd.Timestamp(f) if f else pd.NaT,
                          "promoter_shares": ps, "promoter_pct": pp,
                          "pledged_pct_of_promoter": pl,
                          "shares_outstanding_reported": so,
                          "shares_outstanding_derived": np.nan}
                         for s, q, f, ps, pp, pl, so in rows])


RES = pos.ScripResolver(SMAP.assign(valid_from=pd.to_datetime(["2000-01-01", "2000-01-01"])))
Q = [("5000", "2015-12-31", "2016-01-20 10:00", 600.0, 60.0, 10.0, 1000.0),
     ("5000", "2016-03-31", "2016-04-20 10:00", 550.0, 55.0, 20.0, 1000.0),
     ("5000", "2016-06-30", "2016-07-20 16:00", 1000.0, 50.0, 25.0, 2000.0)]


def _a2(rows, actions=None, mes=(date(2016, 5, 31), date(2016, 7, 29), date(2016, 8, 31))):
    pr = ho.pairs(ho.quarters(_summary(rows)), actions, RES.all_isins())
    st = ho.a2_features(pr, {m: ["INA", "INB"] for m in mes}, RES)
    return ft.to_wide(st, ho.feature_names())


def test_a2_quarter_usable_after_M_cannot_change_M_and_after_1530_is_next_day():
    a = _a2(Q)
    b = _a2(Q + [("5000", "2016-09-30", "2016-08-31 16:00", 1.0, 1.0, 99.0, 9.0)])
    pd.testing.assert_frame_equal(a, b)          # filed 16:00 on M: usable after M
    # the Jul quarter, filed 16:00 on 2016-07-20, is read at 07-29, not before
    assert a.loc[(date(2016, 5, 31), "INA"), "pledge_pct"] == 20.0
    assert a.loc[(date(2016, 7, 29), "INA"), "pledge_pct"] == 25.0


def test_a2_values_split_restated_and_unexplained_share_change():
    acts = pd.DataFrame({"isin": ["INA"], "ex_date": [date(2016, 5, 15)],
                         "factor": [0.5], "source": ["purpose"]})   # 1:1 split
    w = _a2(Q, acts)
    r = w.loc[(date(2016, 8, 31), "INA")]
    assert r["prom_shares_chg_1q"] == pytest.approx((1000 - 550 * 2) / 2000)
    assert r["prom_pct_chg_1q"] == pytest.approx(-5.0)
    assert r["pledge_pct_chg_2q"] == pytest.approx(15.0)
    assert r["so_unexplained_chg_1q"] == pytest.approx(0.0)       # the split explains it
    w0 = _a2(Q)                                                     # no action recorded
    assert w0.loc[(date(2016, 8, 31), "INA"), "so_unexplained_chg_1q"] == pytest.approx(1.0)


def test_a2_missing_pair_is_nan_never_substituted_and_uncovered_is_nan():
    w = _a2([Q[0], Q[2]])                       # the March quarter is missing
    r = w.loc[(date(2016, 8, 31), "INA")]
    assert np.isnan(r["prom_shares_chg_1q"]) and np.isnan(r["pledge_pct_chg_1q"])
    assert r["prom_pct_chg_2q"] == pytest.approx(-10.0)
    assert r["pledge_pct"] == 25.0
    assert w.loc[(date(2016, 8, 31), "INB")].isna().all()          # no quarter: not zero


def test_a2_config_columns_are_the_builders():
    c = _toml.load("configs/e5a_a2.toml")
    assert family.family_of(c) == "A2"
    assert family.family_features(c) == ho.feature_names()
    assert c["e5a"]["a2"]["quarters"] == list(ho.QUARTERS)
