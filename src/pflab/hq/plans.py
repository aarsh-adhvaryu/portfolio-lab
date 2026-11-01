"""Plan versions, approval and amendments (S69).

An investigation's INSTRUCTIONS are numbered. Version 1 is the request; each later version is an amendment he made in chat (or the review day's
reopening). A version is `drafting` (the instruction is recorded; the coordinator has not yet planned it), then `proposed` (a plan that needs his yes: a
new request from him, or an amendment that changes the scope or a financial policy) or `auto` (a plan inside a scope he already approved), then
`approved` when he says yes. A newer approved or auto version `superseded`s the older; one he declines is `rejected`.

    approve once       the first plan of a request from him waits for his yes; the tasks exist (owners, dependencies) but do not run (`needs_approval`)
    then stay inside   a later amendment that only refines (a different horizon, a cost assumption, a worry to look at) is applied at once: no second yes
    ask again          an amendment that changes the question, adds a different kind of work, or touches a financial policy waits for his yes again
    never trade        approving a plan starts research and calculation; it places no order and changes no target, limit or the stock list

Every worker task carries the version it was started under (`hq_tasks.instruction_version`). A result from an older version is not published as it stands:
the review is asked again after an amendment (a verdict older than the active version is ignored), and the reviewer is told which tasks ran under which
version.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

KEYS = ["case_id", "version", "created_at", "source", "instruction", "plan_json", "status", "decided_at", "decided_by", "note", "material"]


def versions(con, cid: int) -> List[dict]:
    rows = con.execute("SELECT " + ", ".join(KEYS) + " FROM hq_plan_versions WHERE case_id=? ORDER BY version", [cid]).fetchall()
    out = []
    for r in rows:
        d = dict(zip(KEYS, r))
        d["plan"] = json.loads(d.pop("plan_json") or "null")
        out.append(d)
    return out


def active(con, cid: int) -> Optional[dict]:
    """The version being carried out: the newest one that is approved, or inside an approved scope."""
    act = [v for v in versions(con, cid) if v["status"] in ("approved", "auto")]
    return act[-1] if act else None


def active_number(con, cid: int) -> int:
    a = active(con, cid)
    return int(a["version"]) if a else 0


def waiting(con, cid: int) -> Optional[dict]:
    """The plan that waits for his yes, if any."""
    p = [v for v in versions(con, cid) if v["status"] == "proposed"]
    return p[-1] if p else None


def drafting(con, cid: int) -> Optional[dict]:
    d = [v for v in versions(con, cid) if v["status"] == "drafting"]
    return d[-1] if d else None


def begin(con, now: datetime, cid: int, source: str, instruction: str, material: bool) -> int:
    """Record an instruction as the next version, to be planned. Only one version drafts at a time (a second instruction replaces its text)."""
    d = drafting(con, cid)
    if d:
        con.execute("UPDATE hq_plan_versions SET instruction=?, material=?, source=? WHERE case_id=? AND version=?",
                    [instruction[:1500], bool(material) or bool(d["material"]), source, cid, d["version"]])
        return int(d["version"])
    n = int(con.execute("SELECT coalesce(max(version), 0) + 1 FROM hq_plan_versions WHERE case_id=?", [cid]).fetchone()[0])
    con.execute("INSERT INTO hq_plan_versions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [cid, n, now, source, instruction[:1500], None, "drafting", None, None, None, bool(material)])
    return n


def settle(con, now: datetime, cid: int, plan: list) -> dict:
    """The coordinator's plan arrived for the drafting version. Material (needs his yes) -> `proposed`; otherwise it takes effect now (`auto`)."""
    d = drafting(con, cid)
    if d is None:                                   # a mission from before S69, or a replan nobody recorded: inside the scope already approved
        n = begin(con, now, cid, "replan", "(replanned)", False)
        d = {"version": n, "material": False}
    status = "proposed" if d["material"] else "auto"
    con.execute("UPDATE hq_plan_versions SET plan_json=?, status=?, decided_at=?, decided_by=? WHERE case_id=? AND version=?",
                [json.dumps(plan), status, None if status == "proposed" else now, None if status == "proposed" else "inside the approved scope",
                 cid, d["version"]])
    if status == "auto":
        _supersede(con, cid, int(d["version"]))
    return {"version": int(d["version"]), "status": status}


