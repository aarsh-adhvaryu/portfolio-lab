"""Working memory (S72): what the system concluded before and why, what contradicts it, what was already checked, what changed, what is still open.

The knowledge graph held documents (filings, results, news, deals), and a growing count of them proves nothing about learning. Learning is when what was found and corrected
changes the next piece of work. So memory here is judged by its effects, and it answers five questions, by code, at the start of any task:

    conclusions     what did we conclude about this before, and why (an older view is marked as older when a newer investigation covers the same subject)
    contradictions  what evidence about the same subject, written or read after that conclusion, goes against it
    methods         which calculation was already made and checked, so it is re-run on today's record instead of being written again
    changed         what changed since the last conclusion: documents, the price, his trades, the rules, his answers
    open            what is still unresolved: requests waiting for a report, evidence marked missing, questions to him, reviews that are due

The records (investigations, evidence, calculations, reviews) stay the source of truth; `recall` reads them, and `record_case` links them into the graph (an investigation, its
conclusion, the methods it used and the subjects they are about) so the graph tools and screens can follow the same links. An embedding may one day propose a link; it never
answers. `offer` records what memory put in front of a new investigation and `observe` records, when it is done, what it really did with it (`hq_memory_effects`): a method
re-run, a contradiction taken up, an earlier conclusion cited, a question closed. Those counts, not the number of nodes, say whether the memory is working.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence

KINDS = ("conclusion_cited", "method_reused", "contradiction_addressed", "question_closed")
DAY = timedelta(days=1)


def _themes() -> List[dict]:
    try:
        from pathlib import Path
        from pflab import _toml
        d = _toml.load(Path(__file__).resolve().parents[3] / "configs" / "themes.toml").get("theme", {})
        return [{"code": k, "label": v.get("label", k)} for k, v in d.items()]
    except Exception:
        return []


def subjects_of(con, text: str) -> List[str]:
    """The companies, sectors and themes a text is about, as graph ids: company:<ISIN>, sector:<label>, theme:<code>."""
    t = (text or "")
    low = t.lower()
    out: List[str] = []
    for isin, sym, name in con.execute("SELECT isin, symbol, name FROM instruments WHERE asset_class = 'equity' AND listed").fetchall():
        hit = bool(sym) and len(sym) >= 3 and re.search(r"\b" + re.escape(sym) + r"\b", t, re.I)
        if not hit and name:
            first = " ".join(name.split()[:2]).lower()
            hit = len(first) >= 6 and first in low
        if hit:
            out.append(f"company:{isin}")
    for (sector,) in con.execute("SELECT DISTINCT sector FROM instruments WHERE sector IS NOT NULL AND asset_class = 'equity'").fetchall():
        if len(sector) >= 4 and re.search(r"\b" + re.escape(sector.lower()) + r"\b", low):
            out.append(f"sector:{sector}")
    for th in _themes():
        toks = [x for x in th["code"].split("_") if len(x) >= 2 and x not in ("it", "and", "the")]
        if re.search(r"\b" + re.escape(th["label"].lower()) + r"\b", low) or any(re.search(r"\b" + re.escape(x) + r"\b", low) for x in toks):
            out.append(f"theme:{th['code']}")
    return list(dict.fromkeys(out))


def _case_subjects(con, cid: int, question: str, isin: Optional[str]) -> List[str]:
    s = subjects_of(con, question)
    return list(dict.fromkeys(([f"company:{isin}"] if isin else []) + s))


def _concluded(con, exclude: Optional[int]) -> List[dict]:
    """Investigations that reached a conclusion, newest first, with what they decided and how the independent review judged them."""
    rows = con.execute(
        "SELECT c.case_id, c.question, c.isin, c.decision, c.decision_reason, c.closed_at, c.next_review_at, m.result_json, m.state "
        "FROM hq_cases c LEFT JOIN hq_missions m ON m.case_id = c.case_id WHERE c.decision IS NOT NULL ORDER BY coalesce(c.closed_at, c.updated_at) DESC LIMIT 60").fetchall()
    out = []
    for cid, q, isin, dec, why, closed, nxt, res, mstate in rows:
        if cid == exclude:
            continue
        r = {}
        try:
            r = json.loads(res or "{}") if res else {}
        except ValueError:
            pass
        rev = con.execute("SELECT outcome FROM hq_case_reviews WHERE case_id = ? AND outcome IS NOT NULL ORDER BY review_id DESC LIMIT 1", [cid]).fetchone()
        out.append({"case_id": int(cid), "question": q, "isin": isin, "decision": dec, "reason": why or "", "at": closed, "next_review": nxt,
                    "answer": str(r.get("answer", ""))[:600], "limits": str(r.get("limitations", ""))[:300], "review": rev[0] if rev else None,
                    "subjects": _case_subjects(con, cid, q, isin)})
    return out


def recall(con, about, now: datetime, exclude_case: Optional[int] = None) -> dict:
    """The five answers for a text (or a list of graph ids). Every item names the record it comes from, so a reader can follow it."""
    subs = about if isinstance(about, (list, tuple)) else subjects_of(con, str(about))
    want = set(subs)
    out: Dict[str, object] = {"subjects": list(subs), "conclusions": [], "contradictions": [], "methods": [], "changed": [], "open": [], "rules": []}
    if not want:
        return out
    cs = [c for c in _concluded(con, exclude_case) if want & set(c["subjects"])]
    for i, c in enumerate(cs):
        newer = next((n for n in cs[:i] if set(n["subjects"]) & set(c["subjects"])), None)      # cs is newest first: an earlier entry is a newer conclusion
        out["conclusions"].append({**c, "at": str(c["at"])[:10] if c["at"] else None, "next_review": str(c["next_review"])[:10] if c["next_review"] else None,
                                   "status": "older" if newer else "current", "newer_case": newer["case_id"] if newer else None})
    out["conclusions"] = out["conclusions"][:4]
    ids = [c["case_id"] for c in cs]
    since = min((c["at"] for c in cs if c["at"]), default=None)
    if cs and ids:
        q = ",".join("?" * len(ids))
        # evidence AGAINST, in any investigation on the same subject, or a material reading of a held or watched name, written after the earliest conclusion in scope
        for ev_id, cid, text, added, src in con.execute(
                f"SELECT ev_id, case_id, text, added_at, source_id FROM hq_case_evidence WHERE stance = 'against' AND case_id IN ({q}) ORDER BY added_at DESC LIMIT 8", ids).fetchall():
            c = next(x for x in cs if x["case_id"] == cid)
            out["contradictions"].append({"ev_id": ev_id, "case_id": cid, "text": text[:200], "at": str(added)[:10], "source": src, "after_conclusion": bool(c["at"] and added > c["at"])})
        isins = [s.split(":", 1)[1] for s in want if s.startswith("company:")]
        if isins and since:
            ph = ",".join("?" * len(isins))
            for doc, read_at, summary, js in con.execute(
                    f"SELECT doc_id, read_at, summary, isins_json FROM hq_readings WHERE material = 'yes' AND read_at > ? ORDER BY read_at DESC LIMIT 40", [since]).fetchall():
                try:
                    hit = set(json.loads(js or "[]")) & set(isins)
                except ValueError:
                    hit = set()
                if hit:
                    out["contradictions"].append({"ev_id": None, "case_id": None, "text": f"a material document was read: {str(summary or '')[:160]}", "at": str(read_at)[:10],
                                                  "source": doc, "after_conclusion": True})
        # checked methods that can be run again
        for calc_id, cid, code, params, created, chk in con.execute(
                f"SELECT calc_id, case_id, code, params_json, created_at, check_json FROM hq_calcs WHERE status = 'checked' AND case_id IN ({q}) ORDER BY calc_id DESC LIMIT 12", ids).fetchall():
            if str(code).startswith("trusted:"):
                out["methods"].append({"calc_id": calc_id, "case_id": cid, "tool": str(code)[8:], "params": _short(params), "at": str(created)[:10],
                                       "how": "re-run on today's record (reviewed code; no worker needs to write it)"})
        # open: requests waiting, evidence marked missing, due reviews
        for k, req, st in con.execute(f"SELECT dep_key, request, status FROM hq_case_deps WHERE case_id IN ({q}) AND status <> 'arrived' LIMIT 6", ids).fetchall():
            out["open"].append({"what": f"waiting for: {req[:140]}", "ref": f"dep:{k}"})
        for (text,) in con.execute(f"SELECT text FROM hq_case_evidence WHERE stance = 'missing' AND case_id IN ({q}) LIMIT 4", ids).fetchall():
            out["open"].append({"what": f"evidence missing: {text[:140]}", "ref": "missing"})
        for c in cs:
            if c["next_review"] and c["next_review"] <= now:
                out["open"].append({"what": f"review of #{c['case_id']} was due {str(c['next_review'])[:10]}", "ref": f"case:{c['case_id']}"})
    if since:
        isins = [s.split(":", 1)[1] for s in want if s.startswith("company:")]
        for isin in isins[:3]:
            a = con.execute("SELECT close FROM prices WHERE isin = ? AND date >= ? ORDER BY date LIMIT 1", [isin, since]).fetchone()
            b = con.execute("SELECT close, date FROM prices WHERE isin = ? ORDER BY date DESC LIMIT 1", [isin]).fetchone()
            sym = (con.execute("SELECT symbol FROM instruments WHERE isin = ?", [isin]).fetchone() or [isin])[0]
            if a and b and a[0]:
                out["changed"].append(f"{sym} moved {100.0 * (b[0] / a[0] - 1):+.1f}% in the stored closes since {str(since)[:10]} (latest {b[1]})")
            n = con.execute("SELECT count(*) FROM events WHERE isin = ? AND kind IN ('buy', 'sell') AND trade_date > ?", [isin, since]).fetchone()[0]
            if n:
                out["changed"].append(f"{n} trade(s) in {sym} on your record since {str(since)[:10]}")
        r = con.execute("SELECT count(*) FROM hq_rules WHERE created_at > ? AND status IN ('active', 'pending')", [since]).fetchone()[0]
        if r:
            out["changed"].append(f"{r} house rule(s) made or changed since {str(since)[:10]}")
        a = con.execute("SELECT count(*) FROM questions WHERE answered_at > ?", [since]).fetchone()[0]
        if a:
            out["changed"].append(f"you answered {a} question(s) since {str(since)[:10]}")
    from pflab.hq import rules
    out["rules"] = [{"name": r["name"], "text": r["text"], "kind": r["kind"]} for r in rules.active(con)]
    return out


def _short(params) -> str:
    try:
        p = json.loads(params or "{}")
    except ValueError:
        return str(params)[:80]
    keys = ("falls_json", "falls", "amount", "amount_rupees", "fall_pct", "horizon_months", "default_beta")
    return ", ".join(f"{k}={p[k]}" for k in keys if k in p)[:120] or "stored parameters"


def brief(rec: dict) -> str:
    """The memory in a few lines for a planner or a worker. Empty when there is nothing earlier on this subject."""
    if not rec.get("conclusions") and not rec.get("open") and not rec.get("methods"):
        return ""
    L = ["MEMORY (what the system already knows about this; use it, do not redo it, and say if it still holds):"]
    for c in rec["conclusions"][:3]:
        L.append(f"- Earlier investigation #{c['case_id']} ({c['at']}) concluded '{c['decision']}': {c['reason'][:200] or c['answer'][:200]}"
                 + (f" [independent review: {c['review']}]" if c.get("review") else "") + (f" [older: investigation #{c['newer_case']} is newer]" if c["status"] == "older" else "")
                 + (f" Limits then: {c['limits'][:160]}" if c.get("limits") else ""))
    for x in rec["contradictions"][:4]:
        L.append(f"- Evidence against, {x['at']}{' (after the conclusion)' if x.get('after_conclusion') else ''}: {x['text'][:180]}")
    for m in rec["methods"][:4]:
        L.append(f"- Already checked: {m['tool']} ({m['params']}) in investigation #{m['case_id']}, calculation #{m['calc_id']}; {m['how']}.")
    for line in rec["changed"][:4]:
        L.append(f"- Changed: {line}")
    for o in rec["open"][:4]:
        L.append(f"- Still open: {o['what']}")
    return "\n".join(L)[:2200]


# --- the graph ------------------------------------------------------------------------------------------------------------------

def record_case(con, cid: int, now: datetime) -> int:
    """Link an investigation into the knowledge graph: the investigation, what it is about, its conclusion, the methods it used and the evidence against. Idempotent."""
    from pflab.kg import graph as g
    c = con.execute("SELECT question, isin, decision, decision_reason, closed_at, opened_at FROM hq_cases WHERE case_id = ?", [cid]).fetchone()
    if c is None:
        return 0
    n = 0
    inv, t0 = f"inv:{cid}", c[5] or now
    g.node(con, inv, "investigation", c[0][:120], {"case_id": cid}, now=now)
    for s in _case_subjects(con, cid, c[0], c[1]):
        kind = s.split(":", 1)[0]
        g.node(con, s, kind, s.split(":", 1)[1], None, now=now) if kind != "company" else None
        n += g.edge(con, inv, "about", s, t0, "hq_cases", str(cid), now=now) or 0
    if c[2]:
        cn = f"concl:{cid}"
        g.node(con, cn, "conclusion", f"{c[2]}: {(c[3] or '')[:100]}", {"decision": c[2], "reason": (c[3] or "")[:300]}, now=now)
        n += g.edge(con, inv, "concluded", cn, c[4] or now, "hq_cases", str(cid), now=now) or 0
    for calc_id, code, st in con.execute("SELECT calc_id, code, status FROM hq_calcs WHERE case_id = ? AND status = 'checked'", [cid]).fetchall():
        mn = f"method:{calc_id}"
        g.node(con, mn, "method", str(code)[:60], {"calc_id": calc_id}, now=now)
        n += g.edge(con, inv, "used", mn, t0, "hq_calcs", str(calc_id), now=now) or 0
    for ev_id, text in con.execute("SELECT ev_id, text FROM hq_case_evidence WHERE case_id = ? AND stance = 'against'", [cid]).fetchall():
        en = f"ev:{ev_id}"
        g.node(con, en, "evidence", text[:100], {"stance": "against"}, now=now)
        n += g.edge(con, f"concl:{cid}" if c[2] else inv, "contradicts", en, t0, "hq_case_evidence", str(ev_id), now=now) or 0
    return n


# --- effects --------------------------------------------------------------------------------------------------------------------

def offer(con, now: datetime, cid: int, rec: dict) -> int:
    """Remember what memory put in front of an investigation (so that `observe` can tell what it did with it)."""
    from pflab.pm.store import next_id
    if con.execute("SELECT 1 FROM hq_memory_effects WHERE case_id = ? AND kind = 'offered' LIMIT 1", [cid]).fetchone():
        return 0
    payload = {"conclusions": [c["case_id"] for c in rec.get("conclusions", [])], "methods": [{"calc_id": m["calc_id"], "tool": m["tool"]} for m in rec.get("methods", [])],
               "contradictions": [x.get("source") or x.get("ev_id") for x in rec.get("contradictions", [])], "open": [o["ref"] for o in rec.get("open", [])]}
    if not any(payload.values()):
        return 0
    con.execute("INSERT INTO hq_memory_effects VALUES (?,?,?,?,?,?)", [next_id(con, "hq_memory_effects", "effect_id"), cid, "offered", "", json.dumps(payload), now])
    return 1


def observe(con, now: datetime, cid: int) -> List[str]:
    """When an investigation is done: which of the things memory offered did it really use? Recorded once per kind and reference."""
    from pflab.pm.store import next_id
    row = con.execute("SELECT detail FROM hq_memory_effects WHERE case_id = ? AND kind = 'offered' ORDER BY effect_id LIMIT 1", [cid]).fetchone()
    if not row:
        return []
    offered = json.loads(row[0])
    done = {(k, r) for k, r in con.execute("SELECT kind, ref FROM hq_memory_effects WHERE case_id = ?", [cid]).fetchall()}
    found: List[tuple] = []
    own = {(str(code)[8:], ) for (code,) in con.execute("SELECT code FROM hq_calcs WHERE case_id = ? AND status = 'checked'", [cid]).fetchall() if str(code).startswith("trusted:")}
    for m in offered.get("methods", []):
        if (m["tool"],) in own:
            found.append(("method_reused", f"calc:{m['calc_id']}", f"{m['tool']} was run again in this investigation"))
    res = con.execute("SELECT result_json FROM hq_missions WHERE case_id = ?", [cid]).fetchone()
    try:
        r = json.loads(res[0] or "{}") if res and res[0] else {}
    except ValueError:
        r = {}
    answer = " ".join(str(r.get(k, "")) for k in ("answer", "limitations", "monitor_next"))
    for prior in offered.get("conclusions", []):
        if re.search(rf"(investigation|case)\s*#?\s*{prior}\b|earlier (investigation|conclusion)", answer, re.I) or r.get("change") in ("changed", "unchanged"):
            found.append(("conclusion_cited", f"case:{prior}", f"the answer refers to the earlier conclusion (change: {r.get('change') or 'cited'})"))
    texts = " ".join(t for (t,) in con.execute("SELECT text FROM hq_case_evidence WHERE case_id = ?", [cid]).fetchall()) + " " + answer
    for src in offered.get("contradictions", []):
        if src and (str(src) in texts or (isinstance(src, int) and f"#{src}" in texts)):
            found.append(("contradiction_addressed", f"ev:{src}", "the contradicting item appears in this investigation's evidence or answer"))
    for ref in offered.get("open", []):
        if ref.startswith("dep:"):
            st = con.execute("SELECT status FROM hq_case_deps WHERE dep_key = ? ORDER BY dep_id DESC LIMIT 1", [ref[4:]]).fetchone()
            if st and st[0] == "arrived":
                found.append(("question_closed", ref, "the request that was open has been answered"))
    new = []
    for kind, ref, detail in found:
        if (kind, ref) not in done:
            con.execute("INSERT INTO hq_memory_effects VALUES (?,?,?,?,?,?)", [next_id(con, "hq_memory_effects", "effect_id"), cid, kind, ref, detail, now])
            new.append(kind)
    return new


def effects_summary(con, days: int = 30, now: Optional[datetime] = None) -> dict:
    """The measure of whether memory works: how many recent investigations were offered something, and how many used it, by kind."""
    now = now or datetime.now()
    since = now - timedelta(days=days)
    offered = con.execute("SELECT count(DISTINCT case_id) FROM hq_memory_effects WHERE kind = 'offered' AND logged_at >= ?", [since]).fetchone()[0]
    by = {k: int(n) for k, n in con.execute("SELECT kind, count(*) FROM hq_memory_effects WHERE kind <> 'offered' AND logged_at >= ? GROUP BY 1", [since]).fetchall()}
    used = con.execute("SELECT count(DISTINCT case_id) FROM hq_memory_effects WHERE kind <> 'offered' AND logged_at >= ?", [since]).fetchone()[0]
    return {"days": days, "investigations_offered_memory": int(offered), "investigations_that_used_it": int(used), "by_kind": by}
