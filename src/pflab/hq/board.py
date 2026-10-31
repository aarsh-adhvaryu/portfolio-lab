"""The board: tasks between agents, and the investor's orders to any agent (S59, PLAN A16; S67 durable states).

A task names who asked (The investor, an agent, the brain), who does it, the text, and where the answer goes back (the
dashboard, Telegram). One agent's result may hand work to another (`Reply.then`): the new task carries one more hop.
A chain longer than MAX_HOPS is not run: it goes to the brain, which decides (in shadow mode it only notes it), so
agents can never talk to each other in a loop. Tasks run one at a time, in order (the local model and the GPU are shared).

S67: work survives a stop. A task is queued, running, waiting (for data: `waiting_on` names what it needs; `wake` re-queues it when
that arrives), retry (a failure that may pass: tried again at `next_review_at`, at most MAX_ATTEMPTS times in all), needs_approval,
held (a chain over the hop limit), done, failed or dismissed. A task `running` when the process died is put back to retry (or failed after
MAX_ATTEMPTS), and what it already did is kept in `hq_effects` so a second run does not repeat it (`once`). A held task has two ways out, both
explicit and journaled: `release` (run it once, its chain still counted) and `dismiss`; one nobody resolves for HELD_DAYS is dismissed by
`expire_held`, with its reason, never silently.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

MAX_HOPS = 3
MAX_ATTEMPTS = 3                                          # runs of one task in all (an interruption counts as one)
RETRY_MINUTES = 5                                         # the first wait; doubled for each further attempt
HELD_DAYS = 3                                             # a held task nobody resolved is dismissed after this
OPEN = ("queued", "running", "waiting", "retry", "needs_approval", "held")
_KEYS = ["id", "created", "from", "to", "text", "body", "status", "hops", "parent", "channel", "result", "result_json",
         "cost", "started", "finished", "replied", "attempts", "next_review", "waiting_on", "progress", "dedup_key"]


@dataclass
class Reply:
    text: str
    route: List[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)
    cost: float = 0.0
    status: str = "done"                                  # done | failed | needs_approval | waiting (data: data["waiting_on"]) | deferred (data: resume_at)
    then: List[Tuple[str, str]] = field(default_factory=list)   # (agent, text): work handed on


def post(con, to: str, text: str, now: datetime, *, frm: str = "investor", body: Optional[dict] = None,
         parent: Optional[int] = None, channel: str = "dashboard", dedup_key: Optional[str] = None) -> int:
    """A task on the board. With `dedup_key`, a task already open under the same key is returned instead of a second one."""
    from pflab.pm.store import next_id
    if dedup_key:
        r = con.execute(f"SELECT task_id FROM hq_tasks WHERE dedup_key=? AND status IN ({','.join('?' * len(OPEN))}) "
                        "ORDER BY task_id LIMIT 1", [dedup_key, *OPEN]).fetchone()
        if r:
            return int(r[0])
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
                "channel, attempts, dedup_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [tid, now, frm, to, text[:4000], json.dumps(body or {}, default=str), status, hops, parent, channel, 0, dedup_key])
    return tid


def get(con, tid: int) -> Optional[dict]:
    r = con.execute(f"SELECT task_id, created_at, from_agent, to_agent, text, body_json, status, hops, parent_id, channel, "
                    f"result, result_json, cost_inr, started_at, finished_at, replied_at, attempts, next_review_at, waiting_on, "
                    f"progress, dedup_key FROM hq_tasks WHERE task_id=?", [tid]).fetchone()
    if not r:
        return None
    d = dict(zip(_KEYS, r))
    d["attempts"] = d["attempts"] or 0
    d["body"] = json.loads(d["body"] or "{}")
    d["result_json"] = json.loads(d["result_json"] or "{}")
    return d


def next_queued(con, now: Optional[datetime] = None, his_only: bool = False) -> Optional[int]:
    """The oldest task to run: queued, or a retry whose time has come. `his_only` (paused): only a task he ordered himself."""
    r = con.execute("SELECT min(task_id) FROM hq_tasks WHERE (status='queued' OR (status='retry' AND (next_review_at IS NULL "
                    "OR next_review_at <= ?)))" + (" AND from_agent='investor'" if his_only else ""), [now or datetime.now()]).fetchone()
    return r[0] if r and r[0] is not None else None


def once(con, task_id: Optional[int], key: str, kind: str, now: datetime, do: Callable[[], object], detail: str = "") -> bool:
    """Do an effect (a message, a question, a ledger-side note) once for the key, however often the task is resumed. True when done now,
    False when an earlier run already did it. The key is written first, so an effect that dies halfway is not repeated blindly: the
    next run sees the key and the task's `progress` says it was interrupted there."""
    if con.execute("SELECT 1 FROM hq_effects WHERE effect_key=?", [key]).fetchone():
        return False                          # done, or 'started' by a run that died: not repeated blindly (see `uncertain`)
    con.execute("INSERT INTO hq_effects (effect_key, task_id, kind, done_at, detail, state) VALUES (?,?,?,?,?,'started')",
                [key, task_id, kind, now, detail[:300]])
    try:
        do()
    except Exception:
        con.execute("DELETE FROM hq_effects WHERE effect_key=?", [key])      # it did not happen: the next run may try again
        raise
    con.execute("UPDATE hq_effects SET state='done' WHERE effect_key=?", [key])
    return True