def _supersede(con, cid: int, keep: int) -> None:
    con.execute("UPDATE hq_plan_versions SET status='superseded' WHERE case_id=? AND version<? AND status IN ('approved','auto','proposed')", [cid, keep])


def approve(con, now: datetime, cid: int, by: str = "the investor", note: str = "") -> dict:
    """His yes to the plan that waits. Its tasks (held as `needs_approval`) are queued, or parked on the tasks they depend on."""
    from pflab.hq import cases, missions
    p = waiting(con, cid)
    if p is None:
        return {"approved": False, "why": "no plan is waiting for approval"}
    v = int(p["version"])
    con.execute("UPDATE hq_plan_versions SET status='approved', decided_at=?, decided_by=?, note=? WHERE case_id=? AND version=?", [now, by, note[:300], cid, v])
    _supersede(con, cid, v)
    ids = [r[0] for r in con.execute("SELECT task_id FROM hq_tasks WHERE case_id=? AND status='needs_approval' AND coalesce(instruction_version, 0)=? ORDER BY task_id",
                                     [cid, v]).fetchall()]
    for tid in ids:
        con.execute("UPDATE hq_tasks SET status='queued', progress='plan approved' WHERE task_id=?", [tid])
        deps = json.loads(con.execute("SELECT coalesce(depends_on, '[]') FROM hq_tasks WHERE task_id=?", [tid]).fetchone()[0])
        missions._park_if_waiting(con, tid, deps)
    con.execute("UPDATE hq_missions SET state='working', updated_at=?, last_progress_at=?, next_trigger=?, blocker=NULL WHERE case_id=? AND state='awaiting_approval'",
                [now, now, "all steps done, then the independent review", cid])
    cases.log(con, cid, now, "plan approved", f"plan v{v} approved by {by}; {len(ids)} task(s) released" + (f" | {note[:120]}" if note else ""))
    missions._tell(con, now, cid, "working")
    return {"approved": True, "version": v, "tasks": ids}


def decline(con, now: datetime, cid: int, by: str = "the investor", note: str = "") -> dict:
    """He does not approve the plan that waits: its tasks are dropped, the investigation is closed as declined (he can ask again, differently)."""
    from pflab.hq import cases
    p = waiting(con, cid)
    if p is None:
        return {"declined": False, "why": "no plan is waiting for approval"}
    v = int(p["version"])
    con.execute("UPDATE hq_plan_versions SET status='rejected', decided_at=?, decided_by=?, note=? WHERE case_id=? AND version=?", [now, by, note[:300], cid, v])
    con.execute("UPDATE hq_tasks SET status='dismissed', finished_at=?, result=? WHERE case_id=? AND status='needs_approval'",
                [now, f"superseded: plan v{v} was not approved", cid])
    # an amendment he declines leaves the work as it was; a first plan he declines ends the investigation
    if active(con, cid) is None:
        con.execute("UPDATE hq_missions SET state='declined', updated_at=?, next_trigger=?, blocker=? WHERE case_id=?",
                    [now, "he can ask again, differently", "the plan was not approved", cid])
        cases.conclude(con, cid, now, "nothing", f"the plan was not approved by {by}" + (f": {note[:160]}" if note else ""), next_review_at=None)
    else:
        con.execute("UPDATE hq_missions SET state='working', updated_at=?, next_trigger=?, blocker=NULL WHERE case_id=? AND state='awaiting_approval'",
                    [now, f"the amendment (v{v}) was declined; the earlier plan goes on", cid])
    cases.log(con, cid, now, "plan declined", f"plan v{v} declined by {by}" + (f": {note[:160]}" if note else ""))
    return {"declined": True, "version": v}


