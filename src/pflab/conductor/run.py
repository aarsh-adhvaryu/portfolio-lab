"""One conductor pass (S53), run as the service's `conductor` job every 15 minutes, after the other jobs of the tick.

    1. mode        the market's mode now (closed, pre-open, market, after close)
    2. sync        what is in step, what the jobs are filling, what only the investor can provide
    3. asks        a question (and one message) per new ask; asks that resolved themselves are dropped
    4. notes       on the first start or after being off: what happened and what it is doing about it;
                   before a closed stretch: when to switch on again so the next session is prepared
    5. fact sheet  reports/situation.json and .md
Messages go through the outbox (the tick delivers them); each has a dedup key, so a pass repeated in the same
situation sends nothing new.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, List, Optional

from pflab.agents import questions
from pflab.conductor import calendar as cl
from pflab.conductor import situation as st
from pflab.conductor import sync
from pflab.service import telegram as tgm
from pflab.service.jobs import Ctx

AGENT = "conductor"


def _queue(ctx: Ctx, text: str, kind: str, key: str) -> bool:
    return tgm.enqueue(ctx.con, text, kind, dedup_key=key, now=ctx.now) is not None


def sync_asks(ctx: Ctx, findings: List[sync.Finding]) -> dict:
    """Open a question per new ask (and message it); drop the conductor's open questions that no longer apply."""
    want = {f.ask_key: f for f in sync.asks(findings)}
    opened = []
    for key, f in want.items():
        qid = questions.ask(ctx.con, AGENT, key, f.ask_text, now=ctx.now)
        if qid is not None:
            opened.append(qid)
            _queue(ctx, f"I need something from you (question #{qid}):\n{f.ask_text}\n"
                        "No need to reply: I notice by myself when it is done and close the question.",
                   "request", f"ask:{key}")
    dropped = 0
    for (key,) in ctx.con.execute("SELECT subject_key FROM questions WHERE status='open' AND agent=?", [AGENT]).fetchall():
        if key not in want and questions.drop(ctx.con, key, now=ctx.now):
            dropped += 1
    return {"opened": opened, "dropped": dropped}


def wake_note(ctx: Ctx, gap: Optional[timedelta], last: Optional[datetime], findings: List[sync.Finding]) -> Optional[str]:
    """First start, or back after more than a day and a half: what is behind and who fills it."""
    if gap is not None and gap <= sync.OFFLINE_AFTER:
        return None
    auto = [f for f in findings if f.status == "auto"]
    need = sync.asks(findings)
    warn = [f for f in findings if f.status == "warn"]
    head = ("First start: I have checked the data, the ledger and the service." if last is None else
            f"Back after {gap.days} day(s) {gap.seconds // 3600} h off (last pass {last:%a %d %b %H:%M}).")
    lines = [head]
    if auto:
        lines += ["Catching up by myself:"] + [f"- {f.name.removeprefix('data:')}: {f.detail}" for f in auto]
    else:
        lines.append("Everything I collect by myself is in step.")
    if need:
        lines += ["Needed from you (each sent as its own question):"] + [f"- {f.name}: {f.detail}" for f in need]
    if warn:
        lines += ["Worth a look:"] + [f"- {f.name}: {f.detail}" for f in warn]
    return "\n".join(lines)


def closing_note(ctx: Ctx, cal: cl.Calendar) -> Optional[str]:
    """On a trading day, after the evening jobs, when the market is shut tomorrow: when to switch on again."""
    d = ctx.now.date()
    if not cal.is_trading_day(d) or ctx.now.time() < cl.EVENING_READY:
        return None
    shut = cal.closed_after(d)
    if not shut:
        return None
    nxt = cal.next_trading_day(d)
    on = datetime.combine(nxt - timedelta(days=1), cl.SWITCH_ON_AT)
    special = [f"{x:%a %d %b}: {cal.special[x]}" for x in shut if x in cal.special]
    text = (f"Markets are shut {cl.describe_closed(cal, shut)}; the next session is {nxt:%a %d %b}.\n"
            f"Today's data and checks are done; you can switch me off. Switch me on by {on:%a %d %b %H:%M} so I can "
            f"collect the news and filings from the break and have {nxt:%a}'s picture ready before the open.")
    if special:
        text += "\nSpecial session: " + "; ".join(special) + " (hours as NSE announces them)."
    return text


def conduct(ctx: Ctx, cal: Optional[cl.Calendar] = None, networth_fn: Optional[Callable] = None) -> dict:
    cal = cal or cl.load()
    last = sync.last_pass(ctx.con, ctx.now)
    gap = None if last is None else ctx.now - last
    findings = sync.check(ctx, cal)
    asks = sync_asks(ctx, findings)
    sent = []
    w = wake_note(ctx, gap, last, findings)
    if w and _queue(ctx, w, "conductor", f"wake:{last:%Y-%m-%dT%H:%M}" if last else "wake:first"):
        sent.append("wake")
    c = closing_note(ctx, cal)
    if c and _queue(ctx, c, "conductor", f"closing:{ctx.now.date()}"):
        sent.append("closing")
    if networth_fn is None:
        from pflab.agents.tools import networth as networth_fn
    sheet = st.build(ctx.con, ctx.now, cal, findings, networth_fn)
    st.write(sheet, ctx.pm_dir / "reports", ctx.now)
    count = {k: sum(f.status == k for f in findings) for k in ("ok", "auto", "ask", "warn")}
    return {"mode": cal.mode(ctx.now), "offline_hours": None if gap is None else round(gap.total_seconds() / 3600, 1),
            **count, "asked": asks["opened"], "dropped": asks["dropped"], "sent": sent}
