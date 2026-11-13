"""S85 E7 (`loopchat`): the chat and the thinking loop. He is in the loop through the chat; the chat itself never decides (rule 8: the model reads and names a closed class; code sizes, the registered
rule acts).

  look_into(con, now, name_or_isin, chat_id, why="")   "look into X": a case at once (it counts in the day's 3; a full day queues it for the next day and says so); the case's first message has his words
  suggest_stock(con, now, name, reason, chat_id)         a suggested stock: recall, company card (the liquidity floor), one read (role read, agent chat) and a verdict from the closed list pick / wait_for / pass;
                                                         the name joins the watch "from you" for 120 sessions whatever the verdict; at most 5 a day, the rest queue for the next desk
  note_from_him(con, now, doc_id, chat_id)               a report or note he sent (read once by `readers`): for every held, picked or watched name it bears on a case opens or is joined and is thought
                                                         through; the answer is what the case did (one option, worst / likely / best in rupees), or "nothing new: already known from <source, date>"
  overrule(...)                                          "hold it" / "do not buy that": a standing instruction (hold_name / pause_buys) AND a record on the case, scored on the `user` track both ways
  cases_text / case_card / case_outcomes / scorecard_text / reserve_text / what_do_you_know / watch_from_you   the chat's reading tools
Hooks called from elsewhere (each inside a try): `scope_entries` (watch.scope), `release_queued` + `scan` (watch._commit), `tell_chat` (session.tell), `score_user` (score.score_due),
`preopen_text` (desk.plan_text), `run_queued_suggestions` (desk.tick_hook). Tables: `pm/mig_s79/m_loopchat85.py` (340-344). Scripted fakes go in `DEPS`.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from pflab import think
from pflab.think import cases

DEPS: dict = {}                                   # tests: {"gateway": fake, "rule_gateway": callable(system, messages, schema)}
MAX_NAMES_A_DAY = 5                               # suggested stocks examined a day (E7); more wait for the next desk
WATCH_SESSIONS = 120                              # how long a suggested name stays on the watch list "from you"
MAX_THOUGHT_INLINE = 3                            # cases of one note thought through while he waits; the rest are left to the loop's next step (said so)
VERDICTS = ("pick", "wait_for", "pass")
WAIT_KINDS = ("none", "next_results", "next_filing", "pullback_10", "pullback_20", "other_event")
FROM_YOU = "from_you"

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "why": {"type": "string"},
        "thesis": {"type": "string"},
        "break_condition": {"type": "string"},
        "takes_from": {"type": "string"},
        "learned_from": {"type": "string"},
        "wait_kind": {"type": "string", "enum": list(WAIT_KINDS)},
        "wait_text": {"type": "string"},
    },
    "required": ["verdict", "why", "thesis", "break_condition", "takes_from", "learned_from", "wait_kind", "wait_text"],
}

SYSTEM = ("You are the reading desk of a paper portfolio. The investor has suggested a stock. You get its company card (code's numbers), what the system already knows, his words and the picks "
          "scorecard. Say ONE verdict: pick (you believe in it enough to name it a pick: write the thesis, what would break it, and in takes_from what it takes from earlier notes, if any), "
          "wait_for (it may be good but something must happen first: wait_kind is next_results, next_filing, pullback_10, pullback_20 or other_event with its words in wait_text) or pass (say why). "
          "Never write a size, a price, a weight, a probability or a target: code sizes any pick inside the rails and the reserve. Use only numbers that are in the facts you were given. "
          "Unused texts are empty strings and wait_kind is none unless the verdict is wait_for.")


# --- plumbing --------------------------------------------------------------------------------------------------------------------------------------------------------------

def _id(con, table: str, col: str) -> int:
    from pflab.pm.store import next_id
    return next_id(con, table, col)


def _gw():
    if "gateway" in DEPS:
        return DEPS["gateway"]
    from pflab.llm import gateway
    return gateway


def _day(x) -> date:
    return x.date() if isinstance(x, datetime) else x


def _rs(x) -> str:
    x = float(x or 0.0)
    return f"Rs {x:,.0f}" if x >= 0 else f"-Rs {abs(x):,.0f}"


def _cut(s, n: int = 160) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "..."


def _session_after(market: str, day: date, n: int) -> date:
    try:
        from pflab import markets
        return markets.get("US" if market == "US" else "IN").session_after(day, n)
    except Exception:
        return day + timedelta(days=int(n * 7 / 5) + 1)


def _isin_like(s: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", (s or "").strip().upper()))


def resolve(con, name_or_isin: str, market: Optional[str] = None) -> dict:
    """His words -> {"isin","symbol","market","name"} by code, or {"error": reason}."""
    n = " ".join(str(name_or_isin or "").split())
    if not n:
        return {"error": "no name was given"}
    if _isin_like(n):
        r = con.execute("SELECT isin, symbol, name, market FROM instruments WHERE isin=?", [n.upper()]).fetchone()
        if r:
            mk = "US" if (r[3] == "US" or r[0].startswith("ZZ")) else "IN"
            return {"isin": r[0], "symbol": (r[1] or r[0]).upper(), "market": mk, "name": r[2]}
        if n.upper().startswith("ZZ"):
            return {"isin": n.upper(), "symbol": n.upper(), "market": "US", "name": n.upper()}
        return {"error": f"I do not know the ISIN {n}"}
    from pflab.entrance import rules_intake
    r = rules_intake.resolve_name(con, n, market if market in ("IN", "US") else "both")
    if r.get("error"):
        return r
    nm = None
    try:
        row = con.execute("SELECT name FROM instruments WHERE isin=?", [r["isin"]]).fetchone()
        nm = row[0] if row else None
    except Exception:
        pass
    return {**r, "name": nm or r["symbol"]}


def _entry(con, now: datetime, isin: str, symbol: str, market: str) -> dict:
    """The watch's own scope entry for this name (held names carry their value, others the labelled stand-in)."""
    from pflab.think import watch
    day = _day(now)
    try:
        for e in watch.scope(con, day):
            if e["isin"] == isin:
                return e
    except Exception:
        pass
    whole = 0.0
    try:
        whole = watch._whole_inr(con, day)
    except Exception:
        pass
    stand = float(watch.settings()["standin_weight"]) * whole
    return {"isin": isin, "symbol": symbol, "name": symbol, "market": market, "exposure_inr": stand, "exposure_pct": (stand / whole) if whole > 0 else 0.0, "held": False,
            "why": "from you", "exposure_basis": "stand-in"}


# --- the origin of a case and how it is opened ----------------------------------------------------------------------------------------------------------------------------