def amend(con, now: datetime, cid: int, instruction: str, *, scope_change: bool = False, financial_policy: bool = False,
          by: str = "the investor (chat)") -> dict:
    """A new instruction for an investigation, from the conversation. It becomes the next version at once and persists; the coordinator replans only what
    it changes; unstarted tasks of the older version are dropped (said), running ones finish and are re-checked by the review. A change of scope or of a
    financial policy waits for his yes again; a refinement does not. Idempotent: the same words twice are one version."""
    from pflab.hq import board, cases, missions
    m = missions.mission_of(con, cid)
    if m is None:
        return {"amended": False, "why": "there is no investigation with that id"}
    if m["state"] in ("declined",):
        return {"amended": False, "why": "that investigation was declined; start a new one"}
    text = " ".join((instruction or "").split())[:1500]
    if len(text) < 8:
        return {"amended": False, "why": "say what should change"}
    vs = versions(con, cid)
    if any(v["instruction"] == text and v["status"] != "rejected" for v in vs):
        return {"amended": False, "duplicate": True, "version": active_number(con, cid), "why": "that instruction is already recorded"}
    material = bool(scope_change or financial_policy)
    v = begin(con, now, cid, "amendment", text, material)
    dropped = []
    for (tid, role, st) in con.execute("SELECT task_id, role, status FROM hq_tasks WHERE case_id=? AND status IN ('queued','waiting','retry','needs_approval') "
                                       "AND role IN ('research','quant','review') ORDER BY task_id", [cid]).fetchall():
        con.execute("UPDATE hq_tasks SET status='dismissed', finished_at=?, result=? WHERE task_id=?", [now, f"superseded: instruction v{v} replaced it", tid])
        dropped.append(tid)
    for (tid, body) in con.execute("SELECT task_id, body_json FROM hq_tasks WHERE case_id=? AND status='running' AND role IN ('research','quant','review')", [cid]).fetchall():
        b = json.loads(body or "{}")
        b["superseded_by"] = v
        con.execute("UPDATE hq_tasks SET body_json=? WHERE task_id=?", [json.dumps(b), tid])
    prev = m["result"] or {}
    con.execute("UPDATE hq_missions SET state='planning', round=0, updated_at=?, last_progress_at=?, next_trigger=?, blocker=NULL WHERE case_id=?",
                [now, now, f"the coordinator plans what instruction v{v} changes", cid])
    cases.set_status(con, cid, "running", now)
    cases.log(con, cid, now, "amendment", f"v{v} from {by}{' (needs his yes: scope or policy)' if material else ''}: {text[:260]}"
              + (f" | {len(dropped)} unstarted task(s) replaced" if dropped else ""))
    body = {"case_id": cid, "role": "coordinator", "promise": missions.DEFAULT_PROMISE["coordinator"], "goal": m["goal"], "step": "plan", "amendment": v}
    prompt = (f"AMENDMENT v{v} to an investigation. Original question: {m['goal'][:300]}. The investor now says: {text}. "
              + (f"Earlier answer: {str(prev.get('answer', ''))[:500]}. " if prev.get("answer") else "")
              + "Plan ONLY what this changes: new steps, and steps to do again because their inputs changed. Finished work that is still valid is reused, "
                "not repeated. Say in `approach` which finished tasks the amendment affects.")
    tid = board.post(con, missions.AGENT_OF["coordinator"], prompt, now, frm="investor", dedup_key=f"mission:{cid}:amend:{v}", body=body)
    missions._tag(con, tid, cid, "coordinator", m["snapshot"], [], version=v)
    return {"amended": True, "version": v, "needs_approval": material, "replaced_tasks": dropped, "task_id": tid}


def instructions_text(con, cid: int) -> str:
    """The instruction history as a worker or reviewer reads it: what was asked, what changed, which version is in force."""
    vs = versions(con, cid)
    if not vs:
        return ""
    act = active_number(con, cid)
    lines = [f"INSTRUCTIONS (version in force: v{act or '-'}; later versions replace earlier wording where they differ):"]
    for v in vs:
        lines.append(f"  v{v['version']} [{v['status']}, {v['source']}, {str(v['created_at'])[:16]}]: {(v['instruction'] or '')[:400]}")
    return "\n".join(lines)


def superseded_tasks(con, cid: int) -> List[dict]:
    """Finished worker tasks that ran under an instruction version older than the one in force: the review must say whether each still holds."""
    act = active_number(con, cid)
    if not act:
        return []
    return [{"id": r[0], "role": r[1], "version": int(r[2] or 0)} for r in con.execute(
        "SELECT task_id, role, instruction_version FROM hq_tasks WHERE case_id=? AND status='done' AND role IN ('research','quant') "
        "AND coalesce(instruction_version, 0) < ? ORDER BY task_id", [cid, act]).fetchall()]
