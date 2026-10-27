"""The US sleeve in the ledger's own terms (S64 Phase 6 items 2 and 5): identifiers, dollar trades, FIFO lots, gains in rupees.

The Indian ledger engine (ledger/book.py) is rupee-only and frozen by its tests; US positions live beside it in `us_trades`
(dollars, with the rate that converts them) and join the portfolio at valuation. Nothing here changes a rupee lot.

IDENTIFIERS. A US instrument uses its real ISIN when a statement shows one. Until then its key is a pseudo-ISIN: "ZZ" plus the
10-digit SEC CIK (12 characters; "ZZ" is not an ISO country code, so it never meets a real ISIN). `instrument_alias` maps the
pseudo key to the real ISIN once seen, from a date.

TAX. Cost and proceeds are converted at the SBI telegraphic-transfer buying rate of the last day of the month BEFORE the month of
purchase and of sale (rule 115; tax/foreign.py). That rate is not in our data: the FRED noon-New-York USDINR rate stands in, so
every rupee figure here is an ESTIMATE, labelled. The holding class (more than 24 months = long) and the rates come from
configs/tax/foreign.toml (sourced, dated).
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import date, datetime
from typing import Dict, List, Optional

PSEUDO_PREFIX = "ZZ"
FX_PAIR = "USDINR"
FX_LABEL = "estimate: FRED noon New York rate stands in for the SBI TT buying rate (rule 115)"


def pseudo_isin(cik) -> str:
    n = int(str(cik).strip().lstrip("0") or "0")
    if not 0 < n < 10 ** 10:
        raise ValueError(f"not a CIK: {cik!r}")
    return f"{PSEUDO_PREFIX}{n:010d}"


def is_pseudo(isin: str) -> bool:
    return isinstance(isin, str) and len(isin) == 12 and isin.startswith(PSEUDO_PREFIX) and isin[2:].isdigit()


def add_alias(con, alias: str, isin: str, since: date) -> None:
    if not is_pseudo(alias):
        raise ValueError("an alias maps a pseudo-ISIN to a real one")
    con.execute("INSERT INTO instrument_alias VALUES (?,?,?) ON CONFLICT (alias) DO UPDATE SET isin=excluded.isin, since=excluded.since",
                [alias, isin, since])


def resolve(con, key: str, on: Optional[date] = None) -> str:
    """The real ISIN a pseudo key maps to on `on` (the key itself before the alias begins, or when it has none)."""
    r = con.execute("SELECT isin, since FROM instrument_alias WHERE alias=?", [key]).fetchone()
    return r[0] if r and (on is None or on >= r[1]) else key


def register_instrument(con, symbol: str, key: str, name: str, market: str = "US", currency: str = "USD", etf: bool = False,
                        now: Optional[datetime] = None) -> None:
    con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at, market, currency) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (isin) DO NOTHING",
                [key, "pseudo" if is_pseudo(key) else "isin", "etf" if etf else "equity", "FOREIGN", True, symbol, name,
                 "us sleeve (S64)", now or datetime.now(), market, currency])


# --- exchange rates ----------------------------------------------------------------------------------------------------------

def load_fx(con, root) -> int:
    """USDINR from FRED (data/macro DEXINUS) into fx_rates; days already there are kept."""
    from pflab.data import macro
    df = macro.load("USDINR", root)
    df = df.dropna(subset=["value"])
    have = {d for (d,) in con.execute("SELECT date FROM fx_rates WHERE pair=?", [FX_PAIR]).fetchall()}
    n = 0
    for d, v in zip(df["date"], df["value"]):
        d = d.date() if hasattr(d, "date") else d
        if d not in have and v > 0:
            con.execute("INSERT INTO fx_rates VALUES (?,?,?,?)", [d, FX_PAIR, float(v), "FRED DEXINUS"])
            n += 1
    return n


def fx_on(con, d: date) -> Optional[tuple]:
    """(rate, the day it is for): the latest rate on or before `d`; None when there is none."""
    r = con.execute("SELECT rate, date FROM fx_rates WHERE pair=? AND date<=? ORDER BY date DESC LIMIT 1", [FX_PAIR, d]).fetchone()
    return (float(r[0]), r[1]) if r else None


# --- entries (the dashboard form and the statement parser both land here) ----------------------------------------------------

def add_trade(con, trade_date: date, symbol: str, isin: str, side: str, qty: float, price_usd: float, charges_usd: float = 0.0,
              fx_rate: Optional[float] = None, fx_source: Optional[str] = None, source: str = "manual", note: str = "",
              now: Optional[datetime] = None) -> int:
    from pflab.pm.store import next_id
    if side not in ("buy", "sell"):
        raise ValueError("side is buy or sell")
    if qty <= 0 or price_usd <= 0:
        raise ValueError("quantity and price are positive")
    if side == "sell":
        held = holding(con, isin, trade_date)
        if qty > held + 1e-9:
            raise ValueError(f"selling {qty:g} of {symbol} but {held:g} are held on {trade_date}: nothing is guessed")
    tid = next_id(con, "us_trades", "trade_id")
    con.execute("INSERT INTO us_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [tid, trade_date, symbol.upper(), isin, side, qty, price_usd, charges_usd, fx_rate, fx_source, source,
                 now or datetime.now(), note])
    return tid


def add_remittance(con, remit_date: date, usd: float, inr: float, tcs_inr: Optional[float] = None, bank: str = "",
                   source: str = "manual", note: str = "", now: Optional[datetime] = None) -> int:
    from pflab.pm.store import next_id
    rid = next_id(con, "us_remittances", "remit_id")
    con.execute("INSERT INTO us_remittances VALUES (?,?,?,?,?,?,?,?,?)",
                [rid, remit_date, usd, inr, tcs_inr, bank, source, now or datetime.now(), note])
    return rid


def fy_of(d: date) -> int:
    """The financial year's starting year (April to March)."""
    return d.year if d.month >= 4 else d.year - 1