def once_db(con, task_id: Optional[int], key: str, kind: str, now: datetime, do: Callable[[], object], detail: str = "") -> bool:
    """`once` for an effect that only writes to the store: the marker and the effect commit together or not at all, so a stop can leave
    neither half behind (no 'started' row, nothing to be uncertain about). For a message sent outside, use `once`."""
    from pflab.pm.store import transaction
    if con.execute("SELECT 1 FROM hq_effects WHERE effect_key=?", [key]).fetchone():
        return False
    with transaction(con):
        con.execute("INSERT INTO hq_effects (effect_key, task_id, kind, done_at, detail, state) VALUES (?,?,?,?,?,'done')",
                    [key, task_id, kind, now, detail[:300]])
        do()
    return True


def uncertain(con) -> List[dict]:
    """Effects whose run stopped between 'started' and 'done': they may or may not have happened outside (a message, a question). Never
    repeated by the system; listed so he is told and can say. A store-only effect cannot be here (`once_db`)."""
    return [{"key": r[0], "task": r[1], "kind": r[2], "since": str(r[3])[:16], "detail": r[4]} for r in con.execute(
        "SELECT effect_key, task_id, kind, done_at, detail FROM hq_effects WHERE state='started' ORDER BY done_at").fetchall()]


def wake(con, key: str, now: datetime, note: str = "") -> int:
    """What a waiting task needed has arrived: every task waiting on `key` is queued again. Returns how many."""
    ids = [r[0] for r in con.execute("SELECT task_id FROM hq_tasks WHERE status='waiting' AND waiting_on=?", [key]).fetchall()]
    for tid in ids:
        con.execute("UPDATE hq_tasks SET status='queued', waiting_on=NULL, wait_kind=NULL, resume_condition=NULL, progress=? WHERE task_id=?",
                    [f"resumed: {note or key} arrived {now:%Y-%m-%d %H:%M}", tid])
    return len(ids)


class Retryable(RuntimeError):
    """An agent raises this (or any network or timeout error) when trying again later may work."""


_TRANSIENT_NAMES = {"APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError", "OverloadedError", "ConnectTimeout",
                    "ReadTimeout", "ConnectionError", "Timeout", "ChunkedEncodingError", "ServiceUnavailable"}


def is_transient(e: BaseException) -> bool:
    """A failure that may pass by itself: a network or timeout error, an API overload or rate limit, or an explicit Retryable. A bug
    (ZeroDivisionError, KeyError) is not retried: it would fail the same way."""
    return isinstance(e, (Retryable, ConnectionError, TimeoutError)) or any(c.__name__ in _TRANSIENT_NAMES for c in type(e).__mro__)


def _backoff(attempts: int) -> timedelta:
    return timedelta(minutes=RETRY_MINUTES * 2 ** max(0, attempts - 1))


_LIVE: set = set()                                         # task ids being run by THIS process (a process that died has none)
_LIVE_LOCK = threading.Lock()


def live_ids() -> set:
    with _LIVE_LOCK:
        return set(_LIVE)


def run_one(rt, agents: Dict[str, Callable], deliver: Optional[Callable[[dict], None]] = None, his_only: bool = False) -> Optional[dict]:
    """Take the oldest task due, run its agent, keep the result, hand on its follow-ups, deliver the answer. A failure that may
    pass becomes `retry` (bounded by MAX_ATTEMPTS); an agent that needs data returns status 'waiting' and is resumed by `wake`."""
    con = rt.cursor()
    now = rt.clock()
    tid = next_queued(con, now, his_only)
    if tid is None:
        return None
    with _LIVE_LOCK:
        _LIVE.add(tid)                                     # this process owns it until it ends: a wake must not reap it
    try:
        return _run_claimed(rt, agents, deliver, con, tid, now)
    finally:
        with _LIVE_LOCK:
            _LIVE.discard(tid)


