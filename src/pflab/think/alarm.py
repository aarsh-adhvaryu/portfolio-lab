"""S86 the alarm lane (A73-A78, his words of 2026-11-13: "an action delayed does not make sense; the very existence of the system is to do this").

While the app is open, a serious headline, filing or move on a name the book is exposed to reaches the thinking loop and his phone within minutes. Code only up to the case: no model, no cost
until a case is thought through (and then inside his cap).

    run(con, now, root, ...)      one pass: ask the sources (`ingest/headlines.py`), classify each new headline by code, raise the RED ones, record the four times, watch the eyes
    lane_of(title, entry)         ("red" | "amber" | "grey", kind, severity): `classify.rule_kind` on the title; RED = a thesis-break kind at medium or high AND the company's name in the headline
                                  on a name the book holds, picked, keeps in the reserve or he suggested; or at least `alarm_outlets` different outlets on one name within an hour against its norm
    status(con, day)              the day's alarms: count, median and worst minutes from first published to "heard"
    eyes(con, now)                each source the system sees with: last answer and age (Today, `pflab service status`)

RED does five things in the same run: (a) one Telegram line, before any model: "Heard at HH:MM: <headline> (<outlet>). You hold <weight>. Looking into it now."; (b) new buying in the name is frozen by
code until the case decides; (c) a case opens AT ONCE and is thought through at once, outside the day's cap of three (an alarm is dropped only by the kill switch or his monthly cap); (d) the decision
is told ("Decided: ..."); (e) the same story arriving again joins the case, a materially new one (another kind of news) triggers a new look. An UNCONFIRMED headline never sells by itself: a sale comes
only through the case's own rule (which reads the company's filings and checks the cause on the web) or the exit manager on a CONFIRMED event (the company's own filing, an SEC 8-K).
AMBER (any other linked headline, or a RED-kind one on a name only watched): no message; stored, in `recall` and on the desk's agenda. GREY: stored only. At most `alarm_heard_per_day` "Heard"
messages a day, then one summary line. The four times of every alarm are stored (`alarm_s86`); a RED that took more than 30 minutes while the app was open is a Problems line with its cause.
Honest limit (RUNNING.md): nothing on a closed laptop can watch. At the next open the lane catches up first and says what happened meanwhile (`on_open` below).
"""
from __future__ import annotations

import json
import re
import statistics
import threading
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional

from pflab import think
from pflab.ingest import headlines as ing
from pflab.kg2 import classify, headlines as kg
from pflab.think import cases

DEFAULTS = {"alarm": True, "alarm_heard_per_day": 6, "alarm_outlets": 4, "alarm_outlet_minutes": 60, "alarm_story_hours": 36, "alarm_seconds": 110.0, "alarm_target_minutes": 30,
            "alarm_blind_minutes": 60, "alarm_gap_minutes": 30, "alarm_gap_days": 7, "alarm_graph_sync": True, "alarm_fresh_hours": 8, "alarm_sources": ["google_news", "yahoo", "gdelt_doc"]}
EYE_LABELS = {"google_news": "news (Google News)", "yahoo": "news (Yahoo Finance)", "gdelt_doc": "news (GDELT)", "filings": "Indian company filings (BSE)", "sec_8k": "US company filings (SEC)",
              "india_quotes": "Indian quotes", "us_quotes": "US quotes"}
_TURN = re.compile(r"\b(?:resign\w*|steps? down|stepping down|ousted|ouster|removed|fired|dismiss\w*|terminated|arrest\w*|indict\w*|charged|restat\w+|defaults?|downgrad\w+|bankrupt\w*|interim (?:ceo|chief))\b", re.I)
_DENIAL = re.compile(r"\b(?:denies|denied|denial|refutes?|rejects?|dismisses|baseless|unfounded|false report|clarif\w+|no truth)\b", re.I)
_COMMENTARY = re.compile(r"\b(?:what to know|what we know|takeaways?|who is|who are|who could|why did|explainer|analysis|opinion|here.s why|what comes next|what it means|buying dips?|live updates|key questions|raises? (?:critical )?questions|what market pros)\b", re.I)
LOCK = threading.RLock()
_RUNNING = threading.Event()


def settings() -> dict:
    out = dict(DEFAULTS)
    try:
        out.update({k: v for k, v in think.settings().items() if k in DEFAULTS})
    except Exception:
        pass
    return out


def on() -> bool:
    try:
        from pflab import core
        return bool(settings()["alarm"]) and think.on() and not core.killed()
    except Exception:
        return False


def _id(con, table: str, col: str) -> int:
    from pflab.pm.store import next_id
    return next_id(con, table, col)


# --- lanes -------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def lane_of(title: str, entry: dict, fresh: bool = True) -> tuple:
    """(lane, kind, severity) of one headline on one name, by code. `fresh` False (published long before it was seen: a week fetched for a name asked about for the first time, a feed that keeps
    old items): never RED, the news is not new."""
    kind, sev = kg.kind_of(title)
    named = ing.linked_by(title, entry) == "title"
    if not named:
        return "grey", kind, sev
    if kind in classify.THESIS_BREAK_KINDS and sev in ("medium", "high") and entry.get("red_ok") and fresh:
        return "red", kind, sev
    return "amber", kind, sev


