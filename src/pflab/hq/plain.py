"""What the numbers mean, in plain words (S64; the investor: "they say the P/E is high, we should sell; I have no idea what that
means"). Every sentence is built by code from the stock's own numbers; no model writes a figure. The brain is told to say these
things the same way, and the dashboard can show them under the numbers.

Trader's shorthand is explained, not obeyed: each sentence says what the shorthand claims, what it can miss, and, where this
system has tested the rule, what the test found (`learner/rules.py`).
"""
from __future__ import annotations

from typing import List, Optional


def pe(p: float, own: Optional[dict], mkt: Optional[dict], tested: Optional[dict] = None) -> List[str]:
    out = [f"P/E {p:.1f} means you pay about Rs {p:.0f} for every Re 1 the company earned over the last year. Put the other way, "
           f"each Rs 100 you put in buys about Rs {100 / p:.1f} of yearly profit ({100 / p:.1f}% a year, the 'earnings yield')."]
    if isinstance(own, dict) and own.get("median"):
        pct = own.get("percentile_now")
        out.append(f"In the last 5 years it usually traded at about {own['median']:.0f} times (its middle). Today it is "
                   + ("dearer than it was in almost every one of those months" if pct is not None and pct >= 90 else
                      "cheaper than it was in almost every one of those months" if pct is not None and pct <= 10 else
                      f"dearer than it was in {pct:.0f} of every 100 of those months" if pct is not None else "near its usual")
                   + ". Traders call that expensive or cheap 'for this company'.")
    if mkt:
        out.append(f"The whole Nifty 500 trades at about {mkt['pe']:.0f} times, so this one is priced at {p / mkt['pe']:.0%} of the "
                   "market's level" + (" (dearer than the market)." if p > mkt["pe"] else " (cheaper than the market)."))
    out.append("Why traders say 'high P/E, sell': a high P/E means the price already expects strong growth. If the growth comes in "
               "lower, the price can fall even when the business is fine, because buyers will pay a lower multiple. A low P/E can be a "
               "trap too: it is cheap because the profit may be about to shrink. It is a way of talking about expectations, not a law.")
    t = (tested or {}).get("label")
    if t in ("passed", "failed"):
        out.append(f"This system tested the cut-off 'P/E above 50' on the Nifty 500 (one month ahead, 2010-2021): {t}. "
                   "A one-month test does not settle what valuation does over years.")
    return out


def growth(assumed_pct: Optional[float], delivered_pct: Optional[float]) -> Optional[str]:
    if assumed_pct is None:
        return None
    s = f"The price assumes the profit grows about {assumed_pct:.0f}% a year for the next 10 years (then slows to 5%)."
    if delivered_pct is not None:
        gap = assumed_pct - max(min(delivered_pct, 30.0), 0.0)
        s += (f" Over the last year it actually grew {delivered_pct:.0f}%. "
              + ("That asks for more than it has delivered; it needs to speed up or the price is stretched." if gap > 10 else
                 "That is within what it has delivered, so the price is not asking for a miracle."))
    return s


def volatility(ratio: Optional[float], v3m: Optional[float], v3y: Optional[float]) -> Optional[str]:
    if ratio is None:
        return None
    if ratio > 1.3:
        return (f"It has been jumpier than usual lately: its daily swings are {ratio:.1f} times its 3-year norm ({v3m:.0f}% a year "
                f"against {v3y:.0f}%). Jumpy usually means the market is arguing about it; size a buy smaller and in parts.")
    if ratio < 0.8:
        return f"It has been calmer than usual lately ({v3m:.0f}% a year against its norm of {v3y:.0f}%)."
    return f"Its recent swings ({v3m:.0f}% a year) are about its usual ({v3y:.0f}%)."


def below_sma200(flag: Optional[bool], tested: Optional[dict] = None) -> Optional[str]:
    if flag is None:
        return None
    base = ("It trades below its average price of the last 200 sessions, which traders read as a downtrend." if flag
            else "It trades above its average price of the last 200 sessions, which traders read as an uptrend.")
    t = (tested or {}).get("label")
    if t == "passed" and flag:
        base += (" This system tested that for the Nifty 500: names below the average earned about 0.6% to 0.75% a month less than "
                 "the rest in both 2010-2017 and 2018-2021, so buying into one is going against a tested headwind.")
    return base


def growth_lines(v: dict, peg_test: Optional[dict] = None) -> List[str]:
    """PEG, the forward P/E and the five-year profit, in words (from the valuation facts)."""
    out: List[str] = []
    peg = v.get("peg")
    if peg is not None:
        s = (f"PEG {peg:.2f}: the P/E divided by the yearly profit growth in percent. Below 1 means you pay less than one year of "
             "the P/E for each point of growth; traders read that as cheap for its growth. ")
        s += ("It leans on last year's growth continuing, which is the shaky part. " if peg < 1 else "Above 1 means the price asks more than the growth supports. ")
        t = (peg_test or {}).get("label")
        if t in ("passed", "failed"):
            s += (f"This system tested 'PEG below 1 becomes a multibagger within 5 years' on the Nifty 500 (2010-2016 starts): {t}, "
                  "with weak power (seven starting years).")
        else:
            s += "The 'PEG below 1 means multibagger' claim has not been tested here."
        out.append(s)
    elif v.get("eps_growth_ttm_yoy_pct") is not None and v["eps_growth_ttm_yoy_pct"] <= 0:
        out.append("PEG cannot be worked out: the profit did not grow over the last year, and a PEG needs growth above zero.")
    if v.get("forward_pe_our_estimate") is not None:
        out.append(f"Forward P/E (our own estimate) {v['forward_pe_our_estimate']:.1f}: the price over next year's profit if it grows "
                   f"as fast as last year's, capped at 30%. Analysts publish their own; we hold none, so this one is only an extrapolation.")
    if v.get("next_5y_profit_pct_of_price") is not None:
        p5 = v["next_5y_profit_pct_of_price"]
        out.append(f"If the profit grows at that pace, the next 5 years of profit add up to about {p5:.0f}% of today's price. "
                   + ("Traders look for 100% or more, that is, the profits of five years repay the whole price, as a sign of a potential "
                      "multibagger; this one clears it." if p5 >= 100 else
                      "Traders look for 100% or more (the profits of five years repaying the price); this one is below that, so the price "
                      "depends on growth beyond five years."))
    return out


def all_lines(pe_value: Optional[float], own, mkt, assumed, delivered, vol: dict, sma_flag, tested: dict) -> List[str]:
    out: List[str] = []
    if pe_value:
        out += pe(pe_value, own, mkt, (tested or {}).get("pe_above_50"))
    for line in (growth(assumed, delivered), volatility(vol.get("ratio"), vol.get("vol_3m_pct"), vol.get("vol_3y_pct")),
                 below_sma200(sma_flag, (tested or {}).get("below_sma200"))):
        if line:
            out.append(line)
    return out
