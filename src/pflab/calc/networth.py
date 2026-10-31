"""Whole net worth on one date: ledger holdings and cash (S14) plus fixed deposits (S33), by bucket.

Buckets: equity (shares, equity funds), gold (SGBs, gold ETFs, physical), debt (FDs, bonds, debt funds), cash.
FDs whose `purpose` starts with "reserve:" are shown but kept out of the investable total that allocation
targets apply to (The investor, 2026-10-15: the May-2028 batch is a PhD reserve). An unpriced holding is listed and
left out of every total, never valued at cost. FD values are the bank's figures on the day it was read, else
labelled estimates.
"""
from __future__ import annotations

from datetime import date
from typing import Dict

import pandas as pd

from pflab.calc import valuation as val
from pflab.ledger import events as ev
from pflab.ledger.book import Ledger
from pflab.pm import estimate as est
from pflab.pm import fd as fdm

GOLD_WORDS = ("GOLD", "SGB")


def bucket(asset_class: str, tax_class: str, name: str = "") -> str:
    a, n = (asset_class or "").lower(), (name or "").upper()
    if a in ("sgb", "gold_physical") or (tax_class == "LISTED_NONEQUITY" and any(w in n for w in GOLD_WORDS)):
        return "gold"
    if a == "equity" or tax_class == "EQUITY":
        return "equity"
    if a in ("bond",) or tax_class in ("DEBT_MF", "UNLISTED_DEBT", "LISTED_NONEQUITY"):
        return "debt"
    return "review"


def build(con, asof: date) -> Dict[str, object]:
    led = Ledger.replay(ev.load(con), upto=asof)
    v = val.value_ledger(led, val.store_price_fn(con), asof)
    meta = {r[0]: r[1:] for r in con.execute(
        "SELECT isin, asset_class, tax_class, symbol, name FROM instruments").fetchall()}
    pos = v.positions.copy()
    pos["symbol"] = [meta.get(i, (None, None, None, None))[2] or meta.get(i, (None, None, None, None))[3] or i
                     for i in pos["isin"]]
    pos["bucket"] = [bucket(*(meta.get(i, ("", "", "", ""))[:2]), meta.get(i, ("", "", "", ""))[3] or "")
                     for i in pos["isin"]]
    every = [f for f in fdm.load(con) if f.term_start <= asof]
    fds = [f for f in every if f.status == "open" and f.maturity >= asof]
    fd_rows, fd_out = [], []
    for f in fds:
        try:
            x = fdm.value(f, asof)
        except fdm.FDError as e:                               # (2026-10-31) one deposit that cannot be valued never breaks the whole picture
            fd_out.append({"fd_id": f.fd_id, "bank": f.bank, "maturity": f.maturity, "why": f"not valued: {e}"})
            continue
        fd_rows.append(dict(fd_id=f.fd_id, maturity=f.maturity, value=x.value if isinstance(x, est.Estimate) else x,
                            estimate=isinstance(x, est.Estimate), reserve=f.purpose.startswith("reserve:"),
                            purpose=f.purpose, bank=f.bank, method=x.method if isinstance(x, est.Estimate) else "the bank's value that day",
                            as_of=getattr(x, "as_of", None) if isinstance(x, est.Estimate) else asof))
    for f in fdm.unresolved(every, asof):                      # matured, renewal or payout not seen: listed, kept out (a payout is in the bank)
        fd_out.append({"fd_id": f.fd_id, "bank": f.bank, "maturity": f.maturity, "contract_amount": f.maturity_amount,
                       "why": "matured; renewed or paid out is not known yet: drop the bank's latest deposit summary"})
    fdf = pd.DataFrame(fd_rows, columns=["fd_id", "maturity", "value", "estimate", "reserve", "purpose", "bank", "method", "as_of"])
    by = pos.dropna(subset=["value"]).groupby("bucket")["value"].sum().to_dict()
    by["cash"] = v.cash_total
    by["debt"] = by.get("debt", 0.0) + float(fdf.loc[~fdf["reserve"], "value"].sum())
    reserve = float(fdf.loc[fdf["reserve"], "value"].sum())
    investable = sum(by.values())
    return {"asof": asof, "valuation": v, "positions": pos, "fds": fdf, "buckets": by, "reserve": reserve,
            "investable": investable, "net_worth": investable + reserve,
            "fd_estimated": bool(fdf["estimate"].any()) if len(fdf) else False, "fd_excluded": fd_out}


def render(nw: Dict[str, object]) -> str:
    v, pos = nw["valuation"], nw["positions"]
    lines = [f"Net worth on {nw['asof']}: {nw['net_worth']:,.2f}"
             + ("  (FD part ESTIMATED from the bank's last values)" if nw["fd_estimated"] else ""),
             f"  investable {nw['investable']:,.2f}   PhD/other reserve (held out of targets) {nw['reserve']:,.2f}"]
    inv = nw["investable"] or 1.0
    for b in ("equity", "gold", "debt", "cash", "review"):
        if nw["buckets"].get(b):
            lines.append(f"  {b:<7} {nw['buckets'][b]:>15,.2f}  {100 * nw['buckets'][b] / inv:5.1f}% of investable")
    lines.append("Holdings:")
    for r in pos.sort_values(["bucket", "value"], ascending=[True, False]).itertuples():
        if r.value is None or pd.isna(r.value):
            lines.append(f"  {r.account:<11} {r.symbol:<14} {r.qty:>8g}  UNPRICED (cost {r.cost:,.2f})")
            continue
        flag = " STALE" if r.stale else ""
        lines.append(f"  {r.account:<11} {str(r.symbol)[:14]:<14} {r.qty:>8g} x {r.price:>10,.2f} = {r.value:>13,.2f}"
                     f"  unrealised {r.unrealised:>+12,.2f}  ({r.price_date}){flag}")
    lines.append("Cash: " + ", ".join(f"{c.account} {c.balance:,.2f}" for c in v.cash.itertuples() if c.balance))
    f = nw["fds"]
    if len(f):
        lines.append(f"FDs: {len(f)} open, {f['value'].sum():,.2f} "
                     f"(reserve {f.loc[f['reserve'], 'value'].sum():,.2f}; investable {f.loc[~f['reserve'], 'value'].sum():,.2f})")
    for x in nw.get("fd_excluded") or []:
        lines.append(f"! FD {x['bank']} {x['fd_id']} (maturity {x['maturity']}): left out of the total: {x['why']}")
    if v.unpriced:
        lines.append(f"! {len(v.unpriced)} holding(s) unpriced: left out of every total")
    return "\n".join(lines)
