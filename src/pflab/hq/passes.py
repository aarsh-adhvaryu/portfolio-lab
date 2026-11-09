"""The journal of model passes (the rows of `hq_passes`): one row per chat answer or ask, with its cost, its note and the tools it called; the investor's marks on a pass;
and the slider's model lookup. Moved out of `hq/brain.py` when the brain's own loop was cut (S80 phase 4); the table keeps its old name and its old rows.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from pflab.hq import governor as gv

SHADOW = False


def record(con, now: datetime, trigger: str, evs: List[dict], model: str, role: str, status: str, note: str = "",
           decisions: Optional[list] = None, cost: float = 0.0, call_id: Optional[int] = None,
           error: Optional[str] = None) -> int:
    from pflab.pm.store import next_id
    pid = next_id(con, "hq_passes", "pass_id")
    con.execute("INSERT INTO hq_passes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [pid, now, trigger, json.dumps(evs, default=str), model, role, SHADOW or role == "rival", status, note,
                 json.dumps(decisions or [], default=str), cost, call_id, error])
    return pid


def close(con, pid: int, status: str, note: str = "", decisions: Optional[list] = None, cost: float = 0.0,
          call_id: Optional[int] = None, error: Optional[str] = None) -> None:
    con.execute("UPDATE hq_passes SET status=?, note=?, decisions_json=?, cost_inr=?, call_id=?, error=? WHERE pass_id=?",
                [status, note, json.dumps(decisions or [], default=str), cost, call_id, error, pid])


def tool_calls(con, pass_id: int) -> List[dict]:
    rows = con.execute("SELECT turn, tool, kind, args_json, status, result, ms FROM hq_tool_calls WHERE pass_id=? "
                       "ORDER BY call_no", [pass_id]).fetchall()
    return [{"turn": t, "tool": n, "kind": k, "args": json.loads(a or "{}"), "status": s, "result": (r or "")[:600], "ms": m}
            for t, n, k, a, s, r, m in rows]


def slider(job: str, fallback: str) -> str:
    """S61: the model the slider sets for a job (`hq/models.py`), the fallback if it cannot be read."""
    try:
        from pflab.hq import models
        return models.model_id(job)
    except Exception:
        return fallback


def pair() -> Tuple[str, str]:
    """(the main model, the other of Opus and Sonnet): the slider's `brain` job and the other."""
    main = slider("brain", gv.OPUS)
    return main, (gv.SONNET if main == gv.OPUS else gv.OPUS)


def mark(con, pass_id: int, mattered: bool, now: datetime) -> int:
    """The investor's mark on a pass (usefulness), kept as feedback in memory; a new mark replaces the last."""
    from pflab.agents import memory as mem
    subject = f"brain pass #{pass_id}"
    prev = con.execute("SELECT max(mem_id) FROM memory WHERE kind='feedback' AND subject=? AND valid_to IS NULL",
                       [subject]).fetchone()[0]
    return mem.remember(con, "feedback", "mattered" if mattered else "did not matter", subject=subject,
                        source="dashboard", now=now, supersedes=prev)


def marks(con) -> Dict[int, bool]:
    out = {}
    for subject, text in con.execute("SELECT subject, text FROM memory WHERE kind='feedback' AND subject LIKE 'brain pass #%' "
                                     "AND valid_to IS NULL ORDER BY mem_id").fetchall():
        out[int(subject.split("#")[1])] = text == "mattered"
    return out


def journal(con, limit: int = 30) -> List[dict]:
    rows = con.execute("SELECT pass_id, passed_at, trigger, events_json, model, role, status, note, decisions_json, cost_inr, error "
                       "FROM hq_passes ORDER BY pass_id DESC LIMIT ?", [limit]).fetchall()
    keys = ["id", "at", "trigger", "events", "model", "role", "status", "note", "decisions", "cost", "error"]
    out = []
    m = marks(con)
    for r in rows:
        d = dict(zip(keys, r))
        d["mattered"] = m.get(d["id"])
        d["events"] = [e.get("text", "") for e in json.loads(d["events"] or "[]")]
        d["decisions"] = json.loads(d["decisions"] or "[]")
        d["tools"] = tool_calls(con, d["id"]) if d["role"] in ("brain", "rival") else []
        out.append(d)
    return out
