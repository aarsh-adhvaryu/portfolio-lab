"""S79 item 11: option-implied calibration, the cascade reading and the session-horizon simulation (synthetic data throughout)."""
from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from pflab import markets
from pflab.hq import tools_s79
from pflab.hq.tools import Ctx
from pflab.pm import store
from pflab.quant import hawkes as hk
from pflab.quant import implied, implied_calibration as ic
from pflab.risk import montecarlo as mc

NOW = datetime(2025, 9, 30, 18, 0)


@pytest.fixture
def con(tmp_path):
    """Only this item's migration is applied (the store's other tables are not needed here, and a sibling item's migration is not this test's concern)."""
    import duckdb
    from pflab.pm.mig_s79 import m_implied
    c = duckdb.connect(str(tmp_path / "x.duckdb"))
    store.migrate(c, m_implied.MIGRATIONS)
    return c


def _ctx(con, root, now=NOW):
    rt = SimpleNamespace(data_root=root, cursor=lambda: con)
    return Ctx(rt=rt, pass_id=None, model="x", shadow=False, syms={}, gate=None, now=now)


def _tool(name):
    return next(t for t in tools_s79.collect() if t.name == name)


def _index(root, dates, closes, key="NIFTY50_PRICE"):
    (root / "indices").mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": pd.to_datetime(dates), "close": closes}).to_parquet(root / "indices" / f"{key}.parquet")


def _fill(con, rows):
    """rows: (asof, fall_pct, p_implied, outcome, expiry_no)"""
    for i, (d, lv, p, o, e) in enumerate(rows):
        con.execute("INSERT INTO implied_calibration_s79 VALUES ('IN',?,20,?,?,?,?,?,22000,22000)",
                    [d, lv, p, o, d, date(2025, 1, 1 + e % 28)])


def _obs(n, p, rate, seed=1):
    rng = np.random.default_rng(seed)
    out = (rng.uniform(size=n) < rate).astype(int)
    return [(date(2025, 1, 1), 10.0, p, int(out[i]), i) for i in range(n)]


def test_migration_74_creates_the_table(con):
    cols = [r[0] for r in con.execute("DESCRIBE implied_calibration_s79").fetchall()]
    for c in ("market", "asof", "horizon", "fall_pct", "p_implied", "outcome", "resolved_at"):
        assert c in cols


def test_calibration_map_direction(con):
    _fill(con, _obs(60, 0.20, 0.05))                       # options ran far above what happened
    r = ic.calibrated_fall_probability(con, "IN", date(2025, 3, 1), 20, 10.0)
    assert r["n"] == 60 and r["p_implied"] == pytest.approx(0.20, abs=1e-6)
    assert r["p_calibrated"] < r["p_implied"] * 0.6
    con.execute("DELETE FROM implied_calibration_s79")
    _fill(con, _obs(60, 0.05, 0.30, seed=2))               # options ran below what happened
    r = ic.calibrated_fall_probability(con, "IN", date(2025, 3, 1), 20, 10.0)
    assert r["p_calibrated"] > r["p_implied"]


def test_small_sample_gives_n_and_no_conclusion(con):
    _fill(con, _obs(10, 0.20, 0.0))
    r = ic.calibrated_fall_probability(con, "IN", date(2025, 3, 1), 20, 10.0)
    assert r["n"] == 10 and r["p_calibrated"] is None and r["p_implied"] == pytest.approx(0.2)
    assert "no conclusion" in r["note"]


def test_calibration_is_point_in_time(con):
    _fill(con, _obs(40, 0.20, 0.05))
    con.execute("UPDATE implied_calibration_s79 SET resolved_at = DATE '2025-06-01'")
    assert ic.calibrated_fall_probability(con, "IN", date(2025, 5, 1), 20, 10.0)["n"] == 0
    assert ic.calibrated_fall_probability(con, "IN", date(2025, 6, 2), 20, 10.0)["n"] == 40


