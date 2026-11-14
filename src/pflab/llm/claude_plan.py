"""S87 O1: Claude Code through the Agent SDK, on his Claude plan (no API key). The ONLY module that imports `claude_agent_sdk` (a test greps for it).

* The child process gets an environment with every key-like variable BLANKED (the SDK always inherits the parent's environment, so a blank override is how a key is kept out) and, before every
  session, `claude auth status` must say the sign-in is his claude.ai subscription. Never a fall back to an API key.
* Usage, not rupees: each session is a row in `api_calls` (tokens in and out, model, purpose; engine "claude_plan", cost 0 = "plan"). A daily token budget per purpose class (desk, cases, chat, build)
  stops that class for the day. A usage-limit or rate-limit answer raises `PlanPaused` (with the reset time when known): code-only parts go on, the thinking waits.
* The gateway's caller-owned tool loop works unchanged: the caller's tools are shown to the model as stubs and the first call it makes is CAPTURED and handed back (the session is interrupted);
  the caller runs it and calls again with the result in the conversation.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("pflab.claude_plan")

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "core.toml"
CLASSES = ("desk", "cases", "chat", "build")
DEFAULTS = {"enabled": True, "budget_desk": 600000, "budget_cases": 900000, "budget_chat": 1500000, "budget_build": 1200000, "max_turns_desk": 12, "max_turns_chat": 14, "max_turns_build": 40,
            "build_per_day": 2, "signin_cache_s": 600, "session_timeout_s": 900}
KEY_LIKE = re.compile(r"(_API_KEY|_AUTH_TOKEN|_ACCESS_TOKEN|_SECRET_KEY|^ANTHROPIC_BASE_URL$|^CLAUDE_CODE_USE_(BEDROCK|VERTEX|FOUNDRY)$|^CLAUDE_CODE_OAUTH_TOKEN$)", re.I)
CALLER_SERVER = "caller"
LIMIT_WORDS = re.compile(r"usage limit|limit reached|rate.?limit|too many requests|overloaded|quota|resets? at|try again (later|at)", re.I)

# tests: a scripted stand-in for the SDK client (an async context manager with query / receive_response / interrupt), and for the sign-in check
client_factory: Optional[Callable[..., Any]] = None
signin_fn: Optional[Callable[[], dict]] = None
_SIGNIN: Dict[str, Any] = {"at": 0.0, "val": None}
_LOCK = threading.Lock()


class PlanUnusable(RuntimeError):
    """Not signed in on his Claude plan (or the guard could not tell): nothing runs, no key is tried."""


class PlanPaused(RuntimeError):
    """The plan's usage or rate limit is reached: the thinking waits (`resume_at` when the reset time is known)."""

    def __init__(self, msg: str, resume_at: Optional[datetime] = None):
        super().__init__(msg)
        self.resume_at = resume_at


class PlanBudgetSpent(RuntimeError):
    """The day's token budget of this purpose class is spent: that class stops until tomorrow."""

    def __init__(self, msg: str, resume_at: Optional[datetime] = None):
        super().__init__(msg)
        self.resume_at = resume_at


def settings() -> dict:
    out = dict(DEFAULTS)
    try:
        from pflab import _toml
        out.update({k: v for k, v in (_toml.load(CONFIG).get("operator") or {}).items() if k in DEFAULTS})
    except Exception:
        pass
    return out


def klass_of(agent: str, purpose: str = "") -> str:
    a = (agent or "").lower()
    if a in ("chat", "assistant", "router", "wording", "operator"):
        return "chat"
    if a == "desk" or purpose.startswith("desk"):
        return "desk"
    if a == "build":
        return "build"
    return "cases"


# --- the environment and the sign-in ----------------------------------------------------------------------------------------------------

def child_env(parent: Optional[dict] = None) -> Dict[str, str]:
    """Overrides for the child process: every key-like variable of the parent set to "" (an API key, an auth token, a cloud-provider switch), so none reaches Claude Code."""
    parent = os.environ if parent is None else parent
    out = {k: "" for k in parent if KEY_LIKE.search(k)}
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY"):
        out[k] = ""
    return out


