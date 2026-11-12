"""T2x: what we already know (S84). ONE function that returns, point-in-time, newest first and inside a size limit, what the system already holds about a name or a topic, from the two stores that
did not meet before: the paid analyst's and research notes (the OLD graph's `kg_docs` documents `analyst_note` and `memory` rows) and the rebuilt graph's (`kg2` events, relations, facts), plus
the storylines a name sits in, its pick (thesis and break condition) or skip (and why), and earlier cases on it or on the same kind of case with what was chosen and how it scored. Lookup is by
ISIN, symbol, sector and topic keys, never by a model. It writes nothing except `mark_used` (a row in `knowledge_use_s84`) and `write_back` (a dated note).

    recall(con, now, *, isin, symbol, topic, sector, asof, limit_chars)  -> {"items": [{"kind","id","day","source","title","text"}], "text", "n"}
    mark_used(con, items, *, by_kind, by_ref, day)                       the row that says a decision READ the item (stored is not used until something reads it)
    same_subject_fresh(con, now, *, isin, topic, since_move, question)   the "never pay twice" check: a note on the same subject with no event, result or move beyond the watch's thresholds since
    write_back(con, now, *, isin, symbol, topic, title, text, source, cost_rupees, case_id)  a dated note on the names it is about, where `recall` and the old chat find it
    knowledge_line(con, day)                                             paid notes this month, how many a decision has read, rupees of notes nothing has read in 30 days

Point-in-time: nothing dated after `asof` (default `now`) is returned; an event is held back until its own `ts` (a filing with no release time carries the next trading day's open, A58).
Item ids: an analyst or written-back note is its `kg_docs` doc id, a memory row its `mem_id`, an event its `event_id`, a pick `pick:<id>`, a skip `skip:<id>`, a case `case:<id>`, a storyline `story:<id>`.
It never raises: a missing table or an unreadable row leaves that source out.

Decisions (2026-11-12): web facts are NOT written into `kg2_event` (the graph's tables are rebuilt from raw files every night and an extra row would fail its byte-identical audit): they live in
`recall_notes_s84` with their source and `recall` returns them. An analyst note's memory row and graph document are one note (the memory row is not returned twice).
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional

from pflab import think

log = logging.getLogger("pflab.recall")

DEFAULTS = {"recall_item_chars": 700, "recall_max_age_days": 45, "recall_topic_days": 14, "recall_similarity": 0.5}
GENERIC_TOPICS = {"", "general", "workshop", "portfolio", "brain", "brain web", "web", "selfcheck", "assistant", "fetch", "explain", "chat"}
# how many items of each kind at most (so one busy source never crowds the rest out)
CAPS = {"analyst_note": 3, "note": 3, "memory": 2, "kg2_event": 5, "kg2_relation": 3, "kg2_peer_event": 3, "kg2_sector_event": 2, "storyline": 4, "pick": 1, "skip": 1, "case": 4, "case_same_kind": 2}
STALE_KINDS = ("results", "results_miss", "guidance_cut", "management_change", "corporate_action", "fund_raise", "regulatory_action", "fraud_investigation", "auditor_resignation",
               "promoter_pledge_increase", "rating_downgrade", "large_order_loss", "leadership_crisis")
USE_BY = ("case", "desk", "pick", "card", "session")
MOVE_FLOOR = 0.02


def _s(key: str):
    return think.settings().get(key, DEFAULTS[key])


def _rows(con, sql: str, args=()) -> list:
    try:
        return con.execute(sql, list(args)).fetchall()
    except Exception as e:                                           # a missing table or column leaves that source out
        log.debug("recall source skipped: %s", e)
        return []


def _cutoff(now: datetime, asof) -> datetime:
    if asof is None:
        return now
    if isinstance(asof, datetime):
        return min(asof, now)
    return min(datetime.combine(asof, time(23, 59, 59)), now)


def _clip(text, n: int) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _day(x) -> str:
    return x.date().isoformat() if isinstance(x, datetime) else (x.isoformat() if isinstance(x, date) else str(x)[:10])


def _words(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 3}


def _tokens(t: Optional[str]) -> set:
    return {x.strip().upper() for x in re.split(r"[,;/]", t or "") if x.strip()}


def _has_word(text: Optional[str], word: Optional[str]) -> bool:
    return bool(text and word and len(word) >= 2 and re.search(r"(?<![A-Za-z0-9])" + re.escape(word) + r"(?![A-Za-z0-9])", text, re.I))


# --- who is it -----------------------------------------------------------------------------------------------------------------------

def resolve(con, isin: Optional[str] = None, symbol: Optional[str] = None) -> dict:
    """{"isin","symbol","name"} from what is given, by code (the graph's node table, the instruments, the picks): any part may be None."""
    isin = (isin or "").strip() or None
    symbol = (symbol or "").strip().upper() or None
    name = None
    if isin:
        for sql in ("SELECT symbol, name FROM kg2_node WHERE isin=?", "SELECT symbol, name FROM instruments WHERE isin=?", "SELECT symbol, NULL FROM picks_s83 WHERE isin=? ORDER BY pick_id DESC LIMIT 1"):
            r = _rows(con, sql, [isin])
            if r:
                symbol = symbol or (str(r[0][0]).upper() if r[0][0] else None)
                name = name or r[0][1]
                if symbol and name:
                    break
    elif symbol:
        for sql in ("SELECT isin, name FROM kg2_node WHERE upper(symbol)=?", "SELECT isin, name FROM instruments WHERE upper(symbol)=? ORDER BY listed DESC NULLS LAST",
                    "SELECT isin, NULL FROM picks_s83 WHERE upper(symbol)=? ORDER BY pick_id DESC LIMIT 1", "SELECT isin, NULL FROM skips_s83 WHERE upper(symbol)=? ORDER BY skip_id DESC LIMIT 1"):
            r = _rows(con, sql, [symbol])
            if r:
                isin, name = r[0][0], r[0][1]
                break
    return {"isin": isin, "symbol": symbol, "name": name}


def _industry(con, isin: str, day: date) -> Optional[str]:
    r = _rows(con, "SELECT fvalue FROM kg2_fact WHERE isin=? AND fkey='industry' AND as_of <= ? AND known_from <= ? ORDER BY as_of DESC LIMIT 1", [isin, day, day])
    return str(r[0][0]) if r and r[0][0] else None


# --- the sources ---------------------------------------------------------------------------------------------------------------------

def _note_item(doc_id, at, title, source, text, kind="analyst_note", **extra) -> dict:
    d = {"kind": kind, "id": str(doc_id), "day": _day(at), "source": source or "", "title": _clip(title, 160), "text": text or "", "written_at": at.isoformat() if isinstance(at, datetime) else str(at)}
    d.update(extra)
    return d


def _notes(con, cut: datetime, who: dict, topic: Optional[str], sector: Optional[str], question: Optional[str] = None, since: Optional[datetime] = None) -> List[dict]:
    """The paid analyst's and research notes (old graph documents + the notes written back), newest first, on this name or topic."""
    isin, sym = who["isin"], who["symbol"]
    topics = [t for t in ((topic or "").strip(), (sector or "").strip()) if t and t.lower() not in GENERIC_TOPICS]
    out: List[dict] = []
    seen = set()
    # (a) notes written back (the index table: keyed by ISIN, symbol and topic, no graph link needed)
    w, a = [], [cut]
    if isin:
        w.append("isin=?")
        a.append(isin)
    if sym:
        w.append("upper(symbol)=?")
        a.append(sym)
    for t in topics:
        w.append("lower(topic)=?")
        a.append(t.lower())
    if w:
        for nid, doc, at, src, title, text, cost, case_id in _rows(con, f"SELECT note_id, doc_id, written_at, source, title, text, cost_rupees, case_id FROM recall_notes_s84 WHERE written_at <= ? AND ({' OR '.join(w)}) "
                                                                    "ORDER BY written_at DESC, note_id DESC LIMIT 20", a):
            if since is not None and at < since:
                continue
            seen.add(doc)
            out.append(_note_item(doc, at, title, src, text, kind="note", cost_rupees=float(cost or 0.0), case_id=case_id))
    # (b) the analyst's API notes (old graph documents; `api_calls.topic` holds the symbols, the graph's links may be off)
    linked = set()
    if isin:
        linked = {r[0] for r in _rows(con, "SELECT src FROM kg_edges WHERE dst=? AND rel='about' AND valid_from <= ?", [f"company:{isin}", cut])}
    for doc, at, dtitle, src, attrs, ctopic, cquestion in _rows(con, """SELECT d.doc_id, d.published_at, d.title, d.source, d.attrs_json, c.topic, c.question FROM kg_docs d LEFT JOIN api_calls c ON c.note_doc = d.doc_id
                                                                          WHERE d.kind = 'analyst_note' AND d.published_at <= ? AND d.dup_of IS NULL ORDER BY d.published_at DESC LIMIT 400""", [cut]):
        if doc in seen:
            continue
        if since is not None and at < since:
            break
        try:
            at_json = json.loads(attrs or "{}")
        except ValueError:
            at_json = {}
        if at_json.get("recall"):                                    # a written-back note: the index table already gave it
            continue
        tk, cq = _tokens(ctopic), cquestion or dtitle or ""
        hit = doc in linked or (sym and (sym in tk or (ctopic and ctopic.strip().upper() in GENERIC_TOPICS_UP and _has_word(cq, sym)))) \
            or any(t.upper() in tk or (ctopic and ctopic.strip().upper() in GENERIC_TOPICS_UP and _has_word(cq, t)) for t in topics) \
            or (question is not None and _similar(question, cq))
        if not hit:
            continue
        seen.add(doc)
        out.append(_note_item(doc, at, cq or dtitle, src, str(at_json.get("answer") or ""), call_id=None))
    out.sort(key=lambda x: x["written_at"], reverse=True)
    return out


GENERIC_TOPICS_UP = {t.upper() for t in GENERIC_TOPICS}


def _similar(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    return bool(wa and wb and len(wa & wb) / len(wa | wb) >= float(_s("recall_similarity")))


def _memory(con, cut: datetime, who: dict, topic: Optional[str]) -> List[dict]:
    subs = [x.lower() for x in (who["isin"], who["symbol"], (topic or "").strip()) if x]
    if not subs:
        return []
    rows = _rows(con, f"""SELECT mem_id, valid_from, kind, subject, text, source FROM memory WHERE valid_from <= ? AND (valid_to IS NULL OR valid_to > ?) AND kind IN ('note','outcome')
                          AND lower(subject) IN ({','.join('?' * len(subs))}) AND source NOT LIKE 'analyst call #%' AND source NOT LIKE 'recall:%' AND source NOT IN ('investor','cli')
                          ORDER BY valid_from DESC, mem_id DESC LIMIT 4""", [cut.date(), cut.date(), *subs])
    return [{"kind": "memory", "id": str(r[0]), "day": _day(r[1]), "source": r[5], "title": f"{r[2]} on {r[3]}", "text": r[4] or ""} for r in rows]


_EV_SQL = "SELECT e.event_id, e.ts, e.kind, e.severity, e.headline, e.source, e.isin FROM kg2_event e WHERE e.ts IS NOT NULL AND e.ts <= ? "
_EV_MATERIAL = "AND (e.severity IN ('medium','high') OR e.kind IN ({}))".format(",".join(f"'{k}'" for k in STALE_KINDS))


def _event_item(r, kind: str, name_of: Dict[str, str]) -> dict:
    who = name_of.get(r[6]) or r[6]
    return {"kind": kind, "id": str(r[0]), "day": _day(r[1]), "source": r[5], "title": f"{who}: {r[2]} ({r[3]})", "text": r[4] or "", "written_at": r[1].isoformat()}


def _graph(con, cut: datetime, who: dict, sector: Optional[str]) -> List[dict]:
    """kg2 events of the name, its peers (the graph's named relations) and its industry; the relations themselves."""
    isin, day = who["isin"], cut.date()
    out: List[dict] = []
    names: Dict[str, str] = {}

    def nm(i):
        if i not in names:
            r = _rows(con, "SELECT coalesce(symbol, name) FROM kg2_node WHERE isin=?", [i])
            names[i] = str(r[0][0]) if r and r[0][0] else i
        return names[i]
    peers: Dict[str, str] = {}
    if isin:
        names[isin] = who["symbol"] or isin
        out += [_event_item(r, "kg2_event", names) for r in _rows(con, _EV_SQL + "AND e.isin=? " + _EV_MATERIAL + " ORDER BY e.ts DESC, e.event_id LIMIT 6", [cut, isin])]
        for s, d, rule, detail, as_of in _rows(con, "SELECT src_isin, dst_isin, rule, detail, as_of FROM kg2_relation WHERE (src_isin=? OR dst_isin=?) AND as_of <= ? ORDER BY as_of DESC, rule LIMIT 6", [isin, isin, day]):
            other = d if s == isin else s
            peers[other] = rule
            out.append({"kind": "kg2_relation", "id": f"{s}>{d}:{rule}", "day": _day(as_of), "source": f"kg2 rule {rule}", "title": f"{nm(s)} relates to {nm(d)} by {rule}", "text": detail or ""})
        if peers:
            ph = ",".join("?" * len(peers))
            out += [_event_item(r, "kg2_peer_event", names) for r in _rows(con, _EV_SQL + f"AND e.isin IN ({ph}) AND e.ts > ? " + _EV_MATERIAL + " ORDER BY e.ts DESC, e.event_id LIMIT 4",
                                                                           [cut, *peers, cut - timedelta(days=60)])]
    ind = _industry(con, isin, day) if isin else (sector or None)
    if ind:
        same = [r[0] for r in _rows(con, "SELECT DISTINCT isin FROM kg2_fact WHERE fkey='industry' AND fvalue=? AND as_of <= ?", [ind, day]) if r[0] != isin and r[0] not in peers]
        if same:
            ph = ",".join("?" * len(same))
            out += [_event_item(r, "kg2_sector_event", names) for r in _rows(con, _EV_SQL + f"AND e.isin IN ({ph}) AND e.ts > ? AND e.severity = 'high' ORDER BY e.ts DESC, e.event_id LIMIT 3",
                                                                              [cut, *same, cut - timedelta(days=30)])]
    for it in out:
        it.pop("written_at", None)
    return out


def _storylines(con, cut: datetime, who: dict, topic: Optional[str], sector: Optional[str]) -> List[dict]:
    day = cut.date()
    rows = []
    if who["isin"]:
        rows += _rows(con, """SELECT s.storyline_id, s.claim, s.direction, s.status, s.status_on, s.opened_on, s.subject, e.exposure FROM storyline_exposure_s80 e JOIN storylines_s80 s USING (storyline_id)
                              WHERE e.isin=? AND s.opened_on <= ?""", [who["isin"], day])
    for t in [x for x in (topic, sector) if x and x.lower() not in GENERIC_TOPICS]:
        rows += _rows(con, "SELECT storyline_id, claim, direction, status, status_on, opened_on, subject, NULL FROM storylines_s80 WHERE opened_on <= ? AND (lower(subject)=? OR lower(claim) LIKE ?)",
                      [day, t.lower(), f"%{t.lower()}%"])
    seen, out = set(), []
    for sid, claim, direction, status, status_on, opened_on, subject, exposure in rows:
        if sid in seen:
            continue
        seen.add(sid)
        state = status if (status_on is None or status_on <= day) else "open"           # a later status change was not known on `day`
        p = _rows(con, "SELECT probability, prob_date FROM storyline_prob_s80 WHERE storyline_id=? AND prob_date <= ? ORDER BY prob_date DESC LIMIT 1", [sid, day])
        when = max([d for d in (opened_on, p[0][1] if p else None) if d is not None])
        txt = f"{'up' if (direction or 0) > 0 else 'down'} storyline on {subject}, {state}" + (f", probability {p[0][0]:.0%} on {p[0][1]}" if p else "") + (f", exposure {exposure:.0%}" if exposure else "")
        out.append({"kind": "storyline", "id": f"story:{sid}", "day": _day(when), "source": "storylines", "title": _clip(claim, 160), "text": txt, "_open": state == "open"})
    out.sort(key=lambda x: (not x["_open"], x["day"]), reverse=False)
    for it in out:
        it.pop("_open", None)
    return out


def _pick_skip(con, cut: datetime, who: dict) -> List[dict]:
    if not who["isin"]:
        return []
    day = cut.date()
    out = []
    for pid, sym, src, thesis, brk, state, proposed_on, state_on, reason in _rows(con, "SELECT pick_id, symbol, source, thesis, break_condition, state, proposed_on, state_changed_on, state_reason FROM picks_s83 "
                                                                                     "WHERE isin=? AND proposed_on <= ? ORDER BY pick_id DESC LIMIT 1", [who["isin"], day]):
        out.append({"kind": "pick", "id": f"pick:{pid}", "day": _day(proposed_on), "source": f"picks ({src})", "title": f"{sym} is a pick, {state}",
                    "text": f"thesis: {thesis} | breaks if: {brk}" + (f" | {state} on {state_on}: {reason}" if state_on and state_on <= day and reason else "")})
    for sid, sym, why, on in _rows(con, "SELECT skip_id, symbol, why, skipped_on FROM skips_s83 WHERE isin=? AND skipped_on <= ? ORDER BY skipped_on DESC, skip_id DESC LIMIT 1", [who["isin"], day]):
        out.append({"kind": "skip", "id": f"skip:{sid}", "day": _day(on), "source": "skips", "title": f"{sym} was looked at and skipped", "text": why or ""})
    return out


def _cases(con, cut: datetime, who: dict, kind: Optional[str]) -> List[dict]:
    day = cut.date()
    rows = []
    if who["isin"]:
        rows += [(r, "case") for r in _rows(con, "SELECT case_id, opened_on, kind, symbol, title, state, klass, pending, summary, closed_reason FROM think_cases_s84 WHERE isin=? AND opened_on <= ? AND state <> 'noticed' "
                                                 "ORDER BY opened_on DESC, case_id DESC LIMIT 4", [who["isin"], day])]
    if kind:
        rows += [(r, "case_same_kind") for r in _rows(con, "SELECT case_id, opened_on, kind, symbol, title, state, klass, pending, summary, closed_reason FROM think_cases_s84 WHERE kind=? AND opened_on <= ? AND state <> 'noticed' "
                                                       "AND coalesce(isin,'') <> ? ORDER BY opened_on DESC, case_id DESC LIMIT 2", [kind, day, who["isin"] or ""])]
    out = []
    for (cid, opened, ckind, sym, title, state, klass, pending, summary, closed_reason), why in rows:
        bits = [f"{state}" + (f", class {klass}" if klass else ""), _clip(summary, 240)] if summary else [f"{state}" + (f", class {klass}" if klass else "")]
        if pending:
            bits.append(f"pending: {_clip(pending, 120)}")
        for acted, reason, dec_on, dec_id in _rows(con, "SELECT acted_option, reason, decided_on, decision_id FROM think_decisions_s84 WHERE case_id=? AND decided_on <= ? ORDER BY decision_id LIMIT 2", [cid, day]):
            bits.append(f"chose {acted} on {dec_on}" + (f" ({_clip(reason, 100)})" if reason else ""))
            for hz, trk, opt, vs, sc_on in _rows(con, "SELECT horizon_sessions, track, option, vs_nothing_inr, scored_on FROM think_scores_s84 WHERE decision_id=? AND scored_on <= ? ORDER BY horizon_sessions, track", [dec_id, day]):
                bits.append(f"scored at {hz} sessions ({trk} track, {opt}): Rs {vs:,.0f} against doing nothing" if vs is not None else f"scored at {hz} sessions ({trk} track)")
        out.append({"kind": why, "id": f"case:{cid}", "day": _day(opened), "source": f"think case ({ckind})", "title": f"case #{cid} on {sym or 'the market'}: {_clip(title, 120)}", "text": "; ".join(bits)})
    return out


# --- recall --------------------------------------------------------------------------------------------------------------------------

def recall(con, now: datetime, *, isin: Optional[str] = None, symbol: Optional[str] = None, topic: Optional[str] = None, sector: Optional[str] = None, asof=None, limit_chars: int = 6000,
           kind: Optional[str] = None) -> dict:
    """What we already know about a name (by `isin` or `symbol`) or a topic/sector, point-in-time at `asof` (a date or datetime, default `now`), newest first, inside `limit_chars` of text.
    `kind`: a case kind, to add earlier cases of the same kind on other names. Returns {"items", "text", "n"}; items are {"kind","id","day","source","title","text"} (+ extra keys)."""
    cut = _cutoff(now, asof)
    who = resolve(con, isin, symbol)
    item_chars = int(_s("recall_item_chars"))
    pools: List[List[dict]] = []
    for src in (lambda: _notes(con, cut, who, topic, sector), lambda: _memory(con, cut, who, topic), lambda: _graph(con, cut, who, sector if not who["isin"] else None),
                lambda: _storylines(con, cut, who, topic, sector), lambda: _pick_skip(con, cut, who), lambda: _cases(con, cut, who, kind)):
        try:
            pools.append(src())
        except Exception as e:                                       # recall never raises
            log.warning("recall source failed: %s", e)
            pools.append([])
    items: List[dict] = []
    taken: Dict[str, int] = {}
    for pool in pools:
        for it in pool:
            k = it["kind"]
            if taken.get(k, 0) >= CAPS.get(k, 3):
                continue
            taken[k] = taken.get(k, 0) + 1
            it = dict(it)
            it["text"] = _clip(it["text"], item_chars)
            items.append(it)
    # keep the newest of every kind first, then fill by newest; the result is shown newest first
    items_sorted = sorted(items, key=lambda x: x["day"], reverse=True)
    chosen, used, firsts = [], 0, set()
    for it in items_sorted:
        if it["kind"] not in firsts:
            firsts.add(it["kind"])
            chosen.append(it)
            used += len(_line(it))
    for it in items_sorted:
        if it in chosen:
            continue
        ln = len(_line(it))
        if used + ln > limit_chars:
            continue
        chosen.append(it)
        used += ln
    while chosen and sum(len(_line(i)) for i in chosen) > limit_chars and len(chosen) > 1:      # the firsts alone may be over the limit: drop the oldest
        chosen.remove(min(chosen, key=lambda x: x["day"]))
    chosen.sort(key=lambda x: x["day"], reverse=True)
    return {"items": chosen, "text": "\n".join(_line(i) for i in chosen), "n": len(chosen), "resolved": who}


def _line(it: dict) -> str:
    return f"- {it['day']} [{it['kind']} {it['id']}; {it['source']}] {it['title']}" + (f": {it['text']}" if it["text"] else "")


# --- stored is not used until something reads it -----------------------------------------------------------------------------------------

def mark_used(con, items, *, by_kind: str, by_ref, day) -> int:
    """One `knowledge_use_s84` row per item a decision (a case, a desk step, a pick, a company card, a session) read, once per item, reader and day. Returns the rows added."""
    from pflab.pm.store import next_id
    n = 0
    day = day.date() if isinstance(day, datetime) else day
    for it in items or []:
        key = [str(it["kind"]), str(it["id"]), by_kind, str(by_ref), day]
        if con.execute("SELECT 1 FROM knowledge_use_s84 WHERE item_kind=? AND item_id=? AND used_by_kind=? AND used_by_ref=? AND day=?", key).fetchone():
            continue
        try:
            item_day = date.fromisoformat(str(it.get("day"))[:10])
        except ValueError:
            item_day = None
        uid = next_id(con, "knowledge_use_s84", "use_id")
        con.execute("INSERT INTO knowledge_use_s84 VALUES (?,?,?,?,?,?,?)", [uid, it["kind"], str(it["id"]), item_day, by_kind, str(by_ref), day])
        n += 1
    return n


def _paid(con, month_from: Optional[datetime] = None) -> List[dict]:
    """Every paid note: analyst API notes (api_calls with a stored note) and written-back notes with a cost. {"doc_id","day","rupees"}."""
    out = []
    for doc, at, inr in _rows(con, "SELECT note_doc, created_at, cost_inr FROM api_calls WHERE status='done' AND note_doc IS NOT NULL AND coalesce(cost_inr,0) > 0"):
        out.append({"doc_id": doc, "day": at.date(), "rupees": float(inr)})
    for doc, day, inr in _rows(con, "SELECT doc_id, day, cost_rupees FROM recall_notes_s84 WHERE coalesce(cost_rupees,0) > 0"):
        out.append({"doc_id": doc, "day": day, "rupees": float(inr)})
    return out


def knowledge_line(con, day: date) -> dict:
    """The nightly line for Today and the reports: paid notes written this month, how many a decision has read, and the rupees of notes (30 days old or more) nothing has read in 30 days."""
    day = day.date() if isinstance(day, datetime) else day
    first = date(day.year, day.month, 1)
    paid = _paid(con)
    uses: Dict[str, List[date]] = {}
    for iid, d in _rows(con, "SELECT item_id, day FROM knowledge_use_s84 WHERE day <= ?", [day]):
        uses.setdefault(str(iid), []).append(d)
    month = [p for p in paid if first <= p["day"] <= day]
    read = [p for p in month if uses.get(str(p["doc_id"]))]
    unread = sum(p["rupees"] for p in paid if p["day"] <= day - timedelta(days=30) and not any(d > day - timedelta(days=30) for d in uses.get(str(p["doc_id"]), [])))
    text = (f"Paid notes this month: {len(month)}; a decision has read {len(read)} of them; Rs {unread:,.0f} of notes nothing has read in 30 days."
            if month or unread else "Paid notes this month: none; nothing paid for is waiting unread.")
    return {"paid_notes_this_month": len(month), "read_by_a_decision": len(read), "unread_30d_rupees": round(unread, 2), "text": text}


# --- never pay twice -------------------------------------------------------------------------------------------------------------------------

_SYMS = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9&\-]{2,14}(?![A-Za-z0-9])")


def _isins_in(con, text: str) -> List[str]:
    """ISINs of the names written in capitals in `text` that are listed in the graph's nodes or the instruments (by code; a word that is not a symbol is ignored)."""
    out = []
    for tok in dict.fromkeys(_SYMS.findall(text or "")):
        r = _rows(con, "SELECT isin FROM kg2_node WHERE upper(symbol)=? UNION SELECT isin FROM instruments WHERE upper(symbol)=? LIMIT 1", [tok, tok])
        if r:
            out.append(r[0][0])
    return out[:4]


def _price(con, isin: str, day: date) -> Optional[float]:
    r = _rows(con, "SELECT close FROM prices WHERE isin=? AND date <= ? AND close > 0 ORDER BY date DESC LIMIT 1", [isin, day])
    return float(r[0][0]) if r else None


def move_since(con, isin: str, since: date, now: datetime) -> dict:
    """{"move": fraction or None, "threshold": fraction}: the close-to-close move of a name from `since` to `now`, against the watch's own measures: `move_sigmas` of its usual daily move over the
    sessions between (from its last 60 closes), never more than a fall of `fall_pct_10d`."""
    st = think.settings()
    cap = float(st["fall_pct_10d"])
    p0, p1 = _price(con, isin, since), _price(con, isin, now.date())
    if not p0 or not p1:
        return {"move": None, "threshold": cap}
    closes = [float(r[0]) for r in _rows(con, "SELECT close FROM prices WHERE isin=? AND date <= ? AND close > 0 ORDER BY date DESC LIMIT 61", [isin, now.date()])][::-1]
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    thr = cap
    if len(rets) >= 20:
        m = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
        sessions = max(1, int((now.date() - since).days * 5 / 7))
        thr = min(cap, max(MOVE_FLOOR, float(st["move_sigmas"]) * sd * math.sqrt(sessions)))        # never under a 2% drift: a flat history must not make every note stale
    return {"move": p1 / p0 - 1, "threshold": thr}


def changed_since(con, now: datetime, isin: Optional[str], since: datetime) -> dict:
    """What happened to the name since a note was written: {"events": [...material kg2 events], "move": {...}, "changed": bool}."""
    if not isin:
        return {"events": [], "move": {"move": None, "threshold": None}, "changed": False}
    ev = [{"event_id": r[0], "ts": r[1].isoformat(), "kind": r[2], "severity": r[3], "headline": r[4]} for r in _rows(
        con, "SELECT event_id, ts, kind, severity, headline FROM kg2_event e WHERE isin=? AND ts > ? AND ts <= ? AND ts IS NOT NULL AND (severity <> 'low' OR kind IN ({})) ORDER BY ts DESC LIMIT 8".format(
            ",".join(f"'{k}'" for k in STALE_KINDS)), [isin, since, now])]
    mv = move_since(con, isin, since.date(), now)
    big = mv["move"] is not None and abs(mv["move"]) >= mv["threshold"]
    return {"events": ev, "move": mv, "changed": bool(ev) or big}


def same_subject_fresh(con, now: datetime, *, isin: Optional[str] = None, topic: Optional[str] = None, since_move: Optional[float] = None, question: Optional[str] = None,
                       symbol: Optional[str] = None) -> Optional[dict]:
    """The "never pay twice" check. The newest note on the same subject (the name by `isin`/`symbol`, else a topic, else a question that shares half its words with the note's question) with no
    event, result or move beyond the watch's thresholds since it was written, and not older than `recall_max_age_days` (`recall_topic_days` when there is no name to check events for).
    Returns the note as a recall item with its full text, `age_days` and `why`; None when a fresh read is due. `since_move`: the caller's own move since the note (a fraction), else it is computed."""
    who = resolve(con, isin, symbol)
    if not who["isin"] and question:
        found = _isins_in(con, question)
        if found:
            who = resolve(con, found[0], None)
    topic = (topic or "").strip() or None
    if question:                                                     # a question: the note must have answered about the same thing (half its words shared)
        notes = _notes(con, now, {"isin": None, "symbol": None, "name": None}, None, None, question=question)
    elif who["isin"] or who["symbol"] or (topic and topic.lower() not in GENERIC_TOPICS):
        notes = _notes(con, now, who, topic, None)
    else:
        return None
    if not notes:
        return None
    for note in notes:                                               # newest first: the newest decides
        try:
            at = datetime.fromisoformat(note["written_at"])
        except ValueError:
            continue
        age = (now - at).total_seconds() / 86400.0
        has_name = bool(who["isin"])
        if age > (float(_s("recall_max_age_days")) if has_name else float(_s("recall_topic_days"))) or age < 0:
            return None
        if has_name:
            ch = changed_since(con, now, who["isin"], at)
            if ch["events"]:
                return None
            if since_move is not None:
                thr = ch["move"]["threshold"]
                if abs(since_move) >= (thr if thr is not None else float(think.settings()["fall_pct_10d"])):
                    return None
            elif ch["move"]["move"] is not None and abs(ch["move"]["move"]) >= ch["move"]["threshold"]:
                return None
        return {**note, "age_days": round(age, 1), "why": "no event, result or move beyond the watch's thresholds since the note was written"}
    return None


# --- written back -----------------------------------------------------------------------------------------------------------------------

def write_back(con, now: datetime, *, isin: Optional[str] = None, symbol: Optional[str] = None, topic: Optional[str] = None, title: str, text: str, source: str, cost_rupees: float = 0.0,
               case_id: Optional[int] = None) -> str:
    """Store a dated note on the names it is about, where `recall` finds it tomorrow: a row in `recall_notes_s84` (keyed by ISIN, symbol, topic: no graph link needed), the old graph's
    `analyst_note` document (so the old chat and `analyst.latest_note` read it) and a `memory` row. Returns the document id (the item id `recall` gives it). A note needs a title, a text and a source."""
    from pflab.agents import memory as mem
    from pflab.kg import graph as g
    from pflab.pm.store import next_id
    title, text, source = " ".join(str(title or "").split()), str(text or "").strip(), " ".join(str(source or "").split())
    if not (title and text and source):
        raise ValueError("a note needs a title, a text and a source")
    who = resolve(con, isin, symbol)
    topic = (topic or who["symbol"] or "").strip() or None
    key = f"recall|{now.isoformat()}|{who['isin']}|{topic}|{title}|{source}|{case_id}"
    doc = g.doc(con, "analyst_note", key, now, title[:200], source=source, attrs={"answer": text, "recall": True, "isin": who["isin"], "symbol": who["symbol"], "topic": topic, "case_id": case_id,
                                                                                    "cost_rupees": float(cost_rupees or 0.0)}, now=now)
    if who["isin"]:
        g.edge(con, doc, "about", f"company:{who['isin']}", now, "recall", source, now=now)               # a no-op while the old graph is switched off
    nid = next_id(con, "recall_notes_s84", "note_id")
    con.execute("INSERT INTO recall_notes_s84 VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [nid, doc, who["isin"], who["symbol"], topic, now.date(), now, source[:200], title[:300], text, float(cost_rupees or 0.0), case_id])
    mem.remember(con, "note", f"{title} ({now:%Y-%m-%d}): {text[:1500]}", subject=who["symbol"] or topic, source=f"recall:{source}"[:200], now=now)
    return doc