def test_refresh_records_and_resolves_by_session_horizon(con, tmp_path):
    root = tmp_path / "data"
    (root / "derived").mkdir(parents=True)
    exp = date(2025, 2, 27)
    rows = [{"date": d, "expiry": exp, "days": (exp - d).days, "spot": 100.0, "p_below_5": 0.3, "p_below_10": 0.1, "p_below_15": 0.03, "p_below_20": 0.01}
            for d in (date(2025, 1, 29), date(2025, 2, 10))]
    pd.DataFrame(rows).to_parquet(root / "derived" / "implied_probs.parquet")
    days = pd.bdate_range("2025-01-20", "2025-03-10")
    close = pd.Series(100.0, index=days)
    close[close.index >= "2025-02-27"] = 92.0                  # an 8% fall by the expiry
    _index(root, close.index, close.to_numpy())
    r = ic.refresh(con, root, "IN", date(2025, 3, 5))
    assert r["added"] == 8 and r["resolved"] == 8
    got = {(str(a), lv): o for a, lv, o in con.execute("SELECT \"asof\", fall_pct, outcome FROM implied_calibration_s79").fetchall()}
    assert got[("2025-01-29", 5.0)] == 1 and got[("2025-01-29", 10.0)] == 0
    h = markets.get("IN").session_count(date(2025, 1, 29), exp)
    assert con.execute("SELECT min(horizon) FROM implied_calibration_s79 WHERE \"asof\"='2025-01-29'").fetchone()[0] == h
    assert ic.refresh(con, root, "IN", date(2025, 3, 5)) == {"added": 0, "resolved": 0}      # idempotent
    # not resolved before its horizon is known
    con.execute("DELETE FROM implied_calibration_s79")
    assert ic.refresh(con, root, "IN", date(2025, 2, 12))["resolved"] == 0


def test_no_option_data_says_so_and_never_invents(con, tmp_path):
    root = tmp_path / "data"
    days = pd.bdate_range("2023-01-02", "2025-09-30")
    rng = np.random.default_rng(3)
    _index(root, days, 100 * np.cumprod(1 + rng.normal(0.0004, 0.01, len(days))))
    c = ic.calibrated_fall_probability(con, "IN", date(2025, 9, 30), 20, 5.0, root=root)
    assert c["p_implied"] is None and c["p_calibrated"] is None and "no option data" in c["note"]
    out = _tool("implied_dist").fn(_ctx(con, root), {})
    assert out["option_data"] is False and "No option-chain data" in out["message"]
    b = out["realised_frequency_baseline"]["5%"]
    assert b["available"] and 0.0 <= b["frequency"] <= 1.0
    us = _tool("implied_dist").fn(_ctx(con, root), {"market": "US"})
    assert us["option_data"] is False and "US" in us["message"]


def test_implied_dist_with_kept_days(con, tmp_path):
    root = tmp_path / "data"
    (root / "derived").mkdir(parents=True)
    d, exp = date(2025, 9, 26), date(2025, 10, 28)
    row = {"date": d, "expiry": exp, "days": 32, "spot": 100.0, "forward": 100.5, "rate": 0.07, "strikes": 40, "fit_rmse": 0.01, "atm_iv": 0.15, "skew_90_110": 0.1,
           "m_lo": -0.1, "m_hi": 0.1, "p_below_20": 0.001, "p_below_15": 0.005, "p_below_10": 0.03, "p_below_5": 0.10, "p_above_5": 0.08, "p_above_10": 0.01}
    pd.DataFrame([row]).to_parquet(root / "derived" / "implied_probs.parquet")
    days = pd.bdate_range("2025-08-01", "2025-09-30")
    _index(root, days, np.full(len(days), 100.0))
    out = _tool("implied_dist").fn(_ctx(con, root), {})
    assert out["option_data"] and out["current"]
    f = out["fall_probabilities"]
    assert f["5%"]["p_implied"] == pytest.approx(0.10) and f["5%"]["p_calibrated"] is None and f["5%"]["n"] == 0
    assert f["10%"]["p_implied"] < f["5%"]["p_implied"]
    assert out["calibration"]["n"] == 0


def test_distribution_quantiles_and_p_fall_are_monotone():
    grid = np.linspace(50, 150, 801)
    cdf = 1 / (1 + np.exp(-(grid - 100) / 6))
    dist = {"spot": 100.0, "grid": grid, "cdf": cdf}
    q = implied.quantiles(dist)
    lv = [q[k]["level"] for k in ("q05", "q25", "q50", "q75", "q95")]
    assert lv == sorted(lv) and lv[2] == pytest.approx(100.0, abs=0.5)
    assert implied.p_fall(dist, 10) < implied.p_fall(dist, 5) < implied.p_fall(dist, 0.5)


