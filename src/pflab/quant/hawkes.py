"""Exponential Hawkes processes (S40): fitting, goodness of fit, simulation, today's state.

Univariate:  lambda(t) = mu + alpha * beta * sum_{t_i < t} exp(-beta (t - t_i))
    alpha is the branching ratio (expected events each event triggers; < 1 for a stationary process),
    1/beta the mean delay of a triggered event. The baseline is mu events per unit time.
Bivariate:   lambda_k(t) = mu_k + sum_j alpha_kj * beta_kj * sum_{t_i in j, t_i < t} exp(-beta_kj (t - t_i))
    alpha_kj: events in k triggered by one event in j; stationary when the spectral radius of alpha < 1.

Fitted by maximum likelihood with scipy (L-BFGS-B, several starts). Goodness of fit by the time-rescaling
theorem: under the fitted model the compensator increments between events are i.i.d. Exp(1); a
Kolmogorov-Smirnov test checks that. Simulation by Ogata's thinning. Times are floats in one unit
(sessions for daily exceedances, days for filings); an event at time t does not excite itself or events at t.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

import numpy as np
from scipy import optimize, stats


@dataclass(frozen=True)
class Uni:
    mu: float
    alpha: float
    beta: float

    @property
    def half_life(self) -> float:          # time for the excitation of one event to halve
        return float(np.log(2) / self.beta)


def _a(beta: float, t: np.ndarray, wt: Optional[np.ndarray] = None) -> np.ndarray:
    """A_i = sum_{j < i} wt_j exp(-beta (t_i - t_j)) (wt = 1 by default), vectorised in time blocks short enough
    that exp(beta * dt) cannot overflow (beta * block length <= 500); a carried sum links the blocks."""
    t = np.asarray(t, float)
    wt = np.ones(len(t)) if wt is None else np.asarray(wt, float)
    a = np.zeros(len(t))
    if len(t) < 2:
        return a
    width = 500.0 / beta
    blk = np.floor((t - t[0]) / width).astype(np.int64)
    bounds = np.flatnonzero(np.diff(blk)) + 1
    starts, ends = np.concatenate([[0], bounds]), np.concatenate([bounds, [len(t)]])
    carry, prev_t0 = 0.0, None                      # sum over earlier blocks, measured at prev_t0
    for s, e in zip(starts, ends):
        t0 = t[0] + blk[s] * width
        if prev_t0 is not None:
            carry *= np.exp(-beta * (t0 - prev_t0))
        tau = t[s:e] - t0
        w = wt[s:e] * np.exp(beta * tau)
        cs = np.cumsum(w)
        a[s:e] = np.exp(-beta * tau) * (cs - w + carry)
        carry, prev_t0 = carry + cs[-1], t0
    return a


def loglik(p: Uni, t: np.ndarray, T: float, start: float = 0.0) -> float:
    """Log-likelihood of events `t` (sorted) on [start, T], with no history before `start`."""
    t = np.asarray(t, float)
    lam = p.mu + p.alpha * p.beta * _a(p.beta, t)
    comp = p.mu * (T - start) + p.alpha * np.sum(1.0 - np.exp(-p.beta * (T - t)))
    return float(np.sum(np.log(lam)) - comp)


def loglik_window(p: Uni, t_all: np.ndarray, a: float, b: float) -> float:
    """Log-likelihood of the events in [a, b) given every event before them (out-of-sample scoring)."""
    t_all = np.asarray(t_all, float)
    t_all = t_all[t_all < b]
    lam = p.mu + p.alpha * p.beta * _a(p.beta, t_all)
    inside = t_all >= a
    comp = p.mu * (b - a) + p.alpha * np.sum(np.exp(-p.beta * np.maximum(a - t_all, 0.0)) - np.exp(-p.beta * (b - t_all)))
    return float(np.sum(np.log(lam[inside])) - comp)


def poisson_loglik(rate: float, n: int, length: float) -> float:
    return float(n * np.log(rate) - rate * length)


def fit(t: Sequence[float], T: float, start: float = 0.0, seed: int = 0) -> dict:
    """MLE of a univariate exponential Hawkes on [start, T]; also the Poisson fit and the likelihood-ratio test."""
    t = np.sort(np.asarray(t, float)) - start
    T = T - start
    n = len(t)
    if n < 10:
        raise ValueError("too few events to fit a Hawkes process (need 10)")
    rng = np.random.default_rng(seed)

    def nll(x):          # mu and beta on a log scale, alpha on a logit scale (keeps 0 < alpha < 1)
        return -loglik(Uni(float(np.exp(x[0])), float(1 / (1 + np.exp(-x[1]))), float(np.exp(x[2]))), t, T)

    best = None
    base = n / T
    for a0, b0 in [(0.3, 1.0), (0.5, 0.1), (0.2, 5.0)] + [(rng.uniform(0.05, 0.9), np.exp(rng.uniform(-4, 2))) for _ in range(3)]:
        x0 = np.array([np.log(base * (1 - a0)), np.log(a0 / (1 - a0)), np.log(b0)])
        r = optimize.minimize(nll, x0, method="L-BFGS-B", bounds=[(-20, 10), (-12, 6), (-9, 7)])
        if best is None or r.fun < best.fun:
            best = r
    x = best.x
    p = Uni(float(np.exp(x[0])), float(1 / (1 + np.exp(-x[1]))), float(np.exp(x[2])))
    ll = -float(best.fun)
    ll0 = poisson_loglik(base, n, T)
    lr = 2 * (ll - ll0)
    return {"params": p, "n": n, "length": T, "loglik": ll, "poisson_rate": base, "poisson_loglik": ll0,
            "lr": lr, "lr_p": float(stats.chi2.sf(max(lr, 0.0), 2)), "aic": 2 * 3 - 2 * ll, "poisson_aic": 2 - 2 * ll0,
            "converged": bool(best.success)}


def rescaled(p: Uni, t: np.ndarray, start: float = 0.0) -> np.ndarray:
    """Compensator increments between consecutive events (the first from `start`)."""
    t = np.asarray(t, float)
    a = _a(p.beta, t)
    big = p.mu * (t - start) + p.alpha * (np.arange(len(t)) - a)     # Lambda(t_i)
    return np.diff(np.concatenate([[0.0], big]))


def ks(p: Uni, t: np.ndarray, start: float = 0.0) -> float:
    """Time-rescaling goodness of fit: KS p-value of the increments against Exp(1)."""
    return float(stats.kstest(rescaled(p, t, start), "expon").pvalue)


def compensator(p: Uni, t_all: np.ndarray, xs: np.ndarray) -> np.ndarray:
    """Lambda(x) = mu x + alpha sum_{t_j < x} (1 - exp(-beta (x - t_j))) for each x (absolute time)."""
    t_all, xs = np.asarray(t_all, float), np.asarray(xs, float)
    out = np.empty(len(xs))
    for i in range(0, len(xs), 512):
        dt = xs[i:i + 512, None] - t_all[None, :]
        out[i:i + 512] = p.mu * xs[i:i + 512] + p.alpha * np.where(dt > 0, 1 - np.exp(-p.beta * np.where(dt > 0, dt, 0.0)), 0.0).sum(axis=1)
    return out


def ks_window(p: Uni, t_all: np.ndarray, a: float, b: float) -> float:
    """Time-rescaling KS p-value for the events in [a, b), the intensity using every earlier event."""
    t_all = np.asarray(t_all, float)
    inside = t_all[(t_all >= a) & (t_all < b)]
    lam = compensator(p, t_all[t_all < b], np.concatenate([[a], inside]))
    return float(stats.kstest(np.diff(lam), "expon").pvalue)


def ks_poisson(rate: float, t: np.ndarray, start: float = 0.0) -> float:
    return float(stats.kstest(rate * np.diff(np.concatenate([[start], np.asarray(t, float)])), "expon").pvalue)


def intensity(p: Uni, t: np.ndarray, at: float) -> float:
    """lambda just after `at`, from the events up to and including `at`."""
    t = np.asarray(t, float)
    t = t[t <= at]
    return float(p.mu + p.alpha * p.beta * np.sum(np.exp(-p.beta * (at - t))))


def chance_within(p: Uni, t: np.ndarray, now: float, h: float) -> float:
    """P(at least one new event in (now, now + h]): exact, because until the first new event the intensity is
    the known decay of the history (no simulation needed)."""
    t = np.asarray(t, float)
    t = t[t <= now]
    comp = p.mu * h + p.alpha * np.sum(np.exp(-p.beta * (now - t)) - np.exp(-p.beta * (now + h - t)))
    return float(1 - np.exp(-comp))


def simulate(p: Uni, T: float, rng: np.random.Generator, history: Optional[np.ndarray] = None,
             start: float = 0.0) -> np.ndarray:
    """Ogata thinning on (start, T]; `history` (times <= start) excites but is not returned."""
    h = np.asarray(history, float) if history is not None else np.zeros(0)
    exc = float(np.sum(np.exp(-p.beta * (start - h))))          # sum of exp(-beta (s - t_i)) at s
    out, s = [], start
    while True:
        bound = p.mu + p.alpha * p.beta * exc                    # intensity only decays until the next event
        w = rng.exponential(1 / bound)
        s += w
        if s > T:
            return np.asarray(out)
        exc *= np.exp(-p.beta * w)
        if rng.uniform() * bound <= p.mu + p.alpha * p.beta * exc:
            out.append(s)
            exc += 1.0


# ---- bivariate --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Bi:
    mu: Tuple[float, float]
    alpha: Tuple[Tuple[float, float], Tuple[float, float]]     # alpha[k][j]: k excited by j
    beta: Tuple[Tuple[float, float], Tuple[float, float]]

    @property
    def spectral_radius(self) -> float:
        return float(max(abs(np.linalg.eigvals(np.asarray(self.alpha)))))


def _cross(beta: float, tk: np.ndarray, tj: np.ndarray, T: float):
    """sum over j-events before each k-event of exp(-beta dt), and the compensator part over [0, T].
    One pass over the merged events, j-events weighted 1 and k-events 0 (k-events come first on a tie)."""
    t = np.concatenate([tk, tj])
    is_j = np.concatenate([np.zeros(len(tk)), np.ones(len(tj))])
    order = np.lexsort((is_j, t))
    a = _a(beta, t[order], is_j[order])
    s = np.empty(len(t))
    s[order] = a
    return s[: len(tk)], np.sum(1.0 - np.exp(-beta * (T - tj)))


def loglik_bi(p: Bi, ts: Sequence[np.ndarray], T: float) -> float:
    ll = 0.0
    for k in range(2):
        lam = np.full(len(ts[k]), p.mu[k])
        comp = p.mu[k] * T
        for j in range(2):
            s, c = _cross(p.beta[k][j], ts[k], ts[j], T)
            lam = lam + p.alpha[k][j] * p.beta[k][j] * s
            comp += p.alpha[k][j] * c
        ll += np.sum(np.log(lam)) - comp
    return float(ll)


def _bi_from(x) -> Bi:
    e = np.exp(x)
    return Bi((e[0], e[1]), ((e[2], e[3]), (e[4], e[5])), ((e[6], e[7]), (e[8], e[9])))


def fit_bi(ts: Sequence[Sequence[float]], T: float, start: float = 0.0) -> dict:
    """MLE of a bivariate exponential Hawkes (10 parameters) on [start, T]."""
    ts = [np.sort(np.asarray(t, float)) - start for t in ts]
    T = T - start
    nll = lambda x: -loglik_bi(_bi_from(x), ts, T)
    best = None
    for a0, b0 in [(0.2, 1.0), (0.1, 0.2), (0.3, 3.0)]:
        x0 = np.log([len(ts[0]) / T * 0.6, len(ts[1]) / T * 0.6] + [a0] * 4 + [b0] * 4)
        r = optimize.minimize(nll, x0, method="L-BFGS-B", bounds=[(-20, 10)] * 2 + [(-12, 1.5)] * 4 + [(-9, 7)] * 4)
        if best is None or r.fun < best.fun:
            best = r
    p = _bi_from(best.x)
    pvals = []
    for k in range(2):
        big = p.mu[k] * ts[k]
        for j in range(2):
            dt = ts[k][:, None] - ts[j][None, :]
            big = big + p.alpha[k][j] * np.where(dt > 0, 1 - np.exp(-p.beta[k][j] * np.where(dt > 0, dt, 0.0)), 0.0).sum(axis=1)
        pvals.append(float(stats.kstest(np.diff(np.concatenate([[0.0], big])), "expon").pvalue))
    return {"params": p, "loglik": -float(best.fun), "ks": pvals, "converged": bool(best.success)}


def simulate_bi(p: Bi, T: float, rng: np.random.Generator) -> Tuple[np.ndarray, np.ndarray]:
    """Ogata thinning for the bivariate process on (0, T]."""
    ev = ([], [])
    al, be = np.asarray(p.alpha), np.asarray(p.beta)
    exc = np.zeros((2, 2))                                        # exc[k, j]: decayed sum of j-events, kernel k<-j
    lam = lambda: np.asarray(p.mu) + (al * be * exc).sum(axis=1)
    s = 0.0
    while True:
        bound = lam().sum()
        w = rng.exponential(1 / bound)
        s += w
        if s > T:
            return np.asarray(ev[0]), np.asarray(ev[1])
        exc *= np.exp(-be * w)
        l = lam()
        u = rng.uniform() * bound
        for j in range(2):
            if u <= l[: j + 1].sum():
                ev[j].append(s)
                exc[:, j] += 1.0
                break


def jitter(days: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Daily event indices -> continuous times, uniform within the session (time-rescaling needs no ties)."""
    return np.sort(np.asarray(days, float) + rng.uniform(0, 1, len(days)))


