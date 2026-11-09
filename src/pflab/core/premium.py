"""The premium-to-NAV rail for India-listed international ETFs (S81 B8 phase A, amendment A53).

Why. An India-listed ETF that holds overseas assets can only create new units while Indian mutual funds are under the overseas-investment limits (USD 7 billion for
the industry, USD 1 billion of it for ETFs). The limits are used up, so the arbitrage that holds the price near the NAV is stopped: in Sep-Oct 2026 the Nasdaq Q50 ETF
traded at 2.4 times its NAV and fell 36% in two sessions while the NAV did not move; most of its peers sat 15% to 60% above NAV (docs/US_LEG_S81.md section 5: sources,
dates, and what is only secondary). A premium paid is lost when it closes. So the core does not BUY such an ETF while it is dear. Selling is never blocked here.

    premium_series(con, isin, start, end)    the premium of the close over the AMFI NAV of the same date, one row per date both exist (point in time: a row dated d uses
                                             only the close and NAV dated d)
    premium_at(con, isin, day)               the latest premium known on or before `day`, with the ages of its inputs; `known` False when the NAV is missing or too old
    attach(con, state)                       puts {isin: premium} for the buyable international rows into `state["premium"]` (no query when there is none)
    premium_rail(state, targets, cfg)        -> (targets, notes): a target ABOVE the current weight is cut back (to the current weight at the limit, scaled down between
                                             `taper_from_pct` and `max_premium_pct`); a target at or below the current weight is untouched. Reasons are written by code.

The numbers are in `configs/core.toml [premium]` (his to change). The defaults (2.0% and 1.0%) are my judgement, not a measured optimum (docs/US_LEG_S81.md): the best-behaved
ETF of the set ran 2-5% over NAV; the official NAV is struck on the underlying's earlier close, so even a healthy ETF shows about +/-1% of timing noise.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "core.toml"
DEFAULTS = {
    "on": True,
    "max_premium_pct": 2.0,          # no new buying at or above this premium to NAV
    "taper_from_pct": 1.0,           # between this and the limit the purchase is scaled down linearly to zero
    "max_nav_age_days": 5,           # a NAV older than this (calendar days before `day`) is unknown
    "unknown": "skip",               # 'skip': no buying while the premium is unknown; 'allow': buy as the policy says
    "classes": ["international"],    # the policy classes the rail looks at; add "gold" to hold gold ETFs to the same limit (gold ETFs ran 5-12% over NAV in Oct 2025 and Jan 2026: secondary)
}
INTERNATIONAL = "international"


def settings(cfg: Optional[dict] = None) -> dict:
    """The [premium] table with its defaults. `cfg` may be the whole core settings (a 'premium' key) or the table itself."""
    out = dict(DEFAULTS)
    if cfg is None or ("core" in cfg and "premium" not in cfg):          # the whole core settings (which do not carry this table): read the file
        try:
            from pflab import _toml
            cfg = _toml.load(CONFIG).get("premium", {})
        except Exception:
            cfg = {}
    elif "premium" in cfg and isinstance(cfg["premium"], dict):
        cfg = cfg["premium"]
    out.update({k: v for k, v in (cfg or {}).items() if k in DEFAULTS})
    return out


# --- the series ----------------------------------------------------------------------------------------------------------------

def _latest_per_date(con, table: str, col: str, isin: str, lo: date, hi: date) -> pd.DataFrame:
    rows = con.execute(f"SELECT date, {col} FROM {table} WHERE isin=? AND date>=? AND date<=? AND {col} > 0 "
                       f"QUALIFY row_number() OVER (PARTITION BY date ORDER BY fetched_at DESC) = 1 ORDER BY date", [isin, lo, hi]).fetchall()
    return pd.DataFrame(rows, columns=["date", col])


def premium_series(con, isin: str, start: date, end: date) -> pd.DataFrame:
    """Columns: date, close, nav, premium_pct (= (close / nav - 1) * 100). Only dates that have both an exchange close and an AMFI NAV; sorted by date."""
    px = _latest_per_date(con, "prices", "close", isin, start, end)
    nv = _latest_per_date(con, "navs", "nav", isin, start, end)
    if px.empty or nv.empty:
        return pd.DataFrame(columns=["date", "close", "nav", "premium_pct"])
    df = px.merge(nv, on="date", how="inner").sort_values("date").reset_index(drop=True)
    df["premium_pct"] = (df["close"] / df["nav"] - 1.0) * 100.0
    return df


def premium_at(con, isin: str, day: date, max_age_days: int = 5) -> dict:
    """The latest premium on or before `day`. `known` is False when no date has both inputs within `max_age_days` of `day`."""
    s = premium_series(con, isin, day - timedelta(days=max(30, 4 * int(max_age_days))), day)
    if s.empty:
        return {"known": False, "premium_pct": None, "as_of": None, "age_days": None, "why": "no NAV and close of the same date on record"}
    r = s.iloc[-1]
    d = r["date"]
    d = d.date() if hasattr(d, "date") else d
    age = (day - d).days
    if age > int(max_age_days):
        return {"known": False, "premium_pct": float(r["premium_pct"]), "as_of": d, "age_days": age, "why": f"the latest NAV with a close is {age} days old (limit {max_age_days})"}
    return {"known": True, "premium_pct": float(r["premium_pct"]), "as_of": d, "age_days": age, "close": float(r["close"]), "nav": float(r["nav"]), "why": ""}


def is_candidate(row: dict, classes=(INTERNATIONAL,)) -> bool:
    """A holding the rail looks at: a buyable ETF in one of the rail's classes (international by default)."""
    return bool(row.get("buyable")) and (row.get("klass") or "") in tuple(classes) and (row.get("asset_class") or "") == "etf"


