"""S79b items 15, 15b, 7b: the pre-registered event studies of `docs/protocols/s79_wave_sentiment_protocol.md` (with Amendments 1 and 2).

This module is the RULE IN CODE. It may not be tuned after a result is seen: a change is a new, later test. Definitions as implemented (every choice the protocol left open is stated
here and in the report; none was adapted after seeing a return):

PERIOD            2004-01-01 .. 2021-12-31 only (PERIOD_START, PERIOD_END). The index series is cut to this range BEFORE anything is computed, so a window touching 2022-2025 cannot exist:
                  an event whose forward window ends after 2021-12-31 is cut (counted in `n_cut_period`) and `run_*` REFUSES (PeriodRefused) any `end` after PERIOD_END.
INDEX             IN: Nifty 500 TRI (data/indices/NIFTY500_TRI), US: S&P 500 (data/global/US_SP500). The "sessions" are the index series' own rows (each row is a session the index printed);
                  an event dated on a non-row is mapped to the last row on or before it.
FORWARD RETURN    for an event at row i (decided from rows <= i): F_h[i] = close[i+1+h] / close[i+1] - 1, i.e. h sessions, starting at the NEXT session's close (point in time).
NON-OVERLAP       events of one test are one kind (up/down waves, fear/greed readings are pooled, as the protocol has one test per flag); sorted by date, an event within h sessions of the
                  last KEPT event (row distance <= h) is dropped. Kept events are at least h+1 rows apart, so their forward windows share no return.
BASELINE          F_h of every row whose forward window is complete, EXCLUDING the event windows of ALL raw events (rows i .. i+h+1 of each event, kept or dropped).
INFERENCE         effect = mean(F after kept events) - mean(baseline). D* = mean(iid resample of the kept events' F) - mean(moving-block resample of the baseline, block = h sessions, blocks
                  of consecutive entries of the compacted baseline, floor(n_base/h) blocks); 10,000 draws, numpy default_rng(20261108) (one fresh generator per test). 95% interval = 2.5/97.5
                  percentiles of D*. The protocol says "bootstrap of the baseline"; the event side is resampled too because a baseline-only bootstrap ignores the events' own sampling error
                  (the events are non-overlapping, so an iid resample of them is valid). p = one-sided, in the direction of the point estimate: (1 + #{D* on the other side of 0}) / (draws + 1)
                  [the protocol claims "different", not a sign, so no sign is assumed before the data; this equals half a two-sided p]. t = effect / sd(D*) is reported, not gated.
HALVES            kept events split at the median event date (first half: date <= the (n/2)-th kept event); the effect of each half is its event mean minus the baseline mean of the SAME date range.
                  Same sign = both halves have the sign of the full effect.
GATE (all)        n_kept >= 20; p <= 1 - Phi(t_needed(N)) with N = learner.counter.n_tests(con) read at run time (the registration rows are already counted: this test is in N, not added);
                  same sign in both halves; |effect| - 0.2% cost >= 0.5%. Otherwise "no reliable follow-through". n_kept < 20 -> "n too small, no conclusion" (no gate evaluated).
RATE TESTS        value area: share of events whose close is back inside the prior value area within k sessions (back_in_k, measured from the event close) minus the share of the matched
                  baseline (Amendment 2: other days whose close lies the same distance outside a frozen value area; here the baseline is the outside-closes that the non-overlap rule did NOT keep,
                  stratified in 5 bins of distance outside (cut at the events' quantiles), events' bin weights). Claimed direction: events return more often (p one-sided up). The 0.5% index-return
                  condition is not defined for a share: reported as not applicable and not gated.
                  POC migration: events = days with a migration flag (mig = +1/-1 of the committed `volume_profile.event_frame`: 5-session lookback, 0.25 value-area-height dead band); outcome = sign of
                  the 5-session return from the NEXT session's close (ret_5_next); ties dropped; agreement against 50% with a one-sided exact binomial test (claimed direction: follows);
                  the "effect" for the 0.5% condition is the mean of sign(mig) * ret_5_next; halves: agreement above 50% in both.
Nothing here is a model: all numbers are the code's."""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

