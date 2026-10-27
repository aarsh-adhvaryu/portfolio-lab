"""An IPO allotment and the money around it (S64; the investor: "I got 22 shares of a Jio IPO at 1191 and want to invest about
Rs 1.5 lakh in all; I do not know if it goes up or down; it needs a strategy").

What code can say, and what it cannot:
    CAN     the value of the allotment and its share of the budget; what the allotment is worth at any listing price; how large
            IPOs behaved on the exchange (the listing gain against the issue price at the open and the close, and the return
            from the listing-day close over the next 5, 20 and 60 sessions, with the worst fall in those 60); how much of the
            portfolio already sits in the same business group and what the allotment adds; what the standard monthly plan
            would do with the rest (targets, guards, theme limits, nudges all applied); the tax on a sale (estimate, rate sourced)
    CANNOT  say whether this one goes up or down. The grey-market premium (GMP) is an unofficial price whispered between dealers,
            not a record: it is sentiment, never value, and it is looked up (cited, dated) by the brain's web search, not
            stored here. Subscription by category, the valuation against peers and the anchors are likewise looked up.
The base rates are history of listings since 2016 with a day-one traded value of Rs 200 crore or more on the main board; the
"issue price" is the exchange's base price on the listing day (previous close), which equals the issue price for a main-board IPO.
They are not a forecast and they are not about this company.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

SINCE = "2016-01-01"
MIN_TURNOVER = 2e9                      # Rs 200 crore traded on the first day
GAINS = (-0.30, -0.20, -0.10, 0.0, 0.10, 0.25, 0.50)
HORIZONS = (5, 20, 60)


def base_rates(root, since: str = SINCE, cache: bool = True) -> dict:
    """How large IPOs behaved: listing gain (open, close) and the return from the listing-day close, from the panel."""
    from pflab import _duck
    root = Path(root)
    cp = root / "derived" / "ipo_base_rates.parquet"
    if cache and cp.exists() and (pd.Timestamp.now() - pd.Timestamp(cp.stat().st_mtime, unit="s")).days < 14:
        t = pd.read_parquet(cp)
    else:
        ld = pd.read_parquet(root / "panel" / "listing_dates.parquet")
        ld = ld[ld.index.astype(str).str.startswith("INE")]
        ld["first_trade"] = pd.to_datetime(ld["first_trade"])
        ld = ld[ld["first_trade"] >= since]
        d = _duck.sql(f"select date, isin, series, open, close, prev_close, turnover, adj_close from '{root}/panel/prices.parquet' "
                      f"where isin in ({','.join(repr(i) for i in ld.index)}) order by isin, date").df()
        d["date"] = pd.to_datetime(d["date"])
        rows = []
        for isin, g in d.groupby("isin"):
            g = g.reset_index(drop=True)
            if len(g) < 61 or g.loc[0, "date"] != ld.loc[isin, "first_trade"]:
                continue
            f = g.loc[0]
            rows.append({"isin": isin, "date": f["date"], "series": f["series"], "turnover": f["turnover"], "issue": f["prev_close"],
                         "gain_open": f["open"] / f["prev_close"] - 1, "gain_close": f["close"] / f["prev_close"] - 1,
                         **{f"r{k}": g.loc[k, "adj_close"] / f["adj_close"] - 1 for k in HORIZONS},
                         "dd60": (g.loc[:60, "adj_close"] / f["adj_close"]).min() - 1})
        t = pd.DataFrame(rows)
        if cache and len(t):
            cp.parent.mkdir(parents=True, exist_ok=True)
            t.to_parquet(cp)
    big = t[(t["series"] == "EQ") & (t["turnover"] >= MIN_TURNOVER) & t["gain_open"].between(-0.6, 3.0)]

    def q(s: pd.Series) -> dict:
        return {"median": round(float(s.median()), 3), "p10": round(float(s.quantile(.1)), 3), "p90": round(float(s.quantile(.9)), 3),
                "share_up": round(float((s > 0).mean()), 2)}
    return {"n": int(len(big)), "since": since, "first": str(big["date"].min().date()) if len(big) else None,
            "last": str(big["date"].max().date()) if len(big) else None,
            "listing_gain_at_open": q(big["gain_open"]), "listing_gain_at_close": q(big["gain_close"]),
            **{f"after_listing_day_{k}_sessions": q(big[f"r{k}"]) for k in HORIZONS},
            "worst_fall_within_60_sessions": q(big["dd60"]),
            "note": ("large main-board listings since 2016; a listing whose exchange base price is not its issue price (a demerger, "
                     "a relisting) can be in here; history of other companies, not a forecast of this one")}


def scenarios(qty: int, issue: float, gains=GAINS) -> List[dict]:
    """What the allotment is worth at a listing price `gain` above the issue price (arithmetic)."""
    return [{"listing_price_vs_issue_pct": round(g * 100), "price": round(issue * (1 + g), 2),
             "value_rs": round(qty * issue * (1 + g)), "profit_rs": round(qty * issue * g)} for g in gains]


def tax_estimate(profit: float, rate: float) -> float:
    """Short-term capital gains tax on a profit from a sale within a year (an estimate; the rate is from configs/tax_policy_in.toml)."""
    return max(profit, 0.0) * rate


def group_exposure(con, asof: date, group_symbols: List[str], allot_value: float) -> dict:
    """Value of the holdings whose symbol is in the group, as a share of investable money, before and after the allotment."""
    from pflab.pm import today
    n = today.build(con, asof)
    pos = n["positions"]
    held = pos[pos["symbol"].isin(group_symbols) & pos["value"].notna()]
    inv = float(n["investable"]) or 1.0
    have = float(held["value"].sum())
    return {"names_held": {r.symbol: round(float(r.value)) for r in held.itertuples()}, "value_rs": round(have),
            "share_of_investable_pct": round(have / inv * 100, 1), "after_allotment_pct": round((have + allot_value) / inv * 100, 1),
            "investable_rs": round(inv)}


def groups_config(pm_dir: Optional[Path]) -> Dict[str, List[str]]:
    """The investor's business groups (PFLAB_PM_DIR/groups.toml, out of git): name -> NSE symbols."""
    from pflab import _toml
    p = Path(pm_dir) / "groups.toml" if pm_dir else None
    return {k: v.get("symbols", []) for k, v in _toml.load(p).get("group", {}).items()} if p and p.exists() else {}


