"""Investigations (S67, PLAN "completion cycle"): a question the system keeps working on until it can decide, ask or wait.

A case is one question with its record: the evidence (each item with the times it was published, happened and was retrieved, and whether it
is for the thesis, against it, neutral or MISSING), the assumptions, what the data covers, calculations (script, datasets, parameters,
result), the decision, the uncertainty and the next review. Missing evidence and evidence against are different things and are kept apart:
a case with a missing report is not a case against the idea. Everything here is code; the model (the brain's tool loop, `hq/brain.py`) only
chooses what to look at next through the tools in `hq/tools.py`, which call these functions.

States (`hq_cases.status`):
    queued             ready for the brain's next case pass
    running            in a pass now (a pass that died leaves it `retry`: `reap`)
    waiting_data       needs something named in `hq_case_deps` (a report, an answer, a file); `sweep` resumes it when that arrives
    retry              a pass failed; tried again at `next_review_at`, at most `max_attempts` passes in all
    awaiting_approval  the next step needs his yes (a paid call over his limit, an uncontained run, a change of a limit)
    workspace          S68: a scratch case of the assistant's conversation (a calculation or a scenario for him); the brain's case pass never takes it
    done               decided (`decision`, `decision_reason`); `next_review_at` reopens it on that day (`due`)
    failed             out of attempts; shown on the screen, not hidden

Search results and report text are DATA: nothing in them can change a state, a permission or a limit (`add_evidence` stores text; the only
callers that change status are code paths in this module and the tools, which validate their inputs).
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

WAITING_FOR_CONDITION = ("waiting_budget", "waiting_provider")          # S68: waiting is not failing; `next_review_at` is when to look again
STATES = ("queued", "running", "waiting_data", "retry", "awaiting_approval", "done", "failed", "workspace", *WAITING_FOR_CONDITION)
ACTIVE = ("queued", "running", "waiting_data", "retry", "awaiting_approval", *WAITING_FOR_CONDITION)
STANCES = ("for", "against", "neutral", "missing")
DECISIONS = ("nothing", "watch", "suggest", "ask", "tell", "inconclusive")
ORIGINS = ("scheduled", "event", "brain", "chat", "investor", "code")
MAX_STEPS = 4                 # case passes before a case that still has no decision is closed as inconclusive and reviewed later
REVIEW_DAYS = 7               # the default next review of a closed case
RETRY_MINUTES = 15
FRESH_DAYS = {"filing": 30, "result": 100, "article": 3, "web": 7, "dataset": 30, "email": 14, "calculation": 3650, "observation": 3}
MISSION_OWNED = "(SELECT case_id FROM hq_missions WHERE state IN ('planning', 'working', 'reviewing', 'synthesising'))"


def _id(con, table: str, col: str) -> int:
    from pflab.pm.store import next_id
    return next_id(con, table, col)


def subject_key(question: str, subject: Optional[str] = None, day: Optional[date] = None) -> str:
    """The same question about the same subject (on the same day, if given) is one case, however it is worded."""
    words = sorted(set(re.findall(r"[a-z0-9]{4,}", question.lower())))[:12]
    h = hashlib.sha1(" ".join(words).encode()).hexdigest()[:10]
    return f"case:{(subject or 'general').upper()}:{h}" + (f":{day:%Y%m%d}" if day else "")


def log(con, cid: int, now: datetime, event: str, detail: str = "") -> None:
    con.execute("INSERT INTO hq_case_log VALUES (?,?,?,?,?)", [_id(con, "hq_case_log", "log_id"), cid, now, event, detail[:1000]])


def get(con, cid: int) -> Optional[dict]:
    r = con.execute("SELECT case_id, subject_key, opened_at, updated_at, origin, question, subject, isin, status, verdict, assumptions_json, "
                    "coverage_json, uncertainty, decision, decision_reason, next_review_at, attempts, max_attempts, last_error, closed_at, "
                    "pass_id, steps FROM hq_cases WHERE case_id=?", [cid]).fetchone()
    if not r:
        return None
    keys = ["id", "key", "opened", "updated", "origin", "question", "subject", "isin", "status", "verdict", "assumptions", "coverage",
            "uncertainty", "decision", "reason", "next_review", "attempts", "max_attempts", "error", "closed", "pass_id", "steps"]
    d = dict(zip(keys, r))
    d["assumptions"] = json.loads(d["assumptions"] or "[]")
    d["coverage"] = json.loads(d["coverage"] or "{}")
    return d


# --- opening ----------------------------------------------------------------------------------------------------------------

def open_case(con, now: datetime, question: str, *, origin: str = "brain", subject: Optional[str] = None, isin: Optional[str] = None,
              assumptions: Optional[Sequence[str]] = None, key: Optional[str] = None, next_review_at: Optional[datetime] = None) -> Tuple[int, bool]:
    """(case id, True when new). The same key opens one case: asking again returns the open one, and a closed one that is not yet due is
    returned as it is (a new case on the same question needs a new key)."""
    question = question.strip()[:600]
    if not question:
        raise ValueError("a case needs a question")
    if origin not in ORIGINS:
        raise ValueError(f"origin must be one of {ORIGINS}")
    key = key or subject_key(question, subject)
    r = con.execute("SELECT case_id FROM hq_cases WHERE subject_key=?", [key]).fetchone()
    if r:
        return int(r[0]), False
    cid = _id(con, "hq_cases", "case_id")
    con.execute("INSERT INTO hq_cases (case_id, subject_key, opened_at, updated_at, origin, question, subject, isin, status, assumptions_json, "
                "next_review_at, attempts, max_attempts, steps) VALUES (?,?,?,?,?,?,?,?,?,?,?,0,3,0)",
                [cid, key, now, now, origin, question, subject, isin, "queued", json.dumps(list(assumptions or [])[:12]), next_review_at])
    log(con, cid, now, "opened", f"{origin}: {question[:200]}")
    return cid, True


def set_status(con, cid: int, status: str, now: datetime, why: str = "") -> None:
    if status not in STATES:
        raise ValueError(f"status must be one of {STATES}")
    con.execute("UPDATE hq_cases SET status=?, updated_at=? WHERE case_id=?", [status, now, cid])
    if why:
        log(con, cid, now, status, why)


# --- evidence ---------------------------------------------------------------------------------------------------------------------

def add_evidence(con, cid: int, now: datetime, text: str, *, stance: str = "neutral", kind: str = "observation",
                 source_id: Optional[str] = None, source_kind: Optional[str] = None, published_at: Optional[datetime] = None,
                 event_at: Optional[datetime] = None, retrieved_at: Optional[datetime] = None, calc_id: Optional[int] = None,
                 data: Optional[dict] = None) -> int:
    """One piece of evidence. `stance` missing means "this was looked for and is not there": it is a gap, not a finding against.
    Text is kept as data; it is never read as an instruction."""
    if stance not in STANCES:
        raise ValueError(f"stance must be one of {STANCES}")
    if not text.strip():
        raise ValueError("evidence needs text")
    twin = same_evidence(con, cid, text, stance, source_id, published_at)
    if twin is not None:                                    # S69: the same finding again is one piece of evidence, said once in the log
        log(con, cid, now, "merged", f"evidence #{twin} already says this ({stance}, {source_id or 'no source id'}); the copy was merged, not added")
        return twin
    eid = _id(con, "hq_case_evidence", "ev_id")
    con.execute("INSERT INTO hq_case_evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [eid, cid, now, kind, stance, text.strip()[:1200], source_id, source_kind, published_at, event_at, retrieved_at or now,
                 calc_id, json.dumps(data or {}, default=str)])
    con.execute("UPDATE hq_cases SET updated_at=? WHERE case_id=?", [now, cid])
    return eid


def _norm(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9%.]+", " ", text.lower()).strip()


def same_evidence(con, cid: int, text: str, stance: str, source_id: Optional[str], published_at) -> Optional[int]:
    """The id of evidence already in the case that says the same thing with the same stance (the same words, or the same source and date with a
    near-identical sentence). Evidence from the same source that takes the OPPOSITE stance is never merged: a contradiction is material and stays."""
    import difflib
    n = _norm(text)
    for ev_id, st, t, sid, pub in con.execute("SELECT ev_id, stance, text, source_id, published_at FROM hq_case_evidence WHERE case_id=? ORDER BY ev_id", [cid]).fetchall():
        if st != stance or stance == "missing":
            continue
        m = _norm(t)
        if m == n:
            return int(ev_id)
        if source_id and sid == source_id and (published_at is None or pub is None or pub == published_at)                 and difflib.SequenceMatcher(None, m, n).ratio() >= 0.92:
            return int(ev_id)
    return None


def evidence(con, cid: int) -> List[dict]:
    keys = ["id", "at", "kind", "stance", "text", "source_id", "source_kind", "published", "event", "retrieved", "calc_id", "data"]
    rows = con.execute("SELECT ev_id, added_at, kind, stance, text, source_id, source_kind, published_at, event_at, retrieved_at, calc_id, "
                       "data_json FROM hq_case_evidence WHERE case_id=? ORDER BY ev_id", [cid]).fetchall()
    out = []
    for r in rows:
        d = dict(zip(keys, r))
        d["data"] = json.loads(d["data"] or "{}")
        out.append(d)
    return out


def stale_items(ev: Sequence[dict], now: datetime) -> List[dict]:
    """Evidence that is old for its kind (news 3 days, filings 30, results 100, web 7) or undated: not a cause of today."""
    out = []
    for e in ev:
        if e["stance"] == "missing":
            continue
        kind = e.get("source_kind") or e["kind"]
        limit = FRESH_DAYS.get(kind)
        when = e.get("published") or e.get("event")
        if limit is None:
            continue
        if when is None:
            if kind in ("filing", "result", "article", "web"):
                out.append({**e, "why": "undated"})
        elif (now - when).days > limit:
            out.append({**e, "why": f"{(now - when).days} days old (limit {limit})"})
    return out


def assess(con, cid: int, now: Optional[datetime] = None) -> dict:
    """Where the evidence stands, by code: supported | contradicted | mixed | insufficient | open. Missing evidence is `insufficient`
    (never `contradicted`); stale evidence does not count for or against."""
    now = now or datetime.now()
    ev = evidence(con, cid)
    stale = {e["id"] for e in stale_items(ev, now)}
    pro = [e for e in ev if e["stance"] == "for" and e["id"] not in stale]
    con_ = [e for e in ev if e["stance"] == "against" and e["id"] not in stale]
    arrived = {r[0] for r in con.execute("SELECT dep_key FROM hq_case_deps WHERE case_id=? AND status='arrived'", [cid]).fetchall()}
    gaps = [e for e in ev if e["stance"] == "missing" and str(e.get("source_id") or "")[4:] not in arrived]     # a gap that was filled is history
    open_deps = con.execute("SELECT count(*) FROM hq_case_deps WHERE case_id=? AND status='open'", [cid]).fetchone()[0]
    if not pro and not con_:
        verdict = "insufficient" if (gaps or open_deps) else "open"
    elif pro and con_:
        verdict = "mixed" if len(pro) >= len(con_) else "contradicted"
    else:
        verdict = "supported" if pro else "contradicted"
    sources = len({e["source_id"] or e["id"] for e in pro + con_})
    return {"verdict": verdict, "for": len(pro), "against": len(con_), "missing": len(gaps), "stale": len(stale), "sources": sources,
            "open_dependencies": int(open_deps)}


# --- dependencies: a missing report is a named request, not a chat message ----------------------------------------------------------

def request(con, cid: int, now: datetime, dep_key: str, what: str, *, kind: str = "report", match: Optional[dict] = None,
            ask_investor: bool = True) -> Tuple[int, bool]:
    """The case needs something it cannot get itself. One dependency (and, if only he can bring it, one question) per `dep_key`:
    asking again changes nothing. The case waits (`waiting_data`) until `sweep` sees it arrive. `match` says how arrival is recognised:
    {"doc_kind": "result|filing|dataset|email", "isin": ..., "inbox": true, "tijori": symbol, "answer": true}."""
    what = what.strip()[:400]
    if not what:
        raise ValueError("say what is needed")
    r = con.execute("SELECT dep_id, status FROM hq_case_deps WHERE case_id=? AND dep_key=?", [cid, dep_key]).fetchone()
    if r:
        return int(r[0]), False
    did = _id(con, "hq_case_deps", "dep_id")
    qid = None
    if ask_investor:
        from pflab.agents import questions
        c = get(con, cid)
        qid = questions.ask(con, "investigator", f"case:{cid}:{dep_key}",
                            f"For the question \"{c['question'][:160]}\" I need: {what}. I carry on by myself when it arrives.", now)
        if qid is None:
            r2 = con.execute("SELECT q_id FROM questions WHERE subject_key=?", [f"case:{cid}:{dep_key}"]).fetchone()
            qid = int(r2[0]) if r2 else None
    con.execute("INSERT INTO hq_case_deps VALUES (?,?,?,?,?,?,?,?,?,?)",
                [did, cid, dep_key, kind, what, "open", now, None, qid, json.dumps({**(match or {}), "since": str(now)})])
    add_evidence(con, cid, now, f"missing: {what}", stance="missing", kind="observation", source_id=f"dep:{dep_key}", source_kind="request")
    set_status(con, cid, "waiting_data", now, f"waiting for {dep_key}: {what[:160]}")
    return did, True


def _floor(m: dict, requested) -> datetime:
    """The earliest publication date that can answer a report request: the end of the period asked for, else 30 days before the request."""
    from datetime import date as _d
    pe = m.get("period_end")
    try:
        if pe:
            d = _d.fromisoformat(str(pe)[:10])
            return datetime(d.year, d.month, d.day)
    except ValueError:
        pass
    r = requested if isinstance(requested, datetime) else datetime.fromisoformat(str(requested)[:19])
    return r - timedelta(days=30)


def _period_words(pe: str) -> List[str]:
    """How a period's end date may be written inside a sheet: 'Sep 2026', 'September 2026', '2026-09', '30-09-2026', 'Q2 FY27'."""
    from datetime import date as _d
    d = _d.fromisoformat(pe[:10])
    fy = d.year + (1 if d.month >= 4 else 0)
    q = {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3, 1: 4, 2: 4, 3: 4}[d.month]
    # a quarter's end months: only the end month (6, 9, 12, 3) names the quarter
    return [f"{d:%b %Y}".lower(), f"{d:%B %Y}".lower(), f"{d:%Y-%m}", f"{d:%d-%m-%Y}", f"{d:%b-%y}".lower(), f"q{q} fy{str(fy)[2:]}", f"q{q}fy{str(fy)[2:]}"]


