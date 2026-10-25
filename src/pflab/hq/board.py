"""The board: tasks between agents, and the investor's orders to any agent (S59, PLAN A16).

A task names who asked (The investor, an agent, the brain), who does it, the text, and where the answer goes back (the
dashboard, Telegram). One agent's result may hand work to another (`Reply.then`): the new task carries one more hop.
A chain longer than MAX_HOPS is not run: it goes to the brain, which decides (in shadow mode it only notes it), so
agents can never talk to each other in a loop. Tasks run one at a time, in order (the local model and the GPU are shared).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

MAX_HOPS = 3
_KEYS = ["id", "created", "from", "to", "text", "body", "status", "hops", "parent", "channel", "result", "result_json",
         "cost", "started", "finished", "replied"]


@dataclass
class Reply:
    text: str
    route: List[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)
    cost: float = 0.0
    status: str = "done"                                  # done | failed | needs_approval
    then: List[Tuple[str, str]] = field(default_factory=list)   # (agent, text): work handed on


def post(con, to: str, text: str, now: datetime, *, frm: str = "investor", body: Optional[dict] = None,
         parent: Optional[int] = None, channel: str = "dashboard") -> int:
    from pflab.pm.store import next_id
    hops = 0
    if parent is not None:
        r = con.execute("SELECT hops, channel FROM hq_tasks WHERE task_id=?", [parent]).fetchone()
        hops = (r[0] if r else 0) + 1
        channel = channel if channel != "dashboard" or not r else r[1]
    status = "queued"
    if hops > MAX_HOPS:                                    # the chain is too long: the brain looks at it instead
        body = {**(body or {}), "meant_for": to, "why": f"a chain of {hops} hops (more than {MAX_HOPS})"}
        to, status = "brain", "held"
    tid = next_id(con, "hq_tasks", "task_id")
    con.execute("INSERT INTO hq_tasks (task_id, created_at, from_agent, to_agent, text, body_json, status, hops, parent_id, "
                "channel) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [tid, now, frm, to, text[:4000], json.dumps(body or {}, default=str), status, hops, parent, channel])
    return tid


def get(con, tid: int) -> Optional[dict]:
    r = con.execute(f"SELECT task_id, created_at, from_agent, to_agent, text, body_json, status, hops, parent_id, channel, "
                    f"result, result_json, cost_inr, started_at, finished_at, replied_at FROM hq_tasks WHERE task_id=?",
                    [tid]).fetchone()
    if not r:
        return None
    d = dict(zip(_KEYS, r))
    d["body"] = json.loads(d["body"] or "{}")
    d["result_json"] = json.loads(d["result_json"] or "{}")
    return d


def next_queued(con) -> Optional[int]:
    r = con.execute("SELECT min(task_id) FROM hq_tasks WHERE status='queued'").fetchone()
    return r[0] if r and r[0] is not None else None


def run_one(rt, agents: Dict[str, Callable], deliver: Optional[Callable[[dict], None]] = None) -> Optional[dict]:
    """Take the oldest queued task, run its agent, keep the result, hand on its follow-ups, deliver the answer."""
    con = rt.cursor()
    tid = next_queued(con)
    if tid is None:
        return None
    con.execute("UPDATE hq_tasks SET status='running', started_at=? WHERE task_id=? AND status='queued'", [rt.clock(), tid])
    t = get(con, tid)
    fn = agents.get(t["to"])
    try:
        rep = fn(rt, t) if fn else Reply(f"No agent called '{t['to']}'.", status="failed")
    except Exception as e:                                 # an agent failing answers with its error, never silently
        rep = Reply(f"The {t['to']} agent failed: {type(e).__name__}: {str(e)[:300]}", ["error"], status="failed")
    con.execute("UPDATE hq_tasks SET status=?, result=?, result_json=?, cost_inr=?, finished_at=? WHERE task_id=?",
                [rep.status, rep.text[:20000], json.dumps({"route": rep.route, **rep.data}, default=str), rep.cost or None,
                 rt.clock(), tid])
    for agent, text in rep.then:
        post(con, agent, text, rt.clock(), frm=t["to"], parent=tid)
    t = get(con, tid)
    if deliver is not None and t["channel"] != "dashboard":
        try:
            deliver(t)
            con.execute("UPDATE hq_tasks SET replied_at=? WHERE task_id=?", [rt.clock(), tid])
        except Exception:                                  # undelivered stays visible (replied_at empty); never lost
            pass
    rt.bump("hq")
    return t


def run_all(rt, agents: Dict[str, Callable], deliver=None, max_n: int = 20, stop=None) -> int:
    n = 0
    while n < max_n and (stop is None or not stop.is_set()):
        if run_one(rt, agents, deliver) is None:
            break
        n += 1
    return n


def recent(con, limit: int = 40) -> List[dict]:
    ids = [r[0] for r in con.execute("SELECT task_id FROM hq_tasks ORDER BY task_id DESC LIMIT ?", [limit]).fetchall()]
    return [get(con, i) for i in ids]


def reap(con, now: datetime) -> int:
    """A task left `running` by a process that died is failed (it can be ordered again)."""
    n = con.execute("SELECT count(*) FROM hq_tasks WHERE status='running'").fetchone()[0]
    con.execute("UPDATE hq_tasks SET status='failed', result='stopped: the system closed while it ran', finished_at=? "
                "WHERE status='running'", [now])
    return int(n)
