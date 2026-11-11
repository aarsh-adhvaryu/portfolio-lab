"""S79b item 18A, what is left after A60 (the `construct` optimiser, its advice tool, the live path and the comparison engine were deleted: the registered comparison was inconclusive
and it was never adopted). Kept: the shrunk covariance (read by `core/state.py` and `core/card.py`), the charges and tax estimates (read by `lab/runner.py`), the counter record of the
registered study, and the data-break filter `compare.clean`. Synthetic data only."""
from __future__ import annotations

from datetime import date, datetime

import duckdb
import numpy as np
import pandas as pd
import pytest

from pflab import construct as C
from pflab.construct import compare, costs, risk
from pflab.pm import store

NOW = datetime(2026, 11, 6, 21, 0)


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    store.migrate(c)
    return c


# --- the risk model ---------------------------------------------------------------------------------------------------------------
def _lw_loop(X):
    """Ledoit-Wolf 2004 written the long way (one outer product per day) to check the vectorised formula."""
    n, p = X.shape
    X = X - X.mean(0)
    S = sum(np.outer(x, x) for x in X) / n
    mu = np.trace(S) / p
    d2 = np.sum((S - mu * np.eye(p)) ** 2) / p
    b2 = sum(np.sum((np.outer(x, x) - S) ** 2) for x in X) / (n * n * p)
    b = min(b2, d2)
    s = b / d2
    return s * mu * np.eye(p) + (1 - s) * S, s


def test_ledoit_wolf_matches_the_formula_written_out():
    rng = np.random.default_rng(3)
    X = rng.normal(size=(60, 12)) @ rng.normal(size=(12, 12)) * 0.01
    S, s = risk.ledoit_wolf(X)
    S2, s2 = _lw_loop(X)
    assert s == pytest.approx(s2) and np.allclose(S, S2)
    assert 0.0 <= s <= 1.0


def test_shrinkage_beats_the_sample_covariance_on_a_known_case():
    """True covariance = 0.0001 * I (40 names), only 50 days: the sample covariance is far off; the shrunk one is much nearer and its eigenvalues are tighter."""
    rng = np.random.default_rng(11)
    truth = np.eye(40) * 1e-4
    errs_s, errs_l, shr = [], [], []
    for _ in range(20):
        X = rng.normal(size=(50, 40)) * 0.01
        S = np.cov(X.T, bias=True)
        L, s = risk.ledoit_wolf(X)
        errs_s.append(np.sum((S - truth) ** 2))
        errs_l.append(np.sum((L - truth) ** 2))
        shr.append(s)
    assert np.mean(errs_l) < 0.5 * np.mean(errs_s)
    assert np.mean(shr) > 0.3                                    # a spherical truth with few days: mostly the target
    X = rng.normal(size=(20000, 5)) * np.array([0.002, 0.005, 0.01, 0.02, 0.04])      # a far-from-spherical truth with plenty of days: the sample is trusted
    assert risk.ledoit_wolf(X)[1] < 0.02


def test_shrunk_cov_is_point_in_time_and_drops_thin_names():
    idx = pd.bdate_range("2025-01-01", periods=400)
    rng = np.random.default_rng(1)
    px = pd.DataFrame({"A": 100 * np.exp(np.cumsum(rng.normal(0, .01, 400))), "B": 50 * np.exp(np.cumsum(rng.normal(0, .01, 400)))}, index=idx)
    px.loc[idx[:380], "B"] = np.nan                              # B has only 20 days
    r_cut = risk.daily_returns(px, idx[300].date(), 250)
    assert r_cut.index.max() <= idx[300] and list(r_cut.columns) == ["A"]
    m, src, _ = risk.cov_for(["A", "B"], r_cut, None, 0.5, 0.30)
    assert m.shape == (2, 2) and "no return history" in src["B"] and np.sqrt(m[1, 1]) == pytest.approx(0.30) and np.linalg.eigvalsh(m)[0] > 0


# --- costs ------------------------------------------------------------------------------------------------------------------------
def test_charges_and_tax_estimates():
    assert costs.charge("equity", "buy", 100_000) > 0 and costs.charge("equity", "sell", 100_000) > costs.charge("equity", "buy", 100_000) * 0.5
    young = [(date(2026, 6, 1), 100.0, 100.0, "EQUITY")]
    old = [(date(2024, 1, 1), 100.0, 100.0, "EQUITY")]
    t_young, _ = costs.lots_tax(young, 200.0, 100.0, date(2026, 11, 6), "equity")
    t_old, _ = costs.lots_tax(old, 200.0, 100.0, date(2026, 11, 6), "equity")
    assert t_young == pytest.approx(0.20 * 10_000) and t_old == 0.0                    # short term 20%; long term under the Rs 1.25 lakh exemption
    assert costs.tax_rate(young, 200.0, date(2026, 11, 6), "equity") == pytest.approx(0.10)
    assert costs.tax_rate(young, 80.0, date(2026, 11, 6), "equity") == 0.0               # a loss is no cost
    c = costs.trade_cost(young, 200.0, 50.0, "sell", date(2026, 11, 6), "equity")
    assert c["tax"] > 0 and c["charges"] > 0 and costs.trade_cost(young, 200.0, 50.0, "buy", date(2026, 11, 6), "equity")["tax"] == 0


def test_protocol_registration_is_idempotent_and_counts(con):
    from pflab.learner import counter
    n0 = counter.n_tests(con)
    assert C.register(con, NOW) is True and C.register(con, NOW) is False
    assert counter.n_tests(con) == n0 + 1
    assert C.registered_sha(con) == C.protocol_sha()
    assert C.protocol_ok(con) == {"registered": True, "unchanged": True, "why": None}


def test_a_changed_protocol_is_seen_by_the_record_check(con, monkeypatch, tmp_path):
    C.register(con, NOW)
    other = tmp_path / "p.md"
    other.write_text("amended after registration", encoding="utf-8")
    monkeypatch.setattr(C, "PROTOCOL", other)
    assert C.protocol_ok(con)["unchanged"] is False


def test_clean_removes_a_data_break_from_the_path_and_leaves_normal_moves():
    px = pd.DataFrame({"a": [100.0, 101.0, 50.0, 50.5, 51.0]})                      # a 50% print then normal moves
    out = compare.clean(px, 0.40)
    assert out["a"].iloc[-1] == pytest.approx(51.0 * 101.0 / 50.0) and out["a"].iloc[1] == pytest.approx(101.0)
    assert out["a"].pct_change().abs().max() < 0.40