def _dropped_dataset(con, m: dict, floor: datetime) -> str:
    """A dataset the inbox read (kind 'dataset' in the graph) with an edge to the company, whose own text or columns name the period asked for
    (when one was named); empty when none fits."""
    rows = con.execute("SELECT d.doc_id, d.title, coalesce(cast(d.attrs_json AS VARCHAR), '') FROM kg_docs d JOIN kg_edges e ON e.src = d.doc_id "
                       "AND e.dst = ? WHERE d.kind = 'dataset' AND d.dup_of IS NULL ORDER BY d.ingested_at", [f"company:{m['isin']}"]).fetchall()
    for doc_id, title, attrs in rows:
        if m.get("period_end"):
            hay = f"{title} {attrs}".lower()
            try:
                words = _period_words(str(m["period_end"]))
            except ValueError:
                words = []
            if words and not any(w in hay for w in words):
                continue                                            # a sheet that does not show the period asked is not that report
        return f"dataset {doc_id}: {(title or '')[:80]}"
    return ""


def arrive(con, cid: int, dep_key: str, now: datetime, detail: str = "") -> bool:
    """The dependency arrived: mark it, and queue the case again when nothing else is open."""
    r = con.execute("SELECT dep_id FROM hq_case_deps WHERE case_id=? AND dep_key=? AND status='open'", [cid, dep_key]).fetchone()
    if not r:
        return False
    con.execute("UPDATE hq_case_deps SET status='arrived', arrived_at=?, detail=? WHERE dep_id=?",
                [now, json.dumps({**json.loads(_dep_detail(con, r[0])), "arrived": detail[:300]}), r[0]])
    add_evidence(con, cid, now, f"arrived: {detail[:300] or dep_key}", stance="neutral", kind="observation", source_kind="arrival")
    if not con.execute("SELECT 1 FROM hq_case_deps WHERE case_id=? AND status='open'", [cid]).fetchone():
        c = get(con, cid)
        if c and c["status"] == "waiting_data":
            set_status(con, cid, "queued", now, f"resumed: {dep_key} arrived ({detail[:120]})")
    return True


