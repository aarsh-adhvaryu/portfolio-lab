"""S84 wire: the thinking loop's entry points for the loops that already run (T1/T7). New logic lives here; the loops carry only a few lines that call it.

    session_tick(con, now, quotes, root)        the session loop's tick (mode `session`: cheap, held names on live quotes; no follow-up)
    sweep(con, now, root, only_market=None)     the close (`close`, India), the US morning (`us_morning`) and the catch-up (`catchup`, one pass per missed session, oldest first,
                                                point-in-time at that session's close); then the new cases are thought through up to the daily cap; then the follow-up (T7)
    today_block(con, day) / report_lines(con, day)   the text blocks Today and the 15:45 report carry (the thinking block, the reserve, the knowledge line, the desk plan, the scorecard)

Every step is inside a try: a failure is a visible "thinking failed: <reason>" line (the paper act log and the session log, so the 15:45 report shows it) and never stops the close, the session
loop or the catch-up. The kill switch (`core.killed()` / `think.on()`) stops all of it. A session is watched once per (market, day): the marker is a row in `paper_acts` (loop `think_loop`),
written only when the watch succeeded, so a failed one is tried again. The paid parts (the gateway, the workshop guard, his monthly cap) refuse by raising; a refusal is "thinking paused",
the case stays open and is tried again at the next close, and thesis-break sales go on through the exit manager, which this module never touches.
"""
from __future__ import annotations

import importlib
import re
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional

LOOP = "think_loop"
MAX_SWEEP_SESSIONS = 10          # a gap longer than this is caught up for its last 10 sessions (older ones are past any look a case could still need)
SETTLE = {"US": 30}              # minutes after the close before a market's daily bar is final (IN: none)


# --- small helpers ------------------------------------------------------------------------------------------------------------------------------------------------------------

def _mod(name: str):
    """A think module, or ImportError (the caller says "not installed" only when this very module is missing)."""
    return importlib.import_module(f"pflab.think.{name}")


def _missing(e: BaseException, name: str) -> bool:
    return isinstance(e, ImportError) and getattr(e, "name", None) == f"pflab.think.{name}"


def _active() -> bool:
    from pflab import core, think
    return think.on() and not core.killed()


def _data_through(con, root, market: str):
    from pflab.service import catchup
    return catchup.data_through(con, root, market)


def _market_on(market: str) -> bool:
    if market == "US":
        try:
            from pflab import us
            return bool(us.on())
        except Exception:
            return False
    return True


def _asof(market: str, day: date) -> datetime:
    """The moment a session is "known": its close plus the settle time, as naive IST (point-in-time for a catch-up pass)."""
    from pflab import markets
    w = markets.get(market).window_ist(day)
    base = w[1] if w else datetime.combine(day, datetime.min.time()) + timedelta(hours=16)
    return base + timedelta(minutes=SETTLE.get(market, 0))


def _closed(market: str, now: datetime) -> date:
    from pflab import markets
    return markets.get(market).session_closed_by(now - timedelta(minutes=SETTLE.get(market, 0)))


# --- markers and the visible failure line ----------------------------------------------------------------------------------------------------------------------------------

def _marked(con, market: str, day: date) -> bool:
    return bool(con.execute("SELECT 1 FROM paper_acts WHERE loop=? AND what LIKE ? LIMIT 1", [LOOP, f"watch {market} {day} %"]).fetchone())


def _mark(con, now: datetime, market: str, day: date, mode: str, res: dict) -> None:
    from pflab.paper import cadence
    n = len(res.get("signals") or []) if isinstance(res, dict) else 0
    o = len(res.get("cases_opened") or []) if isinstance(res, dict) else 0
    cadence.act(con, now, LOOP, f"watch {market} {day} {mode}: {n} signal(s), {o} case(s) opened", True, {"market": market, "day": str(day), "mode": mode})


def _last_marked(con, market: str) -> Optional[date]:
    best = None
    for (w,) in con.execute("SELECT what FROM paper_acts WHERE loop=? AND what LIKE ?", [LOOP, f"watch {market} %"]).fetchall():
        try:
            d = date.fromisoformat(w.split()[2])
        except Exception:
            continue
        best = d if best is None or d > best else best
    return best


def _refusal(e: BaseException) -> bool:
    """The guard (workshop, no paid call) or the cap said no: not a bug, and the next case would be refused too."""
    return type(e).__name__ in ("OutwardBlocked", "CapReached", "BudgetExceeded", "NoRoom") or bool(re.search(r"(^|[^a-z])cap([^a-z]|$)|budget", str(e)[:80], re.I))