def cli_path() -> str:
    import claude_agent_sdk
    p = Path(claude_agent_sdk.__file__).parent / "_bundled" / ("claude.exe" if os.name == "nt" else "claude")
    return str(p) if p.exists() else (shutil.which("claude") or "claude")


def signin(force: bool = False) -> dict:
    """{"ok", "method", "detail"}: ok only when Claude Code reports his claude.ai subscription. Cached for `signin_cache_s`. Never prints the account."""
    if signin_fn is not None:
        return signin_fn()
    with _LOCK:
        if not force and _SIGNIN["val"] is not None and time.time() - _SIGNIN["at"] < settings()["signin_cache_s"]:
            return _SIGNIN["val"]
    env = {**os.environ, **child_env()}
    try:
        p = subprocess.run([cli_path(), "auth", "status"], capture_output=True, text=True, timeout=30, env=env)
        d = json.loads(p.stdout or "{}")
        method = str(d.get("authMethod") or "")
        ok = bool(d.get("loggedIn")) and method == "claude.ai"
        val = {"ok": ok, "method": method or "none", "detail": "" if ok else (f"Claude Code is signed in by '{method or 'nothing'}', not his Claude subscription" if d.get("loggedIn") else "Claude Code is not signed in")}
    except Exception as e:
        val = {"ok": False, "method": "unknown", "detail": f"the sign-in could not be read ({type(e).__name__})"}
    with _LOCK:
        _SIGNIN.update({"at": time.time(), "val": val})
    return val


def guard(con=None, now: Optional[datetime] = None) -> None:
    """Before every session: refuse (one Problems line, one Telegram line a day) unless the sign-in is his plan."""
    s = signin()
    if s["ok"]:
        return
    msg = f"The operator cannot run: {s['detail']}. Sign in to Claude Code with his Claude account (no API key is ever used)."
    if con is not None:
        _problem_once(con, now or datetime.now(), msg)
    raise PlanUnusable(msg)


def _problem_once(con, now: datetime, text: str) -> None:
    try:
        from pflab.llm import gateway
        gateway._problem(con, now, "claude_plan", "-", text)
    except Exception:
        log.warning("problem line not written: %s", text)


# --- pause and budgets ------------------------------------------------------------------------------------------------------------------

def paused_until(con, now: Optional[datetime] = None) -> Optional[datetime]:
    from pflab.llm import gateway
    v = gateway._get_state(con, "plan_pause") if con is not None else None
    if not v:
        return None
    try:
        t = datetime.fromisoformat(v)
    except ValueError:
        return None
    return t if t > (now or datetime.now()) else None


def set_pause(con, until: datetime, now: datetime, note: str = "") -> None:
    from pflab.llm import gateway
    gateway._set_state(con, "plan_pause", until.isoformat(), now, note)


def tokens_today(con, now: datetime, klass: Optional[str] = None) -> int:
    d0 = datetime(now.year, now.month, now.day)
    q = "SELECT coalesce(sum(coalesce(input_tokens,0)+coalesce(output_tokens,0)),0) FROM api_calls WHERE engine='claude_plan' AND created_at >= ? AND status='done'"
    a: List[Any] = [d0]
    if klass:
        q += " AND topic LIKE ?"
        a.append(f"plan:{klass}:%")
    return int(con.execute(q, a).fetchone()[0])


def budget_of(klass: str, cfg: Optional[dict] = None) -> int:
    return int((cfg or settings())[f"budget_{klass}"])