def origin(con, case_id: int) -> Optional[dict]:
    r = con.execute("SELECT case_id, source, chat_id, doc_id, words, created_at, state, told_json FROM think_case_origin_s85 WHERE case_id=?", [case_id]).fetchone()
    if not r:
        return None
    return dict(zip(("case_id", "source", "chat_id", "doc_id", "words", "created_at", "state", "told_json"), r))


def _set_origin(con, case_id: int, now: datetime, source: str, chat_id: Optional[int], doc_id: Optional[int], words: str, state: str) -> None:
    if origin(con, case_id):
        return
    con.execute("INSERT INTO think_case_origin_s85 VALUES (?,?,?,?,?,?,?,?)", [case_id, source, chat_id, doc_id, _cut(words, 600), now, state, "[]"])


def _room(con, day: date) -> int:
    from pflab.think import watch
    return max(0, int(watch.settings()["max_cases_per_day"]) - cases.cases_opened_on(con, day))


def open_or_join(con, now: datetime, e: dict, why: str, *, source: str, chat_id: Optional[int], doc_id: Optional[int] = None, signal: str = FROM_YOU, kind: str = "from_you",
                 detail: Optional[dict] = None) -> dict:
    """A signal "from you" on a name: join the open case on it, else open one (inside the day's cap), else keep it `noticed` and queued for the next day. -> {"case_id", "how", "signal_id"}."""
    day = _day(now)
    det = {"why": _cut(why, 700), "from": "you", "ref": f"you:{signal}:{doc_id or chat_id}:{day}"}
    det.update(detail or {})
    exp = float(e.get("exposure_inr") or 0.0)
    sid = cases.record_signal(con, now, market=e["market"], isin=e["isin"], symbol=e["symbol"], signal=signal, value=1.0, threshold=1.0, surprise=1.0, exposure_inr=exp, score=exp, detail=det)
    oc = cases.case_for(con, e["isin"])
    if oc is not None:
        cases.set_signal(con, sid, case_id=oc["case_id"], status="joined")
        _set_origin(con, oc["case_id"], now, source, chat_id, doc_id, why, "open")
        return {"case_id": oc["case_id"], "how": "joined", "signal_id": sid}
    title = _cut(f"{e['symbol']}: {why}", 280)
    if _room(con, day) > 0:
        cid = cases.open_case(con, now, market=e["market"], kind=kind, isin=e["isin"], symbol=e["symbol"], title=title, exposure_inr=exp, exposure_pct=float(e.get("exposure_pct") or 0.0),
                              score=exp, opened_by="you", signal_ids=[sid], state="open", names=[e["symbol"]])
        _set_origin(con, cid, now, source, chat_id, doc_id, why, "open")
        return {"case_id": cid, "how": "opened", "signal_id": sid}
    cid = cases.open_case(con, now, market=e["market"], kind=kind, isin=e["isin"], symbol=e["symbol"], title=title, exposure_inr=exp, exposure_pct=float(e.get("exposure_pct") or 0.0),
                          score=exp, opened_by="you", signal_ids=[sid], state="noticed", names=[e["symbol"]])
    cases.set_signal(con, sid, status="not_examined")
    _set_origin(con, cid, now, source, chat_id, doc_id, why, "queued")
    return {"case_id": cid, "how": "queued", "signal_id": sid}


def release_queued(con, now: datetime) -> List[int]:
    """The cases of his that waited for room open when the day has room (the next day, or when a slot is free). Called by the watch at every pass; code only."""
    out: List[int] = []
    day = _day(now)
    try:
        rows = con.execute("SELECT o.case_id FROM think_case_origin_s85 o JOIN think_cases_s84 c ON c.case_id=o.case_id WHERE o.state='queued' AND c.state='noticed' ORDER BY o.created_at").fetchall()
    except Exception:
        return out
    for (cid,) in rows:
        if _room(con, day) <= 0:
            break
        cases.set_case(con, cid, state="open")
        con.execute("UPDATE think_cases_s84 SET opened_on=? WHERE case_id=?", [day, cid])             # it counts in the day it is taken up
        con.execute("UPDATE think_signals_s84 SET status='examined' WHERE case_id=? AND status='not_examined'", [cid])
        con.execute("UPDATE think_case_origin_s85 SET state='open' WHERE case_id=?", [cid])
        out.append(cid)
    return out


# --- (1) look into --------------------------------------------------------------------------------------------------------------------------------------------------

def look_into(con, now: datetime, name_or_isin: str, chat_id: Optional[int], why: str = "") -> int:
    """He says "look into X": a case now. -> the case id (0 when the name is not known; `look_into_result` has the words)."""
    r = look_into_result(con, now, name_or_isin, chat_id, why)
    return int(r.get("case_id") or 0)


def look_into_result(con, now: datetime, name_or_isin: str, chat_id: Optional[int], why: str = "") -> dict:
    n = resolve(con, name_or_isin)
    if n.get("error"):
        return {"ok": False, "case_id": None, "message": n["error"]}
    e = _entry(con, now, n["isin"], n["symbol"], n["market"])
    words = " ".join((why or "").split()) or f"he asked to look into {n['symbol']}"
    res = open_or_join(con, now, e, f"he asked: {words}" if why else words, source="you_look", chat_id=chat_id, detail={"words": _cut(why, 400), "name": n["symbol"]})
    if res["how"] == "opened":
        msg = f"I opened case #{res['case_id']} on {n['symbol']}; the loop thinks it through at its next step and tells you here what it did."
    elif res["how"] == "joined":
        msg = f"{n['symbol']} already has case #{res['case_id']} open: I added what you said to it."
    else:
        msg = (f"Today's three cases are used. I stored case #{res['case_id']} on {n['symbol']} first for the next day; the loop takes it up then and tells you here.")
    return {"ok": True, "case_id": res["case_id"], "how": res["how"], "symbol": n["symbol"], "message": msg}


# --- (2) a suggested stock --------------------------------------------------------------------------------------------------------------------------------------------

def _watch_row(con, watch_id: int) -> Optional[dict]:
    cols = ("watch_id", "name", "isin", "symbol", "market", "suggested_on", "suggested_at", "since", "until", "chat_id", "his_reason", "state", "verdict", "why", "thesis", "condition_kind",
            "condition_text", "ref_price", "ref_day", "floor_ok", "floor_note", "cost_inr", "skip_id", "met_on", "told_json")
    r = con.execute(f"SELECT {', '.join(cols)} FROM watch_from_you_s85 WHERE watch_id=?", [watch_id]).fetchone()
    return dict(zip(cols, r)) if r else None