def _fail(con, now: datetime, where: str, e: BaseException) -> str:
    """The visible line. A refusal by the guard or the cap is "paused", anything else "failed". Said once a day per reason (the session loop ticks every 5 minutes)."""
    from pflab.core import session
    from pflab.paper import cadence
    reason = f"{type(e).__name__}: {str(e)[:180]}"
    paused = _refusal(e)
    line = (f"thinking paused: {where}: {reason}" if paused else f"thinking failed: {where}: {reason}")
    try:
        if session.said(con, now, f"thinkfail:{where}:{type(e).__name__}"):
            session.log(con, now, "degrade", line)
            cadence.act(con, now, LOOP, line, False)
    except Exception:
        pass
    return line


# --- thinking the new cases through -------------------------------------------------------------------------------------------------------------------------------------------

def _unthought(con, limit: int) -> List[int]:
    """Open cases nothing has been thought about yet (a thinking pass that failed or hit the cap left them), the largest first."""
    from pflab.think import cases
    out = []
    for c in cases.open_cases(con):
        if c["state"] == "open" and not cases.steps(con, c["case_id"]):
            out.append(c["case_id"])
    return out[:limit]


def _think(con, now: datetime, ids: List[int], root, out: dict) -> None:
    """Think the cases through, at most `max_cases_per_day` in one pass. A refusal by the guard or the cap ends the pass (the cases stay open); another failure goes on to the next case."""
    from pflab import think
    try:
        ts = _mod("session")
    except ImportError as e:
        if not _missing(e, "session"):
            out["failed"].append(_fail(con, now, "think", e))
        return
    cap = int(think.settings()["max_cases_per_day"])
    for cid in list(dict.fromkeys(ids))[:cap]:
        try:
            r = ts.think_case(con, now, cid, root=root)
            out["thought"].append(cid)
            if isinstance(r, dict) and (r.get("failed") or r.get("error")):
                out["failed"].append(_fail(con, now, f"case #{cid}", RuntimeError(str(r.get("failed") or r.get("error")))))
        except Exception as e:
            out["failed"].append(_fail(con, now, f"case #{cid}", e))
            if _refusal(e):
                break


def _follow(con, now: datetime, day: date, out: dict) -> None:
    try:
        tsn = _mod("session")
    except ImportError as e:
        if not _missing(e, "session"):
            out["failed"].append(_fail(con, now, "follow-up", e))
        return
    try:
        out["follow_up"] = tsn.follow_up(con, now, day)
    except Exception as e:
        out["failed"].append(_fail(con, now, "follow-up", e))


# --- the entry points -------------------------------------------------------------------------------------------------------------------------------------------------------------

def session_tick(con, now: datetime, quotes: Optional[dict], root=None) -> dict:
    """The session loop's tick: the watch on live quotes (mode `session`), then the cases it opened are thought through. No quotes, nothing to watch. Never raises."""
    out: dict = {"mode": "session", "thought": [], "failed": []}
    try:
        if not _active():
            return {"off": True}
        if not quotes:
            return {"skipped": "no live quotes"}
        try:
            w = _mod("watch")
        except ImportError as e:
            return {"skipped": "the watch is not installed"} if _missing(e, "watch") else {"failed": [_fail(con, now, "watch", e)]}
        try:
            res = w.run(con, now, mode="session", quotes=quotes, root=root) or {}
        except Exception as e:
            out["failed"].append(_fail(con, now, "watch (session)", e))
            return out
        out["signals"] = len(res.get("signals") or [])
        out["cases_opened"] = list(res.get("cases_opened") or [])
        _think(con, now, out["cases_opened"], root, out)
    except Exception as e:                                              # the last net: the session loop never sees an exception from here
        out["failed"].append(_fail(con, now, "session tick", e))
    return out


def pending_sessions(con, now: datetime, market: str, root=None) -> List[date]:
    """Sessions of `market` not yet watched, oldest first: those after the last watched one up to the latest whose closes are in the store (the very first time: only the latest)."""
    from pflab import markets
    m = markets.get(market)
    have = _data_through(con, root, market)
    if have is None:
        return []
    upto = min(_closed(market, now), have)
    last = _last_marked(con, market)
    days = [upto] if last is None else m.sessions_between(last + timedelta(days=1), upto)[-MAX_SWEEP_SESSIONS:]
    return [d for d in days if d <= upto and not _marked(con, market, d)]


