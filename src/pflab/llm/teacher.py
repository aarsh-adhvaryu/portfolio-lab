"""S79b item 17: the teacher log. Every cloud call's input and output are kept (redacted) with its later score, as a dataset for model_lab distillation.

The cloud model (Opus) is the teacher; the local models are the students. The record is made ADDITIVELY at the two cloud paths (`agents/analyst.py` ring / trial_note
and `hq/llm.py` call): after a call has been paid for and logged in `api_calls`, `record_message` copies what went in and what came out into `teacher_log_s79`.
Rules: it never blocks or fails a call (everything is try-wrapped), the text passes the same redaction as the egress path (`hq/redact.redact`: his ids, PAN,
phone, e-mail, name, address words become tokens; the count is kept, never the value), and a score is attached later by whoever scores the answer
(`attach_score`). No training happens here; `tools/model_lab/export_teacher.py` writes the rows out as chat-format JSONL. Switch: configs/s79b.toml [seats]
teacher_log (and on).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, List, Optional

MAX_CHARS = 120_000


def enabled(path=None) -> bool:
    from pflab.llm import seats
    sw = seats.switch(path)
    return bool(sw.get("on", True)) and bool(sw.get("teacher_log", True))


def _blocks_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        if isinstance(b, dict):
            t = b.get("type")
            if t == "text":
                out.append(str(b.get("text", "")))
            elif t == "tool_use":
                out.append(f"[tool_use {b.get('name')} {json.dumps(b.get('input'), default=str)[:2000]}]")
            elif t == "tool_result":
                out.append(f"[tool_result {_blocks_text(b.get('content'))[:4000]}]")
        else:
            t = getattr(b, "type", "")
            if t == "text":
                out.append(str(getattr(b, "text", "")))
            elif t == "tool_use":
                out.append(f"[tool_use {getattr(b, 'name', '')} {json.dumps(getattr(b, 'input', None), default=str)[:2000]}]")
    return "\n".join(x for x in out if x)


def _system_text(system: Any) -> str:
    return _blocks_text(system) if not isinstance(system, str) else system


def request_text(params: dict) -> tuple:
    """(system, input) as plain text from an Anthropic request: the messages joined with their roles."""
    msgs = []
    for m in params.get("messages") or []:
        msgs.append(f"[{m.get('role', 'user')}] {_blocks_text(m.get('content'))}")
    return _system_text(params.get("system") or ""), "\n\n".join(msgs)


def _gate(con):
    from pflab.hq import egress
    try:
        return egress.load(con)
    except Exception:
        return egress.Gate()


def redact_text(text: str, gate) -> tuple:
    """(redacted text, number of replacements). Tool-result mode: only his own address words are replaced, not every line with a road in it."""
    from pflab.hq import redact
    out, counts = redact.redact(text or "", gate, lines=False)
    return out[:MAX_CHARS], int(sum(counts.values()))


def record(con, *, call_id: Optional[int], source: str, model: str, system_text: str, input_text: str, output_text: str, tokens_in: int = 0, tokens_out: int = 0,
           cost_inr: float = 0.0, now: Optional[datetime] = None, market: str = "IN", agent: str = "", gate=None, note: str = "") -> Optional[int]:
    """Store one teacher example (redacted). Returns its id, or None when the log is off, the call is already kept, or anything failed (never raises)."""
    try:
        if not enabled():
            return None
        from pflab.pm.store import next_id
        if call_id is not None and con.execute("SELECT 1 FROM teacher_log_s79 WHERE call_id=? AND source=? LIMIT 1", [call_id, source]).fetchone():
            return None
        g = gate if gate is not None else _gate(con)
        sys_r, n1 = redact_text(system_text, g)
        in_r, n2 = redact_text(input_text, g)
        out_r, n3 = redact_text(output_text, g)
        sha = hashlib.sha256((sys_r + "\n" + in_r + "\n" + out_r).encode("utf-8", "replace")).hexdigest()
        tid = next_id(con, "teacher_log_s79", "teacher_id")
        con.execute("INSERT INTO teacher_log_s79 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [tid, market, now or datetime.now(), call_id, source, agent, model, sys_r, in_r, out_r, int(tokens_in or 0), int(tokens_out or 0),
                     float(cost_inr or 0.0), n1 + n2 + n3, sha, None, None, None, note[:200]])
        return tid
    except Exception:
        return None


def record_message(con, call_id: Optional[int], params: dict, msg: Any, source: str, now: Optional[datetime] = None, *, agent: str = "",
                   cost_inr: float = 0.0, gate=None, market: str = "IN") -> Optional[int]:
    """The hook for the two cloud paths: `params` is the request as sent, `msg` the SDK message that came back. Never raises."""
    try:
        if not enabled():
            return None
        system, inp = request_text(params)
        out = _blocks_text(getattr(msg, "content", None) if not isinstance(msg, dict) else msg.get("content"))
        u = getattr(msg, "usage", None)
        return record(con, call_id=call_id, source=source, model=str(params.get("model") or getattr(msg, "model", "")), system_text=system, input_text=inp, output_text=out,
                      tokens_in=int(getattr(u, "input_tokens", 0) or 0), tokens_out=int(getattr(u, "output_tokens", 0) or 0), cost_inr=cost_inr, now=now,
                      market=market, agent=agent, gate=gate)
    except Exception:
        return None


def attach_score(con, call_id: int, score: float, kind: str, now: Optional[datetime] = None) -> int:
    """Attach a later score (0..1 by convention; the kind says what scored it, e.g. 'reviewer', 'outcome', 'user') to every teacher row of a call. Returns rows updated."""
    n = con.execute("SELECT count(*) FROM teacher_log_s79 WHERE call_id=?", [call_id]).fetchone()[0]
    if n:
        con.execute("UPDATE teacher_log_s79 SET score=?, score_kind=?, scored_at=? WHERE call_id=?", [float(score), kind, now or datetime.now(), call_id])
    return int(n)


def rows(con, *, since: Optional[datetime] = None, scored_only: bool = False, min_score: Optional[float] = None, market: Optional[str] = None) -> List[dict]:
    q = ("SELECT teacher_id, market, created_at, call_id, source, agent, model, system_text, input_text, output_text, tokens_in, tokens_out, cost_inr, n_redactions, "
         "score, score_kind FROM teacher_log_s79 WHERE 1=1")
    a: list = []
    if since is not None:
        q += " AND created_at >= ?"
        a.append(since)
    if scored_only or min_score is not None:
        q += " AND score IS NOT NULL"
    if min_score is not None:
        q += " AND score >= ?"
        a.append(float(min_score))
    if market:
        q += " AND market = ?"
        a.append(market)
    cols = ["teacher_id", "market", "created_at", "call_id", "source", "agent", "model", "system", "input", "output", "tokens_in", "tokens_out", "cost_inr", "n_redactions",
            "score", "score_kind"]
    return [dict(zip(cols, r)) for r in con.execute(q + " ORDER BY teacher_id", a).fetchall()]


def to_chat(row: dict) -> dict:
    """One example in chat format (for SFT/distillation): system, user = the input, assistant = the teacher's output."""
    msgs = ([{"role": "system", "content": row["system"]}] if row.get("system") else []) + [{"role": "user", "content": row["input"]}, {"role": "assistant", "content": row["output"]}]
    return {"messages": msgs, "meta": {"teacher_id": row["teacher_id"], "call_id": row["call_id"], "model": row["model"], "source": row["source"], "score": row.get("score")}}


def stats(con, market: str = "IN") -> dict:
    r = con.execute("SELECT count(*), count(score), coalesce(sum(tokens_in),0), coalesce(sum(tokens_out),0), coalesce(sum(cost_inr),0), coalesce(sum(n_redactions),0) "
                    "FROM teacher_log_s79 WHERE market=?", [market]).fetchone()
    return {"examples": int(r[0]), "scored": int(r[1]), "tokens_in": int(r[2]), "tokens_out": int(r[3]), "cost_inr": round(float(r[4]), 2), "redactions": int(r[5])}
