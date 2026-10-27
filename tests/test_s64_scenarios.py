"""S64 Phase 5 item 6: scenario chains from historical betas."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pflab.risk import capm, scenarios as sn

ASOF = date(2026, 9, 30)
IDX = pd.date_range("2018-01-31", "2026-09-30", freq="ME")


def make(beta_stock=2.0, beta_mkt=0.5, seed=3):
    rng = np.random.default_rng(seed)
    f = pd.Series(rng.normal(0, 0.06, len(IDX)), index=IDX)
    mkt = beta_mkt * f + rng.normal(0, 0.02, len(IDX))
    stock = beta_stock * f + rng.normal(0, 0.03, len(IDX))
    return f, mkt, stock


def test_beta_se_recovers_the_slope_and_refuses_short_history():
    f, _m, stock = make()
    b, se, n = sn.beta_se(stock, f)
    assert b == pytest.approx(2.0, abs=0.35) and 0 < se < 0.5 and n == 60
    assert sn.beta_se(stock.iloc[:20], f.iloc[:20]) is None


@pytest.fixture
def patched(monkeypatch):
    f, mkt, stock = make()
    monkeypatch.setattr(sn, "factor_returns", lambda root, factor, asof: f)
    monkeypatch.setattr(capm, "stock_returns", lambda root, isin, asof, years=12: stock)
    monkeypatch.setattr(capm, "for_isin", lambda root, isin, asof, table=None: {"beta": 1.2, "beta_se": 0.1, "n": 60})
    monkeypatch.setattr(capm, "_series", lambda df: pd.Series(1.0, index=IDX))
    monkeypatch.setattr(capm, "monthly_returns", lambda s: mkt if len(s) == len(IDX) and s.nunique() == 1 else pd.Series(dtype=float))
    from pflab.data import indices
    monkeypatch.setattr(indices, "load", lambda key, root=None: pd.DataFrame({"date": IDX, "close": 1.0}))
    return f, mkt, stock


HOLD = [{"isin": "INE000A01011", "symbol": "AAA", "bucket": "equity", "value": 100_000.0},
        {"isin": "INF000A01011", "symbol": "FUND", "bucket": "equity_fund", "value": 50_000.0},
        {"isin": "IN0000000001", "symbol": "GOLD", "bucket": "gold", "value": 30_000.0}]


def test_direct_path(patched):
    r = sn.run(None, "x", ASOF, "oil_up_30", HOLD)
    rows = {x["symbol"]: x for x in r["rows"]}
    assert rows["AAA"]["impact"] == pytest.approx(100_000 * rows["AAA"]["beta"] * 0.30)
    assert rows["AAA"]["beta"] == pytest.approx(2.0, abs=0.4) and rows["FUND"]["beta"] == pytest.approx(0.5, abs=0.2)  # fund = the index
    assert [n["symbol"] for n in r["not_modelled"]] == ["GOLD"]
    lo, hi = r["total_range"]
    assert lo < r["total"] < hi and r["note"].startswith("from historical betas")


def test_via_market_path_goes_through_the_market_and_the_capm_beta(patched):
    r = sn.run(None, "x", ASOF, "us_crash", HOLD)
    mb = float(patched[1].corr(patched[0]) * patched[1].std() / patched[0].std())          # the market's beta to the factor
    rows = {x["symbol"]: x for x in r["rows"]}
    assert rows["AAA"]["impact"] == pytest.approx(100_000 * 1.2 * mb * -0.20, rel=0.05)    # CAPM beta 1.2 x market move
    assert rows["FUND"]["impact"] == pytest.approx(50_000 * 1.0 * mb * -0.20, rel=0.05)
    assert "Nifty 500" in r["chain"] and r["total"] < 0