# --- cascade ---------------------------------------------------------------------------------------------------------------------

P = hk.Uni(0.0125, 0.755, 0.0494)


def _returns(n=400, shocks=()):
    r = pd.Series(0.001, index=pd.bdate_range("2024-01-01", periods=n))
    for k in shocks:
        r.iloc[k] = -0.03
    return r


def test_cascade_reading_cluster_versus_calm():
    calm = hk.cascade_reading(_returns(), P, -0.02, 10, n_sim=300)
    hot = hk.cascade_reading(_returns(shocks=(395, 397, 399)), P, -0.02, 10, n_sim=300)
    assert calm["in_progress"] is False and calm["events_total"] == 0
    assert hot["in_progress"] is True and hot["events_total"] == 3 and len(hot["shocks_in_window"]) == 3
    assert hot["chance_another_shock"] > calm["chance_another_shock"] * 2
    assert hot["expected_further_shocks"] > calm["expected_further_shocks"]
    assert hot["branching_ratio"] == pytest.approx(0.755) and hot["intensity_vs_baseline"] > 5
    again = hk.cascade_reading(_returns(shocks=(395, 397, 399)), P, -0.02, 10, n_sim=300)
    assert again["expected_further_shocks"] == hot["expected_further_shocks"]               # seeded


def test_an_old_shock_is_not_a_fall_in_progress():
    r = hk.cascade_reading(_returns(shocks=(300,)), P, -0.02, 10, n_sim=100)
    assert r["in_progress"] is False and r["sessions_since_last_shock"] == 99


def test_cascade_tool_states_registered_finding_and_no_fall(con, tmp_path):
    root = tmp_path / "data"
    r = _returns(shocks=())
    tri = 100 * (1 + r).cumprod()
    _index(root, tri.index, tri.to_numpy(), "NIFTY500_TRI")
    ctx = _ctx(con, root, datetime(2025, 7, 15, 18, 0))
    out = _tool("cascade").fn(ctx, {})
    assert out["available"] and out["in_progress"] is False and "No fall in progress" in out["reading"] and "170 events" in out["registered_finding"]
    r2 = _returns(shocks=(394, 396))
    r2 = r2[r2.index <= pd.Timestamp("2025-07-15")]
    tri2 = 100 * (1 + _returns(shocks=(394, 396))).cumprod()
    _index(root, tri2.index, tri2.to_numpy(), "NIFTY500_TRI")
    out2 = _tool("cascade").fn(_ctx(con, root, datetime(2025, 7, 30, 18, 0)), {})
    assert out2["in_progress"] is True and "A fall is under way" in out2["reading"]


def test_cascade_without_data_or_for_us(con, tmp_path):
    assert _tool("cascade").fn(_ctx(con, tmp_path / "none"), {})["available"] is False
    assert "No registered cascade fit" in _tool("cascade").fn(_ctx(con, tmp_path), {"market": "US"})["message"]


# --- simulate --------------------------------------------------------------------------------------------------------------------

def _Rd(n=1500, seed=5):
    rng = np.random.default_rng(seed)
    m = rng.normal(0.0004, 0.01, n)
    df = pd.DataFrame({"stocks": m * 1.1 + rng.normal(0, 0.003, n), "n500": m, "mom50": m * 1.2 + rng.normal(0, 0.003, n), "gold": rng.normal(0.0002, 0.008, n)},
                      index=pd.bdate_range("2018-01-01", periods=n))
    df["debt"] = 0.00025
    df["cash"] = 0.00012
    return df


def test_session_paths_reproducible_and_monotone_in_shock():
    Rd = _Rd()
    w = np.array([0.0, 1.0, 0.0, 0.0, 0.0, 0.0])
    a = mc.session_paths(Rd, w, 20, 2000, 79, market_shock=-0.10)
    b = mc.session_paths(Rd, w, 20, 2000, 79, market_shock=-0.10)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, mc.session_paths(Rd, w, 20, 2000, 80, market_shock=-0.10))
    med, breach = [], []
    for s in (0.0, -0.10, -0.20, -0.30, -0.40):
        sm = mc.horizon_summary(mc.session_paths(Rd, w, 20, 3000, 79, market_shock=s))
        med.append(sm["change_quantiles"]["p50"])
        breach.append(sm["p_fall_beyond_limit"])
    assert med == sorted(med, reverse=True) and breach == sorted(breach) and breach[-1] > breach[0]


