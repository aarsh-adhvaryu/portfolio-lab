"""What a screen, the book card, the 15:45 report and the morning report read about the US sub-book (S82). Plain functions returning JSON-able dicts; nothing here writes.

    holdings(con, day)   {open, holdings: [...], cash, open_orders, international_share, gap_risk, funding, whole_book, label}. Each holding: symbol, ISIN key, shares, price and its
                         date, value in USD and in rupees with the FX rate and its source, the cost, and the return after the ESTIMATED Indian tax (labelled "estimate": the lots' own tax
                         rates, the month-end rate before the sale standing in for the SBI TT buying rate, surcharge and cess not added).
    card_summary(con, day)  the short form for the book card JSON (key `us`)
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Optional

from pflab import us
from pflab.us import adapter, book, costs, data, fx as usfx, instruments as uins, transfer, wholebook

ESTIMATE = ("estimate: the return after Indian tax uses the dated rows of configs/us/tax_s81.toml, the month-end rate before the sale for the SBI TT buying rate, and leaves out "
            "surcharge and cess; the rupee figures use the stated USD/INR source")


def _jsonable(x):
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (date, datetime)):
        return str(x)
    return x


def _after_tax(con, canon: str, qty: float, price: float, day: date, fxv: Optional[dict], root) -> dict:
    """Unrealised return in rupees after the estimated tax if everything were sold at `price` today. {} when the rates for it are missing."""
    try:
        lots = book._lots_of(con, canon, day)
        cost_inr = sum(l["qty"] * l["cost_usd_per_share"] * l["fx_tax_acq"] for l in lots if l["fx_tax_acq"])
        if not lots or cost_inr <= 0 or qty <= 0:
            return {}
        ch = costs.charges("sell", qty, price, day)["total"]
        plan = book.plan_sale(con, canon, qty, price, ch, day, root)
        if plan.get("no_rate"):
            return {"note": "no tax FX rate for a date it needs: the tax is not estimated"}
        net = plan["gain_inr"] - plan["tax_inr"]
        return {"cost_inr": round(cost_inr, 2), "gain_inr": round(plan["gain_inr"], 2), "estimated_tax_inr": round(plan["tax_inr"], 2), "return_after_tax_pct": round(net / cost_inr * 100.0, 2),
                "return_before_tax_pct": round(plan["gain_inr"] / cost_inr * 100.0, 2), "label": "estimate"}
    except Exception as e:
        return {"note": f"not estimated: {type(e).__name__}"}


def holdings(con, day: date, root=None) -> dict:
    acct = book.account(con)
    ish = None
    try:
        ish = wholebook.international_share(con, day, root=root)
    except Exception as e:
        ish = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    out = {"open": acct is not None, "on": us.on(), "day": str(day), "gap_risk": adapter.GAP_RISK, "international_share": ish, "label": ESTIMATE}
    try:
        out["whole_book"] = wholebook.whole_book_inr(con, day, root)
    except Exception as e:
        out["whole_book"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    if acct is None:
        out.update({"holdings": [], "cash": {"usd": 0.0, "inr": 0.0}, "open_orders": [], "funding": []})
        return _jsonable(out)
    fx = usfx.rate_for(con, day, root, max_age_days=10)
    rate = fx["rate"] if fx else None
    last = con.execute("SELECT holdings_json FROM us_days_s81 WHERE day <= ? ORDER BY day DESC LIMIT 1", [day]).fetchone()
    info = json.loads(last[0]) if last and last[0] else {}
    hs = []
    for canon, q in sorted(book.positions(con, day).items()):
        if q <= 1e-9:
            continue
        # the mark is keyed by the key it was made under; a symbol key mapped since resolves to the same position
        row = info.get(canon) or next((v for k, v in info.items() if uins.canonical(con, k, date.max) == canon), {})
        px = row.get("close")
        v = row.get("value_usd")
        if v is None and px:
            v = q * px
        h = {"symbol": uins.symbol_of(con, canon) or canon, "isin_key": canon, "shares": round(q, 6), "price_usd": px, "price_date": row.get("close_date"), "value_usd": v,
             "value_inr": None if (v is None or rate is None) else round(v * rate, 2), "fx_rate": rate, "fx_source": None if not fx else fx["source"]}
        h["cost_usd"] = round(sum(l["qty"] * l["cost_usd_per_share"] for l in book._lots_of(con, canon, day)), 2)
        h["after_tax"] = _after_tax(con, canon, q, px, day, fx, root) if px else {}
        hs.append(h)
    cash = book.cash(con, day)
    out["holdings"] = hs
    out["cash"] = {"usd": round(cash, 2), "inr": None if rate is None else round(cash * rate, 2), "fx_rate": rate, "fx_source": None if not fx else fx["source"]}
    out["open_orders"] = [{**o, "placed_day": str(o["placed_day"])} for o in book.open_orders(con)]
    out["funding"] = [{"transfer_id": t["transfer_id"], "us_day": str(t["us_day"]), "rupee_day": str(t["rupee_day"]), "rupees": t["inr"], "dollars": round(t["usd"], 2), "fx_rate": t["fx_rate"],
                       "fx_source": t["fx_source"], "markup_pct": round(t["markup"] * 100, 2), "markup_rupees": round(t["markup_inr"], 2), "phase": t["phase"], "reason": t["reason"],
                       "label": "paper money moved out of the rupee book's cash; the markup is an estimate"} for t in transfer.transfers(con)]
    out["value_usd"] = (wholebook.us_value_usd(con, day) or {}).get("usd")
    out["account"] = {k: (str(v) if isinstance(v, (date, datetime)) else v) for k, v in acct.items()}
    return _jsonable(out)


def card_summary(con, day: date, root=None) -> dict:
    """A small JSON for the book card: what is held, the whole book and the international share, the last funding."""
    h = holdings(con, day, root)
    ish = h.get("international_share") or {}
    return _jsonable({"open": h["open"], "holdings": [{k: x[k] for k in ("symbol", "shares", "value_usd", "value_inr")} for x in h.get("holdings", [])], "cash": h.get("cash"),
                      "open_orders": len(h.get("open_orders", [])), "whole_book": {k: (h.get("whole_book") or {}).get(k) for k in ("whole_inr", "rupee_book_inr", "us_book_inr", "us_book_usd", "fx", "fx_source")},
                      "international_share": {k: ish.get(k) for k in ("target", "share", "phase", "tranche_inr", "gap_inr", "reason")}, "last_funding": (h.get("funding") or [None])[-1],
                      "gap_risk": h["gap_risk"]})