def _run_claimed(rt, agents: Dict[str, Callable], deliver, con, tid: int, now: datetime) -> Optional[dict]:
    con.execute("UPDATE hq_tasks SET status='running', started_at=?, attempts=coalesce(attempts, 0) + 1, next_review_at=NULL "
                "WHERE task_id=? AND status IN ('queued','retry')", [now, tid])
    t = get(con, tid)
    fn = agents.get(t["to"])
    transient = False
    try:
        rep = fn(rt, t) if fn else Reply(f"No agent called '{t['to']}'.", status="failed")
    except Exception as e:                                 # an agent failing answers with its error, never silently
        rep = Reply(f"The {t['to']} agent failed: {type(e).__name__}: {str(e)[:300]}", ["error"], status="failed")
        transient = is_transient(e)
    waiting_on = str(rep.data.get("waiting_on") or "") if rep.status == "waiting" else None
    if rep.status == "waiting" and not waiting_on:
        rep.status = "failed"                              # waiting for nothing named could never be resumed
        rep.text += " (it said it was waiting but named nothing)"
    nxt = None
    deferred = rep.status == "deferred"
    if deferred:                                           # S68: waiting for a budget, the provider or a time is not an attempt spent
        nxt = datetime.fromisoformat(str(rep.data.get("resume_at"))) if rep.data.get("resume_at") else rt.clock() + timedelta(minutes=30)
        rep.status = "retry"
        con.execute("UPDATE hq_tasks SET attempts=greatest(coalesce(attempts, 1) - 1, 0) WHERE task_id=?", [tid])
    if transient and t["attempts"] < MAX_ATTEMPTS:
        rep.status, nxt = "retry", rt.clock() + _backoff(t["attempts"])
        rep.text += f" (attempt {t['attempts']} of {MAX_ATTEMPTS}; tried again at {nxt:%H:%M})"
    elif transient:
        rep.text += f" (attempt {t['attempts']} of {MAX_ATTEMPTS}: no more tries)"
    fin = None if rep.status in ("waiting", "retry") else rt.clock()
    from pflab.pm.store import transaction
    with transaction(con):                                 # the answer and the hand-offs it names are saved together or not at all (audit F6)
        con.execute("UPDATE hq_tasks SET status=?, result=?, result_json=?, cost_inr=coalesce(cost_inr, 0) + ?, finished_at=?, next_review_at=?, waiting_on=?, "
                    "progress=?, wait_kind=?, resume_condition=?, lease_owner=NULL, lease_until=NULL, checkpoint_json=coalesce(?, checkpoint_json), "
                    "artifacts_json=coalesce(?, artifacts_json) WHERE task_id=?",
                    [rep.status, rep.text[:20000], json.dumps({"route": rep.route, **rep.data}, default=str), rep.cost or 0.0,
                     fin, nxt, waiting_on, str(rep.data.get("progress") or "")[:300] or None,
                     (rep.data.get("wait_kind") if rep.status in ("waiting", "retry") else None),
                     (rep.data.get("resume_condition") if rep.status in ("waiting", "retry") else None),
                     json.dumps(rep.data["checkpoint"], default=str) if rep.data.get("checkpoint") is not None else None,
                     json.dumps(rep.data["artifacts"], default=str) if rep.data.get("artifacts") is not None else None, tid])
        for agent, text in rep.then:
            post(con, agent, text, rt.clock(), frm=t["to"], parent=tid, dedup_key=f"then:{tid}:{agent}:{hashlib.sha1(text.encode()).hexdigest()[:10]}")
    t = get(con, tid)
    if t["status"] == "done":                              # S68: whatever waited for this task goes on
        wake(con, f"task:{tid}", rt.clock(), f"task #{tid} finished")
    if deliver is not None and t["channel"] != "dashboard" and t["status"] in ("done", "failed", "needs_approval"):
        try:
            deliver(t)
            con.execute("UPDATE hq_tasks SET replied_at=? WHERE task_id=?", [rt.clock(), tid])
        except Exception:                                  # undelivered stays visible (replied_at empty); never lost
            pass
    rt.bump("hq")
    return t


def run_all(rt, agents: Dict[str, Callable], deliver=None, max_n: int = 20, stop=None, his_only: bool = False) -> int:
    n = 0
    while n < max_n and (stop is None or not stop.is_set()):
        if run_one(rt, agents, deliver, his_only) is None:
            break
        n += 1
    return n


