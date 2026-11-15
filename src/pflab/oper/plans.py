"""S89b: plan cards. A multi-step request ("plan how to test pairs trading", "look into IT stocks and report") first becomes a PLAN CARD: the steps, the tool or agent each step uses and a token estimate, with
Start / Change / Cancel. NOTHING runs before Start. On Start each step runs as one full-road session turn and ticks off live (`rt.bump("plans")` -> `/api/events`); the result lands in the chat and on Telegram.
A plan that hits the plan's limit PAUSES with its finished steps kept and resumes after the reset (`resume_due`, called by the job `operator_plans`). A plan that needs code is a build request (Yes/No) instead.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from pflab.llm import claude_plan as cp
from pflab.llm import gateway as gw

MAX_STEPS = 8
STEP_TOKENS = 25000                                  # the estimate per step, from the measured full road (S88: 19k to 80k a question)
DDL = ["CREATE TABLE IF NOT EXISTS plans_s89 (plan_id INTEGER PRIMARY KEY, created_at TIMESTAMP NOT NULL, chat_id INTEGER, title VARCHAR NOT NULL, status VARCHAR NOT NULL, est_tokens INTEGER, tokens INTEGER, "
       "resume_after TIMESTAMP, result_text VARCHAR, card_msg_id INTEGER, finished_at TIMESTAMP)",
       "CREATE TABLE IF NOT EXISTS plan_steps_s89 (plan_id INTEGER NOT NULL, n INTEGER NOT NULL, text VARCHAR NOT NULL, uses VARCHAR, est_tokens INTEGER, status VARCHAR NOT NULL, result VARCHAR, tokens INTEGER, "
       "started_at TIMESTAMP, finished_at TIMESTAMP, PRIMARY KEY (plan_id, n))"]
RT: Dict[str, Any] = {"rt": None}
RUN_STEP = None                                        # tests: a scripted `fn(con, plan, step, prior_text) -> (text, tokens)`
_LOCK = threading.Lock()
_OWNED: set = set()
_RUNNING: set = set()


def bind(rt) -> None:
    RT["rt"] = rt


def ensure(con) -> None:
    for d in DDL:
        con.execute(d)


def _bump(topic: str = "plans") -> None:
    rt = RT["rt"]
    if rt is not None:
        try:
            rt.bump(topic, "chat")
        except Exception:
            pass


def propose(con, now: datetime, title: str, steps: List[dict], chat_id: Optional[int] = None) -> str:
    """Post the plan card. Nothing runs here."""
    from pflab.entrance import cards
    from pflab.pm.store import next_id
    ensure(con)
    title = " ".join(str(title or "").split())[:120]
    clean = []
    for s in (steps or [])[:MAX_STEPS]:
        t = " ".join(str(s.get("text") if isinstance(s, dict) else s).split())[:240]
        if t:
            clean.append({"text": t, "uses": str((s.get("uses") or s.get("tool") or s.get("agent") or "") if isinstance(s, dict) else "")[:80], "est": int((s.get("est_tokens") if isinstance(s, dict) else 0) or STEP_TOKENS)})
    if len(title) < 6 or len(clean) < 2:
        return "Not proposed: a plan needs a title and at least two steps. Answer a single step directly."
    pid = next_id(con, "plans_s89", "plan_id")
    est = sum(s["est"] for s in clean)
    con.execute("INSERT INTO plans_s89 (plan_id, created_at, chat_id, title, status, est_tokens, tokens) VALUES (?,?,?,?,?,?,0)", [pid, now, chat_id, title, "proposed", est])
    for i, s in enumerate(clean, 1):
        con.execute("INSERT INTO plan_steps_s89 (plan_id, n, text, uses, est_tokens, status) VALUES (?,?,?,?,?,'pending')", [pid, i, s["text"], s["uses"], s["est"]])
    text = (f"Plan: {title}\n" + "\n".join(f"{i}. {s['text']}" + (f" ({s['uses']})" if s["uses"] else "") for i, s in enumerate(clean, 1))
            + f"\nAbout {est:,} tokens of your plan. Yes starts it, No cancels it; to change it, say what to change.")
    mid = cards.post_decision_card(con, now, "plan", {"plan_id": pid}, text, "pflab.oper.plans:on_yes", expires_hours=48)
    con.execute("UPDATE plans_s89 SET card_msg_id=? WHERE plan_id=?", [mid, pid])
    _bump()
    return f"A plan card is in the chat (plan #{pid}, {len(clean)} steps, about {est:,} tokens). Nothing runs until he taps Start."


def on_yes(con, now: datetime, payload: dict) -> str:
    start(con, now, int(payload["plan_id"]))
    return "Started. The steps tick off as they finish; the result comes here and on Telegram."


def get(con, plan_id: int) -> Optional[dict]:
    ensure(con)
    r = con.execute("SELECT plan_id, created_at, chat_id, title, status, est_tokens, tokens, resume_after, result_text, finished_at FROM plans_s89 WHERE plan_id=?", [plan_id]).fetchone()
    if not r:
        return None
    steps = [dict(zip(("n", "text", "uses", "est_tokens", "status", "result", "tokens"), x)) for x in con.execute(
        "SELECT n, text, uses, est_tokens, status, result, tokens FROM plan_steps_s89 WHERE plan_id=? ORDER BY n", [plan_id]).fetchall()]
    return {"plan_id": r[0], "created_at": str(r[1])[:16], "chat_id": r[2], "title": r[3], "status": r[4], "est_tokens": r[5], "tokens": r[6], "resume_after": str(r[7])[:16] if r[7] else None,
            "result": r[8], "finished_at": str(r[9])[:16] if r[9] else None, "steps": steps}


def listing(con, limit: int = 12) -> List[dict]:
    ensure(con)
    return [get(con, int(i)) for (i,) in con.execute("SELECT plan_id FROM plans_s89 ORDER BY plan_id DESC LIMIT ?", [limit]).fetchall()]


def cancel(con, plan_id: int) -> str:
    ensure(con)
    p = get(con, plan_id)
    if not p or p["status"] in ("done", "cancelled"):
        return "Nothing to cancel."
    con.execute("UPDATE plans_s89 SET status='cancelled', finished_at=now() WHERE plan_id=?", [plan_id])
    con.execute("UPDATE plan_steps_s89 SET status='skipped' WHERE plan_id=? AND status IN ('pending','running')", [plan_id])
    _bump()
    return "Cancelled. Finished steps are kept."


def start(con, now: datetime, plan_id: int) -> None:
    ensure(con)
    p = get(con, plan_id)
    if not p or p["status"] not in ("proposed", "paused"):
        return
    with _LOCK:
        _OWNED.add(plan_id)                                           # S91: this process runs it (a 'running' plan nobody owns is abandoned: see reconcile)
    con.execute("UPDATE plans_s89 SET status='running', resume_after=NULL WHERE plan_id=? AND status IN ('proposed','paused')", [plan_id])
    _bump()
    cur = con.cursor()
    threading.Thread(target=run, args=(cur, plan_id), name=f"plan-{plan_id}", daemon=True).start()


def _real_step(con, plan: dict, step: dict, prior: str) -> tuple:
    """One step as one full-road turn: the operator's tools, its folder, a fresh session with the earlier results as text."""
    from pflab.hq import egress, passes
    from pflab.hq import tools as tl
    from pflab.entrance import tools as chat_tools
    from pflab.oper import perms, tools as otools, workspace
    rt = RT["rt"]
    if rt is None:
        raise RuntimeError("the app is not running: a plan runs inside the app")
    now = datetime.now()
    ws = workspace.ensure(str(getattr(rt, "data_root", "") or "") or None)
    gate = egress.load(con)
    pid = passes.record(con, now, "assistant", [], "plan", "assistant", "running")
    ctx = tl.Ctx(rt, pid, "plan", False, {}, gate, now, client=None, mode="economy", source=prior, case_ids=[], task_id=None, role="assistant",
                 allowed=frozenset(n for n in chat_tools.names("all") if n in tl.TOOLS), his_text="")
    spec = gw.resolve("read", engine="claude_plan")
    over = None
    try:
        from pflab.app import s89
        over = s89.agent_override(con, "full")
    except Exception:
        pass
    mcp = {"oper": cp.tool_server("oper", otools.items(ctx))}

    async def can_use(name, inp, c):
        ok, why = perms.decide("answer", name, inp, ws)
        return cp.allow_result() if ok else cp.deny_result(f"refused: {why}")
    prompt = (f"PLAN: {plan['title']}\nSTEP {step['n']} of {len(plan['steps'])}: {step['text']}\n" + (f"EARLIER STEPS' RESULTS:\n{prior}\n" if prior else "")
              + "Do only this step, with the tools; answer in 10 lines or fewer; every number from a tool."
              + (" NOTE: an earlier attempt of this step was cut off by a restart: look in research/ and notes/ for a half-written file before you write again." if str(step.get("result") or "").startswith("interrupted") else ""))
    res = cp.run(con, prompt=prompt, system={"type": "preset", "preset": "claude_code"}, model=(over and over[0]) or spec["model"], effort=(over and over[1]) or "medium", klass="chat", purpose="plan_step",
                 agent="chat", now=now, cwd=str(ws), tools=["Read", "Write", "Edit", "Glob", "Grep", "Bash", "Skill", "Agent"], allowed=["mcp__oper__*"], mcp=mcp, max_turns=12, can_use_tool=can_use,
                 setting_sources=["project"], timeout=900, skills=[])
    return res.text, res.input_tokens + res.output_tokens