def _watch_rows(con, where: str, args: list) -> List[dict]:
    ids = [r[0] for r in con.execute(f"SELECT watch_id FROM watch_from_you_s85 WHERE {where} ORDER BY watch_id", args).fetchall()]
    return [x for x in (_watch_row(con, i) for i in ids) if x]


def watch_from_you(con, day: date) -> List[dict]:
    """The names he suggested that are on the watch list on `day` (active, inside their 120 sessions): what the watch's scope reads."""
    return _watch_rows(con, "state='active' AND since <= ? AND until >= ?", [day, day])


def expire(con, day: date) -> int:
    n = 0
    for w in _watch_rows(con, "state='active' AND until < ?", [day]):
        con.execute("UPDATE watch_from_you_s85 SET state='expired' WHERE watch_id=?", [w["watch_id"]])
        n += 1
    return n


def scope_entries(con, day: date) -> List[dict]:
    """For `watch.scope`: one entry per active name from him. Its `why` has no 'pick' in it (a pick is its own entry; 'passed on' names come through their skip)."""
    out = []
    for w in watch_from_you(con, day):
        out.append({"market": w["market"] or "IN", "isin": w["isin"], "symbol": w["symbol"], "why": f"from you ({(w['verdict'] or 'suggested').replace('_', ' ')})", "base_day": w["since"],
                    "base_why": _cut(w.get("why") or w.get("his_reason"), 300), "ref": f"you:{w['watch_id']}"})
    return out


def _floor_of(card: dict, market: str) -> tuple:
    """(ok, note) from the card's own liquidity block: None when the card could not say."""
    if not isinstance(card, dict) or card.get("ok") is False:
        return None, str((card or {}).get("problem") or "the card could not be built")[:200]
    liq = card.get("liquidity")
    if not isinstance(liq, dict):
        return None, "no liquidity figures were available"
    if market == "US":
        return bool(liq.get("clears_a62_floor")), str(liq.get("floor") or "the US floor (price at least USD 5, median traded value at least USD 2 million a day)")
    if liq.get("clears_picks_floor") is None:
        return None, "no liquidity figures were available"
    ok = bool(liq["clears_picks_floor"])
    v = liq.get("median_traded_value_inr_60d")
    return ok, ("it clears the picks floor of Rs 5 crore a day" if ok else f"its median traded value is Rs {float(v or 0) / 1e7:,.1f} crore a day, under the picks floor of Rs 5 crore")


def _last_price(con, isin: str, day: date) -> Optional[float]:
    try:
        r = con.execute("SELECT close FROM prices WHERE isin=? AND date<=? AND close>0 ORDER BY date DESC LIMIT 1", [isin, day]).fetchone()
        return float(r[0]) if r else None
    except Exception:
        return None


def _scorecard_for_read(con, day: date) -> str:
    try:
        from pflab.think import desk
        return desk.scorecard_text(con, day)
    except Exception:
        return ""


def _today_count(con, day: date) -> int:
    return int(con.execute("SELECT count(*) FROM watch_from_you_s85 WHERE suggested_on=? AND state <> 'queued'", [day]).fetchone()[0])


def _verdict_text(v: dict) -> str:
    sym = v.get("symbol")
    if v["verdict"] == "pick":
        return f"{sym}: picked. {v.get('why')} Code sizes it inside the rails and the reserve; it is bought slowly and scored against the index like every pick."
    if v["verdict"] == "wait_for":
        return f"{sym}: waiting for {v.get('condition_text') or 'a named event'}. {v.get('why')} It stays on the watch list for {WATCH_SESSIONS} sessions."
    return f"{sym}: passed on. {v.get('why')} It stays on the watch list for {WATCH_SESSIONS} sessions and is scored against the index."