def state(con, now: Optional[datetime] = None) -> dict:
    """For `GET /api/operator` and `pflab service status`: the sign-in, paused or running, today's tokens by purpose against their budgets."""
    now = now or datetime.now()
    s = signin()
    cfg = settings()
    until = paused_until(con, now)
    return {"signed_in": bool(s["ok"]), "method": s["method"], "detail": s["detail"], "thinking": "paused" if until else ("running" if s["ok"] else "off"),
            "paused_until": until.isoformat(timespec="minutes") if until else None,
            "tokens_today": {k: {"used": tokens_today(con, now, k), "budget": budget_of(k, cfg)} for k in CLASSES}}


# --- one session ------------------------------------------------------------------------------------------------------------------------

@dataclass
class Result:
    text: str = ""
    structured: Any = None
    session_id: str = ""
    tool_calls: List[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    turns: int = 0
    seconds: float = 0.0
    model: str = ""
    stop_reason: str = ""
    call_id: Optional[int] = None
    steps: List[str] = field(default_factory=list)


def _sdk():
    import claude_agent_sdk as sdk
    return sdk


def _reset_time(raw: Any) -> Optional[datetime]:
    try:
        if raw:
            return datetime.fromtimestamp(float(raw))
    except Exception:
        pass
    return None


def _stub_server(defs: List[dict]):
    sdk = _sdk()
    tools = []
    for d in defs:
        def make(name):
            async def h(args):
                return {"content": [{"type": "text", "text": "recorded"}]}
            return h
        tools.append(sdk.SdkMcpTool(name=d["name"], description=d.get("description", "")[:900], input_schema=d.get("input_schema") or {"type": "object", "properties": {}}, handler=make(d["name"])))
    return sdk.create_sdk_mcp_server(CALLER_SERVER, "1.0", tools)


def tool_server(name: str, items: List[tuple]):
    """An in-process tool server: items = [(tool name, description, input schema, fn(args: dict) -> str)]. The model sees `mcp__<name>__<tool>`; fn runs here, in this process, and returns plain text."""
    sdk = _sdk()
    out = []
    for tname, desc, schema, fn in items:
        def make(f):
            async def h(args):
                try:
                    txt = await asyncio.get_running_loop().run_in_executor(None, lambda: f(dict(args or {})))
                except Exception as e:                                   # the model sees the failure and may try another way
                    return {"content": [{"type": "text", "text": f"error: {type(e).__name__}: {str(e)[:300]}"}], "is_error": True}
                return {"content": [{"type": "text", "text": str(txt)[:12000]}]}
            return h
        out.append(sdk.SdkMcpTool(name=tname, description=desc[:900], input_schema=schema or {"type": "object", "properties": {}}, handler=make(fn)))
    return sdk.create_sdk_mcp_server(name, "1.0", out)


def allow_result(updated: Optional[dict] = None):
    return _sdk().PermissionResultAllow(updated_input=updated) if updated is not None else _sdk().PermissionResultAllow()


def deny_result(msg: str, interrupt: bool = False):
    return _sdk().PermissionResultDeny(message=msg, interrupt=interrupt)


def agent_def(description: str, prompt: str, tools: Optional[List[str]] = None, model: str = "sonnet"):
    return _sdk().AgentDefinition(description=description, prompt=prompt, tools=tools, model=model)


def options(*, system: Optional[str], model: str, effort: Optional[str], cwd: Optional[str], tools=None, allowed=None, disallowed=None, mcp=None, resume: Optional[str] = None,
            max_turns: int = 8, can_use_tool=None, schema: Optional[dict] = None, agents=None, setting_sources=None, add_dirs=None, extra_env: Optional[dict] = None):
    sdk = _sdk()
    kw: Dict[str, Any] = dict(model=model, cwd=cwd, max_turns=max_turns, env={**child_env(), **(extra_env or {})}, cli_path=cli_path(), setting_sources=setting_sources if setting_sources is not None else [])
    if system is not None:
        kw["system_prompt"] = system
    if effort in ("low", "medium", "high", "max"):
        kw["effort"] = effort
    if tools is not None:
        kw["tools"] = tools
    if allowed:
        kw["allowed_tools"] = allowed
    if disallowed:
        kw["disallowed_tools"] = disallowed
    if mcp:
        kw["mcp_servers"] = mcp
    if resume:
        kw["resume"] = resume
    if can_use_tool:
        kw["can_use_tool"] = can_use_tool
    if schema:
        kw["output_format"] = {"type": "json_schema", "schema": schema}
    if agents:
        kw["agents"] = agents
    if add_dirs:
        kw["add_dirs"] = add_dirs
    return sdk.ClaudeAgentOptions(**kw)


async def _drive(opts, prompt, captured: List[dict], steps: List[str]) -> Result:
    sdk = _sdk()
    res = Result()
    texts: List[str] = []
    limit: Dict[str, Any] = {}
    factory = client_factory or sdk.ClaudeSDKClient
    t0 = time.time()
    async with factory(opts) as c:
        await c.query(prompt)
        async for m in c.receive_response():
            name = type(m).__name__
            if name == "AssistantMessage":
                for b in m.content:
                    bn = type(b).__name__
                    if bn == "TextBlock":
                        texts.append(b.text)
                    elif bn == "ToolUseBlock":
                        steps.append(str(b.name))
                res.model = res.model or str(getattr(m, "model", "") or "")
            elif name == "RateLimitEvent":
                info = getattr(m, "rate_limit_info", None) or getattr(m, "info", None)
                if info is not None and str(getattr(info, "status", "")) == "rejected":
                    limit = {"resets_at": getattr(info, "resets_at", None)}
            elif name == "ResultMessage":
                u = m.usage or {}
                res.input_tokens = int(u.get("input_tokens", 0) or 0) + int(u.get("cache_creation_input_tokens", 0) or 0) + int(u.get("cache_read_input_tokens", 0) or 0)
                res.cached_tokens = int(u.get("cache_read_input_tokens", 0) or 0)
                res.output_tokens = int(u.get("output_tokens", 0) or 0)
                res.turns, res.session_id, res.stop_reason = int(m.num_turns or 0), str(m.session_id or ""), str(m.stop_reason or "")
                res.structured = m.structured_output
                if m.result and not texts:
                    texts.append(str(m.result))
                if m.is_error and not captured:
                    blob = " ".join([str(m.result or ""), *(m.errors or [])])
                    if m.api_error_status in (429, 529) or limit or LIMIT_WORDS.search(blob):
                        raise PlanPaused(f"Claude's plan limit: {blob[:200] or 'rate limited'}", _reset_time(limit.get("resets_at")))
                    raise RuntimeError(f"the session failed ({m.subtype}): {blob[:300]}")
    res.text = "\n".join(t for t in texts if t).strip()
    res.tool_calls = list(captured)
    res.seconds = round(time.time() - t0, 1)
    return res


def _parse_reset(text: str, n: datetime) -> Optional[datetime]:
    m = re.search(r"resets? at (\d{1,2})(?::(\d\d))?\s*(am|pm)?", text, re.I)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    t = n.replace(hour=h % 24, minute=mi, second=0, microsecond=0)
    return t if t > n else t + timedelta(days=1)


def run(con, *, prompt: str, system: Optional[str] = None, model: str, effort: Optional[str] = None, klass: str, purpose: str, agent: str = "think", now: Optional[datetime] = None,
        caller_tools: Optional[List[dict]] = None, cwd: Optional[str] = None, tools=None, allowed=None, disallowed=None, mcp: Optional[dict] = None, resume: Optional[str] = None,
        max_turns: Optional[int] = None, can_use_tool=None, schema: Optional[dict] = None, agents=None, setting_sources=None, add_dirs=None, timeout: Optional[float] = None,
        chat_id: Optional[int] = None, case_id: Optional[int] = None, extra_env: Optional[dict] = None) -> Result:
    """One session on his plan. Raises PlanUnusable (not his sign-in), PlanPaused (limit reached), PlanBudgetSpent (the class's day budget). Logs the row. `caller_tools`: the gateway's tool
    definitions, shown as stubs; the first call the model makes is captured and returned in `tool_calls` (the session is interrupted)."""
    now = now or datetime.now()
    cfg = settings()
    if not cfg["enabled"]:
        raise PlanUnusable("the operator engine is switched off ([operator] enabled = false)")
    guard(con, now)
    until = paused_until(con, now)
    if until:
        raise PlanPaused(f"thinking is paused until {until:%H:%M} (the plan's limit)", until)
    if tokens_today(con, now, klass) >= budget_of(klass, cfg):
        raise PlanBudgetSpent(f"today's {klass} token budget ({budget_of(klass, cfg):,}) is spent", datetime(now.year, now.month, now.day) + timedelta(days=1))
    captured: List[dict] = []
    steps: List[str] = []
    mcp = dict(mcp or {})
    allow = list(allowed or [])
    perm = can_use_tool
    if caller_tools:
        mcp[CALLER_SERVER] = _stub_server(caller_tools)
        allow += [f"mcp__{CALLER_SERVER}__{d['name']}" for d in caller_tools]
        sdk = _sdk()
        inner = can_use_tool

        async def perm(name, inp, ctx):                      # noqa: F811
            if name.startswith(f"mcp__{CALLER_SERVER}__"):
                captured.append({"id": "tu_" + uuid.uuid4().hex[:20], "name": name.split("__", 2)[2], "input": dict(inp or {})})
                return sdk.PermissionResultDeny(message="captured: the caller runs it", interrupt=True)
            if inner is not None:
                return await inner(name, inp, ctx)
            return sdk.PermissionResultDeny(message="not allowed here")
    opts = options(system=system, model=model, effort=effort, cwd=cwd or str(_scratch()), tools=[] if tools is None else tools, allowed=allow, disallowed=disallowed, mcp=mcp or None,
                   resume=resume, max_turns=int(max_turns or cfg["max_turns_chat"]), can_use_tool=perm, schema=schema, agents=agents, setting_sources=setting_sources, add_dirs=add_dirs, extra_env=extra_env)
    t_out = float(timeout or cfg["session_timeout_s"])
    try:
        res = _run_async(_drive(opts, prompt, captured, steps), t_out)
    except PlanPaused as e:
        e.resume_at = e.resume_at or _parse_reset(str(e), now)
        set_pause(con, e.resume_at or (now + timedelta(minutes=30)), now, str(e)[:200])
        _row(con, now, model, klass, purpose, agent, Result(), "paused", prompt, chat_id, case_id, str(e)[:300])
        raise
    except Exception as e:
        _row(con, now, model, klass, purpose, agent, Result(), "failed", prompt, chat_id, case_id, f"{type(e).__name__}: {str(e)[:300]}")
        raise
    res.steps = steps
    res.model = res.model or model
    res.call_id = _row(con, now, model, klass, purpose, agent, res, "done", prompt, chat_id, case_id, "")
    return res


def _scratch() -> Path:
    p = Path(os.environ.get("PFLAB_DATA_DIR") or tempfile.gettempdir()) / "operator" / "_engine"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _run_async(coro, timeout: float):
    """Run on a private loop in a worker thread: the caller may itself sit inside a loop (the web app) and the scheduler thread must never block the app's loop."""
    box: Dict[str, Any] = {}

    def go():
        try:
            box["v"] = asyncio.run(asyncio.wait_for(coro, timeout))
        except BaseException as e:           # noqa: BLE001
            box["e"] = e
    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(timeout + 30)
    if t.is_alive():
        raise TimeoutError("the session did not finish in time")
    if "e" in box:
        e = box["e"]
        if isinstance(e, asyncio.TimeoutError):
            raise TimeoutError(f"the session took more than {timeout:.0f}s")
        raise e
    return box["v"]


def _row(con, now: datetime, model: str, klass: str, purpose: str, agent: str, res: Result, status: str, prompt: str, chat_id, case_id, error: str) -> int:
    from pflab.pm.store import next_id
    cid = next_id(con, "api_calls", "call_id")
    body = json.dumps({"engine": "claude_plan", "purpose": purpose, "chars": len(prompt)})
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, topic, question, request_sha, request_json, status, input_tokens, output_tokens, cost_usd, cost_inr, finished_at, error, agent, turn, "
                "policy, his_order) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [cid, now, "plan", res.model or model, f"plan:{klass}:{purpose}"[:200], f"{agent} {purpose}"[:300], hashlib.sha256((prompt or "").encode()).hexdigest(), body, status, res.input_tokens,
                 res.output_tokens, 0.0, 0.0, now, error or None, agent, max(1, res.turns), "plan", klass == "chat"])
    try:
        con.execute("UPDATE api_calls SET engine='claude_plan', vendor='claude_plan', purpose=?, cached_tokens=?, chat_id=?, case_id=? WHERE call_id=?", [purpose[:200], res.cached_tokens, chat_id, case_id, cid])
    except Exception:
        pass
    return cid


