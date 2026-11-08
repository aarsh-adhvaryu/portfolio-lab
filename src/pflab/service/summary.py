"""The morning and evening summaries (S64 Phase 5 item 1; the investor 2026-10-25: Telegram only when it matters, plus a
morning and an evening summary).

One message, built from code: the portfolio change, the market state, watches near their levels, new suggestions with
their price ranges, the count of open Needs-from-you items, the rows held since the last summary and the brain's latest
note (words only, no number of its own). The held rows it carries are then marked sent. A part that cannot be built is
left out and named in one line; nothing is guessed.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable, List, Optional

from pflab.service import telegram as tgm

KIND = "summary"
NEAR = 0.03                          # a watch within 3% of its level is "near"
HELD_LINES = 12                      # more held rows than this are counted, not listed
NOTE_CHARS = 400


def _previous_session(d: date, cal) -> date:
    d -= timedelta(days=1)
    while not cal.is_trading_day(d):
        d -= timedelta(days=1)
    return d


def _portfolio_line(con, asof: date, cal, networth_fn: Callable) -> Optional[str]:
    now_v = networth_fn(con, asof)["net_worth"]
    before = networth_fn(con, _previous_session(asof, cal))["net_worth"]
    ch = now_v - before
    pct = f" ({ch / before:+.2%})" if before else ""
    return f"Portfolio: Rs {now_v:,.0f}, {ch:+,.0f}{pct} since the previous session (a cash movement counts too)."


def _market_line(asof: date, root) -> Optional[str]:
    from pflab.plan import guards as gd
    cl = gd.market_cluster(asof, root)
    dip = gd.market_dip(asof, root)
    s = f"Market: Nifty 500 is {abs(dip['drawdown']):.1%} below its 1-year high"
    return s + (f"; fall-clustering state {cl['state']} (chance of another -2% session within {cl['horizon']} sessions "
                f"{cl['chance']:.0%}, an estimate)." if cl else ".")


def _watch_lines(con, asof: date) -> List[str]:
    from pflab.pm import prices
    out = []
    for isin, sym, kind, level in con.execute("SELECT isin, symbol, kind, level FROM watches WHERE active ORDER BY watch_id").fetchall():
        q = prices.latest_price(con, isin, asof)
        if q is None or not level:
            continue
        gap = q.value / level - 1
        if (kind == "below" and gap <= NEAR) or (kind == "above" and gap >= -NEAR):
            out.append(f"  {sym or isin}: {q.value:,.2f}, watch {kind} {level:,.2f} ({gap:+.1%})")
    return out


def _suggestion_lines(con, since: datetime) -> List[str]:
    out = []
    for sym, text, lo, hi, mb, amt, wrong in con.execute(
            "SELECT symbol, text, price_low, price_high, max_buy, amount, wrong_if FROM hq_suggestions "
            "WHERE made_at > ? AND NOT shadow ORDER BY sug_id", [since]).fetchall():
        nums = ""
        if lo is not None and hi is not None:
            nums = f" Range {lo:,.0f}-{hi:,.0f}" + (f", highest buy {mb:,.0f}" if mb else "")
            nums += f", about Rs {amt:,.0f}." if amt else "."
            nums += f" Wrong if {wrong}." if wrong else ""
        out.append(f"  {sym or ''}: {text}{nums}")
    return out


def _note(con) -> Optional[str]:
    r = con.execute("SELECT note FROM hq_passes WHERE note IS NOT NULL AND note <> '' AND status='ok' "
                    "ORDER BY pass_id DESC LIMIT 1").fetchone()
    return r[0][:NOTE_CHARS] if r else None


def build(con, asof: date, now: datetime, which: str, cal=None, root=None, networth_fn: Optional[Callable] = None) -> dict:
    """The summary text and the ids of the held rows it carries. `which` is 'morning' or 'evening'."""
    from pflab.conductor import calendar as mcal
    cal = cal or mcal.load()
    if networth_fn is None:
        from pflab.agents.tools import networth as networth_fn
    last = con.execute("SELECT max(created_at) FROM outbox WHERE kind=?", [KIND]).fetchone()[0] or (now - timedelta(days=1))
    lines = [f"{'Good morning' if which == 'morning' else 'Evening'} summary, {asof:%a %d %b}."]
    left_out = []
    try:                                                         # S80: the open storylines come first (a code-written line each), not a model-written report
        from pflab.story import numbers as _sn
        txt = _sn.summary_text(con, asof)
        if txt and not txt.startswith("no open storyline"):
            lines.append("What is driving the market (storylines, with the chance the system gives each):")
            lines += [ln.strip() for ln in txt.strip().splitlines()[:4]]
            lines.append("")
    except Exception:
        pass
    for name, fn in (("portfolio", lambda: _portfolio_line(con, asof, cal, networth_fn)),
                     ("market", lambda: _market_line(asof, root))):
        try:
            line = fn()
        except Exception as e:                                   # a half-built ledger or missing index: say so
            left_out.append(f"{name} ({type(e).__name__})")
            continue
        if line:
            lines.append(line)
    try:
        w = _watch_lines(con, asof)
        if w:
            lines.append("Watches near their levels:")
            lines += w
    except Exception as e:
        left_out.append(f"watches ({type(e).__name__})")
    if root is not None:
        try:
            from pflab.quant import options
            fo = options.line(root, asof)
            if fo:
                lines.append("F&O: " + fo)
        except Exception as e:
            left_out.append(f"F&O ({type(e).__name__})")
    if which == "evening" and root is not None:
        try:
            from pflab.risk import themes
            lines += themes.drift(con, root, asof)
        except Exception as e:
            left_out.append(f"basket drift ({type(e).__name__})")
    s = _suggestion_lines(con, last)
    if s:
        lines.append("New suggestions (numbers from code; you place every order):")
        lines += s
    nq = con.execute("SELECT count(*) FROM questions WHERE status='open'").fetchone()[0]
    if nq:
        lines.append(f"Needs from you: {nq} open (Inbox and files, or Needs from you on the dashboard).")
    held = con.execute("SELECT msg_id, kind, text FROM outbox WHERE status='held' ORDER BY msg_id").fetchall()
    if held:
        lines.append(f"Held since the last summary: {len(held)}.")
        for _mid, kind, text in held[:HELD_LINES]:
            lines.append(f"  [{kind}] {text.splitlines()[0][:160]}")
        if len(held) > HELD_LINES:
            lines.append(f"  and {len(held) - HELD_LINES} more on the dashboard.")
    note = _note(con)
    if note:
        lines.append(f"The brain's latest note: {note}")
    if left_out:
        lines.append("Left out (could not be built): " + ", ".join(left_out) + ".")
    return {"text": "\n".join(lines), "held_ids": [h[0] for h in held]}


def send(con, asof: date, now: datetime, which: str, cal=None, root=None, networth_fn: Optional[Callable] = None) -> dict:
    """Build the summary, queue it (sent at once: kind 'summary' is direct) and mark the held rows it carries as sent.
    One per session and kind: a second call the same day does nothing."""
    key = f"summary:{which}:{asof}"
    if con.execute("SELECT 1 FROM outbox WHERE dedup_key=?", [key]).fetchone():
        return {"sent": False, "why": "already queued today"}
    b = build(con, asof, now, which, cal, root, networth_fn)
    mid = tgm.enqueue(con, b["text"], KIND, dedup_key=key, now=now)
    for hid in b["held_ids"]:
        con.execute("UPDATE outbox SET status='sent', sent_at=? WHERE msg_id=?", [now, hid])
    return {"sent": mid is not None, "msg_id": mid, "held_carried": len(b["held_ids"])}
