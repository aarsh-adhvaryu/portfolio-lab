"""The transfer that funds the US sub-book (S82, A57): rupees leave the rupee book's cash and arrive in the sub-book as dollars. Never new money.

    rupee_cash(con, day)                 the rupee book's cash on `day` (broker plus the fake bank), less what its own open buy orders already claim
    debit_rupee(con, rupee_day, inr, ...) takes `inr` out of the rupee book's cash with an event that says why: in the system's own account two `withdrawal` events of the ledger
                                         (the fake bank first, then the fake broker, ref `us_transfer:...`), in the paper-only mode a `paper_cash` row of kind `us_transfer`
    fund(con, now, us_day, inr, fx, ...)  one transfer: debit the rupee book, credit the sub-book in dollars at the day's rate less the funding markup (an ESTIMATE, `us/costs.py`),
                                         one row in `us_transfers_s82`. The whole book's value falls by the markup and by nothing else.
    convert_seed(con, now, ...)           a store that opened the account before S82 holds its start as a 'seed' cash row from nothing (new money): the same rupees are now debited
                                         from the rupee book on the opening day, no row is changed or lost, and the conversion is recorded once (idempotent)
    rupee_flows(con, lo, hi)             the rupees moved out of the rupee book in (lo, hi]: the rupee book's own record counts them as money out, the whole book does not
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional

from pflab.pm.store import next_id
from pflab.us import book, costs

REF = "us_transfer"
PHASES = ("open", "build", "topup", "converted_seed")


def ensure_table(con) -> None:
    """A store still at the S81 schema (the running app may have opened the account with the old seed before this release) has no `us_transfers_s82` until its migration runs: make the
    table exist (the same DDL as migration 144, `IF NOT EXISTS`), so conversion and funding never fail on schema."""
    from pflab.pm.mig_s79 import m_us82
    for _v, _n, sql in m_us82.MIGRATIONS:
        con.execute(sql)


def _own() -> bool:
    from pflab.ledger import system
    return system.active()


def _balances(con, day: date) -> Dict[str, float]:
    """Cash on `day` in the rupee book: {'broker', 'bank'} (the paper-only mode has the one pot, shown as broker)."""
    from pflab.paper import book as pb
    if _own():
        from pflab.ledger import system
        q = "SELECT coalesce(sum(amount), 0) FROM cash_ledger WHERE account_id = ? AND date <= ?"
        return {"broker": float(con.execute(q, [system.SYSBROKER, day]).fetchone()[0]), "bank": float(con.execute(q, [system.SYSBANK, day]).fetchone()[0])}
    return {"broker": float(pb.cash(con, day)), "bank": 0.0}


def _claimed_by_open_buys(con, day: date) -> float:
    """Rupees the rupee book's own open buy orders will spend at their fill (an amount, or quantity x the last close)."""
    from pflab.paper import book as pb
    tot = 0.0
    for isin, qty, amount in con.execute("SELECT isin, qty, amount FROM paper_orders WHERE status='open' AND side='buy'").fetchall():
        if amount:
            tot += float(amount)
        elif qty:
            px = pb.close_on(con, isin, day)
            tot += float(qty) * (px[1] if px else 0.0)
    return tot


def rupee_cash(con, day: date) -> dict:
    """{'cash', 'bank', 'claimed', 'free'}: the rupee book's cash on `day` and what is free to move (never below zero)."""
    b = _balances(con, day)
    claimed = _claimed_by_open_buys(con, day)
    total = b["broker"] + b["bank"]
    return {"cash": b["broker"], "bank": b["bank"], "claimed": claimed, "free": max(0.0, total - claimed)}