# --- the gateway's provider --------------------------------------------------------------------------------------------------------------

def flatten(messages: List[dict], inbox: Optional[Path] = None) -> str:
    """The conversation as one text (the session is stateless for gateway callers): roles labelled, tool calls and results as plain lines; images and PDFs saved under `inbox` and named by path."""
    out: List[str] = []
    for m in messages:
        c = m.get("content")
        parts: List[str] = []
        if isinstance(c, str):
            parts.append(c)
        else:
            for b in c or []:
                t = b.get("type")
                if t == "text":
                    parts.append(b.get("text", ""))
                elif t == "tool_use":
                    parts.append(f"[you called the tool {b.get('name')} with {json.dumps(b.get('input') or {}, default=str)[:1500]}]")
                elif t == "tool_result":
                    rc = b.get("content")
                    txt = rc if isinstance(rc, str) else " ".join(x.get("text", "") for x in rc or [] if isinstance(x, dict) and x.get("type") == "text")
                    parts.append(f"[tool result{' (error)' if b.get('is_error') else ''}: {txt[:6000]}]")
                elif t in ("image", "document") and inbox is not None:
                    src = b.get("source") or {}
                    if src.get("type") == "base64" and src.get("data"):
                        ext = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}.get(src.get("media_type", ""), ".bin")
                        inbox.mkdir(parents=True, exist_ok=True)
                        p = inbox / f"{t}_{uuid.uuid4().hex[:8]}{ext}"
                        p.write_bytes(base64.b64decode(src["data"]))
                        parts.append(f"[a {t} was attached: read it with the Read tool at {p}]")
        if parts:
            out.append(("HE / THE SYSTEM: " if m.get("role") == "user" else "YOU EARLIER: ") + "\n".join(parts))
    return "\n\n".join(out)