# --- S79 item 11: the cascade reading used once a fall has started (additive) --------------------------------------------------

def expected_within(p: Uni, t: np.ndarray, now: float, h: float) -> float:
    """Expected number of new events in (now, now + h] from the baseline and the history's decaying excitation only (the
    compensator): events that the new events would themselves trigger are not counted here (see `cascade_reading`)."""
    t = np.asarray(t, float)
    t = t[t <= now]
    return float(p.mu * h + p.alpha * np.sum(np.exp(-p.beta * (now - t)) - np.exp(-p.beta * (now + h - t))))


def cascade_reading(r, p: Uni, threshold: float, horizon: int, lookback: int = 5, n_sim: int = 1000, seed: int = 20261105) -> dict:
    """The model's reading at the last session of the daily return series `r` (a pandas Series indexed by date, point-in-time up to
    its last row). A fall is IN PROGRESS when at least one session of `threshold` or worse (for example -2%) fell in the last
    `lookback` sessions. Events are placed mid-session as fitted. Expected further shocks over `horizon` sessions are the mean of
    `n_sim` seeded simulations that include the shocks' own offspring. ESTIMATES."""
    ev = np.flatnonzero((r.to_numpy(float) <= threshold)) + 0.5
    now = float(len(r))
    last_k = int(ev[-1] - 0.5) if len(ev) else None
    ago = (len(r) - 1 - last_k) if last_k is not None else None
    recent = [str(r.index[int(k - 0.5)])[:10] for k in ev if now - k <= lookback]
    out = {"asof": str(r.index[-1])[:10] if len(r) else None, "events_total": int(len(ev)), "in_progress": bool(ago is not None and ago < lookback),
           "last_shock": str(r.index[last_k])[:10] if last_k is not None else None, "sessions_since_last_shock": ago,
           "shocks_in_window": recent, "lookback_sessions": lookback, "horizon_sessions": horizon,
           "branching_ratio": float(p.alpha), "half_life_sessions": float(p.half_life), "baseline_per_session": float(p.mu)}
    out["intensity_now"] = intensity(p, ev, now)
    out["intensity_vs_baseline"] = out["intensity_now"] / p.mu if p.mu else None
    out["chance_another_shock"] = chance_within(p, ev, now, horizon)
    out["chance_constant_rate"] = float(1 - np.exp(-(p.mu / (1 - p.alpha)) * horizon)) if p.alpha < 1 else None     # long-run average rate
    out["expected_from_history"] = expected_within(p, ev, now, horizon)
    rng = np.random.default_rng(seed)
    counts = [len(simulate(p, now + horizon, rng, history=ev, start=now)) for _ in range(n_sim)]
    out["expected_further_shocks"] = float(np.mean(counts))
    out["expected_further_shocks_p90"] = float(np.percentile(counts, 90))
    out["simulations"] = n_sim
    return out
