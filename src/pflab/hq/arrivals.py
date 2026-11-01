"""New material wakes the right investigation (S69). A file he drops that has been read (the Inbox), without any new prompt:

    1  the same bytes or the same evidence already in a case is MERGED (code: the file's hash, the case's evidence)
    2  otherwise the LOCAL model, on this PC, is asked one bounded question: which of these investigations does this concern, and does it add something new,
       contradict the case, repeat it, or concern none? Its answer is a JSON object that code validates (a known case id, a known effect, a confidence);
       invalid output is asked for once more with the error named; still invalid, a plain word-overlap rule decides, and when that is not clear either, the
       choice is ESCALATED: the leading candidates' coordinators (the cloud model) get the material and decide. Every decision is recorded (`hq_routing`) with
       the model, the tries and the outcome, so what the local model did is visible and checkable.
    3  new information or a contradiction is added to the case as evidence, and the case is looked at again: a finished investigation is reopened (the coordinator
       plans only what changed, and may conclude "no change" with its reasons); a running one gets a short research task; open proposals are marked for review.

The local model never writes a number into a case: it only routes. Durable scheduling, permissions, retries and the cap on reopenings a day stay in code.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional

EFFECTS = ("new_information", "contradicts", "duplicate", "unrelated")
MAX_PER_DAY = 4                                           # reopenings by arrivals in a day
PER_ROUND = 3                                             # items looked at in one HQ round (the local model is shared)
_LOCAL = threading.Lock()                                 # the GPU: one local question at a time
STOP = set("the a an of to in on and or for with from by at is are was were be been this that these those it its as not no but if then than into over under about "
           "his her their our your how what when which who whom will would should could may might can does did do has have had also more most less very much many "
           "such per vs".split())

SCHEMA = {"type": "object", "properties": {"case_id": {"type": ["integer", "null"]}, "effect": {"type": "string", "enum": list(EFFECTS)},
                                           "confidence": {"type": "number"}, "why": {"type": "string"}},
          "required": ["case_id", "effect", "confidence", "why"]}


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z][a-z0-9&.-]{2,}", (text or "").lower()) if w not in STOP}


def candidates(con, text: str, limit: int = 5) -> List[dict]:
    """Investigations this material may concern, by words they share (code). Finished ones from the last 60 days count; declined ones do not."""
    hay = _words(text)
    out = []
    for cid, goal, state, res, subj, created in con.execute(
            "SELECT m.case_id, m.goal, m.state, m.result_json, coalesce(c.subject, ''), m.created_at FROM hq_missions m JOIN hq_cases c ON c.case_id = m.case_id "
            "WHERE m.state <> 'declined' ORDER BY m.mission_id DESC LIMIT 40").fetchall():
        kw = _words(goal) | _words(subj)
        score = len(kw & hay)
        sym = subj.lower()
        if sym and sym in text.lower():
            score += 3
        if score >= 2:
            ans = (json.loads(res or "{}").get("answer") or "")[:240]
            out.append({"case_id": int(cid), "goal": goal[:200], "state": state, "subject": subj, "score": score, "conclusion": ans})
    out.sort(key=lambda c: -c["score"])
    return out[:limit]


def _ask_local(item: dict, cands: List[dict], error: str = "") -> dict:
    """One bounded question to the local model; returns its parsed JSON (validation is the caller's)."""
    from pflab.llm import client, registry
    model = registry.chosen("general") or "qwen3:8b-q8_0"
    listing = "\n".join(f"- case {c['case_id']} ({c['state']}): {c['goal']}" + (f" | current conclusion: {c['conclusion']}" if c["conclusion"] else "") for c in cands)
    prompt = (f"A document has arrived: '{item['name']}' ({item['kind']}).\nIts text begins:\n{item['text'][:1800]}\n\nOpen investigations:\n{listing}\n\n"
              "Decide: which ONE investigation does it concern (case_id, or null if none), and its effect on that investigation: new_information (adds something not "
              "already known), contradicts (conflicts with its current conclusion), duplicate (says what is already known), or unrelated. Give a confidence from 0 to 1 "
              "and a one-sentence reason from the text. Answer with JSON only." + (f"\nYour previous answer was invalid: {error}. Answer again, valid JSON only." if error else ""))
    with _LOCAL:
        r = client.chat(model, [{"role": "system", "content": "You route documents to investigations for a private investor's system. You only choose; you never state facts "
                                 "or numbers of your own. Answer with a JSON object {case_id, effect, confidence, why}."},
                                {"role": "user", "content": prompt}], num_predict=300, num_ctx=4096, fmt=SCHEMA)
    return {"raw": r.text, "model": r.model}


def _validate(raw: str, cands: List[dict]) -> (Optional[dict], str):
    try:
        d = json.loads(raw)
    except (ValueError, TypeError):
        m = re.search(r"\{.*\}", raw or "", re.S)
        try:
            d = json.loads(m.group(0)) if m else None
        except ValueError:
            d = None
    if not isinstance(d, dict):
        return None, "not a JSON object"
    ids = {c["case_id"] for c in cands}
    cid = d.get("case_id")
    if cid is not None:
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            return None, "case_id is not an integer or null"
        if cid not in ids:
            return None, f"case_id {cid} is not one of {sorted(ids)}"
    if d.get("effect") not in EFFECTS:
        return None, f"effect must be one of {EFFECTS}"
    try:
        conf = float(d.get("confidence"))
    except (TypeError, ValueError):
        return None, "confidence is not a number"
    if not 0.0 <= conf <= 1.0:
        return None, "confidence must be between 0 and 1"
    if d["effect"] != "unrelated" and cid is None:
        return None, "an effect on no investigation must be 'unrelated'"
    return {"case_id": cid, "effect": d["effect"], "confidence": conf, "why": str(d.get("why", ""))[:240]}, ""


def route(con, item: dict, cands: List[dict], ask=None) -> dict:
    """Decide where an item goes. `ask(item, cands, error)` is the local model (injected in tests). Returns {case_id, effect, confidence, why, outcome, tries, model, raw}:
    outcome is 'local' (the model's valid answer), 'local_retry' (valid on the second try), 'rule' (the overlap rule after invalid output) or 'escalated'."""
    ask = ask or _ask_local
    err, raw, model, tries = "", "", None, 0
    for tries in (1, 2):
        try:
            got = ask(item, cands, err)
        except Exception as e:                           # Ollama down, model missing: said, then the rule
            raw, err = f"{type(e).__name__}: {str(e)[:160]}", f"the local model failed ({type(e).__name__})"
            break
        raw, model = got["raw"], got.get("model")
        d, err = _validate(raw, cands)
        if d:
            return {**d, "outcome": "local" if tries == 1 else "local_retry", "tries": tries, "model": model, "raw": raw[:600]}
    # invalid twice (or the model is unavailable): a plain rule where it is clear, the cloud coordinator where it is not
    top = cands[0]
    clear = len(cands) == 1 or top["score"] >= cands[1]["score"] + 3
    if clear:
        return {"case_id": top["case_id"], "effect": "new_information", "confidence": 0.5, "why": f"the local model's answer was unusable ({err}); the words it shares with the "
                "investigation decided", "outcome": "rule", "tries": tries, "model": model, "raw": raw[:600]}
    return {"case_id": top["case_id"], "effect": "new_information", "confidence": 0.3, "why": f"the local model's answer was unusable ({err}) and two investigations fit; "
            "handed to the coordinator", "outcome": "escalated", "tries": tries, "model": model, "raw": raw[:600]}


def _record(con, now: datetime, kind: str, subject: str, cands: List[dict], d: dict, note: str = "") -> int:
    from pflab.pm.store import next_id
    did = next_id(con, "hq_routing", "decision_id")
    con.execute("INSERT INTO hq_routing VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [did, now, kind, subject, json.dumps([{k: c[k] for k in ("case_id", "score", "state")} for c in cands]),
                 json.dumps({k: d.get(k) for k in ("case_id", "effect", "confidence", "why")}) if d else None, (d or {}).get("outcome", "none"), (d or {}).get("tries"),
                 (d or {}).get("model"), (d or {}).get("raw"), note[:300]])
    return did