def run(con, plan_id: int) -> None:
    """Run the pending steps in order. A plan-limit or budget refusal pauses the plan (steps kept); any other failure marks the step and the plan failed."""
    with _LOCK:
        if plan_id in _RUNNING:
            return
        _RUNNING.add(plan_id)
    try:
        while True:
            p = get(con, plan_id)
            if not p or p["status"] != "running":
                return
            step = next((s for s in p["steps"] if s["status"] in ("pending", "running")), None)
            if step is None:
                break
            con.execute("UPDATE plan_steps_s89 SET status='running', started_at=now() WHERE plan_id=? AND n=?", [plan_id, step["n"]])
            _bump()
            prior = "\n".join(f"{s['n']}. {str(s['result'])[:600]}" for s in p["steps"] if s["status"] == "done")
            try:
                text, tokens = (RUN_STEP or _real_step)(con, p, step, prior)
            except (cp.PlanPaused, cp.PlanBudgetSpent) as e:
                if _still_running(con, plan_id):                          # a cancel that arrived meanwhile stays cancelled
                    con.execute("UPDATE plan_steps_s89 SET status='pending' WHERE plan_id=? AND n=?", [plan_id, step["n"]])
                    when = getattr(e, "resume_at", None) or datetime.now()
                    con.execute("UPDATE plans_s89 SET status='paused', resume_after=? WHERE plan_id=? AND status='running'", [when, plan_id])
                _bump()
                return
            except Exception as e:
                if _still_running(con, plan_id):
                    con.execute("UPDATE plan_steps_s89 SET status='failed', result=? WHERE plan_id=? AND n=?", [f"{type(e).__name__}: {str(e)[:200]}", plan_id, step["n"]])
                    con.execute("UPDATE plans_s89 SET status='failed', finished_at=now() WHERE plan_id=? AND status='running'", [plan_id])
                _bump()
                return
            if not _still_running(con, plan_id):                          # cancelled while the step ran: keep what it produced, but the plan stays cancelled and the step skipped
                con.execute("UPDATE plan_steps_s89 SET result=?, tokens=? WHERE plan_id=? AND n=?", ["finished after the cancel: " + str(text)[:3900], int(tokens or 0), plan_id, step["n"]])
                _bump()
                return
            con.execute("UPDATE plan_steps_s89 SET status='done', result=?, tokens=?, finished_at=now() WHERE plan_id=? AND n=?", [str(text)[:4000], int(tokens or 0), plan_id, step["n"]])
            con.execute("UPDATE plans_s89 SET tokens = coalesce(tokens,0) + ? WHERE plan_id=?", [int(tokens or 0), plan_id])
            _bump()
        p = get(con, plan_id)
        body = "\n".join(f"{s['n']}. {s['text']}\n{str(s['result'])[:900]}" for s in p["steps"] if s["status"] == "done")
        text = f"The plan is done: {p['title']}\n\n{body}\n\n({p['tokens']:,} tokens of your plan)"
        con.execute("UPDATE plans_s89 SET status='done', result_text=?, finished_at=now() WHERE plan_id=? AND status='running'", [text, plan_id])
        if not _still_running(con, plan_id) and get(con, plan_id)["status"] != "done":
            return
        try:
            from pflab.entrance import store
            store.post_system(con, datetime.now(), text[:3500], kind="plan", key=f"plan:{plan_id}", chat_id=p.get("chat_id"), channels=("laptop", "telegram"))
        except Exception:
            pass
        _bump()
    finally:
        with _LOCK:
            _RUNNING.discard(plan_id)
            _OWNED.discard(plan_id)


