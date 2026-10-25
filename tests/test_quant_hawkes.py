"""S40 Hawkes processes on SIMULATED events: likelihood, MLE recovery, time-rescaling, forecasts."""
import numpy as np
import pytest

from pflab.quant import hawkes as hk

TRUE = hk.Uni(mu=0.3, alpha=0.6, beta=1.5)


@pytest.fixture(scope="module")
def events():
    return hk.simulate(TRUE, 4000.0, np.random.default_rng(11))


def test_likelihood_by_brute_force():
    t = np.array([0.5, 1.0, 1.7, 4.0])
    p = hk.Uni(0.4, 0.5, 2.0)
    lam = [p.mu + p.alpha * p.beta * sum(np.exp(-p.beta * (ti - tj)) for tj in t if tj < ti) for ti in t]
    comp = p.mu * 5.0 + p.alpha * sum(1 - np.exp(-p.beta * (5.0 - tj)) for tj in t)
    assert hk.loglik(p, t, 5.0) == pytest.approx(np.sum(np.log(lam)) - comp)
    assert hk.loglik_window(p, t, 0.0, 5.0) == pytest.approx(hk.loglik(p, t, 5.0))
    # windows add up: [0, 2) + [2, 5) = [0, 5)
    assert hk.loglik_window(p, t, 0, 2) + hk.loglik_window(p, t, 2, 5) == pytest.approx(hk.loglik(p, t, 5.0))


def test_mle_recovers_simulated_parameters(events):
    f = hk.fit(events, 4000.0)
    p = f["params"]
    assert p.mu == pytest.approx(TRUE.mu, rel=0.2) and p.alpha == pytest.approx(TRUE.alpha, abs=0.08)
    assert p.beta == pytest.approx(TRUE.beta, rel=0.3)
    assert f["lr_p"] < 1e-6 and f["aic"] < f["poisson_aic"]


def test_time_rescaling_accepts_the_true_model_and_rejects_poisson(events):
    assert hk.ks(TRUE, events) > 0.05
    assert hk.ks_poisson(len(events) / 4000.0, events) < 0.01
    assert hk.rescaled(TRUE, events).sum() == pytest.approx(
        TRUE.mu * events[-1] + TRUE.alpha * np.sum(1 - np.exp(-TRUE.beta * (events[-1] - events))), rel=1e-9)


def test_out_of_sample_window_checks(events):
    assert hk.compensator(TRUE, events, events[-1:])[0] == pytest.approx(hk.rescaled(TRUE, events).sum())
    assert hk.ks_window(TRUE, events, 2000.0, 4000.0) > 0.05
    wrong = hk.Uni(TRUE.mu * 3, 0.05, 1.0)
    assert hk.ks_window(wrong, events, 2000.0, 4000.0) < 0.01


def test_poisson_data_shows_no_excitation():
    rng = np.random.default_rng(5)
    t = np.sort(rng.uniform(0, 3000, 900))
    f = hk.fit(t, 3000.0)
    assert f["lr_p"] > 0.01 or f["params"].alpha < 0.05


def test_chance_within_matches_simulation(events):
    now, h = float(events[1000]), 5.0
    exact = hk.chance_within(TRUE, events, now, h)
    rng = np.random.default_rng(2)
    hits = [len(hk.simulate(TRUE, now + h, rng, history=events[events <= now], start=now)) > 0 for _ in range(1500)]
    assert exact == pytest.approx(np.mean(hits), abs=0.04)
    assert hk.intensity(TRUE, events, now) > TRUE.mu                 # right after an event, excitation is high
    assert hk.chance_within(hk.Uni(0.3, 0.0, 1.0), events, now, h) == pytest.approx(1 - np.exp(-1.5))


def test_cross_sums_by_brute_force():
    rng = np.random.default_rng(4)
    tk, tj = np.sort(rng.uniform(0, 50, 40)), np.sort(rng.uniform(0, 50, 30))
    s, c = hk._cross(0.7, tk, tj, 50.0)
    brute = [sum(np.exp(-0.7 * (a - b)) for b in tj if b < a) for a in tk]
    assert np.allclose(s, brute) and c == pytest.approx(np.sum(1 - np.exp(-0.7 * (50 - tj))))
    self_, _ = hk._cross(0.7, tk, tk, 50.0)                    # an event does not excite itself
    assert np.allclose(self_, hk._a(0.7, tk))


def test_bivariate_recovers_one_way_excitation():
    p = hk.Bi((0.2, 0.2), ((0.3, 0.0), (0.5, 0.2)), ((1.0, 1.0), (1.0, 1.0)))      # 0 excites 1, not back
    t0, t1 = hk.simulate_bi(p, 3000.0, np.random.default_rng(3))
    f = hk.fit_bi([t0, t1], 3000.0)
    q = f["params"]
    assert q.alpha[1][0] == pytest.approx(0.5, abs=0.15) and q.alpha[0][1] < 0.1
    assert q.spectral_radius < 1 and min(f["ks"]) > 0.01




def test_jitter_breaks_ties_within_a_session():
    t = hk.jitter(np.array([3, 3, 7]), np.random.default_rng(0))
    assert len(set(t)) == 3 and np.all((t >= 3) & (t < 8)) and np.all(np.diff(t) > 0)
