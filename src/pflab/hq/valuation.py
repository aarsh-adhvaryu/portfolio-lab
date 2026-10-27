"""What a trader looks at first, as facts for the brain (S64; the investor: the system must think like a trader, not only
block).

P/E now, where it sits in the stock's own 5-year range, against the market's P/E, what growth the price assumes against what
the company has delivered, how volatile it has been lately against its own norm, and the usual rules of thumb ("P/E above 50")
as flags. Every number is code: a filed number over a price, as of each date (quarters only when filed). The rules of thumb
are NOT tested here: they are labelled so, saved with each suggestion that reads them, and the suggestion ledger scores the
suggestions, so the record decides over time which rule of thumb earns its place (CLAUDE.md 12). The brain weighs them as a
trader would and says which matter for this company and why; none of them is a trading rule of the system.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

YEARS = 5
MIN_MONTHS = 12
PE_HIGH = 50.0                    # the investor's rule of thumb: above this, avoid buying
OWN_MEDIAN_MULT = 1.5
MARKET_MULT = 2.0
VOL_MULT = 1.5
FALL_FROM_HIGH = -0.25
NOT_TESTED = "rule of thumb, not tested by this system; scored through the suggestions that cite it"


def pe_history(q: pd.DataFrame, scrip: str, closes: pd.Series, asof: date, years: int = YEARS) -> pd.Series:
    """Month-end P/E for the last `years`: that day's close over the TTM EPS of the quarters filed by then. A month with
    no positive TTM EPS has no P/E."""
    from pflab.fundamentals import pit
    c = closes.dropna()
    ends = pd.date_range(end=pd.Timestamp(asof), periods=years * 12, freq="ME")
    out = {}
    for e in ends:
        d = e.date()
        px = c[c.index <= e]
        if px.empty or (e - px.index[-1]).days > 7:
            continue
        eps = pit.ratios(pit.last_quarters(q, scrip, d)).get("eps_ttm")
        if eps and eps > 0:
            out[e] = float(px.iloc[-1]) / eps
    return pd.Series(out, dtype=float)


def with_older_quarters(q: pd.DataFrame, scrip: str, root) -> pd.DataFrame:
    """The store's quarters plus the older ones pulled earlier into data/bse_results, each usable 60 days after its quarter
    ended (past the 45-day filing deadline, so never earlier than the filing). The store's rows win on a shared quarter."""
    from pflab.fundamentals import pit
    try:
        h = pit.load_history(scrip, Path(root))
    except Exception:
        return q
    if h.empty:
        return q
    h = h.assign(scrip_code=str(scrip))
    h["quarter_end"] = pd.to_datetime(h["quarter_end"]).dt.date
    h["usable_from"] = h["quarter_end"].map(lambda d: d + timedelta(days=60))
    h = h[~h["quarter_end"].isin(set(q["quarter_end"]))]
    return pd.concat([h, q], ignore_index=True) if len(h) else q


def vol_ratio(closes: pd.Series) -> Dict[str, Optional[float]]:
    """Annualised volatility of the last 3 months and of the last 3 years, and their ratio."""
    r = np.log(closes.dropna()).diff().dropna()
    if len(r) < 120:
        return {"vol_3m_pct": None, "vol_3y_pct": None, "ratio": None}
    v3m, v3y = float(r.iloc[-63:].std() * np.sqrt(252)), float(r.iloc[-750:].std() * np.sqrt(252))
    return {"vol_3m_pct": round(v3m * 100, 1), "vol_3y_pct": round(v3y * 100, 1), "ratio": round(v3m / v3y, 2) if v3y else None}


def market_pe(root: Path, asof: date) -> Optional[dict]:
    try:
        d = pd.read_parquet(Path(root) / "indices" / "NIFTY500_VALUATION.parquet")
        s = pd.Series(d["pe"].to_numpy(float), index=pd.to_datetime(d["date"])).sort_index()
        s = s[s.index <= pd.Timestamp(asof)]
        w = s[s.index >= s.index[-1] - pd.Timedelta(days=365 * YEARS)]
        return {"pe": round(float(s.iloc[-1]), 1), "on": str(s.index[-1].date()), "median_5y": round(float(w.median()), 1),
                "percentile_5y": round(float((w <= s.iloc[-1]).mean() * 100))}
    except Exception:
        return None


