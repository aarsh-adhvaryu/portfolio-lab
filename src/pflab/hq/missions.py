"""Missions (S68): one request from the investor, carried by several workers to saved, reviewed artifacts.

A mission is a case (`hq_cases`, the parent investigation id) plus `hq_missions` (its goal, state, plan and snapshot) and worker tasks on the
board (`hq_tasks`, with `case_id`, `role`, `depends_on`, a checkpoint, the artifacts they made). Roles:

    coordinator   plans the steps (`plan_mission`), later writes the answer (`submit_answer`) once the review approves
    research      gathers evidence (`case_evidence`), asks for what is missing (`request_report`), looks for disconfirming evidence
    quant         calculations, scenarios and strategy experiments (`case_calculate`, `register_experiment`, ...)
    review        independent context: reproduces the calculations, checks the sources, approves or asks for specific revisions

The state machine here is code and only reads the store, so a restart changes nothing: `tick` looks at the tasks and moves the mission on.
DONE means the promised artifacts exist (`hq_artifacts`), not that a model stopped talking. A task waits for data, the sandbox, the budget or the
provider with a named condition (`waiting_on`, `wait_kind`, `resume_condition`) and no analytical attempt is spent while it waits.

States: planning -> working -> reviewing -> (revising: working again, at most MAX_ROUNDS) -> synthesising -> done; blocked (a task failed for good).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

ROLES = ("research", "quant")                          # the roles a plan may assign (coordinator and review are added by the system)
AGENT_OF = {"coordinator": "w_coord", "research": "w_research", "quant": "w_quant", "review": "w_review"}
PROMISE_KINDS = ("evidence", "calc", "scenario", "experiment", "review", "plan", "answer")
DEFAULT_PROMISE = {"coordinator": {"plan": 1}, "research": {"evidence": 2}, "quant": {"calc": 1}, "review": {"review": 1}}
MAX_TASKS = 24                                         # tasks in one mission, all rounds: a plan cannot run away
MAX_ROUNDS = 2                                         # review rounds that may ask for revisions
OPEN_TASK = ("queued", "running", "waiting", "retry", "needs_approval")
ACTIVE = ("planning", "working", "reviewing", "synthesising")


def _id(con, table: str, col: str) -> int:
    from pflab.pm.store import next_id
    return next_id(con, table, col)


def snapshot_id(con, pm_dir) -> str:
    """The identity of the figures a mission reads: the ledger build's fingerprint and the latest price date. Totals, scenarios and calculations
    carry it, so two results can be seen to be from the same state of the record, or not."""
    fp = "none"
    try:
        from pathlib import Path
        fp = json.loads((Path(pm_dir) / "app" / "ledger_build.json").read_text(encoding="utf-8")).get("fingerprint", "none")[:8]
    except Exception:
        pass
    try:
        d = con.execute("SELECT max(date) FROM prices").fetchone()[0]
    except Exception:
        d = None
    return f"{fp}_{d or 'no-prices'}"


# --- creating, planning ----------------------------------------------------------------------------------------------------------------------

def create(con, now: datetime, goal: str, *, pm_dir=None, origin: str = "investor", subject: Optional[str] = None, why: str = "", revisit: str = "",
           key: Optional[str] = None, isin: Optional[str] = None) -> dict:
    """Open the investigation and its mission, and queue the coordinator. The same goal on the same day is the same mission. `why` is why the system
    chose it (for work nobody asked for) and `revisit` what would justify looking again: both are kept in the case's log and on its card."""
    from pflab.hq import board, cases
    goal = " ".join(goal.split())[:1200]
    if len(goal) < 8:
        raise ValueError("say what to investigate")
    key = key or f"mission:{hashlib.sha1(goal.lower().encode()).hexdigest()[:10]}:{now:%Y%m%d}"
    cid, new = cases.open_case(con, now, goal[:580], origin="investor" if origin == "investor" else "code", subject=subject, isin=isin, key=key)
    r = con.execute("SELECT mission_id, state FROM hq_missions WHERE case_id=?", [cid]).fetchone()
    if r:
        return {"mission_id": r[0], "case_id": cid, "state": r[1], "new": False}
    mid = _id(con, "hq_missions", "mission_id")
    snap = snapshot_id(con, pm_dir) if pm_dir else "unknown"
    con.execute("INSERT INTO hq_missions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [mid, cid, now, now, goal, "planning", 0, None, snap, None, now, "the coordinator plans the steps", None, origin])
    cases.set_status(con, cid, "running", now, "a mission: its workers carry it (hq/missions.py)")
    tid = board.post(con, AGENT_OF["coordinator"], f"Plan the mission: {goal}", now, frm=origin,
                     body={"case_id": cid, "role": "coordinator", "promise": DEFAULT_PROMISE["coordinator"], "goal": goal, "step": "plan"})
    _tag(con, tid, cid, "coordinator", snap, None)
    cases.log(con, cid, now, "mission", f"mission #{mid} opened; coordinator task #{tid}; reads snapshot {snap}")
    if why:
        cases.log(con, cid, now, "chosen", f"why: {why[:300]} | revisit when: {revisit[:200] or 'its review date'}")
    return {"mission_id": mid, "case_id": cid, "task_id": tid, "state": "planning", "new": True, "snapshot": snap}


def _tag(con, tid: int, cid: int, role: str, snap: Optional[str], depends: Optional[List[int]]) -> None:
    con.execute("UPDATE hq_tasks SET case_id=?, role=?, input_version=?, depends_on=? WHERE task_id=?",
                [cid, role, snap, json.dumps(depends or []), tid])


def mission_of(con, cid: int) -> Optional[dict]:
    r = con.execute("SELECT mission_id, case_id, goal, state, round, plan_json, snapshot_id, result_json, next_trigger, blocker, origin, created_at "
                    "FROM hq_missions WHERE case_id=?", [cid]).fetchone()
    if not r:
        return None
    d = dict(zip(["id", "case_id", "goal", "state", "round", "plan", "snapshot", "result", "next_trigger", "blocker", "origin", "created"], r))
    d["plan"], d["result"] = json.loads(d["plan"] or "[]"), json.loads(d["result"] or "{}")
    return d


def add_task(con, now: datetime, cid: int, role: str, what: str, *, promise: Optional[dict] = None, depends_on: Optional[List[int]] = None,
             asked_by: Optional[int] = None, key: str = "") -> dict:
    """A worker task for a mission. Refused (with the reason) when the mission is over, the role is unknown, or it has reached MAX_TASKS."""
    from pflab.hq import board
    m = mission_of(con, cid)
    if m is None or m["state"] not in ACTIVE:
        return {"problem": "there is no active mission for that case"}
    if role not in AGENT_OF or role == "coordinator":
        return {"problem": f"role must be one of {ROLES + ('review',)}"}
    n = con.execute("SELECT count(*) FROM hq_tasks WHERE case_id=? AND created_at >= coalesce((SELECT max(logged_at) FROM hq_case_log WHERE case_id=? "
                    "AND event='reopened'), TIMESTAMP '1970-01-01')", [cid, cid]).fetchone()[0]
    if n >= MAX_TASKS:
        return {"problem": f"this mission has reached its limit of {MAX_TASKS} tasks"}
    promise = {k: int(v) for k, v in (promise or DEFAULT_PROMISE[role]).items() if k in PROMISE_KINDS and int(v) > 0} or DEFAULT_PROMISE[role]
    deps = [int(d) for d in (depends_on or [])]
    dedup = f"mission:{cid}:{role}:{hashlib.sha1((key or what).encode()).hexdigest()[:10]}:{m['round']}"
    tid = board.post(con, AGENT_OF[role], what[:2000], now, frm="mission", dedup_key=dedup,
                     body={"case_id": cid, "role": role, "promise": promise, "goal": m["goal"], "asked_by": asked_by, "key": key})
    _tag(con, tid, cid, role, m["snapshot"], deps)
    _park_if_waiting(con, tid, deps)
    return {"task_id": tid}


def _park_if_waiting(con, tid: int, deps: List[int]) -> None:
    """A task whose dependencies are not all done waits on the first one that is not (and is woken when it finishes)."""
    for d in deps:
        st = con.execute("SELECT status FROM hq_tasks WHERE task_id=?", [d]).fetchone()
        if st and st[0] != "done":
            con.execute("UPDATE hq_tasks SET status='waiting', waiting_on=?, wait_kind='task', resume_condition=?, progress=? WHERE task_id=? AND status='queued'",
                        [f"task:{d}", f"task #{d} finishes", f"waiting for task #{d}", tid])
            return


def set_plan(con, now: datetime, cid: int, steps, approach: str = "") -> dict:
    """Validate the coordinator's plan and create its tasks. A bad plan is refused with the reason (the coordinator is told and may fix it)."""
    from pflab.hq import cases
    m = mission_of(con, cid)
    if m is None or m["state"] != "planning":
        return {"stored": False, "problem": "the mission is not waiting for a plan"}
    if not isinstance(steps, list) or not (1 <= len(steps) <= 8):
        return {"stored": False, "problem": "the plan is 1 to 8 steps"}
    keys, clean = [], []
    for s in steps:
        if not isinstance(s, dict) or s.get("role") not in ROLES or not str(s.get("goal", "")).strip() or not str(s.get("key", "")).strip():
            return {"stored": False, "problem": "each step needs key, role (research or quant) and goal"}
        k = str(s["key"]).strip()[:30]
        if k in keys:
            return {"stored": False, "problem": f"step key {k!r} is used twice"}
        bad = [d for d in s.get("depends_on", []) if d not in keys]
        if bad:
            return {"stored": False, "problem": f"step {k!r} depends on {bad}, which come later or do not exist"}
        keys.append(k)
        clean.append({"key": k, "role": s["role"], "goal": str(s["goal"]).strip()[:1500], "promise": s.get("promise") or DEFAULT_PROMISE[s["role"]],
                      "depends_on": list(s.get("depends_on", []))})
    if not any(s["role"] == "quant" for s in clean) and not any(s["role"] == "research" for s in clean):
        return {"stored": False, "problem": "a plan needs work to do"}
    ids: Dict[str, int] = {}
    for s in clean:
        out = add_task(con, now, cid, s["role"], s["goal"], promise=s["promise"], depends_on=[ids[d] for d in s["depends_on"]], key=s["key"])
        if "task_id" not in out:
            return {"stored": False, "problem": out["problem"]}
        ids[s["key"]] = out["task_id"]
    for s in clean:
        s["task_id"] = ids[s["key"]]
    con.execute("UPDATE hq_missions SET state='working', plan_json=?, updated_at=?, last_progress_at=?, next_trigger=? WHERE case_id=?",
                [json.dumps(clean), now, now, "all steps done, then the independent review", cid])
    cases.log(con, cid, now, "plan", f"{len(clean)} step(s): " + "; ".join(f"{s['key']} ({s['role']})" for s in clean) + (f" | {approach[:200]}" if approach else ""))
    return {"stored": True, "mission_id": m["id"], "tasks": ids}


def set_answer(con, now: datetime, cid: int, answer: str, limits: str, monitor: str) -> dict:
    """The coordinator's answer is kept only after an approving review (or an exhausted revision budget, which the answer must then say)."""
    m = mission_of(con, cid)
    if m is None or m["state"] != "synthesising":
        return {"stored": False, "problem": "the answer is written after the independent review"}
    con.execute("UPDATE hq_missions SET result_json=?, updated_at=? WHERE case_id=?",
                [json.dumps({"answer": answer, "limitations": limits, "monitor_next": monitor, "at": str(now)}), now, cid])
    return {"stored": True, "mission_id": m["id"]}


# --- artifacts: what "done" is judged by ----------------------------------------------------------------------------------------------------

def artifacts(con, cid: Optional[int] = None, task_id: Optional[int] = None) -> List[dict]:
    q, a = "SELECT artifact_id, case_id, task_id, kind, ref, detail, created_at FROM hq_artifacts WHERE ", []
    if task_id is not None:
        q, a = q + "task_id=?", [task_id]
    else:
        q, a = q + "case_id=?", [cid]
    return [dict(zip(["id", "case_id", "task_id", "kind", "ref", "detail", "at"], r)) for r in con.execute(q + " ORDER BY artifact_id", a).fetchall()]


def kept(con, task_id: int, kind: str) -> int:
    """How many artifacts of this kind the task made. A calculation counts only if it ran: 'checked' (the workshop's word for agreement)."""
    rows = [a for a in artifacts(con, task_id=task_id) if a["kind"] == kind]
    if kind == "calc":
        rows = [a for a in rows if a["detail"] == "checked"]
    return len(rows)


def unmet(con, task_id: int, promise: dict) -> List[str]:
    out = []
    for kind, n in promise.items():
        got = kept(con, task_id, kind)
        if got < int(n):
            out.append(f"{kind}: {got} of {n}")
    return out


# --- the state machine ----------------------------------------------------------------------------------------------------------------------

def _tasks(con, cid: int) -> List[dict]:
    rows = con.execute("SELECT task_id, role, status, attempts, result, waiting_on, resume_condition, progress, finished_at, started_at, body_json, wait_kind, "
                       "next_review_at FROM hq_tasks WHERE case_id=? ORDER BY task_id", [cid]).fetchall()
    keys = ["id", "role", "status", "attempts", "result", "waiting_on", "resume", "progress", "finished", "started", "body", "wait_kind", "next_review"]
    out = []
    for r in rows:
        d = dict(zip(keys, r))
        d["body"] = json.loads(d["body"] or "{}")
        out.append(d)
    return out


def _set(con, cid: int, now: datetime, **f) -> None:
    sets = ", ".join(f"{k}=?" for k in f) + ", updated_at=?"
    con.execute(f"UPDATE hq_missions SET {sets} WHERE case_id=?", [*f.values(), now, cid])
    st = f.get("state")
    if st in ("working", "reviewing", "done", "blocked"):
        _tell(con, now, cid, st)


def _tell(con, now: datetime, cid: int, state: str) -> None:
    """The conversation hears each state of a mission once (the assistant's thread, deduplicated by case, state and round)."""
    try:
        from pflab.app import assistant
        m = mission_of(con, cid)
        g = (m["goal"] if m else "")[:140]
        text = {"working": f"I have planned the investigation of \"{g}\" and the workers are on it.",
                "reviewing": f"The research and the calculations for \"{g}\" are in; an independent reviewer is checking them.",
                "done": f"Finished: \"{g}\".\n\n" + ((m["result"] or {}).get("answer", "") if m else "") + "\n\nWhat could invalidate it: "
                        + ((m["result"] or {}).get("limitations", "") if m else "") + "\nWhat I will watch next: " + ((m["result"] or {}).get("monitor_next", "") if m else ""),
                "blocked": f"The investigation of \"{g}\" is stuck: {(m['blocker'] if m else '')}. It needs a person to decide."}[state]
        gen = con.execute("SELECT count(*) FROM hq_case_log WHERE case_id=? AND event='reopened'", [cid]).fetchone()[0]
        assistant.notify(con, now, text, f"mission:{cid}:{state}:{m['round'] if m else 0}:{gen}")
    except Exception:
        pass


MISSION_CAP_RS = 250.0                                 # what one mission may spend in all (workers and the calculation writers); [policy] mission_rupees


def mission_cost(con, cid: int, now: datetime) -> float:
    """Rupees spent while this mission's tasks were running: tasks run one at a time, so every paid call made between a task's start and its finish
    (its own turns and the calculation writers it rang) is the mission's."""
    return float(con.execute(
        "SELECT coalesce(sum(a.cost_inr), 0) FROM api_calls a WHERE a.status IN ('done','refused','submitted','queued') AND EXISTS (SELECT 1 FROM hq_tasks t "
        "WHERE t.case_id=? AND t.started_at IS NOT NULL AND a.created_at >= t.started_at AND a.created_at <= coalesce(t.finished_at, ?))", [cid, now]).fetchone()[0])


def cap_of() -> float:
    try:
        from pflab.agents import analyst as an
        return float(((an.config().get("policy") or {}).get("mission_rupees")) or MISSION_CAP_RS)
    except Exception:
        return MISSION_CAP_RS


def tick(rt) -> dict:
    """Move every active mission on by one step, from what the store says. Code only; safe to call as often as the HQ round does and after any
    restart. Returns {case_id: new state}."""
    from pflab.hq import board, cases
    con, now = rt.cursor(), rt.clock()
    moved = {}
    sandbox_ok = None
    for (cid,) in con.execute(f"SELECT case_id FROM hq_missions WHERE state IN ({','.join(repr(s) for s in ACTIVE)}) ORDER BY mission_id").fetchall():
        m = mission_of(con, cid)
        ts = _tasks(con, cid)
        if sandbox_ok is None and any(t["waiting_on"] == "sandbox" for t in ts):
            try:                                              # missing Docker is a wait: when it is there again, the tasks that waited go on
                from pflab.agents import sandbox as sb
                sandbox_ok = bool(sb.status()["ok"])
            except Exception:
                sandbox_ok = False
            if sandbox_ok:
                board.wake(con, "sandbox", now, "the sandbox is available")
        failed = [t for t in ts if t["status"] in ("failed", "dismissed") and not str(t["result"] or "").startswith("not started: the mission's budget")]
        if failed:
            f = failed[0]
            _set(con, cid, now, state="blocked", blocker=f"task #{f['id']} ({f['role']}) failed: {(f['result'] or '')[:200]}",
                 next_trigger="a person decides: retry the task or close the mission")
            cases.set_status(con, cid, "failed", now, f"mission blocked: task #{f['id']} {f['role']} failed")
            moved[cid] = "blocked"
            continue
        openn = [t for t in ts if t["status"] in OPEN_TASK]
        state = m["state"]
        if state == "planning":
            _progress(con, cid, now, openn, "the coordinator plans the steps")
        elif state == "working":
            work = [t for t in openn if t["role"] in ROLES]
            over = mission_cost(con, cid, now) >= cap_of()
            if work and over:                                 # the mission's money is spent: what has not started is dropped, said, and the review goes ahead
                for t in work:
                    if t["status"] != "running":
                        con.execute("UPDATE hq_tasks SET status='dismissed', finished_at=?, result=? WHERE task_id=?",
                                    [now, f"not started: the mission's budget of Rs {cap_of():,.0f} was spent", t["id"]])
                        cases.log(con, cid, now, "budget", f"task #{t['id']} ({t['role']}) dropped: the mission's budget is spent")
                work = [t for t in work if t["status"] == "running"]
                openn = [t for t in openn if t["status"] == "running" or t["role"] not in ROLES]
            if work:
                _progress(con, cid, now, work, "the workers finish their steps")
            elif not any(t["role"] == "review" and t["status"] in OPEN_TASK for t in ts):
                out = add_task(con, now, cid, "review", f"Review mission #{m['id']}: {m['goal'][:300]}", promise={"review": 1}, key=f"review{m['round']}")
                _set(con, cid, now, state="reviewing", last_progress_at=now, next_trigger="the independent review finishes", blocker=None)
                cases.log(con, cid, now, "review requested", f"task #{out.get('task_id')}, round {m['round']}")
                moved[cid] = "reviewing"
        elif state == "reviewing":
            rev = [t for t in ts if t["role"] == "review"]
            if any(t["status"] in OPEN_TASK for t in rev):
                _progress(con, cid, now, [t for t in rev if t["status"] in OPEN_TASK], "the independent review finishes")
                continue
            r = con.execute("SELECT outcome, note, process_json FROM hq_case_reviews WHERE case_id=? AND outcome IS NOT NULL ORDER BY review_id DESC LIMIT 1",
                            [cid]).fetchone()
            if r is None:
                _set(con, cid, now, state="blocked", blocker="the review task ended without a verdict", next_trigger="a person decides")
                moved[cid] = "blocked"
                continue
            outcome, note, proc = r
            reqs = (json.loads(proc or "{}").get("revisions") or []) if outcome == "revise" else []
            spent_out = mission_cost(con, cid, now) >= cap_of()
            if outcome == "revise" and m["round"] < MAX_ROUNDS and reqs and not spent_out:
                for q in reqs[:4]:
                    role = q.get("role") if q.get("role") in ROLES else "quant"
                    add_task(con, now, cid, role, f"REVISION requested by the independent review: {str(q.get('what', ''))[:600]}",
                             promise=DEFAULT_PROMISE[role], key=f"rev{m['round']}:{q.get('what', '')[:40]}")
                _set(con, cid, now, state="working", round=m["round"] + 1, last_progress_at=now, next_trigger="the revisions, then a second review", blocker=None)
                cases.log(con, cid, now, "revision", f"round {m['round'] + 1}: {len(reqs[:4])} request(s)")
                moved[cid] = "working"
            else:
                final = ("approved" if outcome == "approve" else
                         ("NOT approved: the mission stopped on its budget" if spent_out else "NOT approved after the revision rounds")
                         + ": the answer must state what the review still objects to" if outcome == "revise" else
                         "REJECTED by the review: the answer must be inconclusive and say why")
                _final_task(con, now, cid, m, final, note)
                _set(con, cid, now, state="synthesising", last_progress_at=now, next_trigger="the coordinator writes the answer", blocker=None)
                moved[cid] = "synthesising"
        elif state == "synthesising":
            fin = [t for t in ts if t["role"] == "coordinator" and t["body"].get("step") == "final"]
            if any(t["status"] in OPEN_TASK for t in fin):
                _progress(con, cid, now, [t for t in fin if t["status"] in OPEN_TASK], "the coordinator writes the answer")
            elif fin and fin[-1]["status"] == "done" and m["result"].get("answer"):
                a = con.execute("SELECT outcome FROM hq_case_reviews WHERE case_id=? AND outcome IS NOT NULL ORDER BY review_id DESC LIMIT 1", [cid]).fetchone()
                decision = "inconclusive" if (a and a[0] == "rejected") else "watch"
                cases.conclude(con, cid, now, decision, m["result"]["answer"][:500], uncertainty=m["result"].get("limitations", "")[:400],
                               next_review_at=now + timedelta(days=cases.REVIEW_DAYS))
                _set(con, cid, now, state="done", last_progress_at=now, next_trigger=m["result"].get("monitor_next", "")[:300] or "the case review date", blocker=None)
                moved[cid] = "done"
    return moved


def reopen(con, now: datetime, cid: int, why: str) -> dict:
    """A finished mission is looked at again (its review is due, or something new arrived): the SAME investigation resumes, with its earlier answer,
    its evidence and its calculations in front of the coordinator, who plans only what changed. Idempotent for a mission that is not done."""
    from pflab.hq import board, cases
    m = mission_of(con, cid)
    if m is None or m["state"] != "done":
        return {"reopened": False, "why": "the mission is not finished"}
    prev = m["result"] or {}
    con.execute("UPDATE hq_missions SET state='planning', round=0, plan_json=NULL, updated_at=?, last_progress_at=?, next_trigger=?, blocker=NULL WHERE case_id=?",
                [now, now, "the coordinator plans what changed", cid])
    cases.set_status(con, cid, "running", now)
    cases.log(con, cid, now, "reopened", why[:300])
    text = (f"Review of an earlier investigation: {m['goal'][:300]}. Why now: {why[:300]}. Earlier answer: {str(prev.get('answer', ''))[:600]} "
            f"Watching for: {str(prev.get('monitor_next', ''))[:300]}. Plan only what has CHANGED since {str(prev.get('at', ''))[:10]}: new evidence, "
            "updated numbers on the current snapshot, and whether the earlier conclusion still stands.")
    tid = board.post(con, AGENT_OF["coordinator"], text, now, frm=m["origin"] or "code", dedup_key=f"mission:{cid}:reopen:{now:%Y%m%d}",
                     body={"case_id": cid, "role": "coordinator", "promise": DEFAULT_PROMISE["coordinator"], "goal": m["goal"], "step": "plan"})
    _tag(con, tid, cid, "coordinator", m["snapshot"], [])
    return {"reopened": True, "task_id": tid}


def retry(con, now: datetime, cid: int) -> dict:
    """A person (or the system after a fix) says: try the failed steps again. The tasks that failed go back to the queue with their attempts
    cleared and their checkpoints and artifacts kept; the mission returns to the state those tasks belong to."""
    from pflab.hq import cases
    m = mission_of(con, cid)
    if m is None or m["state"] != "blocked":
        return {"retried": 0, "why": "the mission is not blocked"}
    failed = [t for t in _tasks(con, cid) if t["status"] in ("failed", "dismissed")]
    for t in failed:
        con.execute("UPDATE hq_tasks SET status='queued', attempts=0, finished_at=NULL, waiting_on=NULL, wait_kind=NULL, resume_condition=NULL, "
                    "progress='retried by a person', next_review_at=NULL WHERE task_id=?", [t["id"]])
        cases.log(con, cid, now, "retry", f"task #{t['id']} ({t['role']}) put back in the queue")
    roles = {t["role"] for t in failed}
    state = "reviewing" if "review" in roles else "planning" if ("coordinator" in roles and not m["plan"]) else "synthesising" if "coordinator" in roles else "working"
    _set(con, cid, now, state=state, blocker=None, next_trigger="the retried steps finish", last_progress_at=now)
    cases.set_status(con, cid, "running", now, "a mission: retried")
    return {"retried": len(failed), "state": state}


def _final_task(con, now: datetime, cid: int, m: dict, final: str, note: Optional[str]) -> None:
    from pflab.hq import board
    tid = board.post(con, AGENT_OF["coordinator"], f"Write the final answer for the investor. Review outcome: {final}. Review notes: {(note or '')[:800]}", now,
                     frm="mission", dedup_key=f"mission:{cid}:final",
                     body={"case_id": cid, "role": "coordinator", "promise": {"answer": 1}, "goal": m["goal"], "step": "final"})
    _tag(con, tid, cid, "coordinator", m["snapshot"], [])


def _progress(con, cid: int, now: datetime, open_tasks: List[dict], label: str) -> None:
    """Keep the mission's `blocker` and `next_trigger` truthful from its open tasks: a task that waits says what resumes it."""
    waiting = [t for t in open_tasks if t["status"] in ("waiting", "retry") and t["wait_kind"] != "task"]
    blocker = None
    if waiting:
        w = waiting[0]
        blocker = f"task #{w['id']} ({w['role']}) is waiting: {w['resume'] or w['waiting_on'] or 'a retry'}"
    elif any(t["status"] == "needs_approval" for t in open_tasks):
        blocker = "a step needs your yes"
    con.execute("UPDATE hq_missions SET blocker=?, next_trigger=? WHERE case_id=?", [blocker, label, cid])


# --- the investigation card the screen shows ------------------------------------------------------------------------------------------------

def card(con, cid: int) -> Optional[dict]:
    """Goal, owner, current action, completed outputs, blocker, last useful progress and next trigger of a mission, from the store."""
    m = mission_of(con, cid)
    if m is None:
        return None
    ts = _tasks(con, cid)
    running = [t for t in ts if t["status"] == "running"]
    cur = running[0] if running else next((t for t in ts if t["status"] in OPEN_TASK), None)
    outputs = [{"kind": a["kind"], "ref": a["ref"], "detail": a["detail"], "task": a["task_id"]} for a in artifacts(con, cid)]
    last = con.execute("SELECT max(created_at) FROM hq_artifacts WHERE case_id=?", [cid]).fetchone()[0]
    chosen = con.execute("SELECT detail FROM hq_case_log WHERE case_id=? AND event='chosen' ORDER BY log_id DESC LIMIT 1", [cid]).fetchone()
    return {"mission_id": m["id"], "case_id": cid, "goal": m["goal"], "state": m["state"], "round": m["round"], "snapshot": m["snapshot"],
            "origin": m["origin"], "why_chosen": chosen[0] if chosen else None,
            "owner": (cur or {}).get("role") or ("coordinator" if m["state"] in ("planning", "synthesising") else None),
            "current_action": (cur or {}).get("progress") or (f"{cur['role']} task #{cur['id']} {cur['status']}" if cur else None),
            "tasks": [{"id": t["id"], "role": t["role"], "status": t["status"], "waiting_on": t["waiting_on"], "resume": t["resume"]} for t in ts],
            "outputs": outputs, "blocker": m["blocker"], "last_useful_progress": str(last or m["created"])[:16], "next_trigger": m["next_trigger"],
            "answer": m["result"] or None}


# --- autonomy: work the system chooses (S68) ---------------------------------------------------------------------------------------------------

DAILY_NEW = 3                                         # missions the system may start by itself in a day (twice as many in the acceptance window)


def started_today(con, now: datetime) -> int:
    return int(con.execute("SELECT count(*) FROM hq_missions WHERE origin='system' AND created_at >= ?", [datetime(now.year, now.month, now.day)]).fetchone()[0])


def adopt(rt) -> dict:
    """A signal the stores show (a material document about a held name, an IPO allotment, a hypothesis waiting for a decision) is investigated
    by the workers instead of waiting for a person to ask. Each is a mission with the reason it was chosen and what would justify looking again;
    an unchanged signal is never adopted twice (the case key), a day's starts are bounded, and Pause stops it. Returns {started, held_back}."""
    from pflab.agents import analyst as an
    from pflab.hq import cases, service
    con, now = rt.cursor(), rt.clock()
    cap = DAILY_NEW * (2 if an.acceptance(an.config(), now) else 1)
    out = {"started": [], "held_back": 0}
    # only the signals worth a team: new evidence about a held or watched name, and an IPO allotment. A hypothesis to decide, a thesis ending, an unscored
    # prediction and a held task stay with the brain's own case pass (cheaper, and they are housekeeping of its own journal).
    rows = con.execute("SELECT case_id, question, subject, isin, subject_key FROM hq_cases WHERE origin='code' AND status='queued' "
                       "AND (subject_key LIKE 'discover:reading:%' OR subject_key LIKE 'discover:ipo:%') AND case_id NOT IN (SELECT case_id FROM hq_missions) "
                       "ORDER BY case_id").fetchall()
    # ONE mission per company and kind of signal: the first real run found six missions on six documents about the same company's results, the same story.
    # The first signal leads; the others are folded into its goal and their cases closed as covered, so the team looks at the company once.
    groups: dict = {}
    for row in rows:
        groups.setdefault((row[3] or row[2] or row[0], row[4].split(":")[1]), []).append(row)
    recent = {(r[0], r[1]) for r in con.execute(
        "SELECT coalesce(c.isin, c.subject), split_part(c.subject_key, ':', 2) FROM hq_missions m JOIN hq_cases c ON c.case_id = m.case_id "
        "WHERE m.origin='system' AND m.created_at >= ?", [now - timedelta(days=7)]).fetchall()}
    for (who, kind0), members in groups.items():
        lead, rest = members[0], members[1:]
        if (who, kind0) in recent:                            # already looked at this week: these signals are covered, not repeated
            for r in members:
                _cover(con, now, r[0], "an investigation of this company for this kind of signal was started this week")
            continue
        cid, question, subject, isin, key = lead
        if rest:
            question = (question + " Other documents of the same kind, read in the same period: " + " | ".join(r[1][:160] for r in rest[:5]))[:1200]
            for r in rest:
                _cover(con, now, r[0], f"folded into case #{cid} (the same company, the same kind of signal)")
        if started_today(con, now) >= cap:
            out["held_back"] += 1
            continue
        kind = key.split(":")[1]
        why = {"reading": "a material document about a name he holds or watches was read and nothing connects it to his plan yet",
               "ipo": "an IPO allotment is in hand and the decision must be made before the listing",
               "hypothesis": "a hypothesis about a price move is waiting for a decision",
               "thesis": "a thesis he holds is about to end",
               "prediction": "a prediction passed its date without being scored",
               "held": "a chain of agents stopped at its hop limit"}.get(kind, "a signal in the stores")
        revisit = {"reading": "the company files again, or in a week", "ipo": "the listing day", "hypothesis": "new evidence on the move"}.get(kind, "its review date")
        r = _adopt_case(con, now, cid, question, subject, isin, why, revisit, rt.pm_dir)
        out["started"].append(r["case_id"])
    return out


def _cover(con, now: datetime, cid: int, why: str) -> None:
    """A signal another mission already covers: its case is closed with the reason (never silently dropped, never opened again: the case key stays)."""
    from pflab.hq import cases
    con.execute("UPDATE hq_cases SET status='done', decision='nothing', decision_reason=?, closed_at=?, updated_at=?, next_review_at=NULL WHERE case_id=? AND status='queued'",
                [why[:300], now, now, cid])
    cases.log(con, cid, now, "covered", why[:300])


def _adopt_case(con, now: datetime, cid: int, question: str, subject, isin, why: str, revisit: str, pm_dir) -> dict:
    """Make an existing code-opened case into a mission (the same case id stays the parent investigation)."""
    from pflab.hq import board, cases
    goal = " ".join(question.split())[:1200]
    mid = _id(con, "hq_missions", "mission_id")
    snap = snapshot_id(con, pm_dir) if pm_dir else "unknown"
    con.execute("INSERT INTO hq_missions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [mid, cid, now, now, goal, "planning", 0, None, snap, None, now, "the coordinator plans the steps", None, "system"])
    cases.set_status(con, cid, "running", now, "a mission chosen by the system")
    tid = board.post(con, AGENT_OF["coordinator"], f"Plan the mission: {goal}", now, frm="system",
                     body={"case_id": cid, "role": "coordinator", "promise": DEFAULT_PROMISE["coordinator"], "goal": goal, "step": "plan"})
    _tag(con, tid, cid, "coordinator", snap, None)
    cases.log(con, cid, now, "chosen", f"why: {why} | revisit when: {revisit}")
    cases.log(con, cid, now, "mission", f"mission #{mid} opened by the system; coordinator task #{tid}; reads snapshot {snap}")
    try:
        from pflab.app import assistant
        assistant.notify(con, now, f"While you were away I started looking into: {goal[:200]}\nWhy: {why}.\nI will come back with what I find.", f"chosen:{cid}")
    except Exception:
        pass
    return {"case_id": cid, "mission_id": mid, "task_id": tid}


def due_reviews(rt) -> List[int]:
    """Finished missions whose review day has come are reopened (the same investigation resumes). Bounded like new starts."""
    con, now = rt.cursor(), rt.clock()
    out = []
    for (cid,) in con.execute("SELECT m.case_id FROM hq_missions m JOIN hq_cases c ON c.case_id = m.case_id WHERE m.state='done' AND c.next_review_at IS NOT NULL "
                              "AND c.next_review_at <= ? ORDER BY c.next_review_at", [now]).fetchall():
        if started_today(con, now) + len(out) >= DAILY_NEW * 2:
            break
        r = reopen(con, now, cid, f"its scheduled review day came ({now:%Y-%m-%d})")
        if r["reopened"]:
            out.append(cid)
            try:
                from pflab.app import assistant
                gen = con.execute("SELECT count(*) FROM hq_case_log WHERE case_id=? AND event='reopened'", [cid]).fetchone()[0]
                assistant.notify(con, now, "A scheduled review came due; I have reopened the investigation and am updating it.", f"review:{cid}:{gen}")
            except Exception:
                pass
    return out


def scan(rt) -> dict:
    """The autonomous step of the HQ round: discover signals (free, code), adopt them as missions, reopen due reviews. Never asks a model itself."""
    from pflab.hq import cases, service
    con, now = rt.cursor(), rt.clock()
    held, listed = service.names(rt)
    opened = cases.discover(con, now, held, listed)
    return {"discovered": len(opened), **adopt(rt), "reviews_reopened": due_reviews(rt)}