def _handle(con, now: datetime, item: dict, d: dict, cands: List[dict]) -> str:
    """Act on a routing decision: evidence, then the follow-up the case's state calls for. Returns a sentence."""
    from pflab.hq import cases, missions, proposals
    cid, eff = d["case_id"], d["effect"]
    if eff == "unrelated" or cid is None:
        return "unrelated to every open investigation"
    sid = f"inbox:{item['id']}"
    stance = "against" if eff == "contradicts" else "neutral"
    text = f"File '{item['name']}' arrived ({item['kind']}): {d['why']} | {item['text'][:500].strip()}"
    if eff == "duplicate":
        cases.add_evidence(con, cid, now, text, stance="neutral", kind="dataset", source_id=sid, source_kind="dataset")
        cases.log(con, cid, now, "arrival", f"file '{item['name']}' repeats what the case already holds: noted, nothing reopened")
        return f"repeats case #{cid}: noted"
    cases.add_evidence(con, cid, now, text, stance=stance, kind="dataset", source_id=sid, source_kind="dataset", published_at=item.get("at"))
    proposals.evidence_changed(con, now, cid, f"new material: {item['name']} ({eff})")
    m = missions.mission_of(con, cid)
    if m is None:
        return f"added to case #{cid}"
    why = f"new material arrived without a new prompt: '{item['name']}' ({eff}, {d['outcome']}): {d['why']}"
    if m["state"] == "done":
        if _reopened_today(con, now) >= MAX_PER_DAY:
            cases.log(con, cid, now, "arrival", f"{why} | held: today's limit of {MAX_PER_DAY} reopenings was reached; it is reviewed on the next round of tomorrow")
            return f"added to case #{cid}; its reopening waits for tomorrow's limit"
        r = missions.reopen(con, now, cid, why)
        return f"reopened case #{cid}" if r["reopened"] else f"added to case #{cid}"
    if m["state"] in ("working", "reviewing", "planning", "synthesising", "awaiting_approval"):
        cases.log(con, cid, now, "arrival", why)
        if m["state"] == "working":
            missions.add_task(con, now, cid, "research", f"New material arrived while this investigation runs: '{item['name']}' ({eff}). Read it with the evidence already "
                              f"in the case, record what it changes (or that it changes nothing) as evidence with its source.", promise={"evidence": 1}, key=f"arrival:{item['id']}")
        return f"given to the running case #{cid}"
    return f"added to case #{cid}"


