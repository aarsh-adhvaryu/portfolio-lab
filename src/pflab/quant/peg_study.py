"""PEG and the multibagger claim (docs/research/s64_peg_protocol.md, committed before this code ran).

"A stock bought at a PEG below 1 is a multibagger": the share of PEG-below-1 names that reach 3x total return within five years,
against all other names with a defined PEG, by formation year from 2010 to 2016, with a fixed decision rule.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

from pflab.learner import templates as tp

FORM_START, FORM_END = "2010-01-01", "2016-12-31"
HORIZON = 1260                       # sessions: five years
MULTIPLE = 3.0
MIN_UNIVERSE = 50
YEARS_NEEDED, RATIO_NEEDED = 5, 1.5
BOOT, SEED = 5000, 20261027
YEAR = 252


def peg_frame(w: Dict[str, pd.DataFrame], eps: pd.DataFrame) -> pd.DataFrame:
    """PEG for every session and isin: P/E over the year-on-year TTM EPS growth in percent; NaN where either is undefined, the
    growth is not above zero, or the adjustment factor moved more than 2% between the two EPS dates."""
    pe = (w["close"] / eps).where(eps > 0)
    prev = eps.shift(YEAR)
    growth = (eps / prev - 1.0).where((eps > 0) & (prev > 0))
    fac = w["adj"] / w["close"]
    same_units = ((fac / fac.shift(YEAR)) - 1.0).abs() <= tp.ADJ_TOLERANCE
    g = growth.where(same_units & (growth > 0))
    return (pe / (g * 100.0)).where(g.notna())


def monthly_rates(w: Dict[str, pd.DataFrame], mem: pd.DataFrame, peg: pd.DataFrame) -> pd.DataFrame:
    """Per formation month: names in A (PEG below 1) and B (the rest), and how many of each reached 3x in five years."""
    sessions = w["tr"].index
    every = tp.month_ends(sessions, str(sessions[0].date()), str(sessions[-1].date()))
    tr_f = w["tr"].ffill()
    rows = []
    for i in every:
        t = sessions[i]
        if not pd.Timestamp(FORM_START) <= t <= pd.Timestamp(FORM_END) or i + HORIZON >= len(sessions) or i < tp.HISTORY:
            continue
        live = set(mem[(mem["from_date"] <= t) & (mem["to_date"] > t)]["isin"]) & set(w["tr"].columns)
        cols = sorted(live)
        hist = w["adj"].iloc[i - tp.HISTORY + 1:i + 1][cols].notna().sum()
        cols = [c for c in cols if hist[c] >= 200 and pd.notna(w["tr"].iloc[i][c]) and pd.notna(peg.iloc[i][c])]
        if len(cols) < MIN_UNIVERSE:
            continue
        mult = tr_f.iloc[i + HORIZON][cols] / w["tr"].iloc[i][cols]
        hit = mult >= MULTIPLE
        a = peg.iloc[i][cols] < 1.0
        if int(a.sum()) < 5 or int((~a).sum()) < 5:
            continue
        rows.append({"date": t, "year": t.year, "n_a": int(a.sum()), "n_b": int((~a).sum()),
                     "rate_a": float(hit[a].mean()), "rate_b": float(hit[~a].mean())})
    return pd.DataFrame(rows)


def decide(rates: pd.DataFrame) -> dict:
    """The fixed rule of the protocol on the per-month rates."""
    if rates.empty:
        return {"decision": "fail", "why": "no formation month had a defined PEG for 50 names"}
    by = rates.groupby("year")[["rate_a", "rate_b"]].mean()
    wins = int((by["rate_a"] > by["rate_b"]).sum())
    pooled_a, pooled_b = float(by["rate_a"].mean()), float(by["rate_b"].mean())
    ratio = pooled_a / pooled_b if pooled_b > 0 else float("inf")
    rng = np.random.default_rng(SEED)
    boots = []
    for _ in range(BOOT):
        s = by.iloc[rng.integers(0, len(by), len(by))]
        b = s["rate_b"].mean()
        boots.append(s["rate_a"].mean() / b if b > 0 else np.inf)
    lo = float(np.percentile(boots, 5))
    ok = wins >= YEARS_NEEDED and ratio >= RATIO_NEEDED and lo > 1.0
    out = {"decision": "pass" if ok else "fail", "years": int(len(by)), "years_a_beats_b": wins, "pooled_rate_a": round(pooled_a, 4),
           "pooled_rate_b": round(pooled_b, 4), "ratio": round(ratio, 3), "ratio_p5": round(lo, 3),
           "months": int(len(rates)), "avg_names_a": round(float(rates["n_a"].mean())), "avg_names_b": round(float(rates["n_b"].mean())),
           "by_year": {int(y): {"a": round(float(r.rate_a), 4), "b": round(float(r.rate_b), 4)} for y, r in by.iterrows()}}
    out["why"] = (f"A beat B in {wins} of {len(by)} formation years (needs {YEARS_NEEDED}); pooled ratio {ratio:.2f} (needs "
                  f"{RATIO_NEEDED}); 5th percentile of the ratio over resampled years {lo:.2f} (needs above 1)")
    return out


def run(root: Path, con=None, now: Optional[datetime] = None) -> dict:
    mem = tp.members(root)
    w = tp.wide_panel(root, sorted(set(mem["isin"])), "2008-06-01", "2022-06-30")
    eps = tp.eps_ttm_frame(root, w)
    res = decide(monthly_rates(w, mem, peg_frame(w, eps)))
    if con is not None:
        from pflab.learner import counter
        counter.record(con, now or datetime.now(), "study", "peg_multibagger", {"horizon_sessions": HORIZON, "multiple": MULTIPLE},
                       passed=res["decision"] == "pass", note=res["why"][:300])
    return res


def status(con) -> dict:
    """For the facts: not tested, or the stored verdict of the study."""
    r = con.execute("SELECT passed, note, ran_at FROM learn_tests WHERE template='peg_multibagger' ORDER BY test_id DESC LIMIT 1").fetchone()
    if not r:
        return {"label": "not tested", "why": None}
    return {"label": "passed" if r[0] else "failed", "why": r[1], "ran": str(r[2])[:10],
            "caveat": "seven formation years: consistent with / not supported, weak power"}


if __name__ == "__main__":
    from pflab.data import data_dir
    from pflab.pm import store
    out = run(data_dir(), store.connect(), datetime.now())
    print(json.dumps(out, indent=1))