def debit_rupee(con, rupee_day: date, inr: float, ref: str, why: str, now: datetime) -> dict:
    """Take `inr` rupees out of the rupee book's cash on `rupee_day`. Raises ValueError when the cash is not there (nothing is written then)."""
    inr = round(float(inr), 2)
    if inr <= 0:
        raise ValueError("a transfer needs a positive amount of rupees")
    b = _balances(con, rupee_day)
    if inr > b["broker"] + b["bank"] + 0.005:
        raise ValueError(f"the rupee book holds Rs {b['broker'] + b['bank']:,.2f} in cash on {rupee_day}; Rs {inr:,.2f} cannot be moved")
    if _own():
        from pflab.ledger import events as ev, system
        from_bank = round(min(inr, max(0.0, b["bank"])), 2)
        from_broker = round(inr - from_bank, 2)
        evs = []
        if from_bank > 0:
            evs.append(ev.Event(kind="withdrawal", account_id=system.SYSBANK, date=rupee_day, amount=from_bank, ref=f"{ref}: {why}"[:160]))
        if from_broker > 0:
            evs.append(ev.Event(kind="withdrawal", account_id=system.SYSBROKER, date=rupee_day, amount=from_broker, ref=f"{ref}: {why}"[:160]))
        system.append(con, evs, now)
        return {"mode": "ledger", "from_bank": from_bank, "from_broker": from_broker}
    con.execute("INSERT INTO paper_cash VALUES (?,?,?,?,?,?)", [next_id(con, "paper_cash", "entry_id"), rupee_day, -inr, "us_transfer", f"{ref}: {why}"[:160], now])
    return {"mode": "paper_cash", "from_bank": 0.0, "from_broker": inr}


def transfers(con) -> List[dict]:
    ensure_table(con)
    cols = ("transfer_id", "us_day", "rupee_day", "inr", "fx_rate", "fx_source", "markup", "usd", "markup_inr", "phase", "rupee_ref", "share_after", "reason")
    return [dict(zip(cols, r)) for r in con.execute(f"SELECT {', '.join(cols)} FROM us_transfers_s82 ORDER BY transfer_id").fetchall()]


def transfers_on(con, rupee_day: date) -> List[dict]:
    return [t for t in transfers(con) if t["rupee_day"] == rupee_day]


def rupee_flows(con, lo: Optional[date], hi: date) -> float:
    """The rupees moved out of the rupee book to the sub-book with a rupee date in (lo, hi], as a NEGATIVE flow (money out), for `paper_days.flows`."""
    try:
        q = "SELECT coalesce(sum(inr), 0) FROM us_transfers_s82 WHERE rupee_day <= ?" + (" AND rupee_day > ?" if lo is not None else "")
        r = con.execute(q, [hi] + ([lo] if lo is not None else [])).fetchone()
        return -float(r[0] or 0.0)
    except Exception:                                   # an old store without the table: nothing moved
        return 0.0


def month_moved(con, day: date) -> float:
    ensure_table(con)
    r = con.execute("SELECT coalesce(sum(inr), 0) FROM us_transfers_s82 WHERE rupee_day >= ? AND rupee_day <= ?", [date(day.year, day.month, 1), day]).fetchone()
    return float(r[0] or 0.0)


