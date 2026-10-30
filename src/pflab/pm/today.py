"""The portfolio today (S58b; the investor 2026-10-24: the system is built around the portfolio, the Kite login is a must).

The ledger is rebuilt from documents and stays the record (tax lots, cost, income). Between statements the broker's
own view is the best knowledge of what is held now, so each Kite check stores a snapshot (`record`: holdings with T1,
Coin funds, today's delivery buys and sells, the cash balance) and `build` is the ledger's net worth with the Zerodha
account replaced by the newest snapshot that is not older than the ledger's documents:

  - quantities are Kite's; each difference from the ledger is listed (a trade the statements have not brought in);
    an added quantity is costed at Kite's price for it, a reduced one keeps the ledger's average cost;
  - cash is Kite's balance. What the ledger's Zerodha cash, after the differences above, does not explain is money
    that left or reached the account: shown as moved to or from the linked bank (an estimate until the bank statement
    brings it in), so Zerodha's payout of unused funds never looks like a loss;
  - no snapshot (no Kite login yet) -> the ledger alone, and `today.source` says so.

`build` returns what `calc.networth.build` returns (the screens, plans, simulations and workshop read it the same way)
plus `today`. Tax always uses the ledger's own lots, never this view.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from typing import Dict, List, Optional

import pandas as pd

from pflab.calc import networth as nw

TOL = 1e-6
CASH_TOL = 1.0                                    # rupees


def record(con, kite, account: str, now: datetime) -> dict:
    """Store what Kite shows now. Each part that fails is skipped and named (holdings are required)."""
    from pflab.agents.tradecheck import isin_of
    from pflab.ingest import kite as km
    from pflab.pm import store
    rows, missing = [], []
    for r in km.holdings_frame(kite.holdings()).itertuples():
        rows.append(("holding", r.isin, r.symbol, r.qty, r.t1, r.avg_price, r.last_price, None))
    for part, fn in (("funds", lambda: km.mf_frame(kite.mf_holdings())), ("today", lambda: km.day_frame(kite.positions())),
                     ("cash", lambda: km.funds_from_margins(kite.margins()))):
        try:
            got = fn()
        except Exception as e:                       # Coin off for the account, a failed call: said, not fatal
            missing.append(f"{part}: {type(e).__name__}")
            continue
        if part == "funds":
            rows += [("fund", r.isin, r.symbol, r.qty, 0.0, r.avg_price, r.last_price, None) for r in got.itertuples()]
        elif part == "today":
            rows += [("today", isin_of(con, r.symbol), r.symbol, r.qty, 0.0, r.buy_price if r.qty > 0 else r.sell_price,
                      None, None) for r in got.itertuples()]
        else:
            rows.append(("cash", None, None, None, None, None, None, got["live_balance"]))
    with store.transaction(con):
        sid = store.next_id(con, "kite_snapshots", "snap_id")
        for k, isin, sym, q, t1, avg, last, amt in rows:
            con.execute("INSERT INTO kite_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        [sid, now, account, k, isin, sym, q, t1, avg, last, amt])
    return {"snap_id": sid, "rows": len(rows), "missing": missing}


KITE_ONLY = "KITE"          # the account label of a snapshot taken before any statement has set up a Zerodha account


def kite_held(con) -> set:
    """ISINs Kite showed in its latest snapshot (holdings and funds): before his statements are read the ledger is empty, and filings, news and
    research must still follow the companies he holds (2026-10-30)."""
    try:
        r = con.execute("SELECT max(snap_id) FROM kite_snapshots").fetchone()[0]
        if r is None:
            return set()
        return {i for (i,) in con.execute("SELECT DISTINCT isin FROM kite_snapshots WHERE snap_id=? AND kind IN ('holding','fund') AND isin LIKE 'IN%' "
                                           "AND qty > 0", [r]).fetchall()}
    except Exception:
        return set()


def broker(con) -> Optional[str]:
    from pflab.agents.tradecheck import zerodha_account
    try:
        return zerodha_account(con)
    except LookupError:
        # no statement has set the account up yet: what Kite itself shows is still the best picture there is, and it says whose it is
        try:
            if con.execute("SELECT 1 FROM kite_snapshots WHERE account_id=? LIMIT 1", [KITE_ONLY]).fetchone():
                return KITE_ONLY
        except Exception:
            pass
        return None


def linked_bank(con, account: str) -> Optional[str]:
    """The bank of the latest transfer to or from the broker account (Zerodha pays unused funds back to it)."""
    r = con.execute("SELECT CASE WHEN account_id=? THEN counter_account ELSE account_id END FROM events "
                    "WHERE kind='cash_transfer' AND (account_id=? OR counter_account=?) ORDER BY trade_date DESC, event_id DESC "
                    "LIMIT 1", [account, account, account]).fetchone()
    return r[0] if r else None


def latest(con, account: str, asof: date) -> Optional[pd.DataFrame]:
    r = con.execute("SELECT max(snap_id) FROM kite_snapshots WHERE account_id=? AND CAST(taken_at AS DATE) <= ?",
                    [account, asof]).fetchone()[0]
    if r is None:
        return None
    return con.execute("SELECT * FROM kite_snapshots WHERE snap_id=?", [r]).df()


def documents_to(con, account: Optional[str] = None) -> Optional[date]:
    q = "SELECT max(trade_date) FROM events" + (" WHERE account_id=? OR counter_account=?" if account else "")
    return con.execute(q, [account, account] if account else []).fetchone()[0]


def build(con, asof: date) -> Dict[str, object]:
    n = nw.build(con, asof)
    acc = broker(con)
    info = {"source": "ledger", "account": acc, "documents_to": documents_to(con), "snapshot_at": None, "diffs": [],
            "kite_cash": None, "ledger_cash": None, "moved": 0.0, "bank": None, "missing": []}
    n["today"] = info
    snap = latest(con, acc, asof) if acc else None
    if snap is None or snap.empty:
        return n
    taken = pd.Timestamp(snap["taken_at"].iloc[0]).to_pydatetime()
    led_to = documents_to(con, acc)
    if led_to is not None and taken.date() < led_to:          # the statements are newer than Kite's last view
        info.update(stale_snapshot=str(taken)[:16])
        return n
    info.update(source="kite", snapshot_at=taken.isoformat(timespec="minutes"))

    from pflab.calc import valuation as val
    pos, v = n["positions"], n["valuation"]
    meta = {r[0]: r[1:] for r in con.execute("SELECT isin, asset_class, tax_class, symbol, name FROM instruments").fetchall()}
    kq: Dict[str, float] = {}
    kpx: Dict[str, float] = {}                                  # Kite's price for an added quantity
    ksym: Dict[str, str] = {}
    sold_px: Dict[str, float] = {}
    for r in snap[snap["kind"] != "cash"].itertuples():
        if not isinstance(r.isin, str) or not r.isin:
            info["missing"].append(f"{r.symbol}: no ISIN known")
            continue
        kq[r.isin] = kq.get(r.isin, 0.0) + float(r.qty)
        ksym.setdefault(r.isin, r.symbol)
        if r.kind == "today" and r.qty > 0 or (r.kind in ("holding", "fund") and r.isin not in kpx):
            kpx[r.isin] = float(r.avg_price or 0) or kpx.get(r.isin, 0.0)
        if r.kind == "today" and r.qty < 0:
            sold_px[r.isin] = float(r.avg_price or 0)
    mine = pos[pos["account"] == acc]
    lq = dict(zip(mine["isin"], mine["qty"]))
    lcost = dict(zip(mine["isin"], mine["cost"]))
    elsewhere = set(pos.loc[pos["account"] != acc, "isin"])
    price_fn = val.store_price_fn(con)
    rows, trade_cash = [], 0.0
    for isin in sorted(set(lq) | set(kq)):
        a, b = float(lq.get(isin, 0.0)), float(kq.get(isin, 0.0))
        if isin not in lq and isin in elsewhere and b > TOL:
            info["missing"].append(f"{ksym.get(isin)} ({isin}): in Kite and in another ledger account; the ledger's kept")
            continue
        p = price_fn(isin, asof)
        price = p.value if p else None
        if abs(a - b) > TOL:
            buy_px = kpx.get(isin) or price or 0.0
            px = buy_px if b > a else (sold_px.get(isin) or price or 0.0)
            trade_cash -= (b - a) * px
            info["diffs"].append({"isin": isin, "symbol": ksym.get(isin) or (meta.get(isin) or (None,) * 4)[2],
                                  "ledger": a, "kite": b, "price_used": px})
        if b <= TOL:
            continue
        cost = (lcost.get(isin, 0.0) * min(a, b) / a if a > TOL else 0.0) + max(b - a, 0.0) * (kpx.get(isin) or price or 0.0)
        m = meta.get(isin, ("", "", None, None))
        value = b * price if price is not None else None
        rows.append(dict(account=acc, isin=isin, qty=b, cost=cost, price=price, price_date=p.date if p else None,
                         price_kind=p.kind if p else "none", stale=p.stale if p else True, value=value,
                         unrealised=value - cost if value is not None else None, dormant=False,
                         symbol=m[2] or m[3] or ksym.get(isin) or isin,
                         bucket=nw.bucket(m[0] or "", m[1] or "", m[3] or ksym.get(isin) or "")))
    new = pd.concat([pos[pos["account"] != acc], pd.DataFrame(rows, columns=pos.columns)], ignore_index=True)

    cash = v.cash.copy()
    c = snap.loc[snap["kind"] == "cash", "amount"]
    if len(c):
        kc = float(c.iloc[0])
        lc = float(cash.loc[cash["account"] == acc, "balance"].sum())
        moved = lc + trade_cash - kc
        info.update(kite_cash=kc, ledger_cash=lc, trade_cash=trade_cash)
        if (cash["account"] == acc).any():
            cash.loc[cash["account"] == acc, ["balance", "available"]] = [kc, kc]
        else:
            cash = pd.concat([cash, pd.DataFrame([dict(account=acc, balance=kc, blocked=0.0, available=kc, dormant=False)])],
                             ignore_index=True)
        bank = linked_bank(con, acc)
        if abs(moved) > CASH_TOL and bank:
            info.update(moved=moved, bank=bank)
            if (cash["account"] == bank).any():
                cash.loc[cash["account"] == bank, ["balance", "available"]] += moved
            else:
                cash = pd.concat([cash, pd.DataFrame([dict(account=bank, balance=moved, blocked=0.0, available=moved,
                                                           dormant=False)])], ignore_index=True)
    invested = float(new["value"].dropna().sum()) if len(new) else 0.0
    ct = float(cash["balance"].sum()) if len(cash) else 0.0
    unpriced = [(r.account, r.isin, r.qty, r.cost) for r in new.itertuples() if r.value is None or r.value != r.value]
    v2 = replace(v, positions=new[[c for c in v.positions.columns]], cash=cash, invested=invested, cash_total=ct,
                 cash_available=float(cash["available"].sum()) if len(cash) else 0.0, total=invested + ct,
                 unpriced=unpriced, stale=sorted({r.isin for r in new.itertuples() if r.stale and r.value is not None}))
    fdf = n["fds"]
    by = new.dropna(subset=["value"]).groupby("bucket")["value"].sum().to_dict()
    by["cash"] = ct
    by["debt"] = by.get("debt", 0.0) + (float(fdf.loc[~fdf["reserve"], "value"].sum()) if len(fdf) else 0.0)
    investable = sum(by.values())
    n.update(valuation=v2, positions=new, buckets=by, investable=investable, net_worth=investable + n["reserve"])
    return n


def summary(t: dict) -> List[str]:
    """The `today` block in words (screens, the morning report)."""
    if t["source"] != "kite":
        why = (f"Kite's last view ({t['stale_snapshot']}) is older than the statements" if t.get("stale_snapshot")
               else "no Kite login yet")
        return [f"From your statements (to {t['documents_to']}); {why}."]
    out = [f"Today per Kite ({t['snapshot_at'].replace('T', ' ')}); statements to {t['documents_to']}."]
    for d in t["diffs"]:
        out.append(f"{d['symbol']}: Kite {d['kite']:g}, statements {d['ledger']:g}")
    if t.get("moved") and t.get("bank"):
        out.append(f"About ₹{abs(t['moved']):,.0f} {'moved to' if t['moved'] > 0 else 'came from'} {t['bank']} "
                   "(estimated from Zerodha's balance; confirmed when the bank statement is added).")
    return out + [f"Not read: {m}" for m in t["missing"]]