def sweep(con, now: datetime, root=None, *, only_market: Optional[str] = None, think_cases: bool = True, follow: bool = True) -> dict:
    """The close (India), the US morning and the catch-up in one: every unwatched session since the last one is watched in order (all but the newest as `catchup`, at its own close, point-in-time;
    the newest as `close` or `us_morning`), then the cases opened (and the ones an earlier pass left unthought) are thought through up to the daily cap, then the follow-up runs once. Never raises."""
    out: dict = {"sessions": {}, "thought": [], "failed": []}
    try:
        if not _active():
            return {"off": True}
        try:
            w = _mod("watch")
        except ImportError as e:
            return {"skipped": "the watch is not installed"} if _missing(e, "watch") else {"failed": [_fail(con, now, "watch", e)]}
        from pflab import markets
        opened: List[int] = []
        newest: Optional[date] = None
        for market in markets.codes():
            if only_market and market != only_market or not _market_on(market):
                continue
            try:
                days = pending_sessions(con, now, market, root)
            except Exception as e:
                out["failed"].append(_fail(con, now, f"sessions of {market}", e))
                continue
            done = []
            for i, day in enumerate(days):
                mode = ("close" if market == "IN" else "us_morning") if i == len(days) - 1 else "catchup"
                try:
                    res = w.run(con, _asof(market, day) if mode == "catchup" else now, mode=mode, root=root) or {}
                except Exception as e:
                    out["failed"].append(_fail(con, now, f"watch ({market} {day} {mode})", e))
                    break                                              # in order: a later session is not watched before an earlier one that failed
                _mark(con, now, market, day, mode, res)
                opened += list(res.get("cases_opened") or [])
                done.append(f"{day}:{mode}")
                newest = day if newest is None or day > newest else newest
            if done:
                out["sessions"][market] = done
        if (not only_market or only_market == "US") and _market_on("US"):
            opened += _us_carry(con, now, w, root, out)
        if think_cases:
            from pflab import think
            ids = opened + _unthought(con, int(think.settings()["max_cases_per_day"]))
            if ids:
                _think(con, now, ids, root, out)
        out["cases_opened"] = opened
        if follow and (newest is not None or _looks_due(con, now)):
            _follow(con, now, now.date(), out)
        _learn(con, now, out, new_session=newest is not None)
    except Exception as e:
        out["failed"].append(_fail(con, now, "sweep", e))
    return out


def _learned(con, day: date) -> bool:
    return bool(con.execute("SELECT 1 FROM paper_acts WHERE loop=? AND what LIKE ? LIMIT 1", [LOOP, f"learn {day} %"]).fetchone())


def _learn(con, now: datetime, out: dict, new_session: bool) -> None:
    """T8, once a day (and again when a new session was watched): score every decision whose 5, 20 or 60 sessions have passed and let the calibration table move (`score.score_due`, `score.calibrate`:
    idempotent, point in time as of the closes in the store). After the close and in the catch-up (both reach here). Never raises: a failure is a visible line and the next pass tries again."""
    day = now.date()
    if not new_session and _learned(con, day):
        return
    try:
        sc = _mod("score")
    except ImportError as e:
        if not _missing(e, "score"):
            out["failed"].append(_fail(con, now, "score", e))
        return
    try:
        n = sc.score_due(con, day)
        try:                                                                  # S86 (A77): the ghost decisions of a replayed gap are scored apart, in their own column
            from pflab.think import fastforward
            fastforward.score_ghosts(con, day)
        except Exception:
            pass
        cal = sc.calibrate(con, day)
        out["learned"] = {"scored": int(n or 0), "calibration": cal}
        from pflab.paper import cadence
        cadence.act(con, now, LOOP, f"learn {day}: {int(n or 0)} score row(s)", True, {"day": str(day)})
    except Exception as e:
        out["failed"].append(_fail(con, now, "score", e))


def _us_carry(con, now: datetime, w, root, out: dict) -> List[int]:
    """The US morning pass on an IST morning that has no new US session before it (a weekend, a US holiday): news made public since the last session's own morning pass (Sunday evening, US time =
    Monday morning IST) is read on that morning, once per IST day, from 07:00 (`watch._us_morning` runs the still-latest session on the real clock). Never raises."""
    try:
        if now.time() < time(7, 0):
            return []
        s = _closed("US", now)
        from pflab.us import clock as uc
        c = uc.close_ist(s)
        if c is None or c.date() >= now.date() or not _marked(con, "US", s):          # the session's own morning pass has not run yet (or it is today's): the normal sweep owns it
            return []
        if con.execute("SELECT 1 FROM paper_acts WHERE loop=? AND what LIKE ? LIMIT 1", [LOOP, f"watch USAM {now.date()} %"]).fetchone():
            return []
        res = w.run(con, now, mode="us_morning", root=root) or {}
        from pflab.paper import cadence
        cadence.act(con, now, LOOP, f"watch USAM {now.date()} us_morning: {len(res.get('signals') or [])} signal(s), {len(res.get('cases_opened') or [])} case(s) opened", True, {"market": "US", "day": str(now.date())})
        out.setdefault("sessions", {}).setdefault("US", []).append(f"{now.date()}:carry")
        return list(res.get("cases_opened") or [])
    except Exception as e:
        out["failed"].append(_fail(con, now, "us morning (carry)", e))
        return []


