"""Reviewed measures (S58b; the investor 2026-10-24: the system exists to do hard, real maths, reused or new, and get it right).

Standard measures of a daily close series, written and reviewed here, each tested against hand-worked answers and a
second implementation (tests/test_s58b_measures.py). The workshop answers a question with one of these before any
model writes code: the local model only picks the measure and reads its values (series, dates, levels) from the
question, and the answer says exactly what was computed, so a misread shows.

Conventions: `s` is a DataFrame with `date` and `close`, any order; the window is [start, end], both inclusive; returns
are simple (close / previous close - 1); a year has 252 sessions; every result carries its window and its n.
A 2026-10-22 workshop calculation for "the largest fall from a peak" computed the largest one-day fall and passed the
model's own test: that is why a measure states its definition in its result.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from pflab.calc import smalln

SESSIONS = 252


def window(s: pd.DataFrame, start: Optional[date] = None, end: Optional[date] = None) -> pd.Series:
    """Closes in [start, end] indexed by date, sorted, without gaps or non-positive values."""
    d = s[["date", "close"]].dropna().copy()
    d["date"] = pd.to_datetime(d["date"]).dt.date
    d = d[d["close"] > 0].sort_values("date").drop_duplicates("date", keep="last")
    if start is not None:
        d = d[d["date"] >= start]
    if end is not None:
        d = d[d["date"] <= end]
    if len(d) < 2:
        raise ValueError(f"fewer than 2 closes between {start} and {end}")
    return pd.Series(d["close"].to_numpy(float), index=list(d["date"]))


def _span(c: pd.Series) -> dict:
    return {"from": str(c.index[0]), "to": str(c.index[-1]), "closes": int(len(c))}


def drawdown(s, start=None, end=None) -> dict:
    """The largest fall from a peak to a later trough inside the window (peaks counted from the window's start), in
    percent and points, with the peak, the trough and the first close back at the peak (None if not yet)."""
    c = window(s, start, end)
    v = c.to_numpy()
    peak = np.maximum.accumulate(v)
    dd = v / peak - 1
    t = int(np.argmin(dd))
    p = int(np.argmax(v[: t + 1]))
    rec = next((c.index[i] for i in range(t + 1, len(v)) if v[i] >= v[p]), None)
    return {"definition": "largest fall from a running peak to a later close", **_span(c),
            "fall_pct": float(-dd[t] * 100), "fall_points": float(v[p] - v[t]),
            "peak_date": str(c.index[p]), "peak": float(v[p]), "trough_date": str(c.index[t]), "trough": float(v[t]),
            "recovered_on": str(rec) if rec else None,
            "sessions_peak_to_trough": t - p}


def period_return(s, start=None, end=None) -> dict:
    """First close to last close in the window, and its yearly rate (CAGR) when the window is at least a year."""
    c = window(s, start, end)
    r = c.iloc[-1] / c.iloc[0] - 1
    years = (c.index[-1] - c.index[0]).days / 365.25
    out = {"definition": "last close / first close - 1", **_span(c), "return_pct": float(r * 100),
           "years": round(years, 3)}
    out["cagr_pct"] = float(((1 + r) ** (1 / years) - 1) * 100) if years >= 1 else None
    return out


def daily_returns(c: pd.Series) -> pd.Series:
    return (c / c.shift(1) - 1).iloc[1:]


def volatility(s, start=None, end=None) -> dict:
    """Standard deviation of daily returns (sample, n-1), and annualised by the square root of 252."""
    c = window(s, start, end)
    r = daily_returns(c)
    sd = float(r.std(ddof=1))
    return {"definition": "sample std of daily returns; annualised x sqrt(252)", **_span(c), "returns": int(len(r)),
            "daily_pct": sd * 100, "annual_pct": sd * math.sqrt(SESSIONS) * 100,
            "annual_label": smalln.annualised(sd * math.sqrt(SESSIONS), len(r))["text"]}


def extreme_days(s, start=None, end=None) -> dict:
    """The largest one-day fall and rise (close to close)."""
    c = window(s, start, end)
    r = daily_returns(c)
    lo, hi = r.idxmin(), r.idxmax()
    return {"definition": "one-day close-to-close change", **_span(c), "worst_day": str(lo), "worst_pct": float(r[lo] * 100),
            "best_day": str(hi), "best_pct": float(r[hi] * 100), "up_days_pct": float((r > 0).mean() * 100)}


def worst_run(s, start=None, end=None, sessions: int = 5) -> dict:
    """The worst change over `sessions` consecutive sessions (close to the close `sessions` later)."""
    c = window(s, start, end)
    n = int(sessions)
    if n < 1 or len(c) <= n:
        raise ValueError(f"need more than {n} closes")
    r = (c.shift(-n) / c - 1).dropna()
    i = r.idxmin()
    j = c.index[c.index.get_loc(i) + n]
    return {"definition": f"close to the close {n} sessions later", **_span(c), "sessions": n,
            "worst_pct": float(r[i] * 100), "from_date": str(i), "to_date": str(j)}


def var_cvar(s, start=None, end=None, level: float = 0.95) -> dict:
    """Historical one-day value at risk (the (1-level) quantile of daily returns, as a loss) and the average loss
    beyond it (CVaR); the count of days in the tail is given (small-numbers rule)."""
    c = window(s, start, end)
    if not 0.5 < level < 1:
        raise ValueError("level between 0.5 and 1")
    r = daily_returns(c).to_numpy()
    q = float(np.quantile(r, 1 - level, method="lower"))
    tail = r[r <= q]
    return {"definition": f"one-day historical VaR and CVaR at {level:.0%}", **_span(c), "returns": int(len(r)),
            "var_pct": -q * 100, "cvar_pct": float(-tail.mean() * 100), "tail_days": int(len(tail)),
            "tail_label": smalln.average(float(-tail.mean() * 100), len(tail), "{:.2f}%")["text"]}


def chance_of_fall(s, start=None, end=None, fall_pct: float = 10.0, sessions: int = 20) -> dict:
    """How often, from a close in the window, the series fell at least `fall_pct` below that close at some close within
    the next `sessions` sessions. Start days overlap, so the error uses n / sessions independent starts."""
    c = window(s, start, end)
    v, n_s, f = c.to_numpy(), int(sessions), float(fall_pct) / 100
    if len(v) <= n_s:
        raise ValueError(f"need more than {n_s} closes")
    starts = len(v) - n_s
    lows = np.array([v[i + 1:i + 1 + n_s].min() for i in range(starts)])
    hit = lows <= v[:starts] * (1 - f)
    p = float(hit.mean())
    n_ind = max(1, starts // n_s)
    return {"definition": f"share of start closes followed by a fall of {fall_pct:g}% within {n_s} sessions",
            **_span(c), "chance_pct": p * 100, "starts": starts, "independent_starts": n_ind,
            "se_pp": math.sqrt(p * (1 - p) / n_ind) * 100, "label": smalln.rate(int(round(p * n_ind)), n_ind)["text"]}


def relation(s, b, start=None, end=None) -> dict:
    """Correlation of daily returns with a second series (on common dates) and the beta to it."""
    x, y = window(s, start, end), window(b, start, end)
    j = pd.concat([daily_returns(x), daily_returns(y)], axis=1, join="inner").dropna()
    if len(j) < 3:
        raise ValueError("fewer than 3 common daily returns")
    a, m = j.iloc[:, 0].to_numpy(), j.iloc[:, 1].to_numpy()
    beta = float(np.cov(a, m, ddof=1)[0, 1] / np.var(m, ddof=1))
    return {"definition": "Pearson correlation of daily returns; beta = cov / var of the second", "from": str(j.index[0]),
            "to": str(j.index[-1]), "returns": int(len(j)), "correlation": float(np.corrcoef(a, m)[0, 1]), "beta": beta}


@dataclass(frozen=True)
class Measure:
    fn: Callable
    about: str
    params: Dict[str, dict] = field(default_factory=dict)      # name -> {"type": "date|number", "about": ...}
    second: bool = False                                       # takes a second series


DATES = {"start": {"type": "date", "about": "first day of the window (optional)"},
         "end": {"type": "date", "about": "last day of the window (optional)"}}
MEASURES: Dict[str, Measure] = {
    "drawdown": Measure(drawdown, "largest fall from a peak (drawdown, crash depth, peak to trough), its dates and recovery",
                        DATES),
    "period_return": Measure(period_return, "return over a period, gain or loss from one date to another, CAGR", DATES),
    "volatility": Measure(volatility, "volatility, standard deviation of daily returns, how much it swings", DATES),
    "extreme_days": Measure(extreme_days, "the worst or best single day, largest one-day fall or rise, share of up days",
                            DATES),
    "worst_run": Measure(worst_run, "worst change over N consecutive sessions (a week = 5, a month = 21)",
                         {**DATES, "sessions": {"type": "number", "about": "sessions in the run"}}),
    "var_cvar": Measure(var_cvar, "value at risk, expected shortfall, CVaR, the one-day loss at a confidence level",
                        {**DATES, "level": {"type": "number", "about": "confidence level between 0.5 and 1, e.g. 0.95"}}),
    "chance_of_fall": Measure(chance_of_fall, "how often / the chance of a fall of X% within N sessions, from history",
                              {**DATES, "fall_pct": {"type": "number", "about": "the fall in percent, e.g. 10"},
                               "sessions": {"type": "number", "about": "sessions ahead, e.g. 20 for a month"}}),
    "relation": Measure(relation, "correlation or beta of one series against another", DATES, second=True),
}


def run(name: str, series: pd.DataFrame, values: dict, second: Optional[pd.DataFrame] = None) -> dict:
    m = MEASURES[name]
    kw = {}
    for k, v in (values or {}).items():
        if k not in m.params or v in (None, ""):
            continue
        kw[k] = pd.Timestamp(str(v)).date() if m.params[k]["type"] == "date" else float(v)
    return m.fn(series, second, **kw) if m.second else m.fn(series, **kw)


def catalogue_text() -> str:
    return "\n".join(f"- {k}: {m.about}; parameters: " + (", ".join(f"{p} ({d['type']}: {d['about']})"
                                                                     for p, d in m.params.items()) or "none")
                     + ("; needs a second series" if m.second else "") for k, m in MEASURES.items())


def describe(name: str, series: str, values: dict, second: Optional[str] = None) -> str:
    """What was computed, in words: shown with the answer so a misread question shows."""
    v = {k: x for k, x in (values or {}).items() if x not in (None, "")}
    return (f"{name} of {series}" + (f" against {second}" if second else "") +
            (" (" + ", ".join(f"{k} {x}" for k, x in v.items()) + ")" if v else " (whole history)"))