def _reopened_today(con, now: datetime) -> int:
    return int(con.execute("SELECT count(*) FROM hq_case_log WHERE event='reopened' AND detail LIKE 'new material arrived%' AND logged_at >= ?",
                           [datetime(now.year, now.month, now.day)]).fetchone()[0])


def pending_items(con, limit: int = PER_ROUND) -> List[dict]:
    from pflab.app.inbox import EVIDENCE_STATES
    q = ",".join("?" * len(EVIDENCE_STATES))
    rows = con.execute(f"SELECT item_id, name, kind, coalesce(text, ''), sha, created_at FROM inbox_items WHERE status IN ({q}) AND kind NOT IN ('statement','ledger','tradebook','contract_note') "
                       f"AND length(coalesce(text, '')) > 80 AND 'inbox:' || cast(item_id AS VARCHAR) NOT IN (SELECT subject FROM hq_routing WHERE kind='inbox') "
                       f"ORDER BY item_id LIMIT ?", [*EVIDENCE_STATES, limit]).fetchall()
    return [{"id": r[0], "name": r[1], "kind": r[2], "text": r[3], "sha": r[4], "at": r[5]} for r in rows]


def scan(rt, ask=None) -> dict:
    """The HQ round's step: route the newly read files. Free of cloud cost; the follow-ups it starts spend through the usual limits."""
    con, now = rt.cursor(), rt.clock()
    out = {"routed": 0, "reopened": 0, "merged": 0, "unrelated": 0, "details": []}
    for it in pending_items(con):
        cands = candidates(con, it["name"] + " " + it["text"])
        sid = f"inbox:{it['id']}"
        dup = con.execute("SELECT case_id FROM hq_case_evidence WHERE source_id=? LIMIT 1", [sid]).fetchone()
        if dup:                                                       # the same file, already evidence: merged without asking anyone
            _record(con, now, "inbox", sid, cands, {"case_id": dup[0], "effect": "duplicate", "confidence": 1.0, "why": "the same file is already evidence", "outcome": "code",
                                                  "tries": 0}, "same file")
            out["merged"] += 1
            continue
        if not cands:
            _record(con, now, "inbox", sid, [], {"case_id": None, "effect": "unrelated", "confidence": 1.0, "why": "no open investigation shares its words", "outcome": "code",
                                              "tries": 0}, "no candidates")
            out["unrelated"] += 1
            continue
        d = route(con, it, cands, ask)
        if d["outcome"] == "escalated":                              # two investigations fit and the model could not say: the leading one's coordinator decides
            d["case_id"] = cands[0]["case_id"]
        did = _record(con, now, "inbox", sid, cands, d)
        res = _handle(con, now, it, d, cands)
        con.execute("UPDATE hq_routing SET note=? WHERE decision_id=?", [res[:300], did])
        out["routed"] += 1
        out["reopened"] += res.startswith("reopened")
        out["details"].append({"item": it["name"], "to": d["case_id"], "effect": d["effect"], "how": d["outcome"], "result": res})
    if out["routed"] or out["merged"]:
        rt.bump("hq")
    return out


def recent(con, limit: int = 20) -> List[dict]:
    return [{"id": r[0], "at": str(r[1])[:16], "kind": r[2], "subject": r[3], "chosen": json.loads(r[4] or "null"), "outcome": r[5], "tries": r[6], "model": r[7], "note": r[8]}
            for r in con.execute("SELECT decision_id, decided_at, kind, subject, chosen_json, outcome, tries, model, note FROM hq_routing ORDER BY decision_id DESC LIMIT ?", [limit]).fetchall()]