def _dep_detail(con, dep_id: int) -> str:
    return con.execute("SELECT coalesce(detail, '{}') FROM hq_case_deps WHERE dep_id=?", [dep_id]).fetchone()[0]


def sweep(con, now: datetime) -> List[Tuple[int, str]]:
    """Look at every open dependency and resume the cases whose data has arrived: a question answered, a document of the right kind
    about the right company since the request, a file in the inbox. Code only and idempotent, so a restart or a wake simply runs it
    again. Returns [(case id, dep key)] of arrivals."""
    out = []
    for dep_id, cid, key, requested, qid, detail in con.execute(
            "SELECT dep_id, case_id, dep_key, requested_at, q_id, detail FROM hq_case_deps WHERE status='open' ORDER BY dep_id").fetchall():
        m = json.loads(detail or "{}")
        found = ""
        if qid is not None:
            a = con.execute("SELECT status, answered_at FROM questions WHERE q_id=?", [qid]).fetchone()
            if a and a[0] in ("answered", "dropped") and m.get("answer", True) and not m.get("doc_kind") and not m.get("inbox"):
                found = f"his answer to question #{qid}" if a[0] == "answered" else f"question #{qid} closed"
        if not found and m.get("doc_kind"):
            # S68: what counts is WHAT the document is, not when it was imported: right company (the edge), right type, published for the
            # period asked (on or after the period's end). A report imported BEFORE the request answers it (no ingested_at floor). Without a
            # period the report must be recent (30 days before the request), so an old one is not taken for the one asked for.
            floor = _floor(m, requested)
            args: list = [m["doc_kind"], floor]
            sql = "SELECT d.doc_id, d.title FROM kg_docs d "
            if m.get("isin"):
                sql += "JOIN kg_edges e ON e.src = d.doc_id AND e.dst = ? "
                args = [f"company:{m['isin']}", *args]
            sql += "WHERE d.kind = ? AND d.published_at >= ? AND d.dup_of IS NULL ORDER BY d.ingested_at LIMIT 1"
            r = con.execute(sql, args).fetchone()
            if r:
                found = f"{m['doc_kind']} {r[0]}: {(r[1] or '')[:80]}"
            elif m.get("isin"):
                found = _dropped_dataset(con, m, floor)           # a file he dropped is a dataset about the company, read by the inbox
        if not found and m.get("inbox"):
            from pflab.app.inbox import EVIDENCE_STATES
            token = str(m.get("company") or (get(con, cid) or {}).get("subject") or "").strip().lower()
            q = ",".join("?" * len(EVIDENCE_STATES))
            # a file that arrived before the request counts; one that failed, is blocked or is still being read does not (it is not evidence yet)
            for iid, name, kind, text, res in con.execute(f"SELECT item_id, name, kind, coalesce(text, ''), coalesce(result_json, '') FROM inbox_items "
                                                          f"WHERE status IN ({q}) ORDER BY item_id", list(EVIDENCE_STATES)).fetchall():
                want = m.get("inbox_kind")
                if want in ("result", "results", "report", "filing", "document"):
                    want = ("other", "market", "result")        # the inbox has no kind 'result': a company report is filed as 'other' or 'market'
                if want and kind not in ((want,) if isinstance(want, str) else want):
                    continue                                      # a statement does not answer a request for a results report
                if token and token not in f"{name} {text[:4000]} {res[:2000]}".lower():
                    continue                                      # a file about someone else does not either
                found = f"file {name} in the inbox"
                break
        if not found and m.get("sandbox"):
            from pflab.agents import sandbox as sb
            if sb.status()["ok"]:
                found = "the sandbox is available"
        if found and arrive(con, cid, key, now, found):
            out.append((cid, key))
    return out


