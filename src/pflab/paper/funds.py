"""The system's fake bank and its broker cash (S77; his answer 2026-11-02: Rs 5,00,000 to start, top-ups up to Rs 50,000 a month by him or by the system).

The bank (`SYSBANK`) feeds the broker (`SYSBROKER`) the way his Zerodha funds are fed from his bank. A top-up is a `deposit` to the bank with the ref `topup:<who>`; the month's
top-ups together never pass `topup_month_max` (system_account.toml). Every move is a ledger event, so it is logged with who made it and shows in the returns as outside money.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pflab.ledger import events as ev, system


def bank_cash(con) -> float:
    return float(con.execute("SELECT coalesce(sum(amount), 0) FROM cash_ledger WHERE account_id = ?", [system.SYSBANK]).fetchone()[0])


def broker_cash(con) -> float:
    return float(con.execute("SELECT coalesce(sum(amount), 0) FROM cash_ledger WHERE account_id = ?", [system.SYSBROKER]).fetchone()[0])


def topped_up_this_month(con, day: date) -> float:
    return float(con.execute("SELECT coalesce(sum(amount), 0) FROM events WHERE kind='deposit' AND account_id = ? AND ref LIKE 'topup:%' AND trade_date >= ? AND trade_date <= ?",
                             [system.SYSBANK, date(day.year, day.month, 1), day]).fetchone()[0])


def room_this_month(con, day: date) -> float:
    return max(0.0, float(system.settings().get("topup_month_max", system.TOPUP_MONTH_MAX)) - topped_up_this_month(con, day))


def topup(con, amount: float, by: str, day: date, now: datetime) -> dict:
    """Add money to the fake bank, within the month's maximum. Returns what was added (never more than the room), or why not."""
    amount = float(amount)
    if amount <= 0:
        return {"added": 0.0, "why": "an amount above zero"}
    room = room_this_month(con, day)
    if room <= 0:
        return {"added": 0.0, "why": f"this month's top-ups have reached Rs {system.settings().get('topup_month_max', system.TOPUP_MONTH_MAX):,.0f}"}
    add = min(amount, room)
    system.append(con, [ev.Event(kind="deposit", account_id=system.SYSBANK, date=day, amount=round(add, 2), ref=f"topup:{by}")], now)
    return {"added": round(add, 2), "by": by, "room_left": round(room - add, 2), "cut": add < amount}


def to_broker(con, amount: float, day: date, now: datetime, why: str = "") -> float:
    """Move up to `amount` from the bank to the broker (what the bank holds). Returns what moved."""
    move = round(min(float(amount), bank_cash(con)), 2)
    if move <= 0:
        return 0.0
    system.append(con, [ev.Event(kind="cash_transfer", account_id=system.SYSBANK, date=day, amount=move, counter_account=system.SYSBROKER, ref=f"to broker: {why}"[:120])], now)
    return move


def ensure(con, need: float, day: date, now: datetime) -> float:
    """Make the broker hold `need` rupees for a buy: first from the bank, then (the system's own top-up, inside the month's maximum) from new money. Returns the broker's cash."""
    short = need - broker_cash(con)
    if short > 1e-6:
        short -= to_broker(con, short, day, now, "cash for a buy")
    if short > 1e-6 and room_this_month(con, day) > 0:
        got = topup(con, short, "the system", day, now)
        if got["added"]:
            to_broker(con, got["added"], day, now, "cash for a buy")
    return broker_cash(con)
