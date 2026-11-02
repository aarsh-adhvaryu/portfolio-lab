"""The paper portfolio's cadence (S77, A37; his word 2026-11-02: "the last thing we need is a system sitting idle and doing nothing. If it decides not to act, that is fine").

Every loop leaves an ACT, even "looked, nothing needed", so idleness is a fact the system can see: a loop silent past its interval is an alert. The loops:

    live_watch    market hours, every HQ round (30 s with the dashboard open, 15 min through the live job): the holdings against the live quote; a move or a rail breach is a
                  reason for the team to look
    daily_look    every evening, weekends and holidays too (code, free): the day's change, the drawdown, the rails, the circuit breaker, what matured, what is waiting
    postmortem    after every scoring: what each kind of decision claimed against what happened (code), kept as LESSONS every paper mission reads
    weekly_review the team's full review (opened by manager.tick)

Circuit breaker (code, no model): while the account is 12% or more below its own high, no new BUY or ADD is accepted; selling, holding and waiting stay open; it lifts by itself on recovery.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

BREAKER_DRAWDOWN = 0.12
LESSON_MIN_N = 5
LOOP_MAX_SILENCE = {"daily_look": timedelta(hours=30), "postmortem": timedelta(days=8), "weekly_review": timedelta(days=9), "live_watch": timedelta(minutes=45)}


def act(con, now: datetime, loop: str, what: str, useful: bool = True, detail: Optional[dict] = None) -> int:
    from pflab.pm.store import next_id
    aid = next_id(con, "paper_acts", "act_id")
    con.execute("INSERT INTO paper_acts VALUES (?,?,?,?,?,?)", [aid, now, loop, what[:400], bool(useful), json.dumps(detail or {}, default=str)[:2000]])
    return aid


def last_acts(con) -> List[dict]:
    return [{"loop": r[0], "at": str(r[1])[:16], "what": r[2], "useful": bool(r[3])} for r in con.execute(
        "SELECT loop, logged_at, what, useful FROM paper_acts WHERE act_id IN (SELECT max(act_id) FROM paper_acts GROUP BY loop) ORDER BY loop").fetchall()]


def acted_since(con, loop: str, since: datetime) -> bool:
    return bool(con.execute("SELECT 1 FROM paper_acts WHERE loop=? AND logged_at >= ? LIMIT 1", [loop, since]).fetchone())


def silent_loops(con, now: datetime) -> List[str]:
    """Loops that should have acted by now and have not. The live watch counts only inside market hours; no loop is expected before the portfolio has started."""
    from pflab.paper import book
    if not book.started(con):
        return []
    out = []
    for loop, limit in LOOP_MAX_SILENCE.items():
        if loop == "live_watch" and not book.session_open(now):
            continue
        r = con.execute("SELECT max(logged_at) FROM paper_acts WHERE loop=?", [loop]).fetchone()[0]
        started = datetime.combine(book.started(con), datetime.min.time())
        ref = r or started
        if now - ref > limit and now - started > limit:
            out.append(f"{loop}: nothing since {str(ref)[:16]} (it should act at least every {limit})")
    return out


# --- the circuit breaker ----------------------------------------------------------------------------------------------------------

def level_path(con) -> List[tuple]:
    """(day, level) of the account with outside money taken out (a top-up is not a gain): 1.0 at the start."""
    rows = con.execute("SELECT day, value, flows FROM paper_days ORDER BY day").fetchall()
    out, g = [], 1.0
    for i, (d, v, f) in enumerate(rows):
        if i:
            v0 = rows[i - 1][1]
            g *= (v - f) / v0 if v0 > 0 else 1.0
        out.append((d, g))
    return out


def breaker(con) -> dict:
    path = level_path(con)
    if len(path) < 2:
        return {"on": False, "drawdown": 0.0}
    peak = max(g for _, g in path)
    dd = path[-1][1] / peak - 1
    return {"on": dd <= -BREAKER_DRAWDOWN, "drawdown": round(dd, 4), "limit": -BREAKER_DRAWDOWN}


# --- lessons ------------------------------------------------------------------------------------------------------------------------

def postmortem(con, now: datetime) -> dict:
    """What each kind of decision claimed against what happened, by code. A lesson says the count first; from LESSON_MIN_N claims it says the rate; the reviewer's own record
    (what it refused, and how that went) is a lesson too. Returns how many lessons were written or changed."""
    from pflab.hq import scorecard
    from pflab.pm.store import next_id
    made = 0

    def put(key: str, kind: str, text: str, n: int, ev: dict) -> None:
        nonlocal made
        old = con.execute("SELECT text, n FROM paper_lessons WHERE key=?", [key]).fetchone()
        if old and old[0] == text:
            return
        con.execute("DELETE FROM paper_lessons WHERE key=?", [key])
        con.execute("INSERT INTO paper_lessons VALUES (?,?,?,?,?,?,?)", [next_id(con, "paper_lessons", "lesson_id"), now, kind, text, n, key, json.dumps(ev)])
        made += 1

    for action, state, status, good, bad in con.execute(
            "SELECT c.action, coalesce(c.state, 'unknown'), d.status, count(*) FILTER (WHERE c.outcome='good'), count(*) FILTER (WHERE c.outcome='bad') FROM paper_claims c "
            "JOIN paper_decisions d ON d.decision_id = c.decision_id WHERE c.outcome IN ('good','bad') GROUP BY 1, 2, 3 ORDER BY 1, 2, 3").fetchall():
        n = int(good + bad)
        if n < 1:
            continue
        who = "the review refused" if status == "not_approved" else "it executed"
        base = f"{action} decisions in a {state.replace('_', ' ')} market ({who}): {int(good)} of {n} claims held"
        if n >= LESSON_MIN_N:
            sk = scorecard.skeptical(int(good), int(bad))
            base += f" ({int(good) / n:.0%}; probably at least {sk:.0%})" if sk is not None else f" ({int(good) / n:.0%})"
        else:
            base += f". Only {n} scored: a count, not a conclusion."
        put(f"claims:{action}:{state}:{status}", "claims", base, n, {"good": int(good), "bad": int(bad)})
    ex = con.execute("SELECT count(*) FILTER (WHERE d.status='executed' AND c.outcome='good'), count(*) FILTER (WHERE d.status='executed' AND c.outcome='bad'), "
                     "count(*) FILTER (WHERE d.status='not_approved' AND c.outcome='good'), count(*) FILTER (WHERE d.status='not_approved' AND c.outcome='bad') "
                     "FROM paper_claims c JOIN paper_decisions d ON d.decision_id = c.decision_id").fetchone()
    eg, eb, rg, rb = (int(x or 0) for x in ex)
    if rg + rb >= 1:
        put("reviewer", "reviewer", f"The independent review refused decisions whose claims then held {rg} of {rg + rb} times; the decisions it let through held {eg} of {eg + eb} times. "
                                    + ("A refusal that was right more often than not is the review doing its job." if rb > rg else
                                       "If refused decisions keep holding more often than the executed ones, the review may be too strict."), rg + rb, {"refused_good": rg, "refused_bad": rb})
    return {"lessons_changed": made}


def lessons(con, limit: int = 8) -> List[dict]:
    return [{"kind": r[0], "text": r[1], "n": r[2]} for r in con.execute("SELECT kind, text, n FROM paper_lessons ORDER BY n DESC, lesson_id DESC LIMIT ?", [limit]).fetchall()]


def lessons_text(con) -> str:
    ls = lessons(con)
    return ("WHAT ITS OWN RECORD HAS TAUGHT IT (by code; use it, and say when you go against it): " + " | ".join(l["text"] for l in ls)) if ls else ""


# --- the daily look -----------------------------------------------------------------------------------------------------------------

def daily_look(con, now: datetime) -> dict:
    """Every evening, every day (code, free): where the account stands and whether anything needs the team. Always leaves an act; 'nothing needs action' is a result, not idleness."""
    from pflab.paper import book, manager, rails
    day = (con.execute("SELECT max(day) FROM paper_days").fetchone() or [None])[0]
    if day is None:
        return {"waiting": "not started"}
    h = book.holdings(con, day)
    prev = con.execute("SELECT value, flows FROM paper_days WHERE day < ? ORDER BY day DESC LIMIT 1", [day]).fetchone()
    cur = con.execute("SELECT value, flows FROM paper_days WHERE day = ?", [day]).fetchone()
    chg = ((cur[0] - cur[1]) / prev[0] - 1) if prev and prev[0] and cur else None
    br = breaker(con)
    flags = rails.flags(con, day)
    why = manager.reasons_to_look(con, now)
    open_orders = con.execute("SELECT count(*) FROM paper_orders WHERE status='open'").fetchone()[0]
    waiting = con.execute("SELECT count(*) FROM paper_decisions WHERE status='proposed'").fetchone()[0]
    bits = [f"value Rs {h['value']:,.0f} as of {day}" + (f" ({chg:+.2%} on the day)" if chg is not None else ""),
            f"drawdown {br['drawdown']:.1%}" + (" (circuit breaker ON: no new buying)" if br["on"] else ""),
            f"{len(flags)} rail flag(s)", f"{open_orders} open order(s), {waiting} decision(s) awaiting the review"]
    if why:
        bits.append("reasons for the team to look: " + "; ".join(why)[:200])
    else:
        bits.append("nothing needs the team today (a decision to do nothing, with these facts)")
    what = "daily look: " + "; ".join(bits)
    act(con, now, "daily_look", what, True, {"reasons": why, "flags": flags, "breaker": br})
    return {"look": what, "reasons": why}


def run(rt) -> dict:
    """The nightly entry (job `paper_daily`, every day): the postmortem, the daily look, and an alert when a loop has gone silent."""
    from pflab.paper import book
    con, now = rt.cursor(), rt.clock()
    if not book.started(con):
        return {"waiting": "the paper portfolio has not started"}
    out = {"postmortem": postmortem(con, now)}
    act(con, now, "postmortem", f"postmortem: {out['postmortem']['lessons_changed']} lesson(s) written or changed", True)
    out.update(daily_look(con, now))
    silent = silent_loops(con, now)
    if silent:
        out["silent"] = silent
        try:
            from pflab.app import assistant
            assistant.notify(con, now, "A loop of the paper portfolio has gone quiet: " + "; ".join(silent)[:300], f"silent:{now:%Y%m%d}")
        except Exception:
            pass
    return out
