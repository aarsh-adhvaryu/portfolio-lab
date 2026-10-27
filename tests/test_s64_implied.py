"""S64: option-implied probabilities: smile fit, Breeden-Litzenberger, kept daily, scored when due."""
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from pflab.quant import implied, options

D = date(2026, 10, 26)


def chain(vol=0.18, F=24_000.0, days=30, r=0.07, skew=0.0, thin_noise=False):
    """A chain priced with Black-76 from a known smile; optionally a few thin strikes with nonsense prices."""
    e = D + timedelta(days=days)
    T = days / 365
    rows = [dict(date=D, symbol="NIFTY", instrument="FUT", kind="index", expiry=e, option=None, strike=np.nan, close=F, settle=F,
                 prev_close=F, underlying=F / math.exp(r * T), oi=1e6, oi_change=0.0, contracts=100.0, lot=75.0)]
    for k in np.arange(F * 0.80, F * 1.20 + 1, 200.0):
        m = math.log(k / F)
        v = vol + skew * (-m)
        for cp in ("CE", "PE"):
            px = options.black76(F, k, T, r, v, cp == "CE")
            rows.append(dict(date=D, symbol="NIFTY", instrument="OPT", kind="index", expiry=e, option=cp, strike=float(k), close=px, settle=px,
                             prev_close=px, underlying=F / math.exp(r * T), oi=5000.0, oi_change=0.0, contracts=10.0, lot=75.0))
    df = pd.DataFrame(rows)
    if thin_noise:
        bad = df.index[(df["option"] == "PE") & (df["strike"].between(F * 0.93, F * 0.95))]
        df.loc[bad, "settle"] *= 3.0
        df.loc[bad, "oi"] = 1.0                               # thin: little weight in the fit
    return df, F, T, r


def test_flat_smile_gives_the_lognormal_probabilities():
    c, F, T, r = chain()
    out = implied.day(c, D, r)
    spot = F / math.exp(r * T)
    for lv in (-0.10, -0.05):
        K = spot * (1 + lv)
        d2 = (math.log(F / K) - 0.5 * 0.18 ** 2 * T) / (0.18 * math.sqrt(T))
        assert out[f"p_below_{abs(int(lv * 100))}"] == pytest.approx(norm.cdf(-d2), abs=0.004)
    assert out["atm_iv"] == pytest.approx(0.18, abs=0.002) and abs(out["skew_90_110"]) < 0.005


def test_a_put_skew_puts_more_weight_on_falls():
    flat = implied.day(chain()[0], D, 0.07)
    skewed = implied.day(chain(skew=0.5)[0], D, 0.07)
    assert skewed["p_below_10"] > flat["p_below_10"] and skewed["skew_90_110"] > 0.05


def test_probabilities_are_ordered_and_thin_strikes_do_not_break_them():
    out = implied.day(chain(thin_noise=True)[0], D, 0.07)
    assert out["p_below_20"] <= out["p_below_15"] <= out["p_below_10"] <= out["p_below_5"] <= 1.0
    assert 0.0 <= out["p_above_10"] <= out["p_above_5"]


def test_no_expiry_in_range_or_too_few_strikes_gives_nothing():
    assert implied.day(chain(days=5)[0], D, 0.07) is None
    c = chain()[0]
    assert implied.day(c[c["instrument"] == "FUT"], D, 0.07) is None


def test_scoring_against_the_close_at_expiry(tmp_path, monkeypatch):
    from pflab.data import indices
    rows = pd.DataFrame([{"date": D, "expiry": D + timedelta(days=30), "spot": 100.0, **{f"p_below_{x}": 0.1 for x in (20, 15, 10, 5)},
                          **{f"p_above_{x}": 0.1 for x in (5, 10)}},
                         {"date": D + timedelta(days=1), "expiry": D + timedelta(days=90), "spot": 100.0,
                          **{f"p_below_{x}": 0.5 for x in (20, 15, 10, 5)}, **{f"p_above_{x}": 0.5 for x in (5, 10)}}])
    (tmp_path / "derived").mkdir()
    rows.to_parquet(tmp_path / "derived" / implied.FILE, index=False)
    idx = pd.bdate_range(D, D + timedelta(days=40))
    monkeypatch.setattr(indices, "load", lambda key, root=None: pd.DataFrame({"date": idx, "close": 93.0}))      # 7% lower
    s = implied.scorecard(tmp_path)
    assert s["scored"] == 1 and s["expiries"] == 1                         # the 90-day row is not due yet
    assert s["levels"]["below_5"]["happened"] == 1.0 and s["levels"]["below_10"]["happened"] == 0.0
    assert s["levels"]["below_5"]["brier"] == pytest.approx(0.81) and s["levels"]["below_10"]["brier"] == pytest.approx(0.01)