# --- calculations: reproducible -------------------------------------------------------------------------------------------------------

MAX_SNAPSHOT_BYTES = 25_000_000                              # a dataset larger than this is hashed but not kept (not reproducible from the original)


def frame_sha(df) -> str:
    """A hash of a frame's content: column names, types and every row (not its parquet bytes, which differ between library versions)."""
    import pandas as pd
    h = hashlib.sha256()
    h.update(json.dumps([[str(c), str(t)] for c, t in zip(df.columns, df.dtypes)]).encode())
    h.update(pd.util.hash_pandas_object(df.reset_index(drop=True), index=False).values.tobytes())
    return h.hexdigest()


def runtime_versions() -> dict:
    import sys
    out = {"python": sys.version.split()[0]}
    for m in ("pandas", "numpy", "pyarrow", "scipy", "statsmodels"):
        try:
            out[m] = __import__(m).__version__
        except Exception:
            out[m] = None
    return out


def snapshot_inputs(con, calc_id: int, inputs: Optional[dict]) -> None:
    import io
    for name, df in (inputs or {}).items():
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        raw = buf.getvalue()
        keep = len(raw) <= MAX_SNAPSHOT_BYTES
        con.execute("INSERT INTO hq_calc_inputs VALUES (?,?,?,?,?,?,?)",
                    [calc_id, name, frame_sha(df), int(len(df)), len(raw), keep, raw if keep else None])


