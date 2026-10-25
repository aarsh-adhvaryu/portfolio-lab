"""S43 maths audit (PLAN A7): every number-producing agent recomputed by a second, independent method on fixed
SYNTHETIC cases. Monte Carlo against closed forms and a deterministic drawdown chain; the allocator and deploy
against hand-worked portfolios; risk stats against textbook formulas; Hawkes against numerical integration.
Findings and their fixes: docs/research/maths_audit_s43.md."""
from datetime import date

import numpy as np
import pandas as pd
import pytest
from scipy import integrate, stats as st

from pflab.pm import fd as F
from pflab.plan import deploy, rebalance
from pflab.plan import targets as tg
from pflab.quant import hawkes as hk
from pflab.risk import montecarlo as mc
from pflab.risk import stats

LIMIT = -np.log(1 + mc.FALL_LIMIT)                 # a fall beyond 35% = log drawdown beyond this


def p_drawdown_chain(cdf, a: float, steps: int, K: int = 800) -> float:
    """P(the log drawdown reaches `a` within `steps` iid log returns with CDF `cdf`), with no simulation:
    D' = max(D - x, 0) on a grid of [0, a) (an atom at 0 plus K bins); mass reaching `a` is absorbed."""
    h = a / K
    lo = np.arange(K) * h
    y = np.concatenate([[0.0], lo + h / 2])
    P = np.empty((K + 1, K + 1))
    P[:, 0] = 1 - cdf(y)
    P[:, 1:] = cdf(y[:, None] - lo[None, :]) - cdf(y[:, None] - lo[None, :] - h)
    p = np.zeros(K + 1)
    p[0] = 1.0
    for _ in range(steps):
        p = p @ P
    return float(1 - p.sum())