def fund(con, now: datetime, us_day: date, inr: float, fx: dict, phase: str, reason: str, rupee_day: Optional[date] = None, share_after: Optional[float] = None,
         rupee_ref: Optional[str] = None, credit_cash: bool = True) -> dict:
    """One transfer. `fx` is `usfx.rate_for(...)` (its source is stored). The rupee book is debited first (this raises if its cash is not there); the sub-book is credited
    `inr / (rate x (1 + markup))` dollars on `us_day`, so the whole book loses the funding markup and nothing else."""
    if phase not in PHASES:
        raise ValueError(f"phase is one of {PHASES}")
    ensure_table(con)
    rupee_day = rupee_day or now.date()
    markup = costs.fx_markup_funding()
    tid = next_id(con, "us_transfers_s82", "transfer_id")
    ref = rupee_ref or f"{REF}:{tid}"
    usd = float(inr) / (float(fx["rate"]) * (1.0 + markup))
    why = f"{inr:,.2f} rupees moved to the US paper sub-book ({phase}); {reason}"
    deb = debit_rupee(con, rupee_day, inr, ref, why, now)
    if credit_cash:
        book.add_cash(con, now, us_day, usd, "transfer", f"{ref}: {inr:,.2f} rupees at {fx['rate']:.4f} ({fx.get('label', fx['source'])}), markup {markup:.2%} ({costs.label()})")
    con.execute("INSERT INTO us_transfers_s82 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [tid, us_day, rupee_day, round(float(inr), 2), float(fx["rate"]), fx["source"], markup, usd, float(inr) - usd * float(fx["rate"]), phase, ref, share_after, reason[:400], now])
    return {"transfer_id": tid, "inr": round(float(inr), 2), "usd": usd, "fx_rate": float(fx["rate"]), "fx_source": fx["source"], "markup": markup, "markup_inr": float(inr) - usd * float(fx["rate"]),
            "rupee_day": str(rupee_day), "phase": phase, "ref": ref, "debited": deb}


def _fix_marked_days(con, rupee_day: date, inr: float) -> bool:
    """A debit dated on or before the rupee book's last marked day changes those days' value and cash, and is outside money on the first of them (the rupee book's return is not hurt)."""
    last = con.execute("SELECT max(day) FROM paper_days").fetchone()[0]
    if last is None or rupee_day > last:
        return False
    first = con.execute("SELECT min(day) FROM paper_days WHERE day >= ?", [rupee_day]).fetchone()[0]
    if first is None:
        return False
    con.execute("UPDATE paper_days SET value = value - ?, cash = cash - ? WHERE day >= ?", [inr, inr, rupee_day])
    con.execute("UPDATE paper_days SET flows = flows - ? WHERE day = ?", [inr, first])
    return True


def convert_seed(con, now: datetime, root=None) -> List[dict]:
    """Safeguard for a store that opened the account at the 5% seed before S82 (new money from nothing). For each 'seed' cash row with no transfer recorded for it: debit the rupee
    book's cash by the seed's rupees (the dollars x the start rate x (1 + markup) = `start_inr`) on the opening day, with an event that says why; if the rupee cash was not there
    that day, on the first day it was, else today. No row of the sub-book is changed or removed. Idempotent: the conversion is recorded by `rupee_ref = seed_entry:<id>`."""
    acct = book.account(con)
    if acct is None:
        return []
    ensure_table(con)
    out = []
    seeds = con.execute("SELECT entry_id, day, usd FROM us_cash_s81 WHERE kind='seed' ORDER BY entry_id").fetchall()
    for entry_id, day, usd in seeds:
        ref = f"seed_entry:{entry_id}"
        if con.execute("SELECT 1 FROM us_transfers_s82 WHERE rupee_ref=?", [ref]).fetchone():
            continue
        markup = costs.fx_markup_funding()
        inr = float(usd) * float(acct["start_fx"]) * (1.0 + markup)
        opened = acct["opened_on"]
        why = (f"the account was opened before S82 with {usd:,.2f} dollars from nothing; those dollars are now paid for out of the rupee book's cash "
               f"({inr:,.2f} rupees = {usd:,.2f} x {acct['start_fx']:.4f} x (1 + {markup:.2%}), the start rate {acct['fx_source']})")
        placed = None
        for d in (opened, now.date()):
            try:
                debit_rupee(con, d, inr, ref, why, now)
                placed = d
                break
            except ValueError:
                continue
        if placed is None:
            out.append({"entry_id": entry_id, "converted": False, "why": "the rupee book's cash cannot pay for the seed yet; tried again at the next run"})
            continue
        tid = next_id(con, "us_transfers_s82", "transfer_id")
        fixed = _fix_marked_days(con, placed, inr)
        con.execute("INSERT INTO us_transfers_s82 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [tid, day, placed, round(inr, 2), float(acct["start_fx"]), acct["fx_source"], markup, float(usd), inr - float(usd) * float(acct["start_fx"]), "converted_seed", ref, None,
                     (why + ("; the rupee book's marked days from then on were restated" if fixed else ""))[:400], now])
        out.append({"entry_id": entry_id, "converted": True, "inr": round(inr, 2), "rupee_day": str(placed), "marked_days_restated": fixed})
    return out