def suggest_stock(con, now: datetime, name: str, reason: str, chat_id: Optional[int], *, market: Optional[str] = None, root=None, _queued_id: Optional[int] = None) -> dict:
    """A stock he suggests -> a verdict dict {"ok","verdict" (pick|wait_for|pass|queued), "symbol","why","floor_ok","watch_until","message"}. Never a size from a model."""
    from pflab.core import picks
    from pflab.lab import screen
    from pflab.think import desk, recall, session
    day = _day(now)
    reason = " ".join((reason or "").split())
    n = resolve(con, name, market)
    if n.get("error"):
        return {"ok": False, "verdict": None, "message": n["error"]}
    isin, sym, mk = n["isin"], n["symbol"], n["market"]
    old = _watch_rows(con, "isin=? AND state IN ('active','queued') AND suggested_on=?", [isin, day])
    if old and _queued_id is None:                                                     # the same name twice in a day: the answer is the stored one, no second read
        w = old[-1]
        if w["state"] == "queued":
            return {"ok": True, "verdict": "queued", "symbol": sym, "message": f"{sym} is already waiting for the next desk."}
        return {"ok": True, "verdict": w["verdict"], "symbol": sym, "why": w["why"], "floor_ok": w["floor_ok"], "watch_until": str(w["until"]), "repeat": True,
                "message": "Already looked at today. " + _verdict_text({"verdict": w["verdict"], "symbol": sym, "why": w["why"], "condition_text": w["condition_text"]})}
    if _queued_id is None and _today_count(con, day) >= MAX_NAMES_A_DAY:
        wid = _id(con, "watch_from_you_s85", "watch_id")
        con.execute("INSERT INTO watch_from_you_s85 (watch_id, name, isin, symbol, market, suggested_on, suggested_at, chat_id, his_reason, state) VALUES (?,?,?,?,?,?,?,?,?,'queued')",
                    [wid, name[:80], isin, sym, mk, day, now, chat_id, reason[:500]])
        return {"ok": True, "verdict": "queued", "symbol": sym, "watch_id": wid,
                "message": f"I look at {MAX_NAMES_A_DAY} suggested names a day and today's are used: {sym} is stored and the next desk takes it up; I will tell you here."}
    # recall, the card and the floor (code)
    rc = recall.recall(con, now, isin=isin, symbol=sym, limit_chars=3000)
    try:
        card = screen.company_card(con, now, mk, sym, root=root)
        card_txt = json.dumps(screen.fit_card(dict(card), 3500), default=str)
    except Exception as e:
        card, card_txt = {"ok": False, "problem": f"{type(e).__name__}"}, "the company card could not be built"
    floor_ok, floor_note = _floor_of(card, mk)
    facts = f"COMPANY CARD:\n{card_txt}\n\nWHAT WE ALREADY KNOW:\n{rc.get('text') or 'nothing stored about this name yet'}\n\nHIS WORDS: {reason or '(he gave no reason)'}\n\nPICKS SCORE:\n{_scorecard_for_read(con, day)}"
    cost, verdict, why, cond_kind, cond_text, thesis, pick_note = 0.0, "pass", "", None, None, "", None
    if floor_ok is False:                                                               # fails the liquidity floor: passed on with the reason, no read needed, still watched
        verdict, why = "pass", f"the system cannot hold it: {floor_note}. A pick must clear the liquidity floor."
    else:
        r = _gw().call(con, "read", [{"type": "text", "text": SYSTEM}], session.scrub(con, [{"role": "user", "content": facts}]), purpose="suggest_stock", now=now, max_tokens=900,
                       schema=session._strict(VERDICT_SCHEMA), agent="chat", chat_id=chat_id) or {}
        cost = float(r.get("cost_rupees") or 0.0)
        j = r.get("json") if isinstance(r.get("json"), dict) else None
        if j is None:
            try:
                j = json.loads(r.get("text") or "")
            except Exception:
                j = None
        if not isinstance(j, dict) or j.get("verdict") not in VERDICTS:
            verdict, why = "pass", "the read did not give a verdict from the list, so nothing was bought; the name stays on the watch list"
        else:
            verdict = j["verdict"]
            why = desk._clean(j.get("why"), facts, "the reason named figures that are not in the sources, so it is left out")
            thesis = desk._clean(j.get("thesis"), facts, "")
            if verdict == "wait_for":
                cond_kind = j.get("wait_kind") if j.get("wait_kind") in WAIT_KINDS and j.get("wait_kind") != "none" else "other_event"
                cond_text = {"next_results": "its next results", "next_filing": "its next filing", "pullback_10": "a 10% pullback from today's price",
                             "pullback_20": "a 20% pullback from today's price"}.get(cond_kind) or desk._clean(j.get("wait_text"), facts, "a named event")
            if verdict == "pick":
                brk = desk._clean(j.get("break_condition"), facts, "")
                out = picks.propose(con, now, mk, [{"symbol": sym, "thesis": thesis, "break_condition": brk, "storylines": [], "takes_from": desk._clean(j.get("takes_from"), facts, "")}],
                                    session_ref=f"chat {chat_id or ''}".strip(), learned_from=desk._clean(j.get("learned_from"), facts, "") or None)
                if not out["accepted"]:
                    verdict, pick_note = "pass", "; ".join(x["reason"] for x in out["refused"])[:400] or "the picks sleeve refused it"
                    why = f"{why} (it could not be named a pick: {pick_note})".strip()
    skip_id = None
    if verdict in ("pass", "wait_for"):                                                 # scored against the index like every skipped idea
        sk = picks.skip_idea(con, now, mk, sym, (why if verdict == "pass" else f"waiting for {cond_text}: {why}")[:480] + " [suggested by him]")
        skip_id = sk.get("skip_id") if sk.get("ok") else None
    if len(why) < 5:
        why = "no reason was given"
    px = _last_price(con, isin, day)
    until = _session_after(mk, day, WATCH_SESSIONS)
    if _queued_id is not None:
        con.execute("DELETE FROM watch_from_you_s85 WHERE watch_id=?", [_queued_id])
    wid = _id(con, "watch_from_you_s85", "watch_id")
    con.execute("INSERT INTO watch_from_you_s85 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [wid, name[:80], isin, sym, mk, day, now, day, until, chat_id, reason[:500], "active", verdict, why[:600], thesis[:600], cond_kind, cond_text, px, day if px else None,
                 floor_ok, floor_note[:300], cost, skip_id, None, "[]"])
    try:                                                                                # recall finds it tomorrow: a dated note "from you"
        recall.write_back(con, now, isin=isin, symbol=sym, title=f"He suggested {sym}: {verdict.replace('_', ' ')}", text=f"His words: {reason or '(none)'}\nVerdict: {verdict}. {why}",
                          source="you", cost_rupees=cost)
    except Exception:
        pass
    v = {"ok": True, "verdict": verdict, "symbol": sym, "why": why, "floor_ok": floor_ok, "floor_note": floor_note, "watch_until": str(until), "watch_id": wid, "condition_text": cond_text,
         "cost_rupees": round(cost, 2)}
    v["message"] = _verdict_text(v)
    return v


def run_queued_suggestions(con, now: datetime, *, root=None, limit: int = MAX_NAMES_A_DAY) -> List[dict]:
    """The next desk takes up the names that were over the day's 5 (each in its own chat, with its own answer posted there). Called by the desk's tick; a failure leaves the name queued."""
    out = []
    day = _day(now)
    for w in _watch_rows(con, "state='queued' AND suggested_on < ?", [day])[:limit]:
        if _today_count(con, day) >= MAX_NAMES_A_DAY:
            break
        try:
            v = suggest_stock(con, now, w["isin"], w["his_reason"] or "", w["chat_id"], root=root, _queued_id=w["watch_id"])
        except Exception:
            continue
        out.append(v)
        if w["chat_id"] and v.get("message"):
            _post(con, now, w["chat_id"], "From the desk: " + v["message"], f"loop:suggest:{w['watch_id']}")
    return out


# --- the watch list: conditions and events (code only) -----------------------------------------------------------------------------------------------------------------

def _post(con, now: datetime, chat_id: Optional[int], text: str, key: str) -> Optional[int]:
    if not chat_id:
        return None
    try:
        from pflab.entrance import store
        return store.post_system(con, now, text, kind="loop", key=key, chat_id=chat_id, channels=("laptop",))
    except Exception:
        return None


def _condition_met(con, w: dict, now: datetime) -> Optional[str]:
    kind, since = w.get("condition_kind"), w["suggested_at"]
    day = _day(now)
    if kind in ("next_results", "next_filing", "other_event"):
        rows = con.execute("SELECT kind, headline, ts FROM kg2_event WHERE isin=? AND ts > ? AND ts <= ? ORDER BY ts", [w["isin"], since, now]).fetchall() if _has(con, "kg2_event") else []
        for k, h, ts in rows:
            kk = str(k or "").lower()
            if kind == "next_results" and ("result" in kk or "earning" in kk or "financial" in kk):
                return f"its results came ({_cut(h, 100)}, {ts:%Y-%m-%d})"
            if kind == "next_filing" and ("filing" in kk or "8_k" in kk or "annual" in kk or "result" in kk):
                return f"a filing came ({_cut(h, 100)}, {ts:%Y-%m-%d})"
            if kind == "other_event":
                return f"an event came ({_cut(h, 100)}, {ts:%Y-%m-%d})"
        return None
    if kind in ("pullback_10", "pullback_20") and w.get("ref_price"):
        px = _last_price(con, w["isin"], day)
        pct = 0.10 if kind == "pullback_10" else 0.20
        if px is not None and px <= float(w["ref_price"]) * (1.0 - pct):
            return f"the price is {100 * (1 - px / float(w['ref_price'])):.0f}% under where it was when he suggested it"
    return None