PERIOD_START = date(2004, 1, 1)
PERIOD_END = date(2021, 12, 31)
SEED = 20261108
DRAWS = 10_000
COST = 0.002
MIN_EFFECT = 0.005
MIN_EVENTS = 20
N_BINS = 5
REPO = Path(__file__).resolve().parents[3]
PROTOCOL = "docs/protocols/s79_wave_sentiment_protocol.md"
RESULTS_JSON = "docs/research/wave_sentiment_results_s79.json"
NOTE_KEY = "s79:wave_sentiment:{test}"

# test -> (family, horizon).  The family decides the event list and the statistic.
TESTS: Dict[str, Tuple[str, int]] = {
    "wave_5": ("wave", 5), "wave_20": ("wave", 20),
    "rotation_5": ("rotation", 5), "rotation_20": ("rotation", 20),
    "crude_fall_5": ("crude_fall", 5), "crude_fall_20": ("crude_fall", 20),
    "extreme_sentiment_5": ("extreme_sentiment", 5), "extreme_sentiment_20": ("extreme_sentiment", 20),
    "value_area_return_1": ("value_area", 1), "value_area_return_5": ("value_area", 5),
    "poc_migration_5": ("poc_migration", 5),
}
INDEX_KEY = {"IN": ("indices", "NIFTY500_TRI"), "US": ("global", "US_SP500")}
INDEX_NAME = {"IN": "Nifty 500 TRI", "US": "S&P 500"}


class PeriodRefused(ValueError):
    """A request that would touch 2022-2025 (spent) or lie before 2004."""


class ProtocolMismatch(RuntimeError):
    """The protocol file is not the committed one: the run refuses."""


# ----------------------------------------------------------------------------------------------------------------------------------
# shas
# ----------------------------------------------------------------------------------------------------------------------------------