def burst(con, now: datetime, entry: dict, cfg: dict) -> Optional[dict]:
    """At least `alarm_outlets` different outlets on one name within `alarm_outlet_minutes`, and at least three times its own usual hour (its last 14 days). None when not."""
    if not entry.get("red_ok"):
        return None
    lo = now - timedelta(minutes=int(cfg["alarm_outlet_minutes"]))
    when = "coalesce(published, first_seen)"                                                    # the story's own time: a week fetched at once is not an hour of coverage
    rows = con.execute(f"SELECT outlet, title FROM headlines_s86 WHERE isin=? AND {when} > ? AND {when} <= ?", [entry["isin"], lo, now]).fetchall()
    outlets = {o for o, t in rows if o and ing.linked_by(t, entry) == "title"}
    if len(outlets) < int(cfg["alarm_outlets"]):
        return None
    serious = [t for o, t in rows if o and ing.linked_by(t, entry) == "title" and kg.kind_of(t)[0] in classify.THESIS_BREAK_KINDS]
    if not serious and len(outlets) < 2 * int(cfg["alarm_outlets"]):
        return None                                                                              # S86 live hour: earnings previews and streak stories were two false alarms; volume alone needs a crowd of twice the line
    hist = con.execute(f"SELECT date_trunc('hour', {when}) h, count(DISTINCT outlet) FROM headlines_s86 WHERE isin=? AND {when} > ? AND {when} <= ? GROUP BY 1",
                       [entry["isin"], now - timedelta(days=14), lo]).fetchall()
    if len(hist) < 24:
        return None                                                                              # "against its norm" needs a norm: under 24 busy hours of history there is none, and no alarm by volume
    norm = statistics.median([int(c) for _h, c in hist])
    if len(outlets) < 3 * norm:
        return None
    return {"outlets": sorted(outlets), "norm": norm}


# --- the four times -----------------------------------------------------------------------------------------------------------------------------------------------------------------