def _has(con, table: str) -> bool:
    try:
        return bool(con.execute("SELECT 1 FROM information_schema.tables WHERE table_name=?", [table]).fetchone())
    except Exception:
        return False


def scan(con, now: datetime) -> List[int]:
    """Names waiting on a condition: when it has happened, the name reopens as a case (told in that chat when the loop has thought it through). Also lets the 120 sessions run out."""
    day = _day(now)
    opened: List[int] = []
    try:
        expire(con, day)
        for w in _watch_rows(con, "state='active' AND verdict='wait_for' AND met_on IS NULL", []):
            why = _condition_met(con, w, now)
            if not why:
                continue
            e = _entry(con, now, w["isin"], w["symbol"], w["market"] or "IN")
            res = open_or_join(con, now, e, f"the condition he suggested we wait for has happened: {why}", source="watch_from_you", chat_id=w["chat_id"], signal="wait_met",
                               detail={"watch_id": w["watch_id"], "waiting_for": w.get("condition_text"), "question": "was the reason for waiting right, and is it time?"})
            con.execute("UPDATE watch_from_you_s85 SET met_on=? WHERE watch_id=?", [day, w["watch_id"]])
            opened.append(res["case_id"])
    except Exception:
        pass
    return opened


# --- (3) a note from him -----------------------------------------------------------------------------------------------------------------------------------------------

_W = re.compile(r"[a-z0-9][a-z0-9.%-]*")


def _tokens(s: str) -> set:
    return {t for t in _W.findall((s or "").lower()) if len(t) >= 4 or any(c.isdigit() for c in t)}


def _known_from(claims: List[str], items: List[dict], skip_ids: set) -> Optional[dict]:
    """An earlier stored item that already says what the claims say (75% of a claim's words in one item; every claim covered): its source and date. Code only."""
    if not claims:
        return None
    best = None
    for c in claims:
        ct = _tokens(c)
        if len(ct) < 3:
            return None
        hit = None
        for it in items:
            if str(it.get("id")) in skip_ids:
                continue
            if len(ct & _tokens(it.get("text") or "")) / len(ct) >= 0.75:
                hit = it
                break
        if hit is None:
            return None
        best = best or hit
    return {"source": best.get("source"), "day": best.get("day"), "title": best.get("title")}


def _doc(con, doc_id: int) -> Optional[dict]:
    cols = ("doc_id", "name", "kind", "summary", "facts_json", "isins_json", "event_id", "note_doc", "received_at", "chat_id")
    r = con.execute(f"SELECT {', '.join(cols)} FROM received_docs_s85 WHERE doc_id=?", [doc_id]).fetchone()
    if not r:
        return None
    d = dict(zip(cols, r))
    for k in ("facts_json", "isins_json"):
        try:
            d[k[:-5]] = json.loads(d.get(k) or "[]")
        except Exception:
            d[k[:-5]] = []
    d["claims"] = [str(f.get("claim") if isinstance(f, dict) else f) for f in d["facts"] if (f.get("claim") if isinstance(f, dict) else f)]
    return d


def _names_it_bears_on(con, now: datetime, doc: dict) -> tuple:
    """(in scope [entries], not in scope [symbols]): the names code finds in the note (the reader's ISINs plus names in its claims) against what the book holds, picks or watches."""
    from pflab.think import recall, watch
    isins = list(dict.fromkeys(list(doc.get("isins") or []) + (recall._isins_in(con, " ".join(doc["claims"] + [doc.get("summary") or ""])) or [])))
    scope = {e["isin"]: e for e in watch.scope(con, _day(now))}
    inside = [scope[i] for i in isins if i in scope]
    outside = []
    for i in isins:
        if i not in scope:
            try:
                r = con.execute("SELECT symbol FROM instruments WHERE isin=?", [i]).fetchone()
                outside.append((r[0] if r and r[0] else i))
            except Exception:
                outside.append(i)
    return inside, outside