def _still_running(con, plan_id: int) -> bool:
    r = con.execute("SELECT status FROM plans_s89 WHERE plan_id=?", [plan_id]).fetchone()
    return bool(r) and r[0] == "running"


def reconcile(con, now: datetime) -> int:
    """S91: a plan left 'running' by a process that died (a crash, a kill, the laptop losing power) has no owner in THIS process: it is set back to 'paused' with its finished steps
    kept, and the step that was running becomes 'pending' again with a note that an earlier attempt was cut off (the next attempt is told, so it checks research/ and notes/ for
    a half-written file before it writes again). -> the number of plans recovered. Called at the start of every `resume_due`, and so at the app's start."""
    ensure(con)
    n = 0
    with _LOCK:
        owned = set(_OWNED)
    for (pid,) in con.execute("SELECT plan_id FROM plans_s89 WHERE status='running'").fetchall():
        if int(pid) in owned:
            continue
        con.execute("UPDATE plan_steps_s89 SET status='pending', result='interrupted: an earlier attempt of this step was cut off by a restart' WHERE plan_id=? AND status='running'", [pid])
        con.execute("UPDATE plans_s89 SET status='paused', resume_after=NULL WHERE plan_id=?", [pid])
        n += 1
    if n:
        _bump()
    return n


def resume_due(con, now: datetime) -> int:
    """Paused plans whose reset time has passed go on from where they stopped (and, first, plans abandoned by a dead process: `reconcile`)."""
    ensure(con)
    reconcile(con, now)
    n = 0
    for (pid,) in con.execute("SELECT plan_id FROM plans_s89 WHERE status='paused' AND (resume_after IS NULL OR resume_after <= ?)", [now]).fetchall():
        if cp.paused_until(con, now):
            continue
        start(con, now, int(pid))
        n += 1
    return n