def one_asset(n=240, mu=0.008, sd=0.075, seed=3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(0.0, index=pd.date_range("2005-01-31", periods=n, freq="ME"), columns=list(mc.ASSETS))
    df["stocks"] = np.expm1(rng.normal(mu, sd, n))
    for c in ("n500", "mom50", "gold"):                # present but unused (weight 0), risky so GBM accepts them
        df[c] = np.expm1(rng.normal(0.005, 0.05, n))
    df["debt"] = (1 + mc.DEBT_RATE) ** (1 / 12) - 1
    df["cash"] = (1 + mc.CASH_RATE) ** (1 / 12) - 1
    return df


W1 = mc.weights_of({"stocks": 1.0})


# ---- Monte Carlo ----------------------------------------------------------------------------------------------

def test_the_chain_itself_matches_brute_force_enumeration():
    """The checker checked: a +-u coin-flip walk, 12 steps, every one of the 4,096 paths enumerated."""
    import itertools
    u = 0.1
    exact = 0.0
    for steps in itertools.product((u, -u), repeat=12):
        x = np.concatenate([[0.0], np.cumsum(steps)])
        exact += float((np.maximum.accumulate(x) - x).max() >= 3.5 * u) / 4096
    cdf = lambda x: 0.5 * (x >= -u) + 0.5 * (x >= u)
    assert 0.05 < exact < 0.95 and p_drawdown_chain(cdf, 3.5 * u, 12, K=7) == pytest.approx(exact, abs=1e-12)


def test_gbm_terminal_quantiles_match_the_lognormal_closed_form():
    R = one_asset()
    L = np.log1p(R["stocks"].values)
    mu, sd = L.mean(), L.std(ddof=1)
    s = mc.simulate(R, {"x": {"stocks": 1.0}}, years=5, n=20_000)["x"]["gbm"]["y5"]
    for q, key in ((5, "p5"), (50, "p50"), (95, "p95")):
        exact = np.exp(60 * mu + np.sqrt(60) * sd * st.norm.ppf(q / 100))
        assert s[key] == pytest.approx(exact, rel=0.02), key


def test_gbm_month_end_fall_chance_matches_the_drawdown_chain():
    R = one_asset()
    L = np.log1p(R["stocks"].values)
    exact = p_drawdown_chain(lambda x: st.norm.cdf(x, L.mean(), L.std(ddof=1)), LIMIT, 60)
    got = mc.simulate(R, {"x": {"stocks": 1.0}}, years=5, n=20_000)["x"]["gbm"]["p_fall_beyond_limit"]
    assert 0.05 < exact < 0.6 and got == pytest.approx(exact, abs=0.012)


def test_gbm_any_day_fall_chance_matches_the_chain_and_exceeds_month_end():
    R = one_asset()
    L = np.log1p(R["stocks"].values)
    m, s = L.mean() / 21, L.std(ddof=1) / np.sqrt(21)
    exact = p_drawdown_chain(lambda x: st.norm.cdf(x, m, s), LIMIT, 1260)
    got = mc.fall_any_day_gbm(R.values, W1, 60, 10_000, np.random.default_rng(1))
    month_end = p_drawdown_chain(lambda x: st.norm.cdf(x, L.mean(), L.std(ddof=1)), LIMIT, 60)
    assert got == pytest.approx(exact, abs=0.015) and exact > month_end + 0.02


def test_bootstrap_of_single_months_matches_the_chain_on_the_empirical_distribution():
    """Block length 1 = iid draws from the history: the chain on the empirical CDF is the exact answer."""
    R = one_asset(n=120, sd=0.09)
    xs = np.sort(np.log1p(R["stocks"].values))
    cdf = lambda x: np.searchsorted(xs, x, side="right") / len(xs)
    exact = p_drawdown_chain(cdf, LIMIT, 60, K=2000)
    v = mc.mix_values(mc.block_paths(R.values, 60, 20_000, np.random.default_rng(2), block=1), W1)
    assert np.mean(mc.max_dd(v) <= mc.FALL_LIMIT) == pytest.approx(exact, abs=0.015)


def test_circular_blocks_draw_every_month_equally_often():
    T = 50
    idx = mc.block_index(T, 60, 20_000, np.random.default_rng(0), 12)
    c = np.bincount(idx.ravel(), minlength=T) / (idx.size / T)
    assert c.min() > 0.96 and c.max() < 1.04          # the old non-circular draw gave the first month 1/12 weight
    starts = idx[:, 0]
    assert all(((idx[k, :12] - starts[k]) % T == np.arange(12)).all() for k in range(50))   # whole blocks, in order


def test_max_drawdown_against_a_plain_loop():
    v = np.cumprod(1 + np.random.default_rng(5).normal(0.005, 0.08, (200, 60)), axis=1)
    loop = []
    for row in v:
        peak, worst = 1.0, 0.0
        for x in row:
            peak = max(peak, x)
            worst = min(worst, x / peak - 1)
        loop.append(worst)
    assert np.allclose(mc.max_dd(v), loop)


def test_any_day_bootstrap_is_never_milder_than_month_ends_on_the_same_history():
    """Daily history whose months compound exactly to the monthly history: every month-end is also a session,
    so the worst fall on any day can only be deeper, and the chance of a big fall can only be higher."""
    R = one_asset(n=120, sd=0.09)
    rng = np.random.default_rng(4)
    days = []
    for d, r in R.iterrows():
        noise = rng.normal(0, 0.02, 21)
        lg = np.log1p(r.values)[None, :] / 21 + (noise - noise.mean())[:, None] * (np.arange(6) < 4)
        days.append(pd.DataFrame(np.expm1(lg), columns=R.columns,
                                 index=pd.bdate_range(d - pd.offsets.MonthBegin(1), periods=21)))
    Rd = pd.concat(days)
    assert np.allclose(np.prod(1 + Rd.values.reshape(len(R), 21, 6), axis=1), 1 + R.values)
    fr = mc.frontier(R, 300, Rd=Rd)
    assert (fr["worst_fall_any_day"] <= fr["worst_fall"] + 1e-12).all()
    p = mc.point(R, {"stocks": 0.5, "gold": 0.2, "debt": 0.3}, Rd)
    port = R[list(mc.FRONTIER_ASSETS)].values @ np.array([0.5, 0, 0, 0.2, 0.3])
    nav = pd.Series(np.cumprod(1 + port))
    assert p["ret"] == pytest.approx(nav.iloc[-1] ** (12 / len(port)) - 1)
    assert p["vol"] == pytest.approx(pd.Series(port).std() * np.sqrt(12))
    assert p["worst_fall"] == pytest.approx(min(0.0, (nav / nav.cummax().clip(lower=1.0) - 1).min()))


def test_lump_vs_staged_against_the_hand_formula():
    R = one_asset()
    R["stocks"] = 0.01                                     # a riskless 1% a month: both engines are exact
    out = mc.lump_vs_staged(R, {"stocks": 1.0}, months_staged=10, horizon=24, n=50)
    d = (1 + mc.DEBT_RATE) ** (1 / 12) - 1
    staged = sum((1 + d) ** k / 10 * 1.01 ** (24 - k) for k in range(10))
    for eng in ("block", "gbm"):
        assert out[eng]["lump_median"] == pytest.approx(1.01 ** 24) and out[eng]["staged_median"] == pytest.approx(staged)


def test_target_mix_reads_fund_names_not_the_order_of_the_buy_list():
    doc = {"meta": {"set_by": "t", "effective_from": date(2026, 1, 1)},
           "bucket": {"equity": {"target": 0.4, "soft_band": 0.05, "hard_band": 0.1},
                      "equity_fund": {"target": 0.4, "soft_band": 0.05, "hard_band": 0.1,
                                      "buy": [{"isin": "M", "weight": 0.3}, {"isin": "N", "weight": 0.7}]},
                      "debt": {"target": 0.2, "soft_band": 0.05, "hard_band": 0.1}}}
    names = {"M": "Some Nifty 500 Momentum 50 Index Fund", "N": "Some Nifty 500 Index Fund"}
    mix = mc.target_mix(tg.parse(doc), names)
    assert mix["mom50"] == pytest.approx(0.12) and mix["n500"] == pytest.approx(0.28)
    with pytest.raises(ValueError, match="fund name unknown"):
        mc.target_mix(tg.parse(doc))


# ---- allocator and deploy ---------------------------------------------------------------------------------------

def targets3():
    return tg.parse({"meta": {"set_by": "t", "effective_from": date(2026, 1, 1)},
                     "bucket": {"equity": {"target": 0.4, "soft_band": 0.05, "hard_band": 0.1},
                                "gold": {"target": 0.2, "soft_band": 0.05, "hard_band": 0.1},
                                "debt": {"target": 0.4, "soft_band": 0.05, "hard_band": 0.2}}})


def test_steering_hand_worked():
    """50/10/40 against 40/20/40, Rs 20 new: total 120, shortfalls gold 14 and debt 8 (equity is over), so
    gold gets 20 x 14/22 and debt 20 x 8/22."""
    a = rebalance.steer({"equity": 50.0, "gold": 10.0, "debt": 40.0}, targets3(), 20.0)
    assert a == pytest.approx({"equity": 0.0, "gold": 20 * 14 / 22, "debt": 20 * 8 / 22})


@pytest.mark.parametrize("seed", range(20))
def test_steering_lands_closest_to_target_of_any_split(seed):
    """Second method: the total distance from target (sum of |weight - target|) after steering is the smallest
    any non-negative split of the same money can reach; 2,000 random splits never beat it."""
    rng = np.random.default_rng(seed)
    t = targets3()
    vals = dict(zip(("equity", "gold", "debt"), rng.uniform(0, 100, 3)))
    c = float(rng.uniform(0, 80))
    dist = lambda add: sum(abs((vals[b] + a) / (sum(vals.values()) + c) - t.buckets[b].target) for b, a in add.items())
    best = dist(rebalance.steer(vals, t, c))
    for s in rng.dirichlet(np.ones(3), size=2000):
        assert best <= dist(dict(zip(vals, c * s))) + 1e-12


def test_months_to_cure_closed_form():
    """Equity 80 / debt 20 against 50/50 with a 10-point hard band: every rupee goes to debt, so the weight is
    80 / (100 + 10 m) and first reaches 60% at m = ceil(100/3 / 10) = 4."""
    t = tg.parse({"meta": {"set_by": "t", "effective_from": date(2026, 1, 1)},
                  "bucket": {"equity": {"target": 0.5, "soft_band": 0.05, "hard_band": 0.1},
                             "debt": {"target": 0.5, "soft_band": 0.05, "hard_band": 0.1}}})
    m = rebalance.months_to_cure({"equity": 80.0, "debt": 20.0}, t, 10.0, "equity", date(2026, 1, 1))
    assert m.value == 4


def fd(fd_id, maturity):
    return F.FD(fd_id=fd_id, principal=100_000.0, rate=0.08, term_start=date(2025, 1, 10), maturity=maturity,
                maturity_amount=0.0, anchor_date=date(2026, 1, 10), anchor_value=105_000.0)


def test_a_matured_batch_keeps_its_remaining_tranches():
    """Found by the audit: a batch vanished from the plan the day after it matured. Matured 2026-09-10, 10
    months from October: on 2026-12-15 the tranches from December on remain, and they add up to the payout
    less the two months already done."""
    f = fd("A", date(2026, 9, 10))
    pay = F.maturity_payout(f).value
    tr = deploy.schedule([f], 10, date(2026, 12, 15))
    assert [t.month for t in tr][0] == date(2026, 12, 1) and len(tr) == 8 and [t.n for t in tr][0] == 3
    assert sum(t.amount for t in tr) == pytest.approx(pay - 2 * round(pay / 10, 2), abs=0.01)
    assert deploy.schedule([f], 10, date(2027, 8, 1)) == [] and len(deploy.schedule([f], 10, date(2027, 7, 31))) == 1


def test_projection_counts_matured_money_once():
    """The matured money is already bank cash in the values: the projection must not add it again, and the
    undeployed pot is not steered against. Equity 0, debt 300, cash 400 = the pot: the first 100 is steered
    against 300 + 100 (all to equity), not against 700 + 100 (which would send 20 to debt)."""
    t = tg.parse({"meta": {"set_by": "t", "effective_from": date(2026, 1, 1)},
                  "bucket": {"equity": {"target": 0.5, "soft_band": 0.05, "hard_band": 0.1},
                             "debt": {"target": 0.5, "soft_band": 0.05, "hard_band": 0.5},
                             "cash": {"target": 0.0, "soft_band": 0.05, "hard_band": 1.0}}})
    months = [date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1), date(2027, 3, 1)]
    tr = [deploy.Tranche(m, 100.0, date(2026, 9, 10), 3 + k) for k, m in enumerate(months)]
    rows = deploy.project({"equity": 0.0, "debt": 300.0, "cash": 400.0}, t, tr, date(2026, 12, 15))
    assert rows[0]["alloc"]["equity"] == pytest.approx(100.0) and rows[0]["alloc"]["debt"] == pytest.approx(0.0)
    # months 2-3 also all to equity (300 -> 100, 200 short); month 4: 300/300 + 100, both 50 short: 50/50
    assert rows[3]["alloc"]["equity"] == pytest.approx(50.0) and rows[3]["alloc"]["debt"] == pytest.approx(50.0)
    last = rows[-1]["weights"]
    assert last["cash"] == pytest.approx(0.0) and last["equity"] == pytest.approx(0.5)


