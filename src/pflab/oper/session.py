"""S87 O2: the chat's brain is the operator: ONE Claude Code session per chat, in the operator's own folder, with the system's tools in process. "New chat" is a new chat id and so a new session; the
same chat resumes its session by id (kept in `engine_state_s85`), so a conversation survives a restart. The intake around it is unchanged (acknowledge in 2 seconds, never block the loop)."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from pflab.llm import claude_plan as cp
from pflab.llm import gateway as gw
from pflab.oper import light, pathrouter, perms, tools as otools, workspace

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


def switches(con) -> dict:
    """The Agents screen's connection switches (all off by default): kite, nse, tijori, connectors."""
    try:
        r = con.execute("SELECT switches_json FROM agent_settings_s89 WHERE agent='_switches'").fetchone()
        import json as _j
        return _j.loads(r[0]) if r and r[0] else {}
    except Exception:
        return {}


def kite_tool(ctx) -> tuple:
    def holdings(args):
        import json as _j
        con = ctx.con
        try:
            rows = con.execute("SELECT symbol, qty, avg_price, last_price, day_change_pct FROM mine_in_s89 ORDER BY symbol").fetchall()
        except Exception:
            rows = []
        return _j.dumps([{"symbol": s, "qty": q, "avg": a, "last": l, "day_pct": d} for s, q, a, l, d in rows][:60]) if rows else "No Kite snapshot yet."
    return ("kite_holdings", "His real Indian holdings from the latest Kite snapshot (read-only; no order tool exists).", {"type": "object", "properties": {}}, holdings)


NSE_OFFICIAL = {"nse-bhavcopy": "https://mcp.nseindia.in/bhavcopy/cm/mcp", "cm-market": "https://mcp.nseindia.in/cmmkt/mcp"}


def nse_server() -> Optional[dict]:
    """NSE's own MCP servers (Streamable HTTP, no login): `[operator] nse_mcp_urls = {name = url}` (the end-of-day bhavcopy server and the live-snapshot server), or the one-address form `nse_mcp_url`.
    Loaded only when the Agents screen's NSE switch is on AND an address is set."""
    try:
        from pflab import _toml
        op = _toml.load(cp.CONFIG).get("operator") or {}
    except Exception:
        return None
    urls = {str(k): str(v) for k, v in (op.get("nse_mcp_urls") or {}).items() if v}
    if not urls and op.get("nse_mcp_url"):
        urls = {"nse": str(op["nse_mcp_url"])}
    if not urls and cp.settings().get("nse_mcp_url"):              # S90: the address he saved on the Settings screen
        urls = {"nse": str(cp.settings()["nse_mcp_url"])}
    if not urls:                                                    # S90: NSE's own two public servers (no login), the ones he named
        urls = dict(NSE_OFFICIAL)
    return {k: {"type": "http", "url": u} for k, u in urls.items()} or None


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


