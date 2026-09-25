"""E2-A §8a — the pre-registered red-flag event study.

**The pass condition was written into the charter on 2026-09-25, before this
module existed and before anything was computed.** It is reproduced here so
the code and the charter can be read against each other, and it is not a
parameter: nothing in this file may be tuned to make a study pass, and §8a
forbids dropping or weighting any flag on the basis of its result.

    Events   a name's FIRST flag in any trailing 12 months, dated by
             `usable_from`, restricted to names in E1's eligible universe
             at that month-end. All nine flags pooled; each also reported
             separately.
    Outcome  return from the next open over 1, 3 and 6 months, MINUS the
             median return of unflagged eligible names in the same
             turnover-rank decile and 12-1 momentum quintile at that
             month-end.
    Pass     mean 6-month excess return across monthly event cohorts is
             negative with t < -2 (Newey-West, 5 lags) in 2017-2019, AND
             negative in 2020-2021.

Why the matching. A flagged name is typically thinner and already falling.
Without matching on both liquidity and momentum the study would measure
size and momentum -- which E1 already trades -- rather than the flag. The
median of the matched cohort is used rather than the mean because a single
multi-bagger in a decile would otherwise set the benchmark.

Why cohorts. Six-month horizons overlap, so individual events are not
independent. Collapsing to one observation per month-end and applying
Newey-West with 5 lags over the cohort series is the standard treatment;
the t-statistic is on the cohort means, never on the pooled events.
"""
from __future__ import annotations

from datetime import date
from typing import Optional, Sequence

import numpy as np
import pandas as pd

HORIZONS = (1, 3, 6)
GATING_HORIZON = 6
NEWEY_WEST_LAGS = 5
T_THRESHOLD = -2.0
TURNOVER_DECILES = 10
MOMENTUM_QUINTILES = 5


def newey_west_t(x: Sequence[float], lags: int = NEWEY_WEST_LAGS) -> Optional[float]:
    """t-statistic of the mean of `x`, autocorrelation-robust.

    Bartlett kernel. Returns None when the series is too short to support
    the lag length, rather than a number computed from nothing.
    """
    a = np.asarray([v for v in x if v is not None and np.isfinite(v)], dtype=float)
    n = len(a)
    if n <= lags + 1:
        return None
    mu = a.mean()
    e = a - mu
    gamma0 = float(e @ e) / n
    s = gamma0
    for L in range(1, lags + 1):
        w = 1.0 - L / (lags + 1.0)
        cov = float(e[L:] @ e[:-L]) / n
        s += 2.0 * w * cov
    if s <= 0:
        return None
    return float(mu / np.sqrt(s / n))


class HorizonPastPeriodEnd(Exception):
    """The horizon would need a price the period has not been shown.

    §8a, 2026-09-25: an event whose 1-, 3- or 6-month horizon ends after the
    period end is excluded from that horizon and COUNTED. Without this a
    six-month horizon opened in late 2019 reaches into 2020 -- data
    development has not seen -- and the last months of validation read into
    the sealed period. Counted rather than silent, because a horizon that
    quietly drops its most recent cohorts is a different study.
    """


def _forward_return(open_w: pd.DataFrame, isin: str, entry: date,
                    months: int, calendar, period_end: Optional[date] = None
                    ) -> Optional[float]:
    """Return from the open after `entry` to the open `months` later.

    The entry is the NEXT open, per §8a, because a flag usable on session t
    can only be acted on at t's open at the earliest.

    Raises HorizonPastPeriodEnd when the horizon would read a price after
    `period_end`. That is deliberately an exception rather than a None: a
    missing price and a horizon running off the end of the period are
    different facts and the report counts them apart.
    """
    if isin not in open_w.columns:
        return None
    start = calendar.next_session(entry)
    if start is None:
        return None
    end_target = start + pd.Timedelta(days=int(round(months * 30.44)))
    end_target = end_target.date() if hasattr(end_target, "date") else end_target
    if period_end is not None and end_target > period_end:
        raise HorizonPastPeriodEnd(
            f"{months}m horizon from {start} ends {end_target}, past {period_end}")
    end = calendar.asof(end_target)
    if end is None:
        return None
    end = calendar[end]
    if period_end is not None and end > period_end:
        raise HorizonPastPeriodEnd(
            f"{months}m horizon from {start} lands {end}, past {period_end}")
    if end <= start:
        return None
    try:
        p0 = float(open_w.at[start, isin])
        p1 = float(open_w.at[end, isin])
    except KeyError:
        return None
    if not np.isfinite(p0) or not np.isfinite(p1) or p0 <= 0:
        return None
    return p1 / p0 - 1.0