def record_calc(con, cid: Optional[int], now: datetime, question: str, out, *, attempts: Optional[int] = None) -> int:
    """Keep a workshop outcome: the script, the datasets it read, its parameters, the result and how it was checked, so the number can
    be reproduced (`reproduce`) and an independent check can be shown beside it."""
    spec = getattr(out, "spec", None)
    run = getattr(out, "run", None)
    code = spec.code if spec else ""
    kid = _id(con, "hq_calcs", "calc_id")
    folder = getattr(out, "folder", None)
    con.execute("INSERT INTO hq_calcs (calc_id, case_id, created_at, question, code, code_sha, alt_code, datasets_json, params_json, result_json, "
                "status, contained, attempts, check_json, workshop_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [kid, cid, now, question[:600], code, hashlib.sha256(code.encode()).hexdigest(), (spec.alt_code if spec else "") or None,
                 json.dumps(spec.datasets if spec else []), json.dumps((spec.params if spec else {}) or {}, default=str),
                 json.dumps(run.result if run else {}, default=str), getattr(out, "status", "failed"),
                 (run.contained if run is not None else None), attempts if attempts is not None else len(getattr(out, "attempts", []) or []),   # S70: None = nothing ran
                 json.dumps({"test": (spec.test if spec else {}), "confirm": getattr(out, "confirm", None), "cross_checked": bool(run and run.cross_checked), "measure": bool(getattr(out, "measure", None)),
                             "problems": (run.problems if run else [])}, default=str),
                 getattr(folder, "name", None)])
    con.execute("UPDATE hq_calcs SET versions_json=? WHERE calc_id=?", [json.dumps(runtime_versions()), kid])
    snapshot_inputs(con, kid, getattr(out, "inputs", None))
    if cid is not None:
        ok = getattr(out, "status", "") == "checked"
        confirmed = (getattr(out, "confirm", None) or {}).get("status")
        add_evidence(con, cid, now, f"calculation ({getattr(out, 'status', 'failed')}"
                                    f"{', independently confirmed' if confirmed == 'agrees' else ', NOT independently confirmed' if ok else ''}): "
                                    + "; ".join(f"{k} {v}" for k, v in list((run.result if run else {}).items())[:6]),
                     stance="neutral", kind="calculation", source_id=f"calc:{kid}", source_kind="calculation", calc_id=kid,
                     data={"datasets": spec.datasets if spec else [], "confirmed": confirmed})
    return kid


def compare_results(kept: dict, got: dict, rel: float = 1e-6) -> List[str]:
    """Every difference between two results, complete: a key missing on either side, a number off by more than `rel`, any other value not
    equal (text, booleans, nested values). An empty list means identical."""
    diffs = []
    for k in sorted(set(kept) | set(got), key=str):
        if k not in got:
            diffs.append(f"{k}: kept {kept[k]!r}, the rerun has no such result")
        elif k not in kept:
            diffs.append(f"{k}: the rerun adds {got[k]!r}, which was not kept")
        else:
            a, b = kept[k], got[k]
            num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)       # noqa: E731
            if num(a) and num(b):
                if abs(float(a) - float(b)) > rel * max(1.0, abs(float(a))):
                    diffs.append(f"{k}: kept {a}, rerun {b}")
            elif a != b or type(a) is not type(b) and (isinstance(a, bool) or isinstance(b, bool)):
                diffs.append(f"{k}: kept {a!r}, rerun {b!r}")
    return diffs


def original_inputs(con, calc_id: int, names: List[str]) -> Tuple[Optional[dict], str]:
    """The data the calculation ran on, from its snapshot, each checked against its recorded hash. (None, why) when any is missing."""
    import io
    import pandas as pd
    out = {}
    for n in names:
        r = con.execute("SELECT sha256, kept, data FROM hq_calc_inputs WHERE calc_id=? AND dataset=?", [calc_id, n]).fetchone()
        if r is None:
            return None, f"the original data of '{n}' was not kept (an older record)"
        if not r[1] or r[2] is None:
            return None, f"the original data of '{n}' was too large to keep (hash {r[0][:12]})"
        df = pd.read_parquet(io.BytesIO(bytes(r[2])))
        if frame_sha(df) != r[0]:
            return None, f"the kept data of '{n}' no longer matches its hash: it was changed or damaged"
        out[n] = df
    return out, ""