def note_from_him(con, now: datetime, doc_id: int, chat_id: Optional[int], *, think_now: bool = True, root=None) -> List[dict]:
    """A report, a note or news he sent (already read once and stored by `readers`). For EVERY held, picked or watched name it bears on: nothing new (recall already has it) or a case (opened or
    joined; first message = the note's claims), thought through now (at most 3 while he waits), the answer being what the case did. A note about the whole market or a sector goes to the storylines and
    tomorrow's pre-open plan. The same document again: the stored answer, no new case, no cost. -> a list of per-name dicts (see `note_text`)."""
    from pflab.think import recall, session
    old = con.execute("SELECT result_json FROM from_you_notes_s85 WHERE doc_id=?", [doc_id]).fetchone()
    if old:
        try:
            res = json.loads(old[0] or "[]")
            return [{**r, "repeat": True} for r in res]
        except Exception:
            return []
    doc = _doc(con, doc_id)
    if not doc or not doc["claims"]:
        return []
    day = _day(now)
    inside, outside = _names_it_bears_on(con, now, doc)
    skip = {str(doc.get("note_doc")), str(doc.get("event_id"))} - {"None"}
    res: List[dict] = []
    thought = 0
    for e in inside:
        try:
            rc = recall.recall(con, now, isin=e["isin"], symbol=e["symbol"], limit_chars=4000)
        except Exception:
            rc = {"items": []}
        known = _known_from(doc["claims"], rc.get("items") or [], skip)
        if known:
            res.append({"symbol": e["symbol"], "isin": e["isin"], "state": "nothing_new", "known_from": known,
                        "text": f"{e['symbol']}: nothing new: already known from {known['source']}, {known['day']}."})
            continue
        why = f"he sent '{_cut(doc.get('name'), 60)}': " + "; ".join(_cut(c, 160) for c in doc["claims"][:5])
        oc = open_or_join(con, now, e, why, source="you_note", chat_id=chat_id, doc_id=doc_id, kind="news", detail={"claims": [_cut(c, 200) for c in doc["claims"][:8]], "doc_id": doc_id})
        row = {"symbol": e["symbol"], "isin": e["isin"], "state": "case", "case_id": oc["case_id"], "how": oc["how"]}
        if think_now and oc["how"] != "queued" and thought < MAX_THOUGHT_INLINE:
            thought += 1
            try:
                row["thought"] = session.think_case(con, now, oc["case_id"], root=root)
            except Exception as ex:
                row["thought"] = {"ok": False, "failed": f"{type(ex).__name__}"}
        c = case_card(con, oc["case_id"])
        row["card"] = c
        if oc["how"] == "queued":
            row["text"] = f"{e['symbol']}: case #{oc['case_id']} is stored for the next day (today's three are used); the loop takes it up then."
        elif c.get("names") and any(x.get("option") for x in c["names"]):
            row["text"] = f"{e['symbol']} (case #{oc['case_id']}): " + " ".join(x["text"] for x in c["names"])
        else:
            row["text"] = f"{e['symbol']}: case #{oc['case_id']} {'joined' if oc['how'] == 'joined' else 'opened'}; the loop thinks it through at its next step and tells you here."
        res.append(row)
    if not inside:                                                                       # about the whole market or a sector (or a name the book does not touch)
        topic = _cut(doc.get("name") or "market note", 80)
        nid = _id(con, "market_notes_s85", "note_id")
        con.execute("INSERT INTO market_notes_s85 VALUES (?,?,?,?,?,?,?,?,?)", [nid, doc_id, chat_id, now, day, "market", topic, " | ".join(_cut(c, 200) for c in doc["claims"][:8]), "new"])
        try:
            recall.write_back(con, now, topic="market", title=f"A note he sent: {topic}", text=" | ".join(doc["claims"][:8]), source="you")
        except Exception:
            pass
        res.append({"symbol": None, "state": "market", "note_id": nid, "not_in_book": outside[:6],
                    "text": "It touches no name the book holds, picks or watches" + (f" ({', '.join(outside[:4])} are named: say 'look into X' or 'suggest X' to have one looked at)" if outside else "")
                            + ". I stored it for the storylines and tomorrow's pre-open plan."})
    con.execute("INSERT INTO from_you_notes_s85 VALUES (?,?,?,?,?)", [doc_id, now, chat_id, json.dumps([r.get("symbol") for r in res]), json.dumps(res, default=str)])
    return res


def note_text(rows: List[dict]) -> str:
    return "\n".join(r["text"] for r in rows if r.get("text"))


def preopen_text(con, day: date) -> str:
    """The notes about the market or a sector he sent in the last two days: one line each, for the desk's plan (Today and the pre-open plan)."""
    try:
        rows = con.execute("SELECT day, topic, text FROM market_notes_s85 WHERE day <= ? AND day >= ? ORDER BY note_id", [day, day - timedelta(days=2)]).fetchall()
    except Exception:
        return ""
    if not rows:
        return ""
    return "From notes he sent: " + " | ".join(f"{d}: {t}: {_cut(x, 200)}" for d, t, x in rows[:4])


# --- (5) the chat's readers and the overrule --------------------------------------------------------------------------------------------------------------------------------------

def _options_for(case: dict, sym: str, opt: str) -> Optional[dict]:
    rows = [o for o in case["options"] if (o["symbol"] == sym) and o["option"] == opt]
    for tr in ("rule", "model", "alt"):
        for o in rows:
            if o["track"] == tr:
                return o
    return rows[0] if rows else None


def case_card(con, case_id: int) -> dict:
    """One case in plain words: what it is, the class, what was decided for each name and why, with worst / likely / best in rupees (after tax, about 20 sessions)."""
    c = cases.get_case(con, case_id)
    if not c:
        return {"case_id": case_id, "text": f"There is no case #{case_id}.", "names": []}
    names = []
    last: Dict[str, dict] = {}
    for d in c["decisions"]:
        last[d["symbol"]] = d
    for sym, d in last.items():
        o = _options_for(c, sym, d["acted_option"]) or _options_for(c, sym, d["rule_option"])
        t = f"{d['acted_option'].replace('_', ' ')}"
        if o and (o["worst_inr"] or o["best_inr"] or o["likely_inr"]):
            t += f": if it goes badly {_rs(o['worst_inr'])}, most likely {_rs(o['likely_inr'])}, if well {_rs(o['best_inr'])} (after tax, about 20 sessions)"
        t += f". Why: {_cut(d['reason'], 220)}" if d.get("reason") else "."
        if d.get("differs"):
            t += f" (the rule chose {d['rule_option']}, the model {d['model_option']}; the rule acts)"
        names.append({"symbol": sym, "option": d["acted_option"], "rule_option": d["rule_option"], "model_option": d["model_option"], "worst_inr": o["worst_inr"] if o else None,
                      "likely_inr": o["likely_inr"] if o else None, "best_inr": o["best_inr"] if o else None, "why": d.get("reason"), "text": t})
    head = f"Case #{case_id} ({c['state']}{', ' + c['klass'].replace('_', ' ') if c.get('klass') else ''}): {c['title']}."
    body = "\n".join(f"- {n['symbol']}: {n['text']}" for n in names) or "- not thought through yet."
    tail = (f" Waiting for: {c['pending']}." if c.get("pending") else "") + (f" It looks again {c['next_look_on']}." if c.get("next_look_on") else "")
    return {"case_id": case_id, "state": c["state"], "klass": c.get("klass"), "title": c["title"], "pending": c.get("pending"), "next_look_on": c.get("next_look_on_s"), "names": names,
            "text": head + "\n" + body + tail}


def case_outcomes(con, case_id: int) -> dict:
    """The outcome table of a case: per name, every option the menu held with worst / likely / best in rupees, which one the model chose, which one the rule chose, which was acted on and why."""
    c = cases.get_case(con, case_id)
    if not c:
        return {"case_id": case_id, "text": f"There is no case #{case_id}.", "names": []}
    out, lines = [], []
    syms = list(dict.fromkeys([o["symbol"] for o in c["options"] if o["symbol"]]))
    for sym in syms:
        d = next((x for x in reversed(c["decisions"]) if x["symbol"] == sym), None)
        rows = []
        for opt in think.OPTIONS:
            o = _options_for(c, sym, opt)
            if o:
                rows.append({"option": opt, "worst_inr": o["worst_inr"], "likely_inr": o["likely_inr"], "best_inr": o["best_inr"], "worst_pct_book": o["worst_pct_book"]})
        out.append({"symbol": sym, "options": rows, "acted": d["acted_option"] if d else None, "rule_option": d["rule_option"] if d else None, "model_option": d["model_option"] if d else None,
                    "why": d["reason"] if d else None})
        lines.append(f"{sym}: " + "; ".join(f"{r['option'].replace('_', ' ')}: bad {_rs(r['worst_inr'])}, likely {_rs(r['likely_inr'])}, good {_rs(r['best_inr'])}" for r in rows)
                     + (f". Acted: {d['acted_option']} ({_cut(d['reason'], 200)})." if d else ". Nothing decided yet."))
    return {"case_id": case_id, "title": c["title"], "state": c["state"], "names": out, "text": "\n".join(lines) or "No outcome table is stored for this case yet."}