def _norm(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def code_sha() -> str:
    return hashlib.sha256(_norm(Path(__file__).read_bytes())).hexdigest()


def protocol_sha(repo: Path = REPO, path: str = PROTOCOL, require_committed: bool = True) -> str:
    """sha256 of the protocol file (line ends normalised). With `require_committed`, the working file must equal the committed one (git HEAD) or the run refuses."""
    p = Path(repo) / path
    if not p.exists():
        raise ProtocolMismatch(f"protocol file missing: {path}")
    cur = _norm(p.read_bytes())
    if require_committed:
        try:
            r = subprocess.run(["git", "-C", str(repo), "show", f"HEAD:{path}"], capture_output=True, timeout=30)
        except Exception as e:                                           # noqa: BLE001
            raise ProtocolMismatch(f"cannot read the committed protocol (git: {type(e).__name__})") from e
        if r.returncode != 0:
            raise ProtocolMismatch("the protocol file is not committed")
        if _norm(r.stdout) != cur:
            raise ProtocolMismatch("the protocol file differs from the committed one: no run")
    return hashlib.sha256(cur).hexdigest()


# ----------------------------------------------------------------------------------------------------------------------------------
# the index, forward returns, events
# ----------------------------------------------------------------------------------------------------------------------------------

def check_period(start: Optional[date], end: Optional[date]) -> Tuple[date, date]:
    s, e = start or PERIOD_START, end or PERIOD_END
    if e > PERIOD_END:
        raise PeriodRefused(f"end {e} is after {PERIOD_END}: 2022-2025 is spent and is never used here")
    if s < PERIOD_START:
        raise PeriodRefused(f"start {s} is before {PERIOD_START}")
    return s, e


def load_index(root, market: str = "IN") -> pd.Series:
    """Close of the market's index per session, cut to the period (nothing after 2021-12-31 is ever in memory)."""
    if market not in INDEX_KEY:
        raise ValueError(market)
    folder, key = INDEX_KEY[market]
    p = Path(root) / folder / f"{key}.parquet"
    if not p.exists():
        return pd.Series(dtype=float)
    d = pd.read_parquet(p)
    col = "close" if "close" in d.columns else d.columns[-1]
    idx = pd.to_datetime(d["date"]).dt.date
    s = pd.Series(pd.to_numeric(d[col], errors="coerce").to_numpy(float), index=idx)
    s = s[s.notna() & (s > 0)]
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s[(s.index >= PERIOD_START) & (s.index <= PERIOD_END)]


def forward_returns(close: np.ndarray, h: int) -> np.ndarray:
    """F_h[i] = close[i+1+h] / close[i+1] - 1 (NaN where the window is not complete)."""
    c = np.asarray(close, float)
    n = len(c)
    out = np.full(n, np.nan)
    if n > h + 1:
        out[: n - h - 1] = c[1 + h:] / c[1: n - h] - 1.0
    return out


def event_rows(dates: Sequence[date], events: Sequence[Tuple[date, str]]) -> Tuple[List[Tuple[int, date, str]], int]:
    """Map event dates to rows (last row on or before). Events after PERIOD_END or before the first row are dropped; returns (rows sorted, n_dropped)."""
    rows, dropped = [], 0
    for d, lab in events:
        if d > PERIOD_END or d < dates[0]:
            dropped += 1
            continue
        i = _bisect(dates, d)
        rows.append((i, dates[i], lab))
    rows.sort(key=lambda r: r[0])
    return rows, dropped


def _bisect(dates: Sequence[date], d: date) -> int:
    lo, hi = 0, len(dates)
    while lo < hi:
        mid = (lo + hi) // 2
        if dates[mid] <= d:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


def non_overlapping(rows: Sequence[Tuple[int, date, str]], h: int) -> List[Tuple[int, date, str]]:
    """Drop events within h sessions (row distance <= h) of the last kept event."""
    kept: List[Tuple[int, date, str]] = []
    for r in rows:
        if kept and r[0] - kept[-1][0] <= h:
            continue
        kept.append(r)
    return kept


def baseline_mask(n: int, raw_rows: Sequence[Tuple[int, date, str]], fwd: np.ndarray, h: int) -> np.ndarray:
    ok = np.isfinite(fwd)
    for i, _, _ in raw_rows:
        ok[i: min(n, i + h + 2)] = False
    return ok


# ----------------------------------------------------------------------------------------------------------------------------------
# the bootstrap and the gate
# ----------------------------------------------------------------------------------------------------------------------------------

def boot_diff(ev: np.ndarray, base: np.ndarray, h: int, draws: int, rng: np.random.Generator) -> np.ndarray:
    """D* = mean(iid resample of ev) - mean(moving-block resample of base, block h). Both sides' sampling error."""
    ev, base = np.asarray(ev, float), np.asarray(base, float)
    n_e, n_b = len(ev), len(base)
    h = max(1, min(int(h), n_b))
    k = max(n_b // h, 1)
    cs = np.concatenate([[0.0], np.cumsum(base)])
    bm = (cs[h:] - cs[:-h]) / h
    out = np.empty(draws)
    step = 2000
    for a in range(0, draws, step):
        m = min(step, draws - a)
        eb = ev[rng.integers(0, n_e, size=(m, n_e))].mean(axis=1)
        bb = bm[rng.integers(0, len(bm), size=(m, k))].mean(axis=1)
        out[a: a + m] = eb - bb
    return out


def one_sided_p(d_star: np.ndarray, effect: float) -> float:
    """In the direction of the point estimate: share of draws on the other side of zero (with the +1 correction)."""
    if effect == 0 or not np.isfinite(effect):
        return 1.0
    c = int((d_star <= 0).sum()) if effect > 0 else int((d_star >= 0).sum())
    return (c + 1) / (len(d_star) + 1)


def p_cut(t_needed: float) -> float:
    from scipy.stats import norm
    return float(norm.sf(t_needed))


def gate(res: dict, t_needed: float, cost: float = COST, min_effect: float = MIN_EFFECT, min_events: int = MIN_EVENTS) -> dict:
    """The four conditions; `effect_ok` is None (not applicable) for the share test."""
    n_ok = res["n_events"] >= min_events
    p_ok = bool(res["p"] is not None and res["p"] <= p_cut(t_needed))
    halves_ok = bool(res.get("same_sign"))
    if res.get("effect_gate_applies", True):
        e_ok = bool(abs(res["effect_gate_value"]) - cost >= min_effect - 1e-15)
    else:
        e_ok = None
    allok = n_ok and p_ok and halves_ok and (e_ok is not False)
    return {"n_ok": n_ok, "p_ok": p_ok, "halves_ok": halves_ok, "effect_ok": e_ok, "passed": bool(allok), "p_cut": p_cut(t_needed), "t_needed": t_needed}


def _verdict(res: dict) -> str:
    if res["status"] == "not_available":
        return "not available"
    if res["status"] == "n_too_small":
        return f"n too small, no conclusion ({res['n_events']} non-overlapping events; {res['n_events_raw']} before the non-overlap rule)"
    if res["passed"]:
        return res["followed"]
    return "no reliable follow-through"


def _fmt_followed(res: dict) -> str:
    u = res.get("unit", "pct")
    if u == "pct":
        return (f"followed through: {res['n_events']} events, effect {res['effect'] * 100:+.2f}%, interval [{res['ci_low'] * 100:+.2f}%, {res['ci_high'] * 100:+.2f}%] "
                f"({res['range'][0]} to {res['range'][1]})")
    return (f"followed through: {res['n_events']} events, difference {res['effect'] * 100:+.1f} points, interval [{res['ci_low'] * 100:+.1f}, {res['ci_high'] * 100:+.1f}] points "
            f"({res['range'][0]} to {res['range'][1]})")


# ----------------------------------------------------------------------------------------------------------------------------------
# study 1: forward return of the index after events (waves, rotation, crude falls, extreme sentiment)
# ----------------------------------------------------------------------------------------------------------------------------------

def _base_result(test: str, market: str, h: int, family: str) -> dict:
    return {"test": test, "market": market, "h": h, "family": family, "status": "ok", "n_events_raw": 0, "n_events": 0, "n_baseline": 0, "n_cut_period": 0, "n_cut_window": 0,
            "effect": None, "ci_low": None, "ci_high": None, "p": None, "sd_boot": None, "t_stat": None, "passed": False, "unit": "pct", "same_sign": None, "halves": None}


def index_event_study(test: str, market: str, h: int, dates: Sequence[date], close: Sequence[float], events: Sequence[Tuple[date, str]],
                      t_needed: float, n_counter: int, draws: int = DRAWS, seed: int = SEED, family: str = "") -> dict:
    """The forward-return study on a given series and event list (see the module docstring). `dates`/`close` must lie inside the period (refused otherwise)."""
    dates = list(dates)
    if dates and (dates[-1] > PERIOD_END or dates[0] < PERIOD_START):
        raise PeriodRefused("the series reaches outside 2004-01-01..2021-12-31")
    res = _base_result(test, market, h, family)
    res.update({"t_needed": t_needed, "n_counter": n_counter, "seed": seed, "draws": draws})
    c = np.asarray(close, float)
    fwd = forward_returns(c, h)
    raw, dropped = event_rows(dates, events)
    res["n_cut_period"] = dropped
    in_window = [r for r in raw if np.isfinite(fwd[r[0]])]
    res["n_cut_window"] = len(raw) - len(in_window)
    kept = non_overlapping(in_window, h)
    res["n_events_raw"] = len(events)
    res["n_events"] = len(kept)
    res["range"] = (str(dates[0]) if dates else None, str(dates[-1]) if dates else None)
    if kept:
        res["event_range"] = (str(kept[0][1]), str(kept[-1][1]))
    if len(kept) < MIN_EVENTS:
        res["status"] = "n_too_small"
        res["verdict"] = _verdict(res)
        return res
    ev = np.array([fwd[i] for i, _, _ in kept])
    mask = baseline_mask(len(c), raw, fwd, h)                       # the windows of ALL raw events are excluded, kept or dropped
    base = fwd[mask]
    base_d = [dates[i] for i in np.where(mask)[0]]
    res["n_baseline"] = int(len(base))
    if len(base) < 3 * h:
        res["status"] = "n_too_small"
        res["verdict"] = "n too small, no conclusion (baseline too short)"
        return res
    effect = float(ev.mean() - base.mean())
    rng = np.random.default_rng(seed)
    d_star = boot_diff(ev, base, h, draws, rng)
    sd = float(d_star.std(ddof=1))
    res.update({"effect": effect, "ci_low": float(np.percentile(d_star, 2.5)), "ci_high": float(np.percentile(d_star, 97.5)), "p": one_sided_p(d_star, effect),
                "sd_boot": sd, "t_stat": effect / sd if sd > 0 else None, "direction": "up" if effect > 0 else "down",
                "median_diff": float(np.median(ev) - np.median(base)), "hit_events": float((ev > 0).mean()), "hit_base": float((base > 0).mean()),
                "mean_events": float(ev.mean()), "mean_base": float(base.mean())})
    # halves: split at the median event date; each half against the baseline of its own dates
    kd = [r[1] for r in kept]
    med = kd[len(kd) // 2 - 1]
    h1 = np.array([fwd[r[0]] for r in kept if r[1] <= med])
    h2 = np.array([fwd[r[0]] for r in kept if r[1] > med])
    b1 = np.array([b for b, d in zip(base, base_d) if d <= med])
    b2 = np.array([b for b, d in zip(base, base_d) if d > med])
    e1 = float(h1.mean() - (b1.mean() if len(b1) else base.mean()))
    e2 = float(h2.mean() - (b2.mean() if len(b2) else base.mean()))
    s = math.copysign(1.0, effect)
    res["halves"] = {"split_at": str(med), "first": {"n": int(len(h1)), "effect": e1}, "second": {"n": int(len(h2)), "effect": e2}}
    res["same_sign"] = bool(math.copysign(1.0, e1) == s and math.copysign(1.0, e2) == s and e1 != 0 and e2 != 0)
    res["effect_gate_applies"], res["effect_gate_value"] = True, effect
    if any("up" in str(r[2]) or "down" in str(r[2]) or r[2] in ("fear", "greed") for r in kept):      # descriptive only, never gated
        by = {}
        for lab in sorted({r[2] for r in kept}):
            v = np.array([fwd[r[0]] for r in kept if r[2] == lab])
            by[lab] = {"n": int(len(v)), "mean_minus_baseline": float(v.mean() - base.mean())}
        res["by_label_descriptive"] = by
    return _finish(res, t_needed)


def _finish(res: dict, t_needed: float) -> dict:
    g = gate(res, t_needed)
    res["gate"] = g
    res["passed"] = g["passed"]
    sens = {}
    from pflab.learner import counter
    for n in (100, 300):
        t = counter.t_needed(n)
        sens[str(n)] = {"t_needed": round(t, 3), "passed": gate(res, t)["passed"]}
    res["sensitivity_bar"] = sens
    if res["passed"]:
        res["followed"] = _fmt_followed(res)
    res["verdict"] = _verdict(res)
    return res


# ----------------------------------------------------------------------------------------------------------------------------------
# study 2: value-area exits (a share), study 3: POC migration (binomial)
# ----------------------------------------------------------------------------------------------------------------------------------

def value_area_study(test: str, market: str, k: int, frame: pd.DataFrame, t_needed: float, n_counter: int, draws: int = DRAWS, seed: int = SEED) -> dict:
    """`frame` = quant.volume_profile.value_area_events (one row per session, ascending, columns date, outside, dist_pct, back_in_1, back_in_5)."""
    res = _base_result(test, market, k, "value_area")
    res.update({"t_needed": t_needed, "n_counter": n_counter, "seed": seed, "draws": draws, "unit": "share", "effect_gate_applies": False, "effect_gate_value": 0.0})
    if frame is None or len(frame) == 0:
        res["status"] = "not_available"
        res["verdict"] = _verdict(res)
        return res
    f = frame.reset_index(drop=True)
    dts = list(f["date"])
    if dts[-1] > PERIOD_END or dts[0] < PERIOD_START:
        raise PeriodRefused("the value-area frame reaches outside 2004-01-01..2021-12-31")
    col = f"back_in_{k}"
    out = (f["outside"].to_numpy(float) != 0) & np.isfinite(f["outside"].to_numpy(float))
    y = f[col].to_numpy(float)
    dist = f["dist_pct"].to_numpy(float)
    ok = out & np.isfinite(y)
    rows = [(int(i), dts[i], "up" if f["outside"].iloc[i] > 0 else "down") for i in np.where(ok)[0]]
    res["n_events_raw"] = len(rows)
    kept = non_overlapping(rows, k)
    res["n_events"] = len(kept)
    res["range"] = (str(dts[0]), str(dts[-1]))
    if kept:
        res["event_range"] = (str(kept[0][1]), str(kept[-1][1]))
    kept_i = {r[0] for r in kept}
    if len(kept) < MIN_EVENTS:
        res["status"] = "n_too_small"
        res["verdict"] = _verdict(res)
        return res
    base_idx = np.array([r[0] for r in rows if r[0] not in kept_i])
    res["n_baseline"] = int(len(base_idx))
    ev_idx = np.array([r[0] for r in kept])
    edges = np.unique(np.quantile(dist[ev_idx], np.linspace(0, 1, N_BINS + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    nb = len(edges) - 1
    be, bb = np.clip(np.searchsorted(edges, dist[ev_idx], side="right") - 1, 0, nb - 1), np.clip(np.searchsorted(edges, dist[base_idx], side="right") - 1, 0, nb - 1) if len(base_idx) else np.array([], int)
    used = [b for b in range(nb) if (be == b).sum() > 0 and (bb == b).sum() >= max(k, 3)]
    if not used:
        res["status"] = "n_too_small"
        res["verdict"] = "n too small, no conclusion (no matched baseline)"
        return res
    w = np.array([(be == b).sum() for b in used], float)
    w /= w.sum()
    rng = np.random.default_rng(seed)

    def strat(ev_pos, ev_b, base_pos, base_b):
        e_rates = np.array([y[ev_pos][ev_b == b].mean() for b in used])
        b_rates = np.array([y[base_pos][base_b == b].mean() for b in used])
        return float((w * (e_rates - b_rates)).sum()), e_rates, b_rates
    effect, e_rates, b_rates = strat(ev_idx, be, base_idx, bb)
    d_star = np.zeros(draws)
    for wb, b in zip(w, used):
        d_star += wb * boot_diff(y[ev_idx][be == b], y[base_idx][bb == b], k, draws, rng)
    sd = float(d_star.std(ddof=1))
    # claimed direction: events return MORE often
    cnt = int((d_star <= 0).sum())
    res.update({"effect": effect, "ci_low": float(np.percentile(d_star, 2.5)), "ci_high": float(np.percentile(d_star, 97.5)), "p": (cnt + 1) / (draws + 1) if effect > 0 else 1.0,
                "sd_boot": sd, "t_stat": effect / sd if sd > 0 else None, "direction": "up" if effect > 0 else "down",
                "share_events": float(y[ev_idx].mean()), "share_baseline_matched": float((w * b_rates).sum()), "bins_used": len(used)})
    kd = [r[1] for r in kept]
    med = kd[len(kd) // 2 - 1]
    effs = []
    base_dates = np.array([dts[i] for i in base_idx], dtype=object)
    for first in (True, False):
        sel = [r for r in kept if (r[1] <= med) == first]
        ei = np.array([r[0] for r in sel])
        bsel = base_idx[np.array([(d <= med) == first for d in base_dates], bool)]
        ebin = np.clip(np.searchsorted(edges, dist[ei], side="right") - 1, 0, nb - 1)
        bbin = np.clip(np.searchsorted(edges, dist[bsel], side="right") - 1, 0, nb - 1) if len(bsel) else np.array([], int)
        ub = [b for b in used if (ebin == b).sum() > 0 and (bbin == b).sum() > 0]
        if not ub:
            effs.append(float("nan"))
            continue
        ww = np.array([(ebin == b).sum() for b in ub], float)
        ww /= ww.sum()
        effs.append(float(sum(wi * (y[ei][ebin == b].mean() - y[bsel][bbin == b].mean()) for wi, b in zip(ww, ub))))
    res["halves"] = {"split_at": str(med), "first": {"n": int(sum(1 for r in kept if r[1] <= med)), "effect": effs[0]},
                     "second": {"n": int(sum(1 for r in kept if r[1] > med)), "effect": effs[1]}}
    res["same_sign"] = bool(all(np.isfinite(e) and e > 0 for e in effs) and effect > 0)
    return _finish(res, t_needed)


def poc_migration_study(test: str, market: str, frame: pd.DataFrame, t_needed: float, n_counter: int, h: int = 5, draws: int = DRAWS, seed: int = SEED) -> dict:
    """`frame` = quant.volume_profile.value_area_events (columns date, mig, ret_5_next)."""
    from scipy.stats import binomtest
    res = _base_result(test, market, h, "poc_migration")
    res.update({"t_needed": t_needed, "n_counter": n_counter, "seed": seed, "draws": draws, "unit": "share"})
    if frame is None or len(frame) == 0:
        res["status"] = "not_available"
        res["verdict"] = _verdict(res)
        return res
    f = frame.reset_index(drop=True)
    dts = list(f["date"])
    if dts[-1] > PERIOD_END or dts[0] < PERIOD_START:
        raise PeriodRefused("the value-area frame reaches outside 2004-01-01..2021-12-31")
    mig, ret = f["mig"].to_numpy(float), f["ret_5_next"].to_numpy(float)
    rows = [(int(i), dts[i], "up" if mig[i] > 0 else "down") for i in range(len(f)) if np.isfinite(mig[i]) and mig[i] != 0 and np.isfinite(ret[i])]
    res["n_events_raw"] = len(rows)
    kept = [r for r in non_overlapping(rows, h) if ret[r[0]] != 0]
    res["n_events"] = len(kept)
    res["range"] = (str(dts[0]), str(dts[-1]))
    if kept:
        res["event_range"] = (str(kept[0][1]), str(kept[-1][1]))
    if len(kept) < MIN_EVENTS:
        res["status"] = "n_too_small"
        res["verdict"] = _verdict(res)
        return res
    sg = np.array([math.copysign(1.0, mig[r[0]]) for r in kept])
    rt = np.array([ret[r[0]] for r in kept])
    agree = (np.sign(rt) == sg)
    n, kk = len(kept), int(agree.sum())
    bt = binomtest(kk, n, 0.5, alternative="greater")
    ci = binomtest(kk, n, 0.5).proportion_ci(confidence_level=0.95)
    signed = sg * rt
    res.update({"effect": kk / n - 0.5, "ci_low": float(ci.low - 0.5), "ci_high": float(ci.high - 0.5), "p": float(bt.pvalue), "agree": kk, "agree_share": kk / n,
                "mean_signed_return": float(signed.mean()), "sd_boot": float(math.sqrt(0.25 / n)), "t_stat": float((kk / n - 0.5) / math.sqrt(0.25 / n)),
                "direction": "follows" if kk / n > 0.5 else "against", "effect_gate_applies": True, "effect_gate_value": float(signed.mean())})
    kd = [r[1] for r in kept]
    med = kd[len(kd) // 2 - 1]
    sh = [float(agree[[r[1] <= med for r in kept]].mean()) - 0.5, float(agree[[r[1] > med for r in kept]].mean()) - 0.5]
    res["halves"] = {"split_at": str(med), "first": {"n": int(sum(r[1] <= med for r in kept)), "effect": sh[0]}, "second": {"n": int(sum(r[1] > med for r in kept)), "effect": sh[1]}}
    res["same_sign"] = bool(sh[0] > 0 and sh[1] > 0)
    return _finish(res, t_needed)


# ----------------------------------------------------------------------------------------------------------------------------------
# event lists for the real run
# ----------------------------------------------------------------------------------------------------------------------------------

def event_list(family: str, market: str, root) -> Optional[List[Tuple[date, str]]]:
    """[(date, label)] for the forward-return families, from the other agents' event lists; None when the list does not exist for the market."""
    s, e = PERIOD_START, PERIOD_END
    if family == "wave":
        from pflab.quant import waves
        return None if market != "IN" else [(x["date"], x.get("direction") or "") for x in waves.wave_events(market, s, e, root=Path(root))]
    if family == "rotation":
        from pflab.quant import waves
        return None if market != "IN" else [(x["date"], x.get("direction") or "") for x in waves.rotation_events(market, s, e, root=Path(root))]
    if family == "crude_fall":
        from pflab.quant import waves
        return [(x["date"], "fall") for x in waves.crude_fall_events(market, s, e, root=Path(root))]
    if family == "extreme_sentiment":
        from pflab.sentiment.compute import extreme_sentiment_events
        df = extreme_sentiment_events(market, s, e, root=Path(root))
        return [(pd.Timestamp(d).date(), str(k)) for d, k in zip(df["date"], df["kind"])]
    raise ValueError(family)


def va_frame(market: str, root) -> pd.DataFrame:
    from pflab.quant import volume_profile as VP
    return VP.value_area_events(market, PERIOD_START, PERIOD_END, root=Path(root))


def bar_now(con) -> Tuple[float, int]:
    from pflab.learner import counter
    n = counter.n_tests(con)
    return counter.t_needed(n), n


def run_test(test: str, market: str, root, con, draws: int = DRAWS, frames: Optional[dict] = None) -> dict:
    """Run one registered test on the real data (or the given root). Returns the result dict (not recorded)."""
    if test not in TESTS:
        raise KeyError(test)
    family, h = TESTS[test]
    t_needed, n = bar_now(con)
    if family in ("value_area", "poc_migration"):
        fr = (frames or {}).get(market)
        if fr is None:
            fr = va_frame(market, root)
        r = value_area_study(test, market, h, fr, t_needed, n, draws) if family == "value_area" else poc_migration_study(test, market, fr, t_needed, n, h, draws)
    else:
        ev = event_list(family, market, root)
        if ev is None:
            r = _base_result(test, market, h, family)
            r.update({"status": "not_available", "t_needed": t_needed, "n_counter": n, "note": "no daily cross-section of names / flows for this market"})
            r["verdict"] = _verdict(r)
            return r
        s = load_index(root, market)
        if s.empty:
            r = _base_result(test, market, h, family)
            r.update({"status": "not_available", "t_needed": t_needed, "n_counter": n, "note": f"no {INDEX_NAME[market]} series"})
            r["verdict"] = _verdict(r)
            return r
        r = index_event_study(test, market, h, list(s.index), s.to_numpy(float), ev, t_needed, n, draws, family=family)
    r["index"] = INDEX_NAME[market]
    return r


# ----------------------------------------------------------------------------------------------------------------------------------
# recording
# ----------------------------------------------------------------------------------------------------------------------------------

def _clean(v):
    if isinstance(v, (np.floating, float)):
        return None if not math.isfinite(float(v)) else float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def result_row(res: dict, protocol_sha_: str, code_sha_: str, now: datetime) -> dict:
    details = {k: res[k] for k in res if k not in ("test", "market", "n_events", "n_baseline", "effect", "ci_low", "ci_high", "p", "t_needed", "n_counter", "passed", "verdict")}
    details = json.loads(json.dumps(details, default=_clean))
    return {"test": res["test"], "market": res["market"], "n_events": int(res["n_events"]), "n_baseline": int(res.get("n_baseline") or 0), "effect": _clean(res.get("effect")),
            "ci_low": _clean(res.get("ci_low")), "ci_high": _clean(res.get("ci_high")), "p": _clean(res.get("p")), "t_needed": _clean(res.get("t_needed")),
            "n_counter": int(res.get("n_counter") or 0), "passed": bool(res.get("passed")), "verdict": res["verdict"], "halves_json": json.dumps(details, default=_clean),
            "ran_at": now, "protocol_sha": protocol_sha_, "code_sha": code_sha_}


COLS = ["test", "market", "n_events", "n_baseline", "effect", "ci_low", "ci_high", "p", "t_needed", "n_counter", "passed", "verdict", "halves_json", "ran_at", "protocol_sha", "code_sha"]


def already_recorded(con, test: str, market: str) -> bool:
    try:
        return con.execute("SELECT 1 FROM wave_study_results_s79 WHERE test=? AND market=?", [test, market]).fetchone() is not None
    except Exception:
        return False


def record(con, res: dict, protocol_sha_: str, now: Optional[datetime] = None) -> dict:
    """One row in wave_study_results_s79 and the filling of the registration row in learn_tests (passed/t_dev/n_dev/threshold_dev, once: only while passed IS NULL).
    Refuses a second record of the same (test, market). Nothing is added to the counter (the registration already counted the test)."""
    now = now or datetime.now()
    if already_recorded(con, res["test"], res["market"]):
        raise RuntimeError(f"{res['test']} / {res['market']} was already run for the record: it is run once")
    row = result_row(res, protocol_sha_, code_sha(), now)
    con.execute(f"INSERT INTO wave_study_results_s79 ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))})", [row[c] for c in COLS])
    filled = 0
    if res["market"] == "IN" and res.get("status") != "not_available":
        note = NOTE_KEY.format(test=res["test"])
        r = con.execute("SELECT test_id FROM learn_tests WHERE note=? AND passed IS NULL", [note]).fetchone()
        if r:
            con.execute("UPDATE learn_tests SET passed=?, t_dev=?, n_dev=?, threshold_dev=? WHERE test_id=?",
                        [bool(res["passed"]), _clean(res.get("t_stat")), int(res["n_events"]), _clean(res.get("t_needed")), r[0]])
            filled = 1
    row["learn_tests_filled"] = filled
    return row


def results(con) -> List[dict]:
    try:
        df = con.execute("SELECT * FROM wave_study_results_s79 ORDER BY market, test").df()
    except Exception:
        return []
    out = []
    for r in df.to_dict("records"):
        try:
            r["details"] = json.loads(r.pop("halves_json") or "{}")
        except Exception:
            r["details"] = {}
        r["ran_at"] = str(r["ran_at"])
        out.append({k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in r.items()})
    return out


# tests that exist in the registration but are not run by this module on a given reason are listed by the runner/tool from here
NOT_RUN_REASONS: Dict[str, str] = {}