def test_cash_is_untouched_by_a_market_shock():
    Rd = _Rd()
    w = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 1.0])
    v = mc.session_paths(Rd, w, 10, 100, 1, market_shock=-0.3)
    assert float(v[:, -1].min()) > 1.0


def test_simulate_tool_without_book_uses_index_and_is_seeded(con, tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setattr(mc, "history_daily", lambda r: _Rd())
    ctx = _ctx(con, root, datetime(2025, 9, 30, 18, 0))
    t = _tool("simulate")
    a = t.fn(ctx, {"shock_pct": -10, "paths": 1000, "horizon": 10})
    b = t.fn(ctx, {"shock_pct": -10, "paths": 1000, "horizon": 10})
    assert a["available"] and a["portfolio"] == "index" and a == b
    c = t.fn(ctx, {"shock_pct": -25, "paths": 1000, "horizon": 10})
    assert c["value_change_quantiles"]["p50"] < a["value_change_quantiles"]["p50"] and c["chance_fall_beyond_35pct"] >= a["chance_fall_beyond_35pct"]
    assert a["horizon_end"] == str(markets.get("IN").session_after(date(2025, 9, 30), 10))


def test_simulate_tool_refusals(con, tmp_path, monkeypatch):
    ctx = _ctx(con, tmp_path)
    t = _tool("simulate")
    assert t.fn(ctx, {"scenario": "oil_up_30", "shock_pct": -5})["available"] is False
    assert "Unknown scenario" in t.fn(ctx, {"scenario": "nope"})["message"]
    assert t.fn(ctx, {"market": "US"})["available"] is False
    out = t.fn(ctx, {})                                          # no history on this root: a harmless message, never an error
    assert out["available"] is False and "not on this PC" in out["message"]
    monkeypatch.setattr(mc, "history_daily", lambda r: _Rd())
    nb = t.fn(ctx, {"scenario": "oil_up_30"})                    # a named scenario acts on holdings: none here
    assert nb["available"] is False and "no book" in nb["message"]


def test_tools_registered_and_probe_safe(con, tmp_path):
    names = {t.name for t in tools_s79.collect()}
    assert {"implied_dist", "cascade", "simulate"} <= names
    for n in ("implied_dist", "cascade", "simulate"):
        t = _tool(n)
        assert t.kind == "read" and t.required == ()
        assert isinstance(t.fn(_ctx(con, tmp_path / "empty"), {}), dict)


def test_simulate_named_scenario_on_a_book(con, tmp_path, monkeypatch):
    from pflab.hq.tools_s79 import t_implied
    from pflab.risk import scenarios as sn
    monkeypatch.setattr(mc, "history_daily", lambda r: _Rd())
    book = {"source": "paper", "note": "x", "value": 1_000_000.0, "mix": {"n500": 1.0}, "hold": [{"isin": "I", "symbol": "S", "bucket": "equity_fund", "value": 1_000_000.0}], "stock_weights": {}}
    monkeypatch.setattr(t_implied, "portfolio", lambda *a, **k: book)

    def fake(con_, root, asof, name, hold=None, cfg=None):
        return {"label": "L", "chain": "chain", "total": -150_000.0, "total_pct_of_modelled": -0.15, "total_range": [-170_000.0, -130_000.0]}
    monkeypatch.setattr(sn, "run", fake)
    ctx = _ctx(con, tmp_path)
    t = _tool("simulate")
    base = t.fn(ctx, {"paths": 1500, "horizon": 10})
    out = t.fn(ctx, {"scenario": "us_crash", "paths": 1500, "horizon": 10})
    assert out["available"] and out["shock"]["kind"] == "scenario" and out["portfolio"] == "paper"
    assert out["value_change_quantiles"]["p50"] < base["value_change_quantiles"]["p50"] - 0.10
    assert abs(out["value_change_quantiles_rupees"]["p50"] - out["value_change_quantiles"]["p50"] * 1_000_000) < 100