# ---- risk statistics -----------------------------------------------------------------------------------------

def test_volatility_beta_drawdown_against_textbook_formulas():
    rng = np.random.default_rng(9)
    idx = pd.bdate_range("2025-01-01", periods=300)
    b = pd.Series(rng.normal(0.0004, 0.01, 300), index=idx)
    r = 0.0001 + 1.3 * b + pd.Series(rng.normal(0, 0.006, 300), index=idx)
    x = r.values
    assert stats.volatility(r) == pytest.approx(np.sqrt(((x - x.mean()) ** 2).sum() / (len(x) - 1) * 252))
    A = np.column_stack([np.ones(300), b.values])
    assert stats.beta(r, b) == pytest.approx(np.linalg.lstsq(A, x, rcond=None)[0][1])
    nav = pd.Series(np.cumprod(1 + x), index=idx)
    peak, worst = -np.inf, 0.0
    for v in nav:
        peak = max(peak, v)
        worst = max(worst, 1 - v / peak)
    assert stats.max_drawdown(nav) == pytest.approx(worst)
    c = stats.concentration(pd.Series({"a": 2.0, "b": 1.0, "c": 1.0}))
    assert c["hhi"] == pytest.approx(0.25 + 0.0625 * 2) and c["effective_n"] == pytest.approx(1 / 0.375)


# ---- Hawkes ------------------------------------------------------------------------------------------------------

def test_hawkes_compensator_and_chance_against_numerical_integration():
    p = hk.Uni(0.05, 0.6, 0.3)
    t = np.array([1.0, 1.4, 6.0, 6.2, 6.25, 14.0])
    for x in (2.0, 6.1, 20.0):
        pts = [0.0] + [e for e in t if e < x] + [x]
        num = sum(integrate.quad(lambda s: hk.intensity(p, t, s), a, b)[0] for a, b in zip(pts[:-1], pts[1:]))
        assert hk.compensator(p, t, np.array([x]))[0] == pytest.approx(num, rel=1e-6)
    now, h = 15.0, 10.0
    num = integrate.quad(lambda s: hk.intensity(p, t, s), now, now + h)[0]
    assert hk.chance_within(p, t, now, h) == pytest.approx(1 - np.exp(-num), rel=1e-6)


def test_hawkes_simulation_runs_at_the_stationary_rate():
    p = hk.Uni(0.2, 0.5, 1.0)
    n = np.mean([len(hk.simulate(p, 2000.0, np.random.default_rng(s))) for s in range(10)])
    assert n / 2000.0 == pytest.approx(p.mu / (1 - p.alpha), rel=0.05)