def recent(con, limit: int = 40) -> List[dict]:
    ids = [r[0] for r in con.execute("SELECT task_id FROM hq_tasks ORDER BY task_id DESC LIMIT ?", [limit]).fetchall()]
    return [get(con, i) for i in ids]


def reap(con, now: datetime) -> int:
    """A task left `running` by a process that died goes back to `retry` (it can be run again, once more, at once), or is failed when it
    has used MAX_ATTEMPTS. What it did before the stop is in `hq_effects`; its `progress` says so. A task this process is still running
    (a slow job, or the PC slept and woke inside the same process) is left alone: only a task no live worker of this process owns is
    one a dead process left. Returns how many were found."""
    mine = live_ids()
    rows = [r for r in con.execute("SELECT task_id, coalesce(attempts, 0) FROM hq_tasks WHERE status='running'").fetchall() if r[0] not in mine]
    for tid, attempts in rows:
        done = con.execute("SELECT count(*) FROM hq_effects WHERE task_id=? AND coalesce(state, 'done')='done'", [tid]).fetchone()[0]
        unsure = con.execute("SELECT count(*) FROM hq_effects WHERE task_id=? AND state='started'", [tid]).fetchone()[0]
        note = (f"interrupted on attempt {attempts} when the system closed" + (f"; {done} effect(s) already done are not repeated" if done else "")
                + (f"; {unsure} effect(s) stopped halfway and may or may not have happened (not repeated, listed for him)" if unsure else ""))
        if attempts < MAX_ATTEMPTS:
            con.execute("UPDATE hq_tasks SET status='retry', next_review_at=?, progress=?, result=? WHERE task_id=?",
                        [now, note, f"stopped: {note}; it runs again", tid])
        else:
            con.execute("UPDATE hq_tasks SET status='failed', finished_at=?, progress=?, result=? WHERE task_id=?",
                        [now, note, f"stopped: {note}; no more tries", tid])
    return len(rows)


def held(con) -> List[dict]:
    """The held tasks: what each was meant for, why it was held, how long it has waited."""
    out = []
    for (tid,) in con.execute("SELECT task_id FROM hq_tasks WHERE status='held' ORDER BY task_id").fetchall():
        t = get(con, tid)
        out.append({"id": tid, "meant_for": t["body"].get("meant_for"), "why": t["body"].get("why"), "text": t["text"],
                    "since": str(t["created"])[:16]})
    return out


def release(con, tid: int, now: datetime, by: str, to: Optional[str] = None) -> dict:
    """Let a held task run once, for the agent it was meant for (or `to`). Its hops stay over the limit, so whatever it hands on is held
    again: a release never reopens a chain, only runs this one link. Journaled in its result."""
    t = get(con, tid)
    if t is None or t["status"] != "held":
        raise ValueError(f"task #{tid} is not held")
    agent = to or t["body"].get("meant_for")
    if not agent:
        raise ValueError(f"task #{tid} does not say who it was meant for")
    body = {**t["body"], "released_by": by, "released_at": str(now)}
    con.execute("UPDATE hq_tasks SET status='queued', to_agent=?, body_json=?, attempts=0, result=? WHERE task_id=?",
                [agent, json.dumps(body, default=str), f"released by {by} at {now:%Y-%m-%d %H:%M} to run once for {agent}", tid])
    return {"id": tid, "to": agent, "by": by}


def dismiss(con, tid: int, now: datetime, by: str, reason: str) -> dict:
    """Close a held task without running it. The reason is kept."""
    t = get(con, tid)
    if t is None or t["status"] != "held":
        raise ValueError(f"task #{tid} is not held")
    con.execute("UPDATE hq_tasks SET status='dismissed', finished_at=?, result=? WHERE task_id=?",
                [now, f"dismissed by {by} at {now:%Y-%m-%d %H:%M}: {reason[:300]}", tid])
    return {"id": tid, "by": by, "reason": reason[:300]}


def expire_held(con, now: datetime, days: int = HELD_DAYS) -> int:
    """Held tasks nobody resolved for `days` days are dismissed, with that said: a hop limit stops a loop, it does not park work forever."""
    n = 0
    for (tid,) in con.execute("SELECT task_id FROM hq_tasks WHERE status='held' AND created_at < ?", [now - timedelta(days=days)]).fetchall():
        dismiss(con, tid, now, "keeper", f"held {days} days with no release; the chain ran too long and no one asked for it again")
        n += 1
    return n


def counts(con) -> Dict[str, int]:
    return {s: int(n) for s, n in con.execute("SELECT status, count(*) FROM hq_tasks WHERE status IN ('queued','running','waiting',"
                                              "'retry','needs_approval','held') GROUP BY status").fetchall()}