def cases_text(con, day: date) -> str:
    """The open cases and why each is open, one block."""
    rows = cases.open_cases(con)
    if not rows:
        return "No case is open."
    lines = []
    for c in rows[:12]:
        o = origin(con, c["case_id"])
        src = {"you_look": " (you asked)", "you_note": " (from a note you sent)", "watch_from_you": " (a name you suggested)"}.get(o["source"], "") if o else ""
        lines.append(f"#{c['case_id']} {c['symbol'] or c['title']} [{c['state']}]{src}: {_cut(c['title'], 150)}"
                     + (f" - waiting for {c['pending']}" if c.get("pending") else "") + (f", looks again {c['next_look_on_s']}" if c.get("next_look_on_s") else ""))
    return "\n".join(lines)


def scorecard_text(con, day: Optional[date] = None) -> str:
    """The decision scorecard (the rule's and the model's choices after tax against doing nothing, the skips) and, when he has overruled, how his choices did beside the loop's."""
    from pflab.think import score
    sc = score.scorecard(con)
    t = sc["text"]
    u = score._track(con, "user")
    if u["n"]:
        lp = score._track(con, "user_loop")
        t += f" His overrules scored at 20 sessions: {u['n']}; his choices against doing nothing: {_rs(u['vs_nothing_inr'])}, the loop's own choices on the same cases: {_rs(lp['vs_nothing_inr'])}."
    return t


def reserve_text(con, day: date) -> str:
    from pflab.think import reserve
    return reserve.text(con, day)


def what_do_you_know(con, now: datetime, name: Optional[str] = None, topic: Optional[str] = None) -> dict:
    """The same body of knowledge the loop reads (`recall`): notes, graph events, storylines, the pick or skip, earlier cases, newest first with source and date."""
    from pflab.think import recall
    isin = sym = None
    if name:
        n = resolve(con, name)
        if not n.get("error"):
            isin, sym = n["isin"], n["symbol"]
        else:
            topic = topic or name
    r = recall.recall(con, now, isin=isin, symbol=sym, topic=topic, limit_chars=5000)
    return {"symbol": sym, "n": r["n"], "text": r["text"] or "nothing is stored about this yet", "items": [{k: i.get(k) for k in ("kind", "id", "day", "source", "title")} for i in r["items"]]}


def overrule(con, now: datetime, name: str, action: str, chat_id: Optional[int] = None, *, case_id: Optional[int] = None, words: str = "", gateway_call=None) -> dict:
    """He overrules the loop on a name: action "hold" (do not sell it) or "no_buy" (do not buy it). A standing instruction through the rules parse (hold_name / pause_buys on the name) AND a record
    on the name's case (an `overruled` step and a row in `overrules_s85`) scored both ways on the `user` track: his choice and the loop's own choice, each against doing nothing."""
    from pflab.entrance import rules_intake
    if action not in ("hold", "no_buy"):
        return {"ok": False, "message": "say whether the system should hold it (not sell) or not buy it"}
    n = resolve(con, name)
    if n.get("error"):
        return {"ok": False, "message": n["error"]}
    sentence = f"hold {n['symbol']}, do not sell it" if action == "hold" else f"pause buying {n['symbol']}"
    res = rules_intake.standing_instruction(con, now, sentence, gateway_call=gateway_call or DEPS.get("rule_gateway"), chat_id=chat_id)
    if res.get("refused") or not res.get("made"):
        return {"ok": False, "message": res.get("reason") or res.get("message") or "the rule could not be made", "rule": res}
    c = cases.get_case(con, case_id) if case_id else (cases.case_for(con, n["isin"]) or next((x for x in reversed(_recent_cases(con, n["isin"], now)) if x), None))
    if c and c.get("case_id") and "decisions" not in c:
        c = cases.get_case(con, c["case_id"])
    user_opt = "hold" if action == "hold" else "nothing"
    loop_opt, cid = None, None
    if c:
        cid = c["case_id"]
        dec = [d for d in c["decisions"] if d["isin"] == n["isin"] or d["symbol"] == n["symbol"]]
        if dec:
            loop_opt = dec[-1]["acted_option"] or dec[-1]["rule_option"]
        cases.add_step(con, cid, now, "overruled", payload={"words": _cut(words or sentence, 300), "user_option": user_opt, "loop_option": loop_opt, "rule_id": res.get("rule_id")})
    oid = _id(con, "overrules_s85", "overrule_id")
    con.execute("INSERT INTO overrules_s85 VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [oid, cid, n["isin"], n["symbol"], now, _day(now), _cut(words or sentence, 300), user_opt, loop_opt, res.get("rule_id"),
                                                                              chat_id, action])
    msg = res.get("message") or f"Done: {sentence}."
    msg += (f" I recorded it on case #{cid}: it is scored both ways, your choice ({user_opt}) and the loop's own ({loop_opt or 'not decided yet'}), after tax." if cid
            else " There is no case on this name to score it against yet; the rule stands.")
    return {"ok": True, "overrule_id": oid, "case_id": cid, "rule_id": res.get("rule_id"), "user_option": user_opt, "loop_option": loop_opt, "message": msg}


def _recent_cases(con, isin: str, now: datetime, days: int = 14) -> List[dict]:
    rows = con.execute("SELECT case_id FROM think_cases_s84 WHERE isin=? AND opened_on >= ? AND state <> 'noticed' ORDER BY case_id", [isin, _day(now) - timedelta(days=days)]).fetchall()
    return [{"case_id": r[0]} for r in rows]


USER_BASE = 2_000_000_000                         # an overrule scores under decision_id = USER_BASE + overrule_id (tracks `user` and `user_loop`)