def remaining_plan(con, asof: date, amount: float) -> dict:
    """What the standard monthly plan would do with `amount` (targets, guards, theme limits and nudges all applied)."""
    from pflab.plan import advisor
    text, adv, tickets = advisor.run(con, asof, amount)
    return {"buys": [{"symbol": b.symbol, "qty": b.qty, "price": b.price, "spend_rs": round(b.cost), "tickets": tickets.get(b.symbol, [])[:4]}
                     for b in adv.buys], "unspent_rs": round(adv.unspent), "notes": adv.notes[:4], "plan": text[:1500]}


def strategy(con, root, asof: date, name: str, qty: int, issue: float, budget: float, group: Optional[str] = None,
             pm_dir: Optional[Path] = None, stcg: Optional[float] = None, with_plan: bool = True) -> dict:
    """The facts for deciding what to do with an allotment and the rest of the money. Choices are listed with their numbers; the
    system does not pick one: the investor's targets, limits and goals do."""
    allot = qty * issue
    left = budget - allot
    out: dict = {"name": name, "allotment": {"shares": qty, "issue_price": issue, "value_rs": round(allot),
                                             "share_of_budget_pct": round(allot / budget * 100, 1), "left_to_invest_rs": round(left)}}
    out["if_listed_at"] = scenarios(qty, issue)
    out["base_rates"] = base_rates(root)
    if stcg is None:
        try:
            from pflab import _toml
            stcg = float(_toml.load(Path(__file__).resolve().parents[3] / "configs" / "tax_policy_in.toml")["stcg_rate"])
        except Exception:
            stcg = None
    if stcg is not None:
        out["tax_on_a_sale_within_a_year"] = {"rate": stcg, "label": "estimate: short-term gains rate from configs/tax_policy_in.toml",
                                              "on_a_25pct_listing_gain_rs": round(tax_estimate(allot * 0.25, stcg))}
    grp = groups_config(pm_dir)
    if group and group in grp:
        out["group_exposure"] = {"group": group, **group_exposure(con, asof, grp[group], allot)}
    elif grp:
        out["group_exposure"] = {"note": f"no group named {group!r}; groups on file: {sorted(grp)}"}
    else:
        out["group_exposure"] = {"note": "no business groups on file (PFLAB_PM_DIR/groups.toml): the allotment's overlap with what you hold cannot be measured"}
    if with_plan and left > 0:
        try:
            out["the_rest_under_the_standard_plan"] = remaining_plan(con, asof, left)
        except Exception as e:
            out["the_rest_under_the_standard_plan"] = {"not_built": f"{type(e).__name__}: {str(e)[:120]}"}
    out["choices_for_the_allotment"] = [
        "Sell on the listing day: takes the pop if there is one (large IPOs listed above the issue price in 7 of 10 cases), "
        "pays short-term tax on the gain, and gives up what comes later.",
        "Hold: the base rates show large IPOs after the listing day were flat to down over 1-3 months with a wide spread; holding "
        "is a view on the company, not on the listing.",
        "Sell part on the day and hold the rest: caps the regret either way.",
        "Whatever the choice, decide it BEFORE the listing and write it down; the listing-day price is where emotion decides for you."]
    out["to_look_up_with_web_search"] = [
        "subscription by category (QIB, NII, retail) and whether the issue closed far above 1x",
        "the grey-market premium (GMP): unofficial, only sentiment, say its date",
        "price against peers (P/E, growth) from the offer document, and the anchor investors and their lock-in ends",
        "what the money raised is for (offer for sale vs fresh issue)"]
    out["not_known"] = "whether this goes up or down; no history of other companies decides that"
    return out