def remitted_in_fy(con, d: date) -> dict:
    fy = fy_of(d)
    r = con.execute("SELECT coalesce(sum(usd),0), coalesce(sum(inr),0), coalesce(sum(tcs_inr),0) FROM us_remittances "
                    "WHERE remit_date >= ? AND remit_date <= ?", [date(fy, 4, 1), date(fy + 1, 3, 31)]).fetchone()
    return {"fy": f"{fy}-{fy + 1}", "usd": float(r[0]), "inr": float(r[1]), "tcs_inr": float(r[2])}


# --- lots, positions, gains ----------------------------------------------------------------------------------------------------

def holding(con, isin: str, asof: date) -> float:
    r = con.execute("SELECT coalesce(sum(CASE WHEN side='buy' THEN qty ELSE -qty END),0) FROM us_trades WHERE isin=? AND trade_date<=?",
                    [isin, asof]).fetchone()
    return float(r[0])


def _conv(con, event: date) -> Optional[float]:
    """Rupees per dollar for a purchase or sale on `event`: the rate of the last day of the month before (the tax rule)."""
    from pflab.tax import foreign as tf
    got = fx_on(con, tf.fx_date(event))
    return None if got is None else got[0]


def fifo(con, asof: date) -> Dict[str, dict]:
    """Per isin: open lots (qty, USD cost per share incl. charges, buy date, INR cost per share) and the realised sales
    (with the lots they used), first in first out. A trade with no usable rate gets `inr` None and is listed in `no_rate`."""
    lots: Dict[str, deque] = defaultdict(deque)
    out: Dict[str, dict] = defaultdict(lambda: {"sales": [], "no_rate": []})
    rows = con.execute("SELECT trade_id, trade_date, symbol, isin, side, qty, price_usd, coalesce(charges_usd,0), fx_rate FROM us_trades "
                       "WHERE trade_date<=? ORDER BY trade_date, trade_id", [asof]).fetchall()
    for tid, d, sym, isin, side, qty, px, ch, fxr in rows:
        rate = _conv(con, d)
        if rate is None:
            out[isin]["no_rate"].append(tid)
        if side == "buy":
            lots[isin].append({"qty": qty, "usd_per_share": px + ch / qty, "date": d, "rate": rate, "symbol": sym})
        else:
            need, parts, proceeds_usd = qty, [], qty * px - ch
            while need > 1e-12 and lots[isin]:
                lot = lots[isin][0]
                take = min(need, lot["qty"])
                parts.append({"qty": take, "bought": lot["date"], "usd_cost": take * lot["usd_per_share"],
                              "inr_cost": None if lot["rate"] is None else take * lot["usd_per_share"] * lot["rate"]})
                lot["qty"] -= take
                need -= take
                if lot["qty"] <= 1e-12:
                    lots[isin].popleft()
            out[isin]["sales"].append({"date": d, "symbol": sym, "qty": qty, "proceeds_usd": proceeds_usd, "rate": rate, "lots": parts})
    for isin, dq in lots.items():
        out[isin]["open"] = [dict(l) for l in dq]
        out[isin]["symbol"] = dq[0]["symbol"] if dq else out[isin].get("symbol")
    return out


