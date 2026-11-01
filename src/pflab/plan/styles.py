"""Paper books of four styles (S74-S75): what a different way of putting the same money to work would have done, forward only.

The scoreboard (plan/twin.py) has four books. These four differ only in WHAT THEY DO WITH THE MONEY, and they get the same rupees on the same days as the others (the deposits and
withdrawals of his broker account). Each starts on the first night it exists, with the value the Nifty 500 book has then; nothing before that is back-filled (a book with no
past is the honest one). They describe; they are never an edge (an edge is a pre-registered test) and nothing here trades or moves money.

    STEADY       waiting cash is put into the Nifty 500 (total return) on the first session of each month (money added mid-month waits for it).
    DIP          the policy `phased_rules` of quant/policies.py as a book: on the first session of a month 60% of the waiting cash goes in and 40% is held back as a reserve, and the
                 reserve goes in when the index is `below_high_pct` below its one-year high (his dip rule if he made one, else 10%) or after 6 months, whichever is first.
    HOLDER       buys once, on the first night, and never sells and never buys again: later money sits in cash, withdrawals come out of cash (never out of the index).
    DIVERSIFIED  portfolio diversification by his own targets (targets.toml): the equity-type buckets in the Nifty 500, gold in the stored gold rate, debt and cash as cash, rebalanced to
                 those weights on the first session of each month. Without targets, or with no gold series, the missing part is held as cash and the book says so.

Cash earns CASH_RATE_PA a year, a session at a time (an assumption, stated); each purchase pays a side cost (the same charge the other books pay). Taxes are not modelled.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Dict, List, Optional

CASH_RATE_PA = 0.06
SESSIONS = 252
STYLES = ("STEADY", "DIP", "HOLDER", "DIVERSIFIED")
BASE_SHARE, RESERVE_SHARE, DEFAULT_TRIGGER, MAX_WAIT_MONTHS = 0.60, 0.40, 10.0, 6
EQUITY_BUCKETS, GOLD_BUCKETS = ("equity", "equity_fund", "reit_invit"), ("gold",)


def _last(con, book: str):
    r = con.execute("SELECT day, value, cash, holdings_json FROM twin_days WHERE book=? ORDER BY day DESC LIMIT 1", [book]).fetchone()
    return (r[0], r[1], r[2], json.loads(r[3])) if r else None


def _save(con, book: str, day: date, value: float, cash: float, fl: float, h: dict) -> None:
    con.execute("INSERT OR REPLACE INTO twin_days VALUES (?,?,?,?,?,?)", [book, day, value, cash, fl, json.dumps(h, sort_keys=True)])


def _weights(targets) -> Dict[str, float]:
    """{'equity', 'gold', 'cash'} shares from his targets (cash gets debt, cash and whatever is not placed); None when no targets are set."""
    if targets is None or not getattr(targets, "buckets", None):
        return {}
    w = {"equity": 0.0, "gold": 0.0, "cash": 0.0}
    for name, b in targets.buckets.items():
        w["equity" if name in EQUITY_BUCKETS else "gold" if name in GOLD_BUCKETS else "cash"] += float(b.target)
    tot = sum(w.values())
    return {k: v / tot for k, v in w.items()} if tot > 0 else {}


def _drawdown(index, day: date, window: int = 365) -> Optional[float]:
    from pflab.plan import envelope
    d = envelope.drawdown(index, day, window)
    return d["below_high_pct"] if d else None


def start(con, day: date, n500_value: float, n500_level: float, gold_rate: Optional[float], targets, only: Optional[List[str]] = None) -> List[str]:
    """Start every style book that does not exist yet, with the money the Nifty 500 book holds today."""
    started = []
    for b in (only or STYLES):
        if _last(con, b) is not None:
            continue
        if b == "DIVERSIFIED":
            w = _weights(targets)
            h = {"units": 0.0, "gold": 0.0, "last": n500_level, "last_gold": gold_rate, "month": f"{day:%Y-%m}", "targets": w, "note": None}
            cash = n500_value
            if w:
                eq, gd = n500_value * w["equity"], (n500_value * w["gold"] if gold_rate else 0.0)
                h["units"], h["gold"], cash = eq / n500_level, (gd / gold_rate if gold_rate else 0.0), n500_value - eq - gd
            else:
                h["note"] = "no targets are set: the whole book is held as cash"
            if w and not gold_rate:
                h["note"] = "no gold rate is stored: the gold part is held as cash"
            _save(con, b, day, n500_value, cash, 0.0, h)
        else:
            _save(con, b, day, n500_value, 0.0, 0.0, {"units": n500_value / n500_level, "last": n500_level, "month": f"{day:%Y-%m}", "reserve": 0.0, "reserve_since": None})
        started.append(b)
    return started


def step(con, day: date, fl: float, n500_level: float, gold_rate: Optional[float], index=None, side_cost: float = 0.0005, targets=None) -> Dict[str, float]:
    """One session for every style book. `fl` is the money that came in (or went out) of his broker account since the last session."""
    from pflab.hq import rules
    amount = None                                                            # the envelope counts his real buys; a paper book invests only its own waiting cash
    dip =next((r for r in rules.active(con) if r["kind"] == "dip_tranche"), None)
    trigger = float(dip["machine"]["below_high_pct"]) if dip else DEFAULT_TRIGGER
    dd = _drawdown(index, day) if index is not None else None
    grow = 1.0 + CASH_RATE_PA / SESSIONS
    month = f"{day:%Y-%m}"
    out = {}
    for b in STYLES:
        last = _last(con, b)
        if last is None:
            continue
        _, _, cash, h = last
        cash = cash * grow + fl
        h = dict(h)
        new_month = month != h.get("month")
        if b == "STEADY" and new_month and cash > 0:
            put = min(cash, amount) if amount is not None else cash
            h["units"] += put * (1 - side_cost) / n500_level
            cash -= put
        elif b == "DIP":
            reserve = float(h.get("reserve", 0.0)) * grow
            if new_month and cash - reserve > 0:
                fresh = cash - reserve
                put_total = min(fresh, amount) if amount is not None else fresh
                base = put_total * BASE_SHARE
                h["units"] += base * (1 - side_cost) / n500_level
                cash -= base
                if reserve <= 0:
                    h["reserve_since"] = str(day)
                reserve += put_total * RESERVE_SHARE
            months = ((day.year - date.fromisoformat(h["reserve_since"]).year) * 12 + day.month - date.fromisoformat(h["reserve_since"]).month) if h.get("reserve_since") else 0
            if reserve > 0 and ((dd is not None and dd >= trigger) or months >= MAX_WAIT_MONTHS):
                h["units"] += reserve * (1 - side_cost) / n500_level
                cash -= reserve
                reserve, h["reserve_since"] = 0.0, None
            h["reserve"] = reserve
        elif b == "HOLDER":
            if cash < 0:
                h["shortfall"] = round(float(h.get("shortfall", 0.0)) - cash, 2)       # a withdrawal larger than the cash: the index is not sold; the shortfall is said
                cash = 0.0
        elif b == "DIVERSIFIED":
            w = h.get("targets") or {}
            gold_units = float(h.get("gold", 0.0))
            if new_month and w:
                total = cash + h["units"] * n500_level + (gold_units * gold_rate if gold_rate else 0.0)
                want_eq, want_gd = total * w["equity"], (total * w["gold"] if gold_rate else 0.0)
                cur_eq, cur_gd = h["units"] * n500_level, (gold_units * gold_rate if gold_rate else 0.0)
                turnover = abs(want_eq - cur_eq) + abs(want_gd - cur_gd)
                h["units"], gold_units = (want_eq - turnover * side_cost / 2) / n500_level, (want_gd / gold_rate if gold_rate else 0.0)
                cash = total - want_eq - want_gd - turnover * side_cost / 2
                h["gold"] = gold_units
        h["last"], h["month"] = n500_level, month
        if gold_rate:
            h["last_gold"] = gold_rate
        value = cash + h["units"] * n500_level + (float(h.get("gold", 0.0)) * (gold_rate or h.get("last_gold") or 0.0))
        _save(con, b, day, value, cash, fl, h)
        out[b] = value
    return out


def gold_on(con, day: date) -> Optional[float]:
    r = con.execute("SELECT rate FROM gold_rates WHERE metal ILIKE 'gold%' AND date <= ? ORDER BY date DESC, session DESC LIMIT 1", [day]).fetchone()
    return float(r[0]) if r else None


def status(con) -> dict:
    """Each style book's value now and since it started (forward only), with the plain note that these describe."""
    out = {}
    for b in STYLES:
        first = con.execute("SELECT day, value FROM twin_days WHERE book=? ORDER BY day LIMIT 1", [b]).fetchone()
        last = _last(con, b)
        if first and last:
            out[b] = {"since": str(first[0]), "start_value": round(first[1], 2), "value": round(last[1], 2), "sessions": con.execute("SELECT count(*) FROM twin_days WHERE book=?", [b]).fetchone()[0] - 1,
                      **({"shortfall": last[3]["shortfall"]} if last[3].get("shortfall") else {}), **({"note": last[3]["note"]} if last[3].get("note") else {})}
    return out
