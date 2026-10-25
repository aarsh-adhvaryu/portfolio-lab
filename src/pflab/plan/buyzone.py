"""Buy zones, version 1 (S54c, the investor 2026-10-22: "it can't predict, but say a good deal is at 1,000 rather than 1,400").

A DESCRIPTION, labelled an estimate, not a tested signal (whether buying in the zone beats buying at once is a
separate pre-registered study, PLAN A9). Three parts, each shown with its working:

    range        where the price has been: the 1-year low and high, the 20th and 40th percentiles of daily closes
    valuation    what the price assumes: the earnings growth a year for 10 years implied by today's price
                 (`fundamentals.pit.implied_growth`, 12% discount, 5% terminal), against the company's own TTM
                 earnings growth; where the price assumes more, the "fair" price is the one at which they match
    touch        the chance of touching a level within HORIZON sessions: a block bootstrap of the stock's own last
                 3 years of daily log returns, the mean removed (no forecast of direction), PATHS paths, with its
                 standard error

    zone         the 20th to the 40th percentile of the last year's closes (where the price itself has been; checked on
                 real data 2026-10-22: a zone set by the fair price fell far outside a year's prices, a level with no
                 realistic chance of being touched, so valuation is a separate check, not the zone)
    rich         the price assumes more than RICH_GAP a year above the company's own (clipped) TTM growth
    verdict      NO (a guard fails or blocks); ABOVE ZONE (a description: the pre-registered study of 2026-10-23,
                 docs/research/buyzone_wait_results.md, found that waiting for the zone cost money, so the zone never
                 says "wait"); RICH (in it, but the price assumes more growth than the company's own: a caution, not
                 tested); IN ZONE (at or
                 under the zone's top and not rich); too little history (fewer than 250 sessions) -> no zone, said so
"""
from __future__ import annotations

import math
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from pflab.calc import smalln

PATHS, HORIZON, BLOCK, SEED = 100_000, 126, 10, 20261022
RICH_GAP = 0.10
RICH_UNKNOWN = 0.25                # with no growth on record, a price assuming more than this is rich too
YEAR, HISTORY = 250, 750


def touch_chance(log_returns: np.ndarray, levels, price: float, paths: int = PATHS, horizon: int = HORIZON,
                 block: int = BLOCK, seed: int = SEED) -> dict:
    """Chance that the running minimum of a bootstrapped path reaches each level (fractions), with standard errors."""
    r = np.asarray(log_returns, float)
    r = r[np.isfinite(r)]
    r = r - r.mean()                                   # no drift: not a forecast of direction
    n = len(r)
    rng = np.random.default_rng(seed)
    nb = math.ceil(horizon / block)
    targets = np.log(np.asarray(levels, float) / price)
    hits = np.zeros(len(targets))
    done = 0
    while done < paths:                                # chunks keep memory small at 100,000 paths
        k = min(20_000, paths - done)
        starts = rng.integers(0, n - block, size=(k, nb))
        idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(k, -1)[:, :horizon]
        low = np.minimum.accumulate(np.cumsum(r[idx], axis=1), axis=1)[:, -1]
        hits += (low[:, None] <= targets[None, :]).sum(axis=0)
        done += k
    p = hits / paths
    return {"p": p.tolist(), "se": np.sqrt(p * (1 - p) / paths).tolist(), "paths": paths, "horizon": horizon}


def fair_price(eps_ttm: Optional[float], growth: Optional[float], discount_rate: float = 0.12, years: int = 10,
               terminal_growth: float = 0.05) -> Optional[float]:
    """The price at which the implied growth equals `growth` (the same model as pit.implied_growth)."""
    from pflab.fundamentals import pit
    if not eps_ttm or eps_ttm <= 0 or growth is None or not math.isfinite(growth):
        return None
    return float(pit._pv_from_growth(eps_ttm, growth, discount_rate, years, terminal_growth))


def zone(closes: pd.Series, asof: date, eps_ttm: Optional[float] = None, growth: Optional[float] = None,
         guard: str = "ok", paths: int = PATHS) -> dict:
    """The zone for one name from its daily closes (oldest first, last = today's price)."""
    from pflab.fundamentals import pit
    c = closes.dropna()
    out: dict = {"asof": str(asof), "sessions": int(len(c)), "guard": guard}
    if len(c) < YEAR:
        out.update(verdict="NO" if guard in ("fail", "block") else "NO DATA",
                   headline=f"too little price history ({len(c)} sessions, {YEAR} needed)")
        return out
    price = float(c.iloc[-1])
    y = c.iloc[-YEAR:]
    p20, p40 = float(y.quantile(0.20)), float(y.quantile(0.40))
    out.update(price=price, low=float(y.min()), high=float(y.max()), p20=p20, p40=p40,
               share_below_p40=float((y <= p40).mean()))
    implied = None
    if eps_ttm and eps_ttm > 0:
        try:
            implied = float(pit.implied_growth(price, eps_ttm, asof).value) / 100.0    # the Estimate is in percent
        except Exception:
            implied = None
    fair = fair_price(eps_ttm, growth)
    rich = implied is not None and ((growth is not None and implied > growth + RICH_GAP)
                                    or (growth is None and implied > RICH_UNKNOWN))
    out.update(eps_ttm=eps_ttm, growth=growth, implied_growth=implied, fair=fair, rich=rich)
    top, bottom = p40, p20
    out.update(top=top, bottom=bottom)
    lr = np.diff(np.log(c.iloc[-HISTORY:].to_numpy(float)))
    t = touch_chance(lr, [top, bottom], price, paths=paths)
    out["touch_top"] = {"p": t["p"][0], **smalln.tail(t["p"][0], paths)}
    out["touch_bottom"] = {"p": t["p"][1], **smalln.tail(t["p"][1], paths)}
    out["horizon"] = t["horizon"]
    if guard in ("fail", "block"):
        verdict, head = "NO", f"no new buying: guard {guard}"
    elif price > top:
        verdict, head = "ABOVE ZONE", f"above its zone {bottom:,.0f}-{top:,.0f}; waiting for the zone cost money on average (study 2026-10-23)"
    elif rich:
        verdict, head = "RICH", (f"in its price zone, but the price assumes {implied:.0%} growth a year against "
                                 + (f"its own {growth:.0%}" if growth is not None else "no growth record (too few quarters)"))
    else:
        verdict, head = "IN ZONE", (f"in the zone {bottom:,.0f}-{top:,.0f}" if price >= bottom else    # S60: the brain
                                    f"below its zone {bottom:,.0f}-{top:,.0f} (under the year's 20th percentile of "
                                    "closes)")                                                     # read "in" wrongly
    out.update(verdict=verdict, headline=head)
    return out