def _mins(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    return None if a is None or b is None else (b - a).total_seconds() / 60.0


def _slow_cause(a: dict, run_started: Optional[datetime]) -> str:
    """Which stretch of published -> first seen -> case -> Telegram took longest, in words."""
    seg = {"the source was late (the headline was public long before it was seen)": _mins(a.get("published_at"), a.get("first_seen_at")),
           "the job was late (the headline was seen, then waited)": _mins(a.get("first_seen_at"), a.get("telegram_queued_at")),
           "the model was late (the case took long to decide)": _mins(a.get("telegram_queued_at"), a.get("decided_at"))}
    seg = {k: v for k, v in seg.items() if v is not None}
    return max(seg, key=seg.get) if seg else "unknown"


def _heard_today(con, day: date) -> int:
    return int(con.execute("SELECT count(*) FROM alarm_s86 WHERE day=? AND telegram_queued_at IS NOT NULL AND coalesce(mode,'live') <> 'gap'", [day]).fetchone()[0])


def _weight_text(e: dict) -> str:
    if e.get("held"):
        return f"{e.get('exposure_pct', 0.0):.1%} of the book" if e.get("exposure_pct") else "a position"
    return "none of it yet (it is a pick or a name you follow)"


def _open_alarm(con, isin: str, now: datetime, hours: int) -> Optional[dict]:
    r = con.execute("SELECT alarm_id, kind, case_id, joined_items, freeze_id FROM alarm_s86 WHERE isin=? AND first_seen_at >= ? AND lane='red' ORDER BY alarm_id DESC LIMIT 1",
                    [isin, now - timedelta(hours=hours)]).fetchone()
    return {"alarm_id": r[0], "kind": r[1], "case_id": r[2], "joined_items": r[3] or 0, "freeze_id": r[4]} if r else None


def _kinds_in_case(con, case_id: Optional[int]) -> set:
    if not case_id:
        return set()
    out = set()
    for s in cases.signals(con, case_id=case_id):
        try:
            k = (json.loads(s.get("detail_json") or "{}") or {}).get("kind")
            if k:
                out.add(k)
        except Exception:
            pass
    return out


def _record_signal(con, now: datetime, item: dict, e: dict, kind: str, sev: str, case_id: Optional[int]) -> int:
    sur = 3.0 if sev == "high" else 2.0
    det = {"ref": f"{ing.kg.SOURCE_PREFIX}{item['source']}:{item['id']}", "kind": kind, "severity": sev, "event_ts": str(now), "text": item["title"][:200], "why": f"headline ({item.get('outlet') or item['source']}): {item['title'][:200]}",
           "px_day": str(now.date()), "published": str(item.get("published")), "outlet": item.get("outlet"), "url": item.get("url")}
    sid = cases.record_signal(con, now, market=e["market"], isin=e["isin"], symbol=e["symbol"], signal="thesis_event", value=sur, threshold=1.0, surprise=sur, exposure_inr=e["exposure_inr"],
                              score=sur * e["exposure_inr"], detail=det)
    if case_id:
        cases.set_signal(con, sid, case_id=case_id, status="joined")
    return sid


def raise_red(con, now: datetime, root, item: dict, e: dict, kind: str, sev: str, *, cfg: Optional[dict] = None, mode: str = "live", think_fn: Optional[Callable] = None,
              tell_fn: Optional[Callable] = None, quiet: bool = False) -> dict:
    """One RED headline: (a) the Heard line, (b) the freeze, (c) the case and its thinking, (d) the decision told. `quiet` (a gap's backlog): no Heard line of its own (the gap message carries it)."""
    cfg = cfg or settings()
    from pflab.service import telegram as tgm
    out = {"isin": e["isin"], "symbol": e["symbol"], "item": item["id"], "kind": kind}
    pub = item.get("published")
    pub = datetime.fromisoformat(str(pub)) if pub and not isinstance(pub, datetime) else pub
    seen = datetime.fromisoformat(str(item["first_seen"])) if not isinstance(item["first_seen"], datetime) else item["first_seen"]
    prior = _open_alarm(con, e["isin"], now, int(cfg["alarm_story_hours"]))
    if prior:                                                                                # the same story again (or a new turn of it): it joins the case
        con.execute("UPDATE alarm_s86 SET joined_items=coalesce(joined_items,0)+1 WHERE alarm_id=?", [prior["alarm_id"]])
        con.execute("UPDATE headlines_s86 SET alarm_id=?, lane='red', kind=?, severity=? WHERE item_id=?", [prior["alarm_id"], kind, sev, item["id"]])
        case = cases.get_case(con, prior["case_id"]) if prior["case_id"] else None
        last = con.execute("SELECT decided_at FROM alarm_s86 WHERE alarm_id=?", [prior["alarm_id"]]).fetchone()[0]
        turn = bool(_TURN.search(item["title"]))                                                                  # a second report that says something DID happen (a resignation, an ouster), not the same story again
        kind_new = kind not in _kinds_in_case(con, prior["case_id"]) | {prior["kind"]}
        spaced = last is None or (now - last) >= timedelta(hours=12)                                       # S86b: at most one new look per alarm per 12 hours: the model's HIGH kinds alternate (leadership / fraud) in one crisis and each change would be a paid look
        new_look = bool(case) and case["state"] != "closed" and spaced and (kind_new or turn)
        if case and case["state"] != "closed":
            _record_signal(con, now, item, e, kind, sev, prior["case_id"])
        out.update({"joined": prior["alarm_id"], "case_id": prior["case_id"], "new_look": new_look})
        if new_look:
            out["thought"] = _think_now(con, now, root, prior["case_id"], think_fn)
            _decided(con, now, prior["alarm_id"], prior["case_id"], tell_fn)
        return out
    aid = _id(con, "alarm_s86", "alarm_id")
    con.execute("INSERT INTO alarm_s86 (alarm_id, isin, symbol, market, lane, kind, severity, headline, outlet, source, item_id, weight_pct, published_at, first_seen_at, joined_items, mode, day) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)", [aid, e["isin"], e["symbol"], e["market"], "red", kind, sev, item["title"][:300], item.get("outlet"), item["source"], item["id"],
                e.get("exposure_pct"), pub, seen, mode, now.date()])
    con.execute("UPDATE headlines_s86 SET alarm_id=?, lane='red', kind=?, severity=? WHERE item_id=?", [aid, kind, sev, item["id"]])
    out["alarm_id"] = aid
    # (a) the Heard line, before any model
    if not quiet and mode != "gap":
        if _heard_today(con, now.date()) < int(cfg["alarm_heard_per_day"]):
            text = (f"Heard at {now:%H:%M}: {item['title'][:200]} ({item.get('outlet') or item['source']}). You hold {_weight_text(e)} of {e['symbol']}. Looking into it now." if e.get("held")
                    else f"Heard at {now:%H:%M}: {item['title'][:200]} ({item.get('outlet') or item['source']}). {e['symbol']} is a name you follow or picked: {_weight_text(e)}. Looking into it now.")
            if tgm.enqueue(con, text, kind="alarm", dedup_key=f"alarm:{aid}:heard", now=now):
                con.execute("UPDATE alarm_s86 SET telegram_queued_at=? WHERE alarm_id=?", [now, aid])
        else:
            tgm.enqueue(con, f"Portfolio Lab: more serious headlines on your names today than I send one by one (limit {int(cfg['alarm_heard_per_day'])} a day); each one is a case; see Today.", kind="alarm",
                        dedup_key=f"alarm:{now.date()}:summary", now=now)
    # (b) no new buying in the name until the case decides
    try:
        if not cases.is_frozen(con, e["isin"], now.date()):
            fid = cases.add_freeze(con, now, isin=e["isin"], symbol=e["symbol"], market=e["market"], case_id=None, until_event="the alarm's case decides",
                                   reason=f"alarm: {kind.replace('_', ' ')} headline, unconfirmed: no new buying until the case decides")
            con.execute("UPDATE alarm_s86 SET freeze_id=? WHERE alarm_id=?", [fid, aid])
            out["freeze_id"] = fid
    except Exception as ex:
        out["freeze_problem"] = f"{type(ex).__name__}: {str(ex)[:100]}"
    # (c) the case, at once, outside the cap
    case = cases.case_for(con, e["isin"])
    if case is None:
        title = f"{e['symbol']}: {item['title'][:170]}"
        cid = cases.open_case(con, now, market=e["market"], kind="event", isin=e["isin"], symbol=e["symbol"], title=title, exposure_inr=e["exposure_inr"], exposure_pct=e["exposure_pct"],
                              score=3.0 * e["exposure_inr"], opened_by="alarm", signal_ids=[], state="open", names=[e["symbol"]])
    else:
        cid = case["case_id"]
    _record_signal(con, now, item, e, kind, sev, cid)
    con.execute("UPDATE alarm_s86 SET case_id=?, case_opened_at=? WHERE alarm_id=?", [cid, now, aid])
    if out.get("freeze_id"):
        con.execute("UPDATE think_freezes_s84 SET case_id=? WHERE freeze_id=?", [cid, out["freeze_id"]])
    out["case_id"] = cid
    out["thought"] = _think_now(con, now, root, cid, think_fn)
    _decided(con, now, aid, cid, tell_fn)
    return out


def _think_now(con, now: datetime, root, case_id: int, think_fn: Optional[Callable]) -> dict:
    try:
        fn = think_fn
        if fn is None:
            from pflab.think import session as ts
            fn = lambda c, n, cid: ts.think_case(c, n, cid, root=root)                          # noqa: E731
        r = fn(con, now, case_id) or {}
        return {"ok": bool(r.get("ok")), "failed": r.get("failed"), "state": r.get("state"), "off": r.get("off")}
    except Exception as ex:                                                                     # a refusal (guard, cap) leaves the case open: `_unthought` and the follow-up try again
        return {"ok": False, "failed": f"{type(ex).__name__}: {str(ex)[:160]}"}


def _decided(con, now: datetime, alarm_id: int, case_id: int, tell_fn: Optional[Callable]) -> None:
    """(d) After the case's decision: the alarm's own freeze is lifted unless the case itself froze, the decision is told (the case's own `tell`, forced), the time is stored."""
    case = cases.get_case(con, case_id)
    if not case:
        return
    decs = [d for d in case["decisions"] if d["decided_on"] == now.date()]
    if not decs and not [s for s in case["steps"] if s["step"] == "answer_ok"]:
        return                                                                                   # not thought through (refused, failed): the freeze stays, the case waits
    fid = con.execute("SELECT freeze_id FROM alarm_s86 WHERE alarm_id=?", [alarm_id]).fetchone()[0]
    own_freeze = [f for f in cases.active_freezes(con, now.date()) if f["case_id"] == case_id and f["freeze_id"] != fid]
    if fid and not own_freeze:
        cases.release_freeze(con, fid)
    decision = "; ".join(f"{d['symbol']}: {d['acted_option']}" for d in decs)[:200] or "read, nothing to do"
    real = datetime.now()                                                                      # the decision's own time includes the model's minutes; a simulated clock (tests, replays) is kept as given
    stamp = real if abs(real - now) < timedelta(minutes=30) else now
    con.execute("UPDATE alarm_s86 SET decided_at=?, decision=? WHERE alarm_id=?", [stamp, decision, alarm_id])
    try:
        from pflab.think import session as ts
        tell = tell_fn or (lambda c, n, cid: ts.tell(c, n, cid, force=True))
        tell(con, now, case_id)
    except Exception:
        pass
    a = con.execute("SELECT published_at, first_seen_at, case_opened_at, telegram_queued_at, decided_at, mode FROM alarm_s86 WHERE alarm_id=?", [alarm_id]).fetchone()
    rec = dict(zip(("published_at", "first_seen_at", "case_opened_at", "telegram_queued_at", "decided_at"), a[:5]))
    m = _mins(rec["published_at"], rec["telegram_queued_at"])
    if m is not None and m > float(settings()["alarm_target_minutes"]) and (a[5] or "live") == "live":
        cause = _slow_cause(rec, None)
        con.execute("UPDATE alarm_s86 SET slow_cause=? WHERE alarm_id=?", [cause, alarm_id])
        try:
            from pflab.core import session as cs
            cs.log(con, now, "degrade", f"a serious headline took {m:.0f} minutes from first published to heard (target {int(settings()['alarm_target_minutes'])}): {cause}")
        except Exception:
            pass


# --- the eyes ---------------------------------------------------------------------------------------------------------------------------------------------------------------------

def record_eye(con, source: str, now: datetime, *, ok: Optional[bool], items: int = 0, error: str = "", requests: int = 0) -> None:
    """One look at a source: `ok` True (it answered), False (it asked and failed), None (nothing was due)."""
    r = con.execute("SELECT last_try, last_ok, blind_since, blind_told_at, back_told_at, requests FROM eyes_s86 WHERE source=?", [source]).fetchone()
    last_try, last_ok, blind, told, back, req = r if r else (None, None, None, None, None, 0)
    if ok is None:
        return
    if ok:
        last_ok, blind = now, None
    else:
        stale = last_try is None or (now - last_try) > timedelta(minutes=45)                    # the app was off in between: the minutes of silence count from now
        blind = blind or (now if stale or last_ok is None else last_ok)
    con.execute("INSERT INTO eyes_s86 (source, label, last_try, last_ok, last_error, items_last, blind_since, blind_told_at, back_told_at, requests) VALUES (?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT (source) DO UPDATE SET label=excluded.label, last_try=excluded.last_try, last_ok=excluded.last_ok, last_error=excluded.last_error, items_last=excluded.items_last, "
                "blind_since=excluded.blind_since, requests=excluded.requests", [source, EYE_LABELS.get(source, source), now, last_ok, (error or None) if not ok else None, items, blind, told, back, (req or 0) + requests])


def blind_check(con, now: datetime, cfg: Optional[dict] = None) -> List[str]:
    """A source silent for `alarm_blind_minutes` while the app is open: ONE Problems line and ONE Telegram line; one more when it is back. Returns the lines said."""
    cfg = cfg or settings()
    from pflab.service import telegram as tgm
    said: List[str] = []
    for source, label, last_ok, blind, told, back in con.execute("SELECT source, label, last_ok, blind_since, blind_told_at, back_told_at FROM eyes_s86 WHERE source IN ('google_news','yahoo','gdelt_doc')").fetchall():
        silent = blind is not None and (now - blind) >= timedelta(minutes=int(cfg["alarm_blind_minutes"]))
        if silent and (told is None or told < blind):
            line = f"I am not getting {label} since {blind:%H:%M}."
            tgm.enqueue(con, f"Portfolio Lab: {line} Other sources keep watching." if _others_ok(con, source) else f"Portfolio Lab: {line} No news source is answering: I am blind to headlines until one returns.",
                        kind="alarm", dedup_key=f"eyes:{source}:{blind:%Y%m%d%H%M}:blind", now=now)
            con.execute("UPDATE eyes_s86 SET blind_told_at=? WHERE source=?", [now, source])
            said.append(line)
            try:
                from pflab.core import session as cs
                cs.log(con, now, "degrade", line)
            except Exception:
                pass
        elif blind is None and told is not None and (back is None or back < told) and last_ok is not None:
            tgm.enqueue(con, f"Portfolio Lab: {label} is answering again (since {last_ok:%H:%M}).", kind="alarm", dedup_key=f"eyes:{source}:{told:%Y%m%d%H%M}:back", now=now)
            con.execute("UPDATE eyes_s86 SET back_told_at=? WHERE source=?", [now, source])
            said.append(f"{label} is back")
    return said


def _others_ok(con, source: str) -> bool:
    return bool(con.execute("SELECT count(*) FROM eyes_s86 WHERE source IN ('google_news','yahoo','gdelt_doc') AND source <> ? AND blind_since IS NULL AND last_ok IS NOT NULL", [source]).fetchone()[0])


def eyes(con, now: datetime) -> List[dict]:
    """Each source with its last answer and age in minutes: the news feeds from the lane's own rows, the filings jobs and the quotes from where they write."""
    out: List[dict] = []
    for source, label, last_ok, last_try, err, blind in con.execute("SELECT source, label, last_ok, last_try, last_error, blind_since FROM eyes_s86 ORDER BY source").fetchall():
        out.append({"source": source, "label": label or EYE_LABELS.get(source, source), "last_ok": last_ok, "last_try": last_try, "age_min": _mins(last_ok, now), "blind_since": blind, "error": err})
    seen = {o["source"] for o in out}
    for job in ("filings", "sec_8k"):
        try:
            t = con.execute("SELECT max(started_at) FROM job_runs WHERE job=? AND status='ok'", [job]).fetchone()[0]
        except Exception:
            t = None
        if job not in seen:
            out.append({"source": job, "label": EYE_LABELS[job], "last_ok": t, "last_try": t, "age_min": _mins(t, now), "blind_since": None, "error": None})
    for source, table, col in (("india_quotes", "live_quotes", "ts"), ("us_quotes", "us_quotes_s86", "quote_ts")):
        try:
            t = con.execute(f"SELECT max({col}) FROM {table}").fetchone()[0]
        except Exception:
            t = None
        if source not in seen:
            out.append({"source": source, "label": EYE_LABELS[source], "last_ok": t, "last_try": t, "age_min": _mins(t, now), "blind_since": None, "error": None})
    return out


def funds_text(con, day, root=None) -> str:
    """For `pflab alarm status`: which funds the lane looks through, or "through funds: not known" when no holdings file or index weights exist."""
    try:
        from pflab.think import exposure
        fw = exposure.fund_weights(con, day, root)
        got = [f"{f['symbol']} ({f['basis']})" for f in fw["funds"].values()]
        unc = [f"{u['symbol']}: {u['why']}" for u in fw.get("uncovered", [])]
        if not got:
            return "through funds: not known" + (f" ({'; '.join(unc)})" if unc else " (the book holds no fund with member data)")
        return "through funds: " + "; ".join(got) + (f"; not covered: {'; '.join(unc)}" if unc else "")
    except Exception:
        return "through funds: not known"


def eyes_text(con, now: datetime) -> str:
    lines = []
    for e in eyes(con, now):
        age = e["age_min"]
        lines.append(f"{e['label']}: " + ("never answered yet" if e["last_ok"] is None else (f"answered {age:.0f} min ago" if age < 120 else f"answered {age / 60:.1f} h ago")) + (f" (silent since {e['blind_since']:%H:%M})" if e["blind_since"] else ""))
    return "\n".join(lines)


# --- the day's numbers ---------------------------------------------------------------------------------------------------------------------------------------------------------------

def status(con, day: date) -> dict:
    rows = con.execute("SELECT published_at, first_seen_at, telegram_queued_at, decided_at, slow_cause, symbol, headline, coalesce(mode,'live') FROM alarm_s86 WHERE day=? ORDER BY alarm_id", [day]).fetchall()
    live = [r for r in rows if r[7] == "live"]
    ph = [_mins(r[0], r[2]) for r in live if r[0] and r[2]]
    pd_ = [_mins(r[0], r[3]) for r in live if r[0] and r[3]]
    return {"day": str(day), "alarms": len(rows), "live": len(live), "gap": len(rows) - len(live), "median_heard_min": round(statistics.median(ph), 1) if ph else None, "worst_heard_min": round(max(ph), 1) if ph else None,
            "median_decided_min": round(statistics.median(pd_), 1) if pd_ else None, "worst_decided_min": round(max(pd_), 1) if pd_ else None, "slow": [r[4] for r in live if r[4]]}


def report_line(con, day: date) -> Optional[str]:
    s = status(con, day)
    if not s["alarms"]:
        return "Alarm lane: no serious headline on your names today."
    t = f"Alarm lane: {s['alarms']} serious headline{'s' if s['alarms'] != 1 else ''} on your names"
    if s["median_heard_min"] is not None:
        t += f"; heard a median {s['median_heard_min']:.0f} min after first published (worst {s['worst_heard_min']:.0f})"
    if s["median_decided_min"] is not None:
        t += f", decided a median {s['median_decided_min']:.0f} min (worst {s['worst_decided_min']:.0f})"
    return t + "."


# --- one pass ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _model_lead(con, root, it: dict, e: dict, model_fn: Optional[Callable]) -> Optional[tuple]:
    """H2: a fresh, named headline on a name the book holds that the RULES call plain news: the LOCAL model (free, closed list, never a number) is asked once; only a thesis-break kind at HIGH
    severity makes it RED (a medium guess of an 8B model is not worth a paid case). The answer is cached like the graph's (`classify.append_cache`) so the rebuild gives the same kinds. None when
    the model is off, cannot answer or says nothing serious."""
    if _COMMENTARY.search(it["title"]):                              # S86b: explainers, takeaways and analysis pieces are commentary on news, not news (43 model HIGHs in the Nvidia week, 23 of them were these): AMBER
        return None
    try:
        from pathlib import Path
        fn = model_fn or classify.model_classify
        r = fn(it["title"])
        if not r or r.get("kind") not in classify.THESIS_BREAK_KINDS or r.get("severity") != "high":
            return None
        classify.append_cache(Path(root), [{"event_id": kg.event_id(it["id"]), "kind": r["kind"], "severity": "high", "method": "model", "headline": it["title"][:200]}])
        return r["kind"], "high"
    except Exception:
        return None


def _classify_new(con, now: datetime, items: List[dict], by_isin: Dict[str, dict], gap_mode: bool = False, root=None, model_fn: Optional[Callable] = None, model_max: int = 8) -> List[dict]:
    """Lane, kind and severity of each new item (by code, then the local model for the leads the rule cannot place), stored on its row. Returns the items with `lane`, `kind`, `sev`, `entry`."""
    out = []
    asked = 0
    for it in items:
        e = by_isin.get(it["isin"])
        if e is None:
            continue
        pub = it.get("published")
        pub = datetime.fromisoformat(str(pub)) if pub and not isinstance(pub, datetime) else pub
        fresh = pub is None or (now - pub) <= timedelta(hours=float(settings()["alarm_fresh_hours"]) if gap_mode is False else 24.0 * float(settings()["alarm_gap_days"]))
        lane, kind, sev = lane_of(it["title"], e, fresh)
        if lane == "amber" and kind == "news" and fresh and e.get("red_ok") and root is not None and asked < model_max and ing.linked_by(it["title"], e) == "title":
            asked += 1
            m = _model_lead(con, root, it, e, model_fn)
            if m:
                lane, kind, sev = "red", m[0], m[1]
        con.execute("UPDATE headlines_s86 SET lane=?, kind=?, severity=? WHERE item_id=?", [lane, kind, sev, it["id"]])
        out.append({**it, "lane": lane, "kind": kind, "sev": sev, "entry": e})
    return out


def bse_today(con, now: datetime, root, entries: List[dict], hours: int = 36) -> List[dict]:
    """H3: the company's OWN filings on Indian names the book holds or picked, released in the last `hours` (the 15-minute `filings` job brings BSE's announcements), classified by the graph's own
    rule (`classify.rule_kind`): a thesis-break kind at medium or high is a RED item, so a case opens within one 15-minute cycle instead of after the nightly rebuild. Nothing is written to the graph
    (the nightly rebuild makes the same events from the same files). Never raises."""
    out: List[dict] = []
    try:
        import hashlib
        from pathlib import Path
        import pandas as pd
        from pflab.data import bse_scrip_isin
        from pflab.kg2 import filing_time as ft
        by = {e["isin"]: e for e in entries if e["market"] == "IN" and e.get("red_ok")}
        if not by:
            return out
        m = bse_scrip_isin.load(Path(root))
        m = m[m["isin"].isin(list(by))]
        codes = {str(r.scrip_code): r.isin for r in m.itertuples()}
        for k in range(2):
            day = (now - timedelta(days=k)).date()
            f = Path(root) / "bse_announcements" / str(day.year) / f"{day.isoformat()}.parquet"
            if not codes or not f.exists():
                continue
            df = pd.read_parquet(f)
            for r in df[df["scrip_code"].astype(str).isin(codes)].itertuples():
                ts, rule, _own = ft.filing_time(r.dissem_dt, getattr(r, "news_dt", None), day)
                if ts is None or not (now - timedelta(hours=hours) <= ts <= now):
                    continue
                kind, sev = classify.rule_kind(str(r.headline or ""), str(r.category or ""), str(r.subcategory or ""))
                if kind not in classify.THESIS_BREAK_KINDS or sev not in ("medium", "high"):
                    continue
                isin = codes[str(r.scrip_code)]
                ref = f"{r.scrip_code}:{ts:%Y%m%d%H%M%S}"
                iid = hashlib.sha1(f"bse|{isin}|{ref}".encode()).hexdigest()[:16]
                if con.execute("SELECT 1 FROM alarm_s86 WHERE item_id=?", [iid]).fetchone():
                    continue
                out.append({"id": iid, "isin": isin, "symbol": by[isin]["symbol"], "market": "IN", "title": str(r.headline or "")[:300], "outlet": "BSE filing (the company's own)", "source": "bse_announcement",
                            "published": ts, "first_seen": now, "lane": "red", "kind": kind, "sev": sev, "entry": by[isin], "confirmed": True})
    except Exception:
        return out
    return out


def merge_scope(root, entries: List[dict]) -> Optional[int]:
    """H1: the held and picked names (both markets, a US name by its company name and ticker) are handed to `kg2/scope.merge_held`, so the daily GDELT collection and the graph cover them too. Only when
    the set of names changed (the scope file is not rewritten every 15 minutes) and only when a scope file exists. Never raises. Returns how many names were merged, or None."""
    try:
        from pathlib import Path
        from pflab.kg2 import scope as sc
        if not sc.scope_path(Path(root)).exists():
            return None
        want = {e["isin"]: list(e["aliases"]) + [t.lower() for t in e["tickers"] if len(t) >= sc.MIN_ALIAS] for e in entries if e.get("red_ok") and (e.get("held") or "pick" in str(e.get("why")))}
        sig = json.dumps(sorted((k, sorted(v)) for k, v in want.items()))
        mark = Path(root) / "kg" / "scope_held_s86.sig"
        if mark.exists() and mark.read_text(encoding="utf-8") == sig:
            return 0
        sc.merge_held(Path(root), list(want), {k: v for k, v in want.items() if v})
        mark.write_text(sig, encoding="utf-8")
        return len(want)
    except Exception:
        return None


def last_try(con) -> Optional[datetime]:
    try:
        return con.execute("SELECT max(last_try) FROM eyes_s86 WHERE source IN ('google_news','yahoo','gdelt_doc')").fetchone()[0]
    except Exception:
        return None


def run(con, now: datetime, root, *, client: Optional[ing.Client] = None, entries: Optional[List[dict]] = None, sources=None, think_fn: Optional[Callable] = None,
        tell_fn: Optional[Callable] = None, force: bool = False, gap: Optional[Callable] = None, model_fn: Optional[Callable] = None) -> dict:
    """One pass of the lane. Never raises for a source's sake; a failure is a line in `problems`. `gap` is the fast-forward hook (`think/fastforward.py`): called with the gap's findings BEFORE the live
    book acts."""
    cfg = settings()
    out: dict = {"started": str(now), "problems": [], "alarms": [], "new": 0, "lanes": {"red": 0, "amber": 0, "grey": 0}}
    if not on():
        out["off"] = True
        return out
    with LOCK:
        try:
            sources = tuple(sources or settings()["alarm_sources"])                                  # S86b C2(d): which feeds are ON is configuration (GDELT's API refuses this PC's every request: OFF)
            prev = last_try(con)
            gap_min = float(cfg["alarm_gap_minutes"])
            is_gap = prev is not None and (now - prev) >= timedelta(minutes=gap_min)
            when = "7d" if is_gap else "6h"
            if entries is None:
                entries = ing.scope_entries(con, now.date(), root)
            by_isin = {e["isin"]: e for e in entries}
            out["scope_merged"] = merge_scope(root, entries)
            r = ing.collect(con, root, entries, now, client=client, sources=sources, when=when, max_seconds=float(cfg["alarm_seconds"]), force=force or is_gap)
            out["by_source"], out["requests"], out["stopped"] = r["by_source"], r.get("requests"), r["stopped"]
            out["problems"] += r["problems"]
            for src, b in r["by_source"].items():
                record_eye(con, src, now, ok=(None if not b["asked"] else b["ok"] > 0), items=b["items"], error="; ".join(p for p in r["problems"] if p.startswith(src))[:200], requests=b["asked"])
            items = _classify_new(con, now, r["items"], by_isin, gap_mode=is_gap, root=root, model_fn=model_fn)
            out["new"] = len(items)
            for it in items:
                out["lanes"][it["lane"]] += 1
            if cfg["alarm_graph_sync"] and items:
                out["graph"] = kg.sync_store(con, root, now)
            reds = [it for it in items if it["lane"] == "red"] + bse_today(con, now, root, entries)
            for it in items:                                                                       # the company's reply to a rumour joins the case it answers (an exchange filing or a headline): both are in the case
                if it["lane"] == "amber" and _DENIAL.search(it["title"]):
                    prior = _open_alarm(con, it["entry"]["isin"], now, int(cfg["alarm_story_hours"]))
                    if prior and prior["case_id"]:
                        _record_signal(con, now, it, it["entry"], "denial", "low", prior["case_id"])
                        con.execute("UPDATE alarm_s86 SET joined_items=coalesce(joined_items,0)+1 WHERE alarm_id=?", [prior["alarm_id"]])
                        out.setdefault("denials", []).append(it["id"])
            seen_burst = set()
            for e in entries:                                                                      # the many-outlets rule
                if e["isin"] in seen_burst or any(it["entry"]["isin"] == e["isin"] for it in reds):
                    continue
                b = burst(con, now, e, cfg) if any(it["entry"]["isin"] == e["isin"] for it in items) else None
                if b:
                    seen_burst.add(e["isin"])
                    pick = next(it for it in items if it["entry"]["isin"] == e["isin"])
                    pick = {**pick, "title": f"{len(b['outlets'])} outlets in an hour on {e['symbol']}: {pick['title']}"[:300]}
                    reds.append({**pick, "kind": "news_burst_outlets", "sev": "medium"})
            if is_gap:
                out["gap"] = _gap(con, now, root, prev, items, reds, cfg, think_fn, tell_fn, gap)
            else:
                for it in sorted(reds, key=lambda x: -x["entry"]["exposure_inr"]):
                    out["alarms"].append(raise_red(con, now, root, it, it["entry"], it["kind"], it["sev"], cfg=cfg, think_fn=think_fn, tell_fn=tell_fn))
            out["blind"] = blind_check(con, now, cfg)
        except Exception as ex:
            out["problems"].append(f"alarm lane: {type(ex).__name__}: {str(ex)[:200]}")
    return out


def _gap(con, now: datetime, root, prev: datetime, items: List[dict], reds: List[dict], cfg: dict, think_fn, tell_fn, ff: Optional[Callable]) -> dict:
    """The app was off from `prev` to `now`: everything since was fetched (7 days at most), every item counted from now (point in time), the RED ones on names the book holds raised QUIETLY (a case each,
    thought through), and ONE message says what happened meanwhile. The fast-forward (`ff`, H7) runs first when present; the live decisions follow."""
    from pflab.service import telegram as tgm
    gid = _id(con, "alarm_gap_s86", "gap_id")
    res: dict = {"gap_id": gid, "off_from": str(prev), "off_to": str(now), "items": len(items), "red": len(reds)}
    held_reds = [x for x in reds if x["entry"].get("held") or x["entry"].get("red_ok")]
    published_in_gap = [x for x in held_reds if x.get("published") and datetime.fromisoformat(str(x["published"])) >= prev - timedelta(hours=1)]
    ff_note = ""
    if ff is not None:
        try:
            ff_res = ff(con, now, root, prev, published_in_gap) or {}
            res["fast_forward"] = ff_res
            ff_note = str(ff_res.get("note") or "")
        except Exception as ex:
            res["fast_forward_problem"] = f"{type(ex).__name__}: {str(ex)[:160]}"
    looked = []
    seen = set()
    for it in sorted(published_in_gap, key=lambda x: -x["entry"]["exposure_inr"]):
        if it["entry"]["isin"] in seen:
            continue
        seen.add(it["entry"]["isin"])
        looked.append(raise_red(con, now, root, it, it["entry"], it["kind"], it["sev"], cfg=cfg, mode="gap", think_fn=think_fn, tell_fn=tell_fn, quiet=True))
    res["cases"] = [x.get("case_id") for x in looked]
    items_txt = "; ".join(f"{x['entry']['symbol']}: {x['title'][:110]} ({x.get('outlet') or x['source']}, {str(x.get('published'))[5:16]})" for x in published_in_gap[:4])
    if published_in_gap:
        text = f"Off from {prev:%a %d %b %H:%M} to {now:%a %d %b %H:%M}. While off: {items_txt}. Looking into {len(looked)} now." + (f" {ff_note}" if ff_note else "")
    else:
        text = f"Off from {prev:%a %d %b %H:%M} to {now:%a %d %b %H:%M}. Nothing serious found on what you hold." + (f" {ff_note}" if ff_note else "")
    tgm.enqueue(con, text[:1500], kind="alarm", dedup_key=f"gap:{prev:%Y%m%d%H%M}:{now:%Y%m%d%H%M}", now=now)
    con.execute("INSERT INTO alarm_gap_s86 VALUES (?,?,?,?,?,?,?,?)", [gid, prev, now, now, len(items), len(reds), text[:1500], _release()])
    res["message"] = text
    return res


def _release() -> str:
    try:
        from pflab import release
        return str(getattr(release, "current", lambda: "workshop")() or "workshop")
    except Exception:
        return "workshop"


def first(ctx) -> Optional[dict]:
    """Called at the top of `catch_up` and `think_loop`: when the app was off (no alarm pass for `alarm_gap_minutes`), the lane's backlog pass runs NOW and to its end, before the rest of the catch-up
    (H5/H7: "what happened while off" comes first). Otherwise nothing. Never raises."""
    try:
        if not on():
            return None
        prev = last_try(ctx.con)
        if prev is None or (ctx.now - prev) < timedelta(minutes=float(settings()["alarm_gap_minutes"])):
            return None
        from pflab.think import fastforward
        return run(ctx.con, ctx.now, ctx.data_root, gap=fastforward.hook())
    except Exception as ex:
        return {"problems": [f"alarm lane (first): {type(ex).__name__}: {str(ex)[:160]}"]}


# --- the thread the job starts --------------------------------------------------------------------------------------------------------------------------------------------------------

def start_background(con, now: datetime, root, **kw) -> dict:
    """The job's body: one pass on its own thread with its own cursor, so the scheduler thread (shared with the 5-minute session loop) is never held. One pass at a time; a second request while one runs is skipped."""
    if _RUNNING.is_set():
        return {"skipped": "an alarm pass is still running"}
    _RUNNING.set()
    cur = con.cursor()

    def body():
        try:
            run(cur, now, root, **kw)
        except Exception:
            pass
        finally:
            _RUNNING.clear()

    threading.Thread(target=body, daemon=True, name="alarm-lane").start()
    return {"started": True}