def flags(pe: Optional[float], own_median: Optional[float], mkt: Optional[dict], rich: Optional[bool], vol: dict,
          from_high: Optional[float], tested: Optional[dict] = None) -> List[dict]:
    """The rules of thumb, each with whether it applies today. `applies` is None where the fact is missing."""
    def f(rule, applies, note, status=NOT_TESTED):
        return {"rule": rule, "applies": applies, "note": note, "status": status}
    t50 = (tested or {}).get("pe_above_50")
    s50 = NOT_TESTED if not t50 or t50["label"] == "not tested" else (
        f"TESTED by the learner (claim #{t50['claim_id']}): {t50['label']}" + (f". {t50['why']}" if t50.get("why") else ""))
    return [
        f(f"P/E above {PE_HIGH:g}", None if pe is None else pe > PE_HIGH,
          "no P/E (loss-making or no filed EPS)" if pe is None else f"P/E is {pe:.1f}", s50),
        f(f"P/E more than {OWN_MEDIAN_MULT:g}x its own 5-year median", None if not (pe and own_median) else pe > OWN_MEDIAN_MULT * own_median,
          "" if not (pe and own_median) else f"{pe / own_median:.2f}x its median {own_median:.1f}"),
        f(f"P/E more than {MARKET_MULT:g}x the Nifty 500's", None if not (pe and mkt) else pe > MARKET_MULT * mkt["pe"],
          "" if not (pe and mkt) else f"{pe / mkt['pe']:.2f}x the market's {mkt['pe']}"),
        f("the price assumes more growth a year than the company has delivered (by 10+ points)", rich,
          "reverse DCF at 12% discount, 10 years, 5% after"),
        f(f"volatility {VOL_MULT:g}x its 3-year norm", None if vol.get("ratio") is None else vol["ratio"] > VOL_MULT,
          "" if vol.get("ratio") is None else f"3-month {vol['vol_3m_pct']}% against {vol['vol_3y_pct']}%"),
        f(f"more than {abs(FALL_FROM_HIGH):.0%} below its 52-week high", None if from_high is None else from_high < FALL_FROM_HIGH,
          "" if from_high is None else f"{from_high:.0%} from the high"),
    ]


def facts(con, root, isin: str, symbol: str, closes: pd.Series, asof: date) -> dict:
    from pflab.fundamentals import pit
    from pflab.quant import forecast as fc
    c = closes.dropna()
    out: dict = {"asof": str(asof)}
    px = float(c.iloc[-1]) if len(c) else None
    scrip = fc.scrip_of(Path(root), isin, asof)
    pe = own_median = None
    rich = None
    if scrip and px:
        q = pit.load(con, scrip)
        if q.empty:
            q = pit.load(con, scrip, "consolidated")
        if not q.empty:
            r = pit.ratios(pit.last_quarters(q, scrip, asof))
            eps, g = r.get("eps_ttm"), r.get("eps_ttm_yoy")
            out["eps_ttm"], out["eps_growth_ttm_yoy_pct"] = eps, None if g is None else round(g * 100, 1)
            pe = pit.valuation_ratios(px, eps)["pe_ttm"]
            out["pe_ttm"] = None if pe is None else round(pe, 1)
            if pe is not None:
                h = pe_history(with_older_quarters(q, scrip, root), scrip, c, asof)
                if len(h) >= MIN_MONTHS:
                    own_median = float(h.median())
                    out["pe_own_5y"] = {"median": round(own_median, 1), "p10": round(float(h.quantile(.1)), 1),
                                        "p90": round(float(h.quantile(.9)), 1), "percentile_now": round(float((h <= pe).mean() * 100)),
                                        "months": int(len(h)), "from": str(h.index[0].date()),
                                        "note": "months with four filed quarters in a row; gaps in the filings are left as gaps"}
                else:
                    out["pe_own_5y"] = f"too little filed history ({len(h)} months)"
                try:
                    imp = float(pit.implied_growth(px, eps, asof).value) / 100.0
                    clip = None if g is None else min(max(g, 0.0), 0.30)
                    out["growth_assumed_by_price_pct"] = round(imp * 100, 1)
                    rich = imp > (clip + 0.10) if clip is not None else imp > 0.25
                except Exception:
                    out["growth_assumed_by_price_pct"] = None
            else:
                out["pe_note"] = "no P/E: loss-making or no four filed quarters in a row"
        else:
            out["pe_note"] = "no filed quarters held for it"
    mkt = market_pe(root, asof)
    if mkt:
        out["nifty500_pe"] = mkt
    vol = vol_ratio(c) if len(c) else {"ratio": None}
    out["volatility"] = vol
    from_high = float(c.iloc[-1] / c.iloc[-250:].max() - 1) if len(c) >= 2 else None
    try:                                                   # F&O build-up class of the stock's future, where it has one
        from pflab.quant import options
        bu = options.buildup_for(root, asof, [symbol]).get(symbol)
        if bu:
            out["futures_buildup"] = {**bu, "note": "price against open interest in its futures; information, not a signal"}
    except Exception:
        pass
    try:
        from pflab.learner import rules
        tested = {"pe_above_50": rules.status(con, "pe_above_50")}
    except Exception:
        tested = None
    out["rules_of_thumb"] = flags(pe, own_median, mkt, rich, vol, from_high, tested)
    out["how_to_use"] = ("read like a trader: say which of these matter for this company and why (a high P/E can be fair for "
                         "fast growth, a low one a trap); every flag is untested folklore, a reason to look, not a rule")
    out["source"] = "hq/valuation.py: filed quarters (point in time) and closes; ratios of a price and a filed number"
    return out