def _reproduce_trusted(con, calc_id: int, name: str, params: dict, datasets: List[str], kept: dict, basis: str, frames_for) -> dict:
    from pflab.quant import trusted
    frames, why = original_inputs(con, calc_id, datasets)
    if frames is None:
        return {"ok": False, "reproduced": False, "basis": "original", "label": "not reproducible", "same_as_kept": False, "why": why, "differences": [],
                "result": {}, "kept": kept, "problems": [why]}
    got = trusted.rerun(name, params, frames)
    diffs = compare_results(kept, got)
    return {"ok": True, "reproduced": not diffs, "basis": "original", "label": "reproduced from the original data" if not diffs else "differs from the kept result",
            "same_as_kept": not diffs, "differences": diffs, "result": got, "kept": kept, "problems": []}


def reproduce(con, calc_id: int, frames_for=None, sandbox=None, basis: str = "original") -> dict:
    """Run a kept calculation again. basis='original' (the default) uses the data it ran on, from its snapshot; if that is not available
    it says so and runs nothing unless the caller gave `frames_for`, in which case the rerun is on current data and is labelled so. It
    never quietly uses today's data as a reproduction. basis='current' runs on `frames_for(datasets)`. `differences` lists every way the
    result differs, missing keys included."""
    from pflab.agents import workshop as wk
    r = con.execute("SELECT code, alt_code, datasets_json, params_json, result_json, question, check_json FROM hq_calcs WHERE calc_id=?", [calc_id]).fetchone()
    if not r:
        raise LookupError(f"no calculation #{calc_id}")
    code, alt, ds, params, result, question, check = r
    if str(code).startswith("trusted:"):                    # S68: reviewed code that ships with the application, rerun by name on the kept inputs
        return _reproduce_trusted(con, calc_id, str(code)[8:], json.loads(params or "{}"), json.loads(ds or "[]"), json.loads(result or "{}"), basis, frames_for)
    test = (json.loads(check or "{}").get("test") or {})
    spec = wk.Spec(json.loads(ds), code, test, alt or "", "", json.loads(params or "{}"))
    frames = None
    if basis == "original":
        frames, why = original_inputs(con, calc_id, spec.datasets)
        if frames is None and frames_for is not None:
            basis = "current"                              # no snapshot: the caller asked for a rerun, and it is labelled as one
        elif frames is None:
            return {"ok": False, "reproduced": False, "basis": "original", "label": "not reproducible", "same_as_kept": False, "why": why,
                    "differences": [], "result": {}, "kept": json.loads(result or "{}"), "problems": [why]}
    if basis == "current":
        if frames_for is None:
            raise ValueError("a rerun on current data needs frames_for")
        frames = frames_for(spec.datasets)
    run = wk.run(spec, frames, sandbox=sandbox)
    kept = json.loads(result or "{}")
    diffs = compare_results(kept, run.result) if run.ok else ["the rerun did not produce a result"]
    same = bool(run.ok) and not diffs
    label = "reproduced from the original data" if basis == "original" else "a rerun on current data, not a reproduction"
    return {"ok": run.ok, "reproduced": basis == "original" and same, "basis": basis, "label": label, "same_as_kept": same, "differences": diffs,
            "result": run.result, "kept": kept, "problems": run.problems}


# --- passes: steps, failures, reaping ---------------------------------------------------------------------------------------------------

def due(con, now: datetime, limit: int = 6) -> List[int]:
    """Cases for the next case pass: queued, retry whose time has come, and closed cases whose review day has come (reopened here,
    with the reason logged). Oldest first."""
    for (cid,) in con.execute("SELECT case_id FROM hq_cases WHERE status='done' AND next_review_at IS NOT NULL AND next_review_at <= ? "
                              "AND case_id NOT IN (SELECT case_id FROM hq_missions)", [now]).fetchall():       # (a mission is reopened by hq/missions.py)
        c = get(con, cid)
        set_status(con, cid, "queued", now, f"scheduled review is due (decision then: {c['decision']}: {(c['reason'] or '')[:100]})")
        con.execute("UPDATE hq_cases SET steps=0, closed_at=NULL, attempts=0 WHERE case_id=?", [cid])
    # a case carried by an active mission belongs to the mission's workers (hq/missions.py), not to the brain's case pass
    return [r[0] for r in con.execute("SELECT case_id FROM hq_cases WHERE (status='queued' OR (status IN ('retry', 'waiting_budget', 'waiting_provider') "
                                      "AND (next_review_at IS NULL OR next_review_at <= ?))) AND case_id NOT IN " + MISSION_OWNED + " ORDER BY opened_at, case_id LIMIT ?",
                                      [now, limit]).fetchall()]


_LIVE: set = set()                                         # case ids in a pass of THIS process: a wake must not reap them
_LIVE_LOCK = threading.Lock()


def start_pass(con, ids: Sequence[int], pass_id: int, now: datetime) -> None:
    with _LIVE_LOCK:
        _LIVE.update(ids)
    for cid in ids:
        con.execute("UPDATE hq_cases SET status='running', pass_id=?, updated_at=?, attempts=attempts + 1 WHERE case_id=?", [pass_id, now, cid])
        log(con, cid, now, "pass", f"case pass #{pass_id} began")


