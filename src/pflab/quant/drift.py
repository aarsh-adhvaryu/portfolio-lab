"""Drift checks (S46, PLAN A7): every adopted rule re-tested on the data that came after it was fixed.

    market_state   the frozen Hawkes fit (2005-2019) on the falls since 2020: time-rescaling KS p-value, and the share
                   of follow-on falls the elevated state warned of (registered: 90% on 2005-2014). DRIFT if the KS
                   p-value < 0.01 or recall < 0.80 with at least 10 follow-on falls.
    dip_rule       how often the market-wide 10% dip trigger fired since 2022 and what followed (60 sessions): reported,
                   no flag (too few triggers for a test).
A drift flag is a question for the investor, never an automatic change of a rule.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pflab import _toml
from pflab.quant import hawkes as hk

KS_MIN, RECALL_MIN, MIN_EVENTS = 0.01, 0.80, 10
CONFIG = Path(__file__).resolve().parents[3] / "configs" / "hawkes_market.toml"


def market_returns(root=None) -> pd.Series:
    from pflab.data import indices
    df = indices.load("NIFTY500_TRI", root)
    s = df.assign(date=pd.to_datetime(df["date"])).set_index("date")["close"].sort_index()
    return s.pct_change().dropna()


def chances(r: pd.Series, p: hk.Uni, threshold: float, h: int) -> pd.Series:
    """The chance at each close, as live (events mid-session); same recursion as the S40 study."""
    fall = (r <= threshold).to_numpy()
    exc, out = 0.0, np.empty(len(r))
    for t in range(len(r)):
        exc *= np.exp(-p.beta)
        if fall[t]:
            exc += np.exp(-p.beta * 0.5)
        out[t] = 1 - np.exp(-(p.mu * h + p.alpha * exc * (1 - np.exp(-p.beta * h))))
    return pd.Series(out, index=r.index)


def market_state(r: pd.Series, c: Optional[dict] = None, since: str = "2020-01-01") -> dict:
    c = c or _toml.load(CONFIG)["market"]
    p = hk.Uni(c["mu"], c["alpha"], c["beta"])
    th, h = c["threshold"], int(c["horizon"])
    ev = np.flatnonzero((r <= th).to_numpy()) + 0.5
    a = float(np.searchsorted(r.index, pd.Timestamp(since)))
    ks = hk.ks_window(p, ev, a, float(len(r)))
    ch = chances(r, p, th, h)
    f = (r <= th).astype(int)
    follow = (f == 1) & (f.shift(1).rolling(h, min_periods=1).sum().fillna(0) > 0)
    win = r.index >= pd.Timestamp(since)
    fo = follow[win]
    warned = (ch.shift(1) >= c["t1"])[win]
    n = int(fo.sum())
    rec = float(warned[fo].mean()) if n else float("nan")
    drift = ks < KS_MIN or (n >= MIN_EVENTS and rec < RECALL_MIN)
    return {"rule": "market_state", "since": since, "falls": int((r[win] <= th).sum()), "follow_on": n,
            "recall": rec, "ks_p": float(ks), "drift": bool(drift),
            "detail": f"KS p {ks:.3f} (min {KS_MIN}); recall of follow-on falls {rec:.0%} on {n} (registered 90%, min "
                      f"{RECALL_MIN:.0%})"}


def dip_rule(r: pd.Series, since: str = "2022-01-01", depth: float = -0.10, ahead: int = 60) -> dict:
    lvl = (1 + r).cumprod()
    dd = lvl / lvl.rolling(250, min_periods=1).max() - 1
    trig = (dd <= depth) & (dd.shift(1) > depth)
    fwd = lvl.shift(-ahead) / lvl - 1
    win = r.index >= pd.Timestamp(since)
    t = trig[win]
    after, base = fwd[win][t].dropna(), fwd[win].dropna()
    return {"rule": "dip_rule", "since": since, "triggers": int(t.sum()), "drift": False,
            "detail": (f"{int(t.sum())} trigger(s); {ahead}-session return after them {after.mean():+.1%} vs all days "
                       f"{base.mean():+.1%} (report only)") if len(after) else f"{int(t.sum())} trigger(s) since {since}"}


def run_all(root=None) -> List[dict]:
    r = market_returns(root)
    return [market_state(r), dip_rule(r)]


def render(rows: List[dict]) -> str:
    return "\n".join(f"{'DRIFT' if x['drift'] else 'ok   '} {x['rule']:<13} {x['detail']}" for x in rows)