def gains(con, fy_start: int, slab: float, asof: Optional[date] = None) -> dict:
    """Realised gains of one financial year in rupees, by sale and in total, with the tax estimated per lot (class by the 24-month
    rule). FX gains are inside: cost and proceeds are converted at their own dates' rates. ESTIMATE."""
    from pflab.tax import foreign as tf
    lo, hi = date(fy_start, 4, 1), date(fy_start + 1, 3, 31)
    book = fifo(con, min(asof or hi, hi))
    rows, tot = [], {"gain_inr": 0.0, "tax_inr": 0.0, "long_gain_inr": 0.0, "short_gain_inr": 0.0}
    skipped = []
    for isin, b in book.items():
        for s in b["sales"]:
            if not lo <= s["date"] <= hi:
                continue
            if s["rate"] is None or any(p["inr_cost"] is None for p in s["lots"]):
                skipped.append({"symbol": s["symbol"], "date": str(s["date"]), "why": "no exchange rate on record for a date it needs"})
                continue
            for p in s["lots"]:
                proceeds = s["proceeds_usd"] * (p["qty"] / s["qty"]) * s["rate"]
                g = proceeds - p["inr_cost"]
                t = tf.gain_tax(g, p["bought"], s["date"], slab)
                rows.append({"symbol": s["symbol"], "sold": str(s["date"]), "bought": str(p["bought"]), "qty": round(p["qty"], 6),
                             "gain_inr": round(g, 2), "class": t["class"], "rate": t["rate"], "tax_inr": t["tax_rs"]})
                tot["gain_inr"] += g
                tot["tax_inr"] += t["tax_rs"]
                tot["long_gain_inr" if t["class"] == "long" else "short_gain_inr"] += g
    return {"fy": f"{fy_start}-{fy_start + 1}", "rows": rows, "total": {k: round(v, 2) for k, v in tot.items()}, "skipped": skipped,
            "label": FX_LABEL + "; " + tf.label(["cg_foreign_long_term_months", "cg_foreign_ltcg_rate", "fx_conversion_rule"]),
            "note": "tax per lot, losses not set off here (the tax engine does that); surcharge and cess excluded"}


def positions(con, asof: date, prices_usd: Optional[Dict[str, float]] = None) -> List[dict]:
    """Open US positions: shares, USD cost, and (with prices) USD and INR value at the latest rate."""
    book = fifo(con, asof)
    rate = fx_on(con, asof)
    out = []
    for isin, b in book.items():
        q = sum(l["qty"] for l in b.get("open", []))
        if q <= 1e-9:
            continue
        cost = sum(l["qty"] * l["usd_per_share"] for l in b["open"])
        row = {"isin": isin, "symbol": b.get("symbol"), "qty": round(q, 6), "cost_usd": round(cost, 2)}
        px = (prices_usd or {}).get(isin)
        if px is not None:
            row["value_usd"] = round(q * px, 2)
            row["value_inr"] = None if rate is None else round(q * px * rate[0], 0)
        out.append(row)
    return out