def end_pass(con, ids: Sequence[int], pass_id: int, now: datetime, ok: bool, error: str = "") -> None:
    """After a case pass: a case the brain left `running` has had a step; it is queued for another, or (steps used up) closed as
    inconclusive with a review date. A failed pass is a failed attempt: retry later, `failed` after max_attempts."""
    with _LIVE_LOCK:
        _LIVE.difference_update(ids)
    for cid in ids:
        c = get(con, cid)
        if c is None or c["status"] != "running":
            continue                                                  # the brain moved it (waiting, done, approval): that stands
        if not ok:
            if c["attempts"] >= c["max_attempts"]:
                con.execute("UPDATE hq_cases SET status='failed', last_error=?, updated_at=? WHERE case_id=?", [error[:300], now, cid])
                log(con, cid, now, "failed", f"{c['attempts']} attempts: {error[:200]}")
            else:
                con.execute("UPDATE hq_cases SET status='retry', last_error=?, next_review_at=?, updated_at=? WHERE case_id=?",
                            [error[:300], now + timedelta(minutes=RETRY_MINUTES * 2 ** (c["attempts"] - 1)), now, cid])
                log(con, cid, now, "retry", f"pass failed ({error[:160]}); attempt {c['attempts']} of {c['max_attempts']}")
            continue
        steps = c["steps"] + 1
        con.execute("UPDATE hq_cases SET steps=?, attempts=0, updated_at=? WHERE case_id=?", [steps, now, cid])
        if steps >= MAX_STEPS:
            conclude(con, cid, now, "inconclusive", f"no decision after {steps} case passes; the evidence is {assess(con, cid, now)['verdict']}",
                     uncertainty="high: the system could not settle this by itself", next_review_at=now + timedelta(days=REVIEW_DAYS))
        else:
            set_status(con, cid, "queued", now, f"step {steps} done, not decided: queued for another look")


def reap(con, now: datetime) -> int:
    """Cases left `running` by a process that died: back to retry (the pass is counted), or failed when out of attempts."""
    with _LIVE_LOCK:
        mine = set(_LIVE)
    rows = [r for r in con.execute("SELECT case_id FROM hq_cases WHERE status='running' AND case_id NOT IN " + MISSION_OWNED).fetchall() if r[0] not in mine]
    for (cid,) in rows:
        end_pass(con, [cid], -1, now, False, "interrupted: the system closed during the pass")
        log(con, cid, now, "interrupted", "the system closed during a pass; effects already done are not repeated")
    return len(rows)


def fail(con, cid: int, now: datetime, error: str) -> None:
    con.execute("UPDATE hq_cases SET status='running' WHERE case_id=? AND status IN ('queued','retry')", [cid])
    end_pass(con, [cid], -1, now, False, error)


# --- conclusion and the reason it changed ------------------------------------------------------------------------------------------------------