def score_user(con, day, root=None) -> int:
    """His overrules scored at 5, 20 and 60 sessions exactly like the rule's and the model's (`score._score_decision`): track `user` (his choice) beside `user_loop` (the loop's choice). Idempotent."""
    from pflab.pm.store import next_id
    from pflab.think import score
    day = _day(day)
    try:
        rows = con.execute("SELECT overrule_id, case_id, isin, symbol, day, user_option, loop_option FROM overrules_s85 WHERE case_id IS NOT NULL").fetchall()
    except Exception:
        return 0
    done, n = score._done(con), 0
    for oid, cid, isin, sym, d0, uopt, lopt in rows:
        d = {"decision_id": USER_BASE + int(oid), "case_id": cid, "isin": isin, "symbol": sym, "decided_on": d0, "rule_option": lopt, "model_option": uopt, "picks": [("user_loop", lopt), ("user", uopt)]}
        try:
            n += score._score_decision(con, d, day, done, root, next_id)
        except Exception:
            continue
    return n


# --- (6) the loop tells the chat it came from -----------------------------------------------------------------------------------------------------------------------------

def tell_chat(con, now: datetime, case_id: int) -> Optional[int]:
    """When a case that came from the entrance (his look, his note, a name he suggested that reopened) has been thought through or acted, say so in THAT chat: what it did and why. One message per
    stage (decision count). The Telegram text is the loop's own (`session.tell`); this is the chat's. -> the message id or None."""
    case = cases.get_case(con, case_id)
    if not case or not case["decisions"]:
        return None
    o = origin(con, case_id)
    if o is None:
        ws = [w for w in watch_from_you(con, _day(now)) if w["isin"] == case.get("isin")]
        if not ws:
            return None
        w = ws[-1]
        _set_origin(con, case_id, now, "watch_from_you", w["chat_id"], None, w.get("why") or w.get("his_reason") or "", "open")
        o = origin(con, case_id)
    if not o or not o.get("chat_id"):
        return None
    intro = {"you_look": "You asked me to look into this", "you_note": "Because of the note you sent", "watch_from_you": "A name you suggested is back on the table"}.get(o["source"], "The loop acted")
    card = case_card(con, case_id)
    text = f"{intro}. " + card["text"]
    if o["source"] == "watch_from_you":
        w = next((x for x in _watch_rows(con, "isin=?", [case.get("isin")])), None)
        if w:
            text = (f"{intro}: {w['symbol']}, which I {'passed on' if w['verdict'] == 'pass' else ('waited on' if w['verdict'] == 'wait_for' else 'picked')} on {w['suggested_on']} "
                    f"({_cut(w['why'], 160)}). Now: " + case["title"] + "\n" + card["text"])
    return _post(con, now, o["chat_id"], text[:3000], f"loop:case:{case_id}:{len(case['decisions'])}")


# --- the chat's tool registrations -----------------------------------------------------------------------------------------------------------------------------------------

def _obj(props: dict, required: list) -> dict:
    return {"type": "object", "properties": props, "required": required}


def register_tools() -> None:
    from pflab.entrance import tools

    def t_cases(ctx, a):
        return {"text": cases_text(ctx.con, ctx.now.date()), "thinking": cases.thinking_block(ctx.con, ctx.now.date())["text"]}

    def t_outcomes(ctx, a):
        return case_outcomes(ctx.con, int(a["case_id"]))

    def t_score(ctx, a):
        return {"text": scorecard_text(ctx.con, ctx.now.date())}

    def t_reserve(ctx, a):
        return {"text": reserve_text(ctx.con, ctx.now.date())}

    def t_know(ctx, a):
        return what_do_you_know(ctx.con, ctx.now, a.get("name"), a.get("topic"))

    def t_look(ctx, a):
        return look_into_result(ctx.con, ctx.now, str(a["name"]), getattr(ctx, "chat_id", None), str(a.get("why") or ""))

    def t_suggest(ctx, a):
        return suggest_stock(ctx.con, ctx.now, str(a["name"]), str(a.get("reason") or ""), getattr(ctx, "chat_id", None))

    def t_overrule(ctx, a):
        return overrule(ctx.con, ctx.now, str(a["name"]), str(a["action"]), getattr(ctx, "chat_id", None), words=str(getattr(ctx, "his_text", "") or a.get("words") or ""))

    reg = tools.register
    reg("thinking_cases", {"name": "thinking_cases", "description": "[read] The cases the thinking loop has open now and why each is open (what you asked it to look into, notes you sent, names you suggested).",
                  "input_schema": _obj({}, [])}, t_cases)
    reg("case_outcomes", {"name": "case_outcomes", "description": "[read] One case's outcome table: for each name every option (sell, trim, hold, freeze, wait, buy in parts, nothing) with worst, likely and best in rupees, and why it decided as it did.",
                          "input_schema": _obj({"case_id": {"type": "integer"}}, ["case_id"])}, t_outcomes)
    reg("decision_scorecard", {"name": "decision_scorecard", "description": "[read] How the loop's decisions did after tax against doing nothing, skipped ideas that ran, and how his overrules did.",
                               "input_schema": _obj({}, [])}, t_score)
    reg("reserve", {"name": "reserve", "description": "[read] The opportunity reserve (cash only the thinking loop may spend) in India and the US sub-book.", "input_schema": _obj({}, [])}, t_reserve)
    reg("what_do_you_know", {"name": "what_do_you_know", "description": "[read] Everything the system already knows about a name or topic (notes, graph events, storylines, its pick or skip, earlier cases), newest first with source and date.",
                             "input_schema": _obj({"name": {"type": "string", "description": "company name, symbol or ISIN"}, "topic": {"type": "string"}}, [])}, t_know)
    reg("look_into", {"name": "look_into", "description": "He asks the system to look into a name or a situation: opens a case at once (the day's three apply; a full day queues it) that the loop thinks through and reports here. Pass his words in why.",
                      "input_schema": _obj({"name": {"type": "string"}, "why": {"type": "string"}}, ["name"])}, t_look)
    reg("suggest_stock", {"name": "suggest_stock", "description": "He suggests a stock (a name, with or without a reason). The system checks what it knows, the company card and the liquidity floor, reads once and says pick, wait_for or pass; the name stays on the watch list for 120 sessions whatever the verdict. At most 5 a day.",
                          "input_schema": _obj({"name": {"type": "string"}, "reason": {"type": "string"}}, ["name"])}, t_suggest)
    reg("overrule", {"name": "overrule", "description": "He overrules the loop on a name ('hold it', 'do not buy that'): a standing instruction on that name and a record on its case, scored both ways later. action: hold or no_buy.",
                     "input_schema": _obj({"name": {"type": "string"}, "action": {"type": "string", "enum": ["hold", "no_buy"]}}, ["name", "action"])}, t_overrule)