def run(events: pd.DataFrame, month_ends: Sequence[date], eligible_at_fn,
        open_w: pd.DataFrame, turnover_w: pd.DataFrame, momentum_w: pd.DataFrame,
        calendar, periods: Optional[dict] = None,
        first_flag_window_months: int = 12,
        period_end: Optional[date] = None) -> dict:
    """The §8a study. Returns cohort means, t-statistics and the pass flag.

    `eligible_at_fn(m)` gives E1's eligible universe at month-end `m`;
    `turnover_w` and `momentum_w` are the wide panels the matching uses.
    """
    periods = periods or {"2017-2019": (date(2017, 1, 1), date(2019, 12, 31)),
                          "2020-2021": (date(2020, 1, 1), date(2021, 12, 31))}
    ev = events.dropna(subset=["isin", "usable_from"]).copy()
    ev["usable_from"] = pd.to_datetime(ev["usable_from"]).dt.date

    cohorts: list = []
    per_flag: dict = {}
    # §8a 2026-09-25: events whose horizon runs past the period end, counted
    excluded = {h: 0 for h in HORIZONS}
    for m in month_ends:
        elig = set(eligible_at_fn(m))
        if not elig:
            continue
        lo = m - pd.Timedelta(days=int(round(first_flag_window_months * 30.44)))
        lo = lo.date() if hasattr(lo, "date") else lo
        # events that became usable in the month ending at m
        prev = [x for x in month_ends if x < m]
        window_start = prev[-1] if prev else lo
        new = ev[(ev["usable_from"] > window_start) & (ev["usable_from"] <= m)
                 & ev["isin"].isin(elig)]
        if not len(new):
            continue
        # §8a: a name's FIRST flag in any trailing 12 months
        prior = set(ev.loc[(ev["usable_from"] > lo) & (ev["usable_from"] <= window_start),
                           "isin"])
        first = new[~new["isin"].isin(prior)]
        if not len(first):
            continue

        matched = _match(elig, turnover_w, momentum_w, m)
        for h in HORIZONS:
            ex = []
            for isin in sorted(set(first["isin"])):
                # §8a 2026-09-25: a horizon that would read a price after the
                # period end is excluded from that horizon and counted.
                try:
                    r = _forward_return(open_w, isin, m, h, calendar, period_end)
                except HorizonPastPeriodEnd:
                    excluded[h] += 1
                    continue
                if r is None:
                    continue
                pr = []
                for peer in matched.get(_bucket_of(isin, matched), []):
                    if peer == isin:
                        continue
                    try:
                        v = _forward_return(open_w, peer, m, h, calendar, period_end)
                    except HorizonPastPeriodEnd:
                        continue
                    if v is not None:
                        pr.append(v)
                if not pr:
                    continue
                ex.append(r - float(np.median(pr)))
            if ex:
                cohorts.append({"month_end": m, "horizon": h,
                                "n_events": len(ex),
                                "mean_excess": float(np.mean(ex))})
        for fl in sorted(set(first["flag"])):
            per_flag.setdefault(fl, 0)
            per_flag[fl] += int((first["flag"] == fl).sum())

    cdf = pd.DataFrame(cohorts)
    out = {"cohorts": int(len(cdf)), "events_by_flag": per_flag, "periods": {},
           "excluded_horizon_past_period_end": {int(k): int(v)
                                                for k, v in excluded.items()},
           "period_end": str(period_end) if period_end else None}
    if not len(cdf):
        out.update({"passes": False, "reason": "no cohorts"})
        return out

    for label, (lo_d, hi_d) in periods.items():
        sub = cdf[(cdf["horizon"] == GATING_HORIZON)
                  & (cdf["month_end"] >= lo_d) & (cdf["month_end"] <= hi_d)]
        vals = list(sub["mean_excess"])
        out["periods"][label] = {
            "cohorts": len(vals),
            "mean_excess_6m": float(np.mean(vals)) if vals else None,
            "t_newey_west": newey_west_t(vals),
            "events": int(sub["n_events"].sum()) if len(sub) else 0,
        }
    out["by_horizon"] = {
        int(h): {"cohorts": int((cdf["horizon"] == h).sum()),
                 "mean_excess": float(cdf.loc[cdf["horizon"] == h, "mean_excess"].mean())}
        for h in HORIZONS if (cdf["horizon"] == h).any()}

    # THE PASS CONDITION, as written in the charter before any of this ran
    a = out["periods"].get("2017-2019", {})
    b = out["periods"].get("2020-2021", {})
    first_ok = (a.get("mean_excess_6m") is not None and a["mean_excess_6m"] < 0
                and a.get("t_newey_west") is not None
                and a["t_newey_west"] < T_THRESHOLD)
    second_ok = (b.get("mean_excess_6m") is not None and b["mean_excess_6m"] < 0)
    out["passes"] = bool(first_ok and second_ok)
    out["condition"] = (f"mean 6-month excess < 0 with t < {T_THRESHOLD} "
                        f"(Newey-West, {NEWEY_WEST_LAGS} lags) in 2017-2019, "
                        f"AND < 0 in 2020-2021")
    out["first_period_passes"], out["second_period_passes"] = first_ok, second_ok
    return out


def _match(elig: set, turnover_w: pd.DataFrame, momentum_w: pd.DataFrame,
           m: date) -> dict:
    """Eligible names bucketed by turnover decile and momentum quintile."""
    names = [i for i in elig if i in turnover_w.columns and i in momentum_w.columns]
    if not names or m not in turnover_w.index:
        return {}
    t = turnover_w.loc[m, names].astype(float)
    q = momentum_w.loc[m, names].astype(float) if m in momentum_w.index else None
    if q is None:
        return {}
    ok = t.notna() & q.notna()
    t, q = t[ok], q[ok]
    if len(t) < TURNOVER_DECILES * MOMENTUM_QUINTILES:
        return {}
    td = pd.qcut(t.rank(method="first"), TURNOVER_DECILES, labels=False)
    qq = pd.qcut(q.rank(method="first"), MOMENTUM_QUINTILES, labels=False)
    out: dict = {}
    for isin in t.index:
        out.setdefault((int(td[isin]), int(qq[isin])), []).append(isin)
    _BUCKET.clear()
    for k, v in out.items():
        for isin in v:
            _BUCKET[isin] = k
    return out


_BUCKET: dict = {}


def _bucket_of(isin: str, matched: dict):
    return _BUCKET.get(isin)