def conclude(con, cid: int, now: datetime, decision: str, reason: str, *, uncertainty: str = "", next_review_at: Optional[datetime] = None,
             coverage: Optional[dict] = None) -> dict:
    """Close the case with a decision. If it had one before (a reopened case), what changed and why is logged. Sets `done`."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    c = get(con, cid)
    a = assess(con, cid, now)
    changed = c["decision"] is not None and (c["decision"] != decision or c["verdict"] != a["verdict"])
    nxt = next_review_at or (now + timedelta(days=REVIEW_DAYS))
    con.execute("UPDATE hq_cases SET status='done', decision=?, decision_reason=?, uncertainty=?, verdict=?, next_review_at=?, closed_at=?, "
                "updated_at=?, coverage_json=? WHERE case_id=?",
                [decision, reason[:600], uncertainty[:400], a["verdict"], nxt, now, now, json.dumps(coverage if coverage is not None else coverage_of(con, cid)), cid])
    if changed:
        log(con, cid, now, "conclusion changed",
            f"was {c['decision']} ({c['verdict']}): {(c['reason'] or '')[:160]} | now {decision} ({a['verdict']}): {reason[:200]}")
    log(con, cid, now, "decided", f"{decision} ({a['verdict']}): {reason[:300]}; next review {nxt:%Y-%m-%d}")
    review(con, cid, now)
    return {"decision": decision, "verdict": a["verdict"], "next_review": str(nxt)[:10], "changed": changed}


def coverage_of(con, cid: int) -> dict:
    ev = evidence(con, cid)
    kinds: Dict[str, int] = {}
    for e in ev:
        if e["stance"] != "missing":
            k = e.get("source_kind") or e["kind"]
            kinds[k] = kinds.get(k, 0) + 1
    dates = [e["published"] or e["event"] for e in ev if (e["published"] or e["event"])]
    return {"items": len(ev), "by_kind": kinds, "newest": str(max(dates))[:10] if dates else None,
            "oldest": str(min(dates))[:10] if dates else None, "gaps": [e["text"][:120] for e in ev if e["stance"] == "missing"][:6]}


# --- the review of the process, not only the outcome -------------------------------------------------------------------------------------------

def review(con, cid: int, now: datetime) -> dict:
    """How the investigation was done, judged by code: stale or undated inputs, tools that failed in its passes, assumptions the evidence
    contradicts, confidence the evidence does not support, a calculation nobody independently confirmed, an alert sent for a decision of
    'nothing'. These are about the process; the price outcome is scored later (`outcome_note`) and never replaces them."""
    c = get(con, cid)
    ev = evidence(con, cid)
    a = assess(con, cid, now)
    flags: List[str] = []
    stale = stale_items(ev, now)
    if stale:
        flags.append(f"{len(stale)} piece(s) of evidence stale or undated at the time of the decision")
    bad_tools = 0
    if c["pass_id"] is not None and c["pass_id"] > 0:
        bad_tools = con.execute("SELECT count(*) FROM hq_tool_calls WHERE pass_id=? AND status IN ('error','withheld','refused')",
                                [c["pass_id"]]).fetchone()[0]
    if bad_tools:
        flags.append(f"{bad_tools} tool call(s) failed or were refused in the last pass")
    against = [e for e in ev if e["stance"] == "against"]
    for asm in c["assumptions"]:
        words = set(re.findall(r"[a-z]{5,}", asm.lower()))
        if words and any(len(words & set(re.findall(r"[a-z]{5,}", e["text"].lower()))) >= 2 for e in against):
            flags.append(f"assumption contradicted by evidence: {asm[:100]}")
    if c["decision"] in ("suggest", "tell") and (a["for"] == 0 or a["sources"] < 2):
        flags.append(f"decision '{c['decision']}' rests on {a['for']} supporting item(s) from {a['sources']} source(s): confidence not supported")
    for e in ev:
        if e["kind"] == "calculation" and e["data"].get("confirmed") not in ("agrees",):
            flags.append("a calculation was used without an independent confirmation")
            break
    if re.search(r"\b(guarantee[sd]?|certain(ly)?|risk[- ]free|sure thing|will (surely )?(rise|outperform|beat)|cannot fail)\b", (c["reason"] or "") + " " + (c["uncertainty"] or ""), re.I):
        flags.append("the reasoning states certainty the evidence cannot give")
    if a["missing"] and c["decision"] in ("suggest", "tell"):
        flags.append("a decision was made with evidence still marked missing")
    sent = con.execute("SELECT count(*) FROM hq_case_log WHERE case_id=? AND event='told'", [cid]).fetchone()[0]
    if sent and c["decision"] == "nothing":
        flags.append("the investor was alerted although the decision was 'nothing'")
    rid = _id(con, "hq_case_reviews", "review_id")
    con.execute("INSERT INTO hq_case_reviews VALUES (?,?,?,?,?,?)",
                [rid, cid, now, json.dumps({"flags": flags, "assessment": a, "decision": c["decision"]}), None, None])
    if flags:
        log(con, cid, now, "process review", "; ".join(flags)[:900])
    return {"flags": flags, "assessment": a}


def outcome_note(con, cid: int, now: datetime, outcome: str) -> None:
    """Later, what followed (a price, a filing). Kept beside the process flags; neither proves the other."""
    r = con.execute("SELECT review_id FROM hq_case_reviews WHERE case_id=? ORDER BY review_id DESC LIMIT 1", [cid]).fetchone()
    if r:
        con.execute("UPDATE hq_case_reviews SET outcome=?, note=? WHERE review_id=?",
                    [outcome[:300], "an outcome alone does not show the reasoning was sound or unsound", r[0]])
    log(con, cid, now, "outcome", outcome[:300])


def link_outcomes(con, now: datetime) -> int:
    """A suggestion made in a case's pass has been scored: say so in the case's log, once. The outcome never replaces the process review."""
    n = 0
    for cid, sid, outcome, quality in con.execute(
            "SELECT c.case_id, s.sug_id, s.outcome, s.quality FROM hq_cases c JOIN hq_suggestions s ON s.pass_id = c.pass_id "
            "WHERE c.decision = 'suggest' AND s.outcome IS NOT NULL AND s.shadow = false").fetchall():
        key = f"suggestion #{sid}"
        if con.execute("SELECT 1 FROM hq_case_log WHERE case_id=? AND event='outcome' AND detail LIKE ?", [cid, key + "%"]).fetchone():
            continue
        outcome_note(con, cid, now, f"{key} scored: {outcome}" + (f" (decision quality: {quality})" if quality else ""))
        n += 1
    return n


# --- discovery: the system finds its own open questions ----------------------------------------------------------------------------------------

# --- views ------------------------------------------------------------------------------------------------------------------------------------

def listing(con, limit: int = 30, active_only: bool = False) -> List[dict]:
    rows = con.execute(f"SELECT case_id FROM hq_cases {'WHERE status IN (' + ','.join(repr(s) for s in ACTIVE) + ')' if active_only else ''} "
                       "ORDER BY updated_at DESC, case_id DESC LIMIT ?", [limit]).fetchall()
    out = []
    for (cid,) in rows:
        c = get(con, cid)
        deps = [{"key": k, "request": r, "status": s} for k, r, s in con.execute(
            "SELECT dep_key, request, status FROM hq_case_deps WHERE case_id=? ORDER BY dep_id", [cid]).fetchall()]
        c["dependencies"] = deps
        c["assessment"] = assess(con, cid)
        out.append(c)
    return out


def counts(con) -> Dict[str, int]:
    return {s: int(n) for s, n in con.execute("SELECT status, count(*) FROM hq_cases GROUP BY status").fetchall()}