def answer_full(rt, con, now: datetime, *, ctx, pid: int, first: str, r: dict, model_id: Optional[str], cid: Optional[int], aid: Optional[int], q: str, progress: Callable[[str], None],
               snap: str = "", notes: Optional[List[str]] = None, lead: str = "", why_full: str = "") -> dict:
    from pflab.agents import analyst as an
    from pflab.entrance import router
    from pflab.hq import passes
    notes = notes or []
    ws = workspace.ensure(str(getattr(rt, "data_root", "") or "") or None)
    spec = gw.resolve(r["role"], engine="claude_plan", model=model_id, thinking=r["thinking"])
    sid = get_session(con, cid)
    hist = hist_tokens(con, cid)
    if sid and hist > HIST_LIMIT:                                   # S88 L3: a session past 60k tokens of history starts fresh, with a summary of the thread
        sid, lead = None, lead or light.thread_summary_for_full(con, cid, aid, q)
        hist = 0
        put_hist(con, cid, 0, now)
    prompt = (new_prompt(first) if sid else first)
    if lead:
        prompt = lead + "\n\n" + prompt
    mcp = {"oper": cp.tool_server("oper", otools.items(ctx))}
    sw = switches(con)
    if sw.get("nse"):                                                # NSE only when switched on AND its address is set
        mcp.update(nse_server() or {})
    if sw.get("kite"):                                               # Kite: the read-only snapshot tool; there is no order tool anywhere
        mcp["kite"] = cp.tool_server("kite", [kite_tool(ctx)])

    async def can_use(name, inp, c):
        ok, why = perms.decide("answer", name, inp, ws)
        return cp.allow_result() if ok else cp.deny_result(f"refused: {why}")
    progress("thinking")
    steps: List[str] = []
    try:
        res = cp.run(con, prompt=prompt, system=PRESET, model=spec["model"], effort=spec["thinking"], klass="chat", purpose="operator_chat", agent="chat", now=now, cwd=str(ws), tools=BUILTIN,
                     allowed=[f"mcp__{k}__*" for k in mcp], mcp=mcp, resume=sid, max_turns=int(cp.settings()["max_turns_chat"]), can_use_tool=can_use,
                     setting_sources=["project"], chat_id=cid, timeout=600, skills=pathrouter.skills_for(q), explicit_model=bool(model_id), strict_mcp=not sw.get("connectors"))
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
    put_hist(con, cid, hist + max(0, res.input_tokens - res.cached_tokens) + res.output_tokens, now)
    steps = [s.replace("mcp__oper__", "") for s in res.steps]
    text = res.text or ""
    clean, dropped = an.only_sourced_numbers(text[:3500], an.Request(ctx.source, "assistant")) if text else ("", 0)
    if notes:
        clean = (clean + "\n\n" if clean else "") + "\n".join(notes)
    passes.close(con, pid, "done", clean, ctx.decisions, 0.0, None, "; ".join(ctx.problems) or None)
    tok = res.input_tokens + res.output_tokens
    meta_txt = f"{router.display_name(r['model_key'], res.model or spec['model'])} · full · thinking {spec['thinking']} · plan, {tok:,} tokens · {why_full or r['why']}" + (f" · {len(steps)} tool call(s)" if steps else "")
    return {"text": clean or "(no answer)", "status": "done", "model": res.model or spec["model"], "thinking": spec["thinking"], "cost": None, "meta": meta_txt,
            "route": [f"tool: {s}" for s in steps[-8:]],
            "meta_obj": {"text": meta_txt, "model": res.model or spec["model"], "price": "plan", "thinking": spec["thinking"], "why": r["why"], "auto": r["auto"], "tools": steps[-8:], "snapshot": snap,
                         "engine": "claude_plan", "path": "full", "tokens": tok, "seconds": res.seconds, "session": res.session_id}}


HIST_LIMIT = 60000


def hist_tokens(con, cid: Optional[int]) -> int:
    v = gw._get_state(con, f"oper_hist:{cid}") if cid else None
    try:
        return int(v) if v else 0
    except ValueError:
        return 0


def put_hist(con, cid: Optional[int], n: int, now: datetime) -> None:
    if cid:
        gw._set_state(con, f"oper_hist:{cid}", str(int(n)), now, "tokens of history in the operator session of the chat (approximate)")


def _done(con, pid, text: str, ctx):
    from pflab.hq import passes
    passes.close(con, pid, "done", text, ctx.decisions, 0.0, None, "; ".join(ctx.problems) or None)