def _looks_due(con, now: datetime) -> bool:
    try:
        from pflab.think import cases
        return bool(cases.looks_due(con, now.date()))
    except Exception:
        return False


# --- what Today and the 15:45 report show -------------------------------------------------------------------------------------------------------------------------------------

def _try(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def scorecard_line(sc: Optional[dict]) -> Optional[str]:
    if not isinstance(sc, dict):
        return None
    n = sc.get("scored") or 0
    if not n:
        return "Decisions: none scored yet (the thinking loop is new)."
    s = f"Decisions: {n} scored"
    v = sc.get("vs_nothing_inr")
    if isinstance(v, (int, float)):
        s += f", Rs {v:+,.0f} against doing nothing, after tax"
    ran, fell = sc.get("skips_ran"), sc.get("skips_fell")
    if isinstance(ran, int) and isinstance(fell, int):
        s += f"; skipped ideas that ran {ran}, that fell {fell}"
    return s + "."


def today_block(con, day: Optional[date] = None) -> Optional[dict]:
    """Today's `think` block: {"thinking": {open cases..., "text"}, "reserve": [lines], "knowledge": line, "plan": text, "scorecard": line}. Each part is None when its module is not there or fails."""
    from pflab import think
    if not think.on():
        return None
    day = day or date.today()
    from pflab.think import cases
    thinking = _try(lambda: _mod("session").thinking_text(con, day))
    block = _try(lambda: cases.thinking_block(con, day))
    reserve = []
    for mk in ("IN", "US"):
        t = _try(lambda: _mod("session").reserve_status(con, mk, day)["text"])
        if t:
            reserve.append(t)
    for t in reserve:                                                   # `session.thinking_text` carries the reserve lines too; Today shows them once, as their own list
        thinking = (thinking or "").replace(t, "")
    thinking = " ".join((thinking or "").split()) or None
    know = _try(lambda: _mod("recall").knowledge_line(con, day)["text"])
    plan = _try(lambda: _mod("desk").plan_text(con, day))
    score = scorecard_line(_try(lambda: _mod("score").scorecard(con)))
    return {"thinking": {**(block or {}), "text": thinking or (block or {}).get("text")}, "reserve": reserve, "knowledge": know, "plan": plan, "scorecard": score}


def _one(text: Optional[str], n: int = 260) -> Optional[str]:
    if not text:
        return None
    t = " ".join(str(text).split())
    return t if len(t) <= n else t[: n - 1] + "..."


def report_lines(con, day: date) -> List[str]:
    """At most three lines for the 15:45 report (its 15-line cap stays): what the loop is thinking about, the reserve, and what it has learned (the scorecard and the knowledge line)."""
    b = _try(lambda: today_block(con, day))
    if not b:
        return []
    out: List[str] = []
    try:                                                                  # S86 (A76): the alarm lane's day, with its latency, in one line
        from pflab.think import alarm as _alarm
        if _alarm.status(con, day)["alarms"]:                       # nothing to say: the report stays as it was
            out.append(_alarm.report_line(con, day))
    except Exception:
        pass
    th = b["thinking"] or {}
    if th.get("open") or th.get("noticed_not_examined_today"):
        out.append((_one(th.get("text")) or "Thinking about: nothing open.") + (f" ({th['noticed_not_examined_today']} noticed, not examined)" if th.get("noticed_not_examined_today") else ""))
    if b["reserve"]:
        out.append(_one("Reserve: " + " | ".join(b["reserve"])))
    try:
        from pflab.think import fastforward as _ff
        g = _ff.scorecard_line(con)
        if g:
            out.append(_one(g))
    except Exception:
        pass
    learn = " ".join(x for x in (b["scorecard"], b["knowledge"]) if x)
    if learn and (b["scorecard"] and "none scored" not in b["scorecard"] or b["knowledge"]):
        out.append(_one(learn))
    return [x for x in out if x]