class ClaudePlanEngine:
    """The provider the gateway speaks to: params -> send -> read, as the Anthropic one, with the plan's session behind it."""
    name = "claude_plan"

    def params(self, spec: dict, st: dict, system, messages: list, tools: Optional[list], max_tokens: int, schema: Optional[dict], tool_choice: Optional[str], *, web: bool = False) -> dict:
        sys_text = system if isinstance(system, str) else "\n\n".join(b.get("text", "") for b in system or [] if isinstance(b, dict))
        return {"model": spec["model"], "effort": spec["thinking"], "system": sys_text, "messages": list(messages), "tools": list(tools or []) if tool_choice != "none" else [],
                "schema": schema, "web": web, "max_tokens": int(max_tokens)}

    def make_client(self, econf: Optional[dict] = None):
        return SimpleNamespace(plan=True)

    def send(self, con, *, agent: str, params: dict, client, now: datetime, mode: str, private_text: str, gate, topic: str, question: str, cfg: Optional[dict], approved: bool, turn: int,
             his_order: bool = False, extra_in: int = 0):
        from pflab.hq import egress, llm
        egress.check(private_text, gate, ("portfolio",), skip=("address_word",))
        inbox = _scratch() / "inbox" / uuid.uuid4().hex[:10]
        prompt = flatten(params["messages"], inbox)
        egress.check(prompt, gate, (), skip=("address_word",))
        purpose = (topic.split(":", 1)[1] if ":" in topic else topic) or "call"
        k = klass_of(agent, purpose)
        schema = params.get("schema")
        allowed = ["Read"] if inbox.exists() else []
        allowed += ["WebSearch", "WebFetch"] if params.get("web") else []
        sys_ = params["system"]
        if schema:
            sys_ += "\n\nAnswer with ONE JSON object that follows the schema given to you, and nothing else."

        async def only_inbox(name, inp, ctx):
            sdk = _sdk()
            if name == "Read" and str(inp.get("file_path", "")).startswith(str(inbox)):
                return sdk.PermissionResultAllow()
            if name in ("WebSearch", "WebFetch"):
                return sdk.PermissionResultAllow()
            return sdk.PermissionResultDeny(message="not allowed here")
        try:
            r = run(con, prompt=prompt, system=sys_, model=params["model"], effort=params["effort"], klass=k, purpose=purpose, agent=agent, now=now, caller_tools=params["tools"] or None,
                    allowed=allowed or None, tools=(["Read"] if inbox.exists() else []) + (["WebSearch", "WebFetch"] if params.get("web") else []), can_use_tool=only_inbox, schema=schema,
                    max_turns=settings()["max_turns_desk"] if k in ("desk", "cases") else settings()["max_turns_chat"])
            if schema and r.structured is None and not _json_like(r.text) and not r.tool_calls:         # ask once more, in the same session, then the caller sees a malformed answer
                r2 = run(con, prompt="Answer again with ONE JSON object only, following the schema.", system=sys_, model=params["model"], effort=params["effort"], klass=k, purpose=purpose + "+retry",
                         agent=agent, now=now, resume=r.session_id or None, schema=schema, max_turns=3)
                r.text, r.structured = r2.text, r2.structured
                r.input_tokens += r2.input_tokens
                r.output_tokens += r2.output_tokens
        finally:
            shutil.rmtree(inbox, ignore_errors=True)
        text = json.dumps(r.structured) if r.structured is not None else r.text
        blocks = [SimpleNamespace(type="text", text=text, citations=None)] if text else []
        blocks += [SimpleNamespace(type="tool_use", id=t["id"], name=t["name"], input=t["input"]) for t in r.tool_calls]
        msg = SimpleNamespace(content=blocks, stop_reason="tool_use" if r.tool_calls else "end_turn", model=r.model, usage=SimpleNamespace(cache_read_input_tokens=r.cached_tokens,
                              cache_creation_input_tokens=0, server_tool_use=None), plan=r)
        return llm.Sent(msg, r.call_id or 0, 0.0, [])

    def read(self, sent) -> dict:
        msg = sent.message
        blocks = list(msg.content)
        tb = [{"text": b.text, "citations": []} for b in blocks if b.type == "text"]
        return {"text": "\n".join(x["text"] for x in tb), "stop_reason": msg.stop_reason, "model": msg.model or None,
                "tool_calls": [{"id": b.id, "name": b.name, "input": dict(b.input)} for b in blocks if b.type == "tool_use"],
                "assistant_content": [({"type": "text", "text": b.text} if b.type == "text" else {"type": "tool_use", "id": b.id, "name": b.name, "input": dict(b.input)}) for b in blocks],
                "raw_content": blocks, "cached_tokens": int(msg.usage.cache_read_input_tokens or 0), "cache_written_tokens": 0, "web_searches": 0, "text_blocks": tb}


def _json_like(t: str) -> bool:
    try:
        from pflab.hq import llm
        return bool(llm.json_of(t))
    except Exception:
        return False