def answer_light(rt, con, now: datetime, *, ctx, pid: int, first: str, r: dict, model_id: Optional[str], cid: Optional[int], aid: Optional[int], q: str, progress: Callable[[str], None],
                 snap: str = "", notes: Optional[List[str]] = None, why: str = "") -> Optional[dict]:
    """The quick road. -> the reply dict, or None when it needs the full operator (the dispatcher then goes there once)."""
    from pflab.agents import analyst as an
    from pflab.entrance import router
    progress("thinking")
    res = light.answer(rt, con, now, ctx=ctx, q=q, route=r, model_id=model_id, cid=cid, aid=aid)
    if res["needs_full"]:
        return {"escalate": res["why"] or "needs more than the quick road has", "tokens": res["input_tokens"] + res["output_tokens"]}
    clean, _ = an.only_sourced_numbers(res["text"][:3500], an.Request(ctx.source, "assistant")) if res["text"] else ("", 0)
    if notes:
        clean = (clean + "\n\n" if clean else "") + "\n".join(notes)
    _done(con, pid, clean, ctx)
    tok = res["input_tokens"] + res["output_tokens"]
    meta_txt = f"{router.display_name(r['model_key'], res['model'])} · quick · thinking {res['thinking']} · plan, {tok:,} tokens · {why or 'a plain question'}"
    return {"text": clean or "(no answer)", "status": "done", "model": res["model"], "thinking": res["thinking"], "cost": None, "meta": meta_txt, "route": [f"tool: {x}" for x in res["steps"][-8:]],
            "meta_obj": {"text": meta_txt, "model": res["model"], "price": "plan", "thinking": res["thinking"], "why": why or r["why"], "auto": r["auto"], "tools": res["steps"][-8:], "snapshot": snap,
                         "engine": "claude_plan", "path": "quick", "tokens": tok, "seconds": res["seconds"], "turns": res["turns"]}}


def dispatch(rt, con, now: datetime, *, ctx, pid: int, first: str, r: dict, model_id: Optional[str], cid: Optional[int], aid: Optional[int], q: str, progress: Callable[[str], None],
             snap: str = "", notes: Optional[List[str]] = None) -> dict:
    """S88 L2: the road for this message (rules only, no model call): ack (a fixed reply), light (quick), full (the whole operator). A quick answer that needs more goes to the full operator ONCE, with the
    thread's summary; the full operator never goes back."""
    path, why, text = pathrouter.choose(q, has_file=pathrouter.FILE_MARK in first, road=(r or {}).get("road"))
    kw = dict(ctx=ctx, pid=pid, first=first, r=r, model_id=model_id, cid=cid, aid=aid, q=text, progress=progress, snap=snap, notes=notes)
    if path == "ack":
        _done(con, pid, pathrouter.ACK_REPLY, ctx)
        return {"text": pathrouter.ACK_REPLY, "status": "done", "model": None, "cost": None, "meta": "no model call", "route": ["ack"],
                "meta_obj": {"text": "no model call · 0 tokens", "price": "plan", "path": "ack", "tokens": 0, "why": why, "engine": "claude_plan"}}
    lead = ""
    if path == "light":
        try:
            out = answer_light(rt, con, now, why=why, **kw)
        except (cp.PlanPaused, cp.PlanBudgetSpent) as e:
            _done(con, pid, "", ctx)
            return {"text": paused_line(e), "status": "done", "cost": None, "meta": "thinking paused (plan limit)", "meta_obj": {"text": "thinking paused (plan limit)", "engine": "claude_plan", "path": "quick"},
                    "route": ["paused"]}
        except cp.PlanUnusable as e:
            _done(con, pid, "", ctx)
            return {"text": str(e), "status": "failed", "cost": None, "meta": "not signed in on his plan", "route": ["unusable"], "error": "PlanUnusable"}
        except Exception as e:
            log.warning("the quick road failed (%s): the full operator takes it", type(e).__name__)
            out = {"escalate": f"the quick road failed ({type(e).__name__})"}
        if "escalate" not in out:
            return out
        why = "the quick road passed it on: " + out["escalate"]
        lead = light.thread_summary_for_full(con, cid, aid, text)
    return answer_full(rt, con, now, lead=lead, why_full=why, **kw)


answer = answer_full                                  # the S87 name (its tests call the full road directly)
