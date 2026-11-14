"""S87 O2: the chat's brain is the operator: ONE Claude Code session per chat, in the operator's own folder, with the system's tools in process. "New chat" is a new chat id and so a new session; the
same chat resumes its session by id (kept in `engine_state_s85`), so a conversation survives a restart. The intake around it is unchanged (acknowledge in 2 seconds, never block the loop)."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from pflab.llm import claude_plan as cp
from pflab.llm import gateway as gw
from pflab.oper import perms, tools as otools, workspace

log = logging.getLogger("pflab.operator")
BUILTIN = ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "Skill", "Agent"]
PRESET = {"type": "preset", "preset": "claude_code"}


def enabled(con) -> bool:
    try:
        return gw.current_engine(con) == "claude_plan" and bool(cp.settings()["enabled"])
    except Exception:
        return False


def session_key(cid: Optional[int]) -> str:
    return f"operator_session:{cid}"


def get_session(con, cid: Optional[int]) -> Optional[str]:
    return gw._get_state(con, session_key(cid)) if cid else None


def put_session(con, cid: Optional[int], sid: str, now: datetime) -> None:
    if cid and sid:
        gw._set_state(con, session_key(cid), sid, now, "operator session of the chat")


def nse_server() -> Optional[dict]:
    try:
        from pflab import _toml
        url = str((_toml.load(cp.CONFIG).get("operator") or {}).get("nse_mcp_url") or "")
    except Exception:
        url = ""
    return {"nse": {"type": "http", "url": url}} if url else None


def new_prompt(first: str) -> str:
    """On a resumed session the history is already in it: send the files, the screen he is on, the snapshot and his words, not the house rules and the history again."""
    for marker in ("FILES HE SENT WITH THIS MESSAGE", "HE IS LOOKING AT:", "RECORD SNAPSHOT:"):
        i = first.find(marker)
        if i >= 0:
            return first[i:]
    return first


def paused_line(e: BaseException) -> str:
    when = getattr(e, "resume_at", None)
    return ("Thinking is paused" + (f" until {when:%H:%M}" if when else " for now") + " (Claude's plan limit). The watch, the alarms and the paper book keep running; ask again then. "
            "Everything that needs no model (the book, prices, alerts) is still on the screens.")


def answer(rt, con, now: datetime, *, ctx, pid: int, first: str, r: dict, model_id: Optional[str], cid: Optional[int], aid: Optional[int], q: str, progress: Callable[[str], None],
           snap: str = "", notes: Optional[List[str]] = None) -> dict:
    from pflab.agents import analyst as an
    from pflab.entrance import router
    from pflab.hq import passes
    notes = notes or []
    ws = workspace.ensure(str(getattr(rt, "data_root", "") or "") or None)
    spec = gw.resolve(r["role"], engine="claude_plan", model=model_id, thinking=r["thinking"])
    sid = get_session(con, cid)
    prompt = new_prompt(first) if sid else first
    mcp = {"oper": cp.tool_server("oper", otools.items(ctx))}
    mcp.update(nse_server() or {})

    async def can_use(name, inp, c):
        ok, why = perms.decide("answer", name, inp, ws)
        return cp.allow_result() if ok else cp.deny_result(f"refused: {why}")
    progress("thinking")
    steps: List[str] = []
    try:
        res = cp.run(con, prompt=prompt, system=PRESET, model=spec["model"], effort=spec["thinking"], klass="chat", purpose="operator_chat", agent="chat", now=now, cwd=str(ws), tools=BUILTIN,
                     allowed=["mcp__oper__*"] + (["mcp__nse__*"] if "nse" in mcp else []), mcp=mcp, resume=sid, max_turns=int(cp.settings()["max_turns_chat"]), can_use_tool=can_use,
                     setting_sources=["project"], chat_id=cid, timeout=600)
    except (cp.PlanPaused, cp.PlanBudgetSpent) as e:
        passes.close(con, pid, "stopped", "", ctx.decisions, 0.0, None, str(e)[:300])
        return {"text": paused_line(e), "status": "done", "cost": None, "meta": "thinking paused (plan limit)", "meta_obj": {"text": "thinking paused (plan limit)", "engine": "claude_plan"},
                "route": ["paused"]}
    except cp.PlanUnusable as e:
        passes.close(con, pid, "stopped", "", ctx.decisions, 0.0, None, str(e)[:300])
        return {"text": str(e), "status": "failed", "cost": None, "meta": "not signed in on his plan", "route": ["unusable"], "error": "PlanUnusable"}
    except Exception as e:
        passes.close(con, pid, "stopped", "", ctx.decisions, 0.0, None, str(e)[:300])
        return {"text": "The operator could not finish this one. Nothing was changed; try again in a moment.", "status": "failed", "cost": None, "meta": "no answer made",
                "route": ["stopped"], "error": f"{type(e).__name__}: {str(e)[:200]}"}
    put_session(con, cid, res.session_id, now)
    steps = [s.replace("mcp__oper__", "") for s in res.steps]
    text = res.text or ""
    clean, dropped = an.only_sourced_numbers(text[:3500], an.Request(ctx.source, "assistant")) if text else ("", 0)
    if dropped:
        clean += "\n\n(Some sentences were removed because they carried numbers no tool had returned.)"
    if notes:
        clean = (clean + "\n\n" if clean else "") + "\n".join(notes)
    passes.close(con, pid, "done", clean, ctx.decisions, 0.0, None, "; ".join(ctx.problems) or None)
    tok = res.input_tokens + res.output_tokens
    meta_txt = f"{router.display_name(r['model_key'], res.model or spec['model'])} · thinking {spec['thinking']} · plan, {tok:,} tokens · {r['why']}" + (f" · {len(steps)} tool call(s)" if steps else "")
    return {"text": clean or "(no answer)", "status": "done", "model": res.model or spec["model"], "thinking": spec["thinking"], "cost": None, "meta": meta_txt,
            "route": [f"tool: {s}" for s in steps[-8:]],
            "meta_obj": {"text": meta_txt, "model": res.model or spec["model"], "price": "plan", "thinking": spec["thinking"], "why": r["why"], "auto": r["auto"], "tools": steps[-8:], "snapshot": snap,
                         "engine": "claude_plan", "tokens": tok, "seconds": res.seconds, "session": res.session_id}}
