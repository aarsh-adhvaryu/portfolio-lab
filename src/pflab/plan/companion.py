"""The nightly pass of the limits (S64 Phase 5 item 4): proposals made once, answers applied, limits held to.

    1. his answers to earlier proposals are applied or declined (risk/themes.resolve)
    2. the theme baskets are proposed, then each theme's limit, the dip reserve and the pot's limit (all Needs from you)
    3. theme and pot limits he applied are checked against today: a breach is a guard message (urgent)
    4. new listings with 20 sessions of prices are noted for the brain; open pot ideas past their horizon are scored
Nothing here changes a target or moves money.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pflab.service import telegram as tgm


def positions(con, asof: date) -> dict:
    """investable, equity-type value, the equity target share and soft band, from the same sources as the plan."""
    from pflab.pm import today
    from pflab.plan import targets as tg
    n = today.build(con, asof)
    b = n["buckets"]
    t = tg.load()
    eq = b.get("equity", 0.0) + b.get("equity_fund", 0.0)
    target = sum(t.buckets[k].target for k in ("equity", "equity_fund") if k in t.buckets)
    soft = t.buckets["equity"].soft_band if "equity" in t.buckets else 0.05
    return {"investable": float(n["investable"]), "equity": float(eq), "target": target, "soft": soft}


def run(con, root, asof: date, now: datetime, index=None) -> dict:
    from pflab.plan import pot, reserve
    from pflab.risk import themes
    out: dict = {"resolved": themes.resolve(con, now)}
    p = positions(con, asof)
    out["baskets_proposed"] = themes.seed_baskets(con, root, asof, now)
    out["limits_proposed"] = themes.propose_limits(con, root, asof, now, cap=p["target"])
    beta = 1.0
    try:
        from pflab.risk import capm
        b = capm.portfolio(con, root, asof).get("beta")
        beta = float(b) if b is not None else 1.0
    except Exception:
        pass
    out["reserve_proposed"] = reserve.propose(con, asof, now, p["investable"], p["equity"], p["target"], p["soft"], beta) is not None
    out["pot_proposed"] = pot.propose_limit(con, now, p["equity"], p["target"] * p["investable"] - p["equity"]) is not None
    try:                                    # the US sleeve study goes to Needs from you once, when the US history is on this PC
        from pflab.risk import sleeve
        if (root / "us" / "raw" / "SPY.parquet").exists():
            out["us_sleeve_proposed"] = sleeve.propose(con, root, asof, now, p["investable"]) is not None
    except Exception as e:
        out["us_sleeve_error"] = f"{type(e).__name__}: {str(e)[:100]}"
    alerts = 0
    try:
        ex = themes.exposure_of(con, root, asof)
        for text in themes.breaches(con, ex):
            alerts += tgm.enqueue(con, text, "guard", dedup_key=f"theme_over:{text[:40]}:{asof:%Y-%W}", now=now) is not None
    except Exception as e:
        out["themes_error"] = f"{type(e).__name__}: {str(e)[:100]}"
    lim = pot.limit(con)
    if lim is not None and pot.used(con) > lim:
        alerts += tgm.enqueue(con, f"Opportunity pot over its limit: Rs {pot.used(con):,.0f} against Rs {lim:,.0f}.", "guard",
                              dedup_key=f"pot_over:{asof:%Y-%W}", now=now) is not None
    out["alerts"] = alerts
    out["pot_scored"] = pot.score_due(con, now, root, index)
    try:
        out["ipo_candidates"] = len(pot.ipo_candidates(con, root, asof))
    except Exception:
        out["ipo_candidates"] = None
    return out