def attach(con, state: dict, cfg: Optional[dict] = None) -> dict:
    """Fill `state['premium']` for the international ETF rows (a no-op, with no query, when the rail is off or the book has none)."""
    s = settings(cfg if cfg is not None else state.get("cfg"))
    state.setdefault("premium", {})
    if not s["on"]:
        return state
    for r in state.get("rows", []):
        if is_candidate(r, s["classes"]) and r["isin"] not in state["premium"]:
            state["premium"][r["isin"]] = premium_at(con, r["isin"], state["day"], int(s["max_nav_age_days"]))
    return state


# --- the rail -------------------------------------------------------------------------------------------------------------------

def scale(premium_pct: float, taper_from: float, limit: float) -> float:
    """The share of an intended purchase that may go ahead at this premium: 1 up to `taper_from`, 0 at `limit` and above, linear between."""
    if premium_pct <= taper_from:
        return 1.0
    if premium_pct >= limit or limit <= taper_from:
        return 0.0
    return (limit - premium_pct) / (limit - taper_from)


def rail_reasons(state: dict, targets: Dict[str, float], cfg: Optional[dict] = None) -> Tuple[Dict[str, float], Dict[str, str]]:
    """-> (targets, {isin: reason}) for the targets the rail changed. `targets` and `state` are not modified."""
    s = settings(cfg if cfg is not None else state.get("cfg"))
    out = dict(targets)
    why: Dict[str, str] = {}
    if not s["on"]:
        return out, why
    total = float(state.get("value") or 0.0)
    if total <= 0:
        return out, why
    prem = state.get("premium") or {}
    limit, taper = float(s["max_premium_pct"]), float(s["taper_from_pct"])
    for r in state.get("rows", []):
        k = r["isin"]
        if k not in targets or not is_candidate(r, s["classes"]):
            continue
        cur = float(r["value"]) / total
        want = float(targets[k])
        if want <= cur + 1e-12:                                          # a sale or a hold is never blocked
            continue
        p = prem.get(k)
        sym = r.get("symbol") or k
        if p is None or not p.get("known"):
            if s["unknown"] == "allow":
                continue
            out[k] = cur
            detail = (p or {}).get("why") or "the premium was not looked up"
            why[k] = f"premium rail: {sym} not bought, its premium to NAV is unknown ({detail})"
            continue
        pct = float(p["premium_pct"])
        f = scale(pct, taper, limit)
        if f >= 1.0:
            continue
        out[k] = cur + (want - cur) * f
        if f <= 0.0:
            why[k] = f"premium rail: {sym} not bought, it trades {pct:.1f}% above its NAV (limit {limit:.1f}%, as of {p['as_of']})"
        else:
            why[k] = f"premium rail: {sym} purchase cut to {f:.0%}, it trades {pct:.1f}% above its NAV (scaled down from {taper:.1f}% to nothing at {limit:.1f}%, as of {p['as_of']})"
    return out, why


def premium_rail(state: dict, targets: Dict[str, float], cfg: Optional[dict] = None) -> Tuple[Dict[str, float], List[str]]:
    """The rail as the loop calls it: (targets, notes), notes being the reasons in plain words (empty when nothing was cut)."""
    new, why = rail_reasons(state, targets, cfg)
    return new, [why[k] for k in sorted(why)]
