"""The one door for model calls (S84, first version): every model call written for the thinking loop (cases, the desk) goes through `call` and nowhere else.

A thin, honest layer over what exists. The call still goes through, in this order and unchanged: the workshop's paid-call guard (`guard.require("paid")`, when the door makes the client itself), the egress
gate (`hq/egress`, `hq/llm.body_check`), the price (count_tokens, worst-case output), the governor (`hq/governor.check`: tokens, passes, the layer's day and month, his monthly cap, the acceptance window),
the send (Opus and Sonnet with the server-side fallback) and the record of the real cost in `api_calls` (cache reads and writes priced). What the door adds:

    ROLE        `decide` (a decision), `read` (reading, connecting), `quick` (short checks): `[engines.claude.<role>]` in configs/core.toml gives each a model and a THINKING level.
    THINKING    one scale for every vendor: low / medium / high / max, mapped by a small table (`[engines.claude.effort]`) to the vendor's own control. For Anthropic (SDK 1.15.0, Opus 5.5 and Sonnet 5.5)
                that is `thinking: {"type": "adaptive"}` plus `output_config.effort`; a fixed thinking budget is rejected (HTTP 400) by these models and is never sent.
    CACHE       the fixed part (the system text, the tool list, a book card the caller marks) is marked cacheable; the cached tokens come back and are logged beside the cost.
    RECORD      api_calls.role / engine / thinking / cached_tokens / case_id / purpose (migration 210), and the same words in the result, so a caller stores them with its step.

Rule 8 is the caller's: the door moves words, never numbers. Failures are raised as they come (see `refusals()`); the caller keeps its case open and tries again later (`refusal_reason`).

How S85 adds a vendor: write a class with the five methods of `AnthropicEngine` (`name`, `effort`, `params`, `make_client`, `send`, `read`), register it in `ENGINES`, give the role a table in configs/core.toml with
`engine = "<name>"` (and its own `[engines.<name>.effort]` map). `call` does not change, and neither do the callers: they read `engine`, `model` and `thinking` off the result.
Tests inject a scripted fake with `set_client(fake)` (an injected client is a test double: the workshop guard applies to the client the door makes itself); everything else is the real path.
"""
from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pflab import guard

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "core.toml"
ROLES = ("quick", "read", "decide")                    # ordered: a role that is not configured falls back to the next one up
LEVELS = ("low", "medium", "high", "max")
DEFAULTS: Dict[str, Any] = {
    "default": "anthropic",
    "claude": {
        "engine": "anthropic", "cache": True,
        "decide": {"model": "claude-opus-5-5", "thinking": "high", "min_tokens": 8000},
        "read": {"model": "claude-sonnet-5-5", "thinking": "medium", "min_tokens": 4000},
        "quick": {"model": "claude-sonnet-5-5", "thinking": "low", "min_tokens": 1500},
        "effort": {"low": "low", "medium": "medium", "high": "high", "max": "max"},
    },
}
AGENTS = ("think", "desk")                              # the governor's names for what the door serves (`hq/governor.LIMITS`)
MAX_BREAKPOINTS = 4                                     # the vendor's limit of cache markers in one request
client_override: Any = None                             # a scripted fake (tests); `set_client(None)` removes it

# the refusals a caller expects and handles (the case stays open, only thesis-break sales still act); the vendor's own failures are other exceptions
def refusals() -> tuple:
    from pflab.agents import analyst as an
    from pflab.hq import egress
    return (egress.EgressBlocked, an.BudgetRefused, an.NeedsApproval, guard.OutwardBlocked)


def set_client(fake: Any) -> None:
    """Tests: every `call` uses this client (a scripted fake with `messages.count_tokens` and the vendor's create method); None removes it."""
    global client_override
    client_override = fake


# --- settings and roles -----------------------------------------------------------------------------------------------------------

def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def settings(path: Optional[Path] = None) -> dict:
    """`[engines]` of configs/core.toml over the defaults: {"default": "anthropic", "claude": {engine, cache, decide, read, quick, effort}}. An unreadable file leaves the defaults."""
    out = copy.deepcopy(DEFAULTS)
    try:
        from pflab import _toml
        out = _merge(out, _toml.load(path or CONFIG).get("engines") or {})
    except Exception:
        pass
    return out


def resolve(role: str, st: Optional[dict] = None) -> dict:
    """The role as it will run: {"role" (asked), "role_used", "engine", "model", "thinking", "min_tokens", "note"}. A role that is switched off (`enabled = false`) or has no model falls back to the next role up, with a note."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}: one of {', '.join(ROLES)}")
    st = st or settings()
    eng = st.get("claude") or {}
    notes = []
    for r in ROLES[ROLES.index(role):]:
        spec = eng.get(r)
        if isinstance(spec, dict) and spec.get("model") and spec.get("enabled", True):
            level = str(spec.get("thinking", "medium")).lower()
            if level not in LEVELS:
                raise ValueError(f"role {r}: thinking {level!r} is not on the scale {'/'.join(LEVELS)}")
            if r != role:
                notes.append(f"role '{role}' is not configured: '{r}' ran instead")
            return {"role": role, "role_used": r, "engine": str(eng.get("engine") or st.get("default") or "anthropic"), "model": str(spec["model"]), "thinking": level,
                    "min_tokens": int(spec.get("min_tokens", 1500)), "note": "; ".join(notes)}
        notes.append(f"role '{r}' is off or has no model")
    raise ValueError(f"no role from '{role}' up is configured in [engines.claude]")


def roles(st: Optional[dict] = None) -> Dict[str, dict]:
    """Every role as it will run, for the screens and the notes: {role: resolve(role)} (a role with nothing above it to fall back to is left out)."""
    out = {}
    for r in ROLES:
        try:
            out[r] = resolve(r, st)
        except ValueError:
            pass
    return out


# --- the engines ------------------------------------------------------------------------------------------------------------------

class AnthropicEngine:
    """Today's only engine: the Anthropic SDK client behind `hq/llm.call` (egress, price, governor, record)."""
    name = "anthropic"

    def effort(self, level: str, st: dict) -> str:
        table = (st.get("claude") or {}).get("effort") or DEFAULTS["claude"]["effort"]
        return str(table.get(level, level))

    def params(self, spec: dict, st: dict, system, messages: list, tools: Optional[list], max_tokens: int, schema: Optional[dict], tool_choice: Optional[str]) -> dict:
        cache = bool((st.get("claude") or {}).get("cache", True))
        sys_blocks = [{"type": "text", "text": system}] if isinstance(system, str) else copy.deepcopy(list(system or []))
        tool_defs = copy.deepcopy(list(tools)) if tools else None
        marks = sum(1 for b in sys_blocks if isinstance(b, dict) and b.get("cache_control"))
        marks += sum(1 for t in (tool_defs or []) if t.get("cache_control"))
        marks += sum(1 for m in messages for b in (m.get("content") if isinstance(m.get("content"), list) else []) if isinstance(b, dict) and b.get("cache_control"))
        if cache:
            if tool_defs and not tool_defs[-1].get("cache_control") and marks < MAX_BREAKPOINTS - 1:        # the tool list is the first thing of the prefix: its last entry closes it
                tool_defs[-1]["cache_control"] = {"type": "ephemeral"}
                marks += 1
            if sys_blocks and not any(b.get("cache_control") for b in sys_blocks) and marks < MAX_BREAKPOINTS - 1:
                sys_blocks[-1]["cache_control"] = {"type": "ephemeral"}
                marks += 1
        out_cfg: Dict[str, Any] = {"effort": self.effort(spec["thinking"], st)}
        if schema:
            out_cfg["format"] = {"type": "json_schema", "schema": schema}
        p: Dict[str, Any] = {"model": spec["model"], "max_tokens": max(int(max_tokens), int(spec["min_tokens"])), "thinking": {"type": "adaptive"}, "output_config": out_cfg,
                             "messages": list(messages)}
        if sys_blocks:
            p["system"] = sys_blocks
        if tool_defs:
            p["tools"] = tool_defs
        if tool_choice == "none":
            p["tool_choice"] = {"type": "none"}
        if cache and marks < MAX_BREAKPOINTS:
            p["cache_control"] = {"type": "ephemeral"}                    # the growing conversation (the last block) is cached as well, as the strategist does
        return p

    def make_client(self):
        from pflab.agents import analyst as an
        try:
            from pflab.pm import secrets as sec
            secrets = sec.load()
        except Exception:
            secrets = None
        return an.make_client(secrets)                                     # applies the workshop's paid-call guard (--paid) before any key is read

    def send(self, con, *, agent: str, params: dict, client, now: datetime, mode: str, private_text: str, gate, topic: str, question: str, cfg: Optional[dict], approved: bool,
             turn: int):
        from pflab.hq import llm
        return llm.call(con, agent, params, client, now=now, mode=mode, private_text=private_text, gate=gate, doc_kinds=("portfolio",), topic=topic, question=question, cfg=cfg,
                        approved=approved, turn=turn, egress_skip=("address_word",))

    def read(self, sent) -> dict:
        from pflab.hq import converse, llm
        msg = sent.message
        u = getattr(msg, "usage", None)
        blocks = list(getattr(msg, "content", None) or [])
        return {"text": llm.text_of(msg), "stop_reason": getattr(msg, "stop_reason", ""), "model": getattr(msg, "model", None),
                "tool_calls": [{"id": getattr(b, "id", ""), "name": b.name, "input": dict(getattr(b, "input", None) or {})} for b in blocks if getattr(b, "type", "") == "tool_use"],
                "assistant_content": [converse.as_param(b) for b in blocks if getattr(b, "type", "") in converse.KEEP_BLOCKS],
                "cached_tokens": int(getattr(u, "cache_read_input_tokens", 0) or 0), "cache_written_tokens": int(getattr(u, "cache_creation_input_tokens", 0) or 0)}


ENGINES: Dict[str, Any] = {"anthropic": AnthropicEngine()}


# --- the door ---------------------------------------------------------------------------------------------------------------------

def _text_of_content(c) -> str:
    if isinstance(c, str):
        return c
    return "\n".join(b.get("text", "") for b in (c or []) if isinstance(b, dict) and b.get("type") == "text")


def _first_user_text(messages: Sequence[dict]) -> str:
    for m in messages:
        if m.get("role") == "user":
            return _text_of_content(m.get("content"))
    return ""


def call(con, role: str, system, messages: list, *, tools: Optional[list] = None, case_id: Optional[int] = None, purpose: str = "", now: Optional[datetime] = None,
         max_tokens: int = 1500, schema: Optional[dict] = None, agent: str = "think", client: Any = None, gate=None, cfg: Optional[dict] = None, approved: bool = False,
         mode: str = "normal", private_text: Optional[str] = None, tool_choice: Optional[str] = None, topic: str = "", question: str = "", st: Optional[dict] = None) -> dict:
    """One model call for a ROLE. Returns {"text", "json" (parsed when `schema` was asked, else None), "tool_calls" ([{id, name, input}]), "assistant_content" (what to append as the assistant turn
    of a tool loop), "cost_rupees", "cached_tokens", "engine", "model", "thinking" (the level), "requested_model", "role", "role_used", "stop_reason", "truncated", "call_id", "warnings", "note"}.

    `system`: a string or a list of text blocks. `messages`: the conversation (a caller may put its own `cache_control` on a book card). `max_tokens` is raised to the role's `min_tokens` (thinking counts
    as output). `tool_choice` may only be None (auto) or "none": a forced tool is rejected by these models. `agent` is the governor's name for the caller: "think" (cases) or "desk".
    `private_text`: what the egress gate reads; None means the first user message (the book card, the strategist's rule); pass "" when the first message is public text. The conversation's turn is counted
    from its assistant messages, so a tool loop is one pass for the governor.

    Raises what the old road raises: egress.EgressBlocked, analyst.BudgetRefused (logged `over_limit`, with `resume_at`), analyst.NeedsApproval, guard.OutwardBlocked (the workshop without --paid), and the
    vendor's own errors. A refusal by the model is a RuntimeError. See `refusals()` and `refusal_reason`. Nothing is sent before the egress gate, the price and the governor have passed."""
    if agent not in AGENTS:
        raise ValueError(f"agent {agent!r} is not one the door serves: {', '.join(AGENTS)}")
    if tool_choice not in (None, "auto", "none"):
        raise ValueError("a forced tool choice (any / a named tool) is rejected by these models: leave tool_choice unset or 'none'")
    now = now or datetime.now()
    st = st or settings()
    spec = resolve(role, st)
    eng = ENGINES.get(spec["engine"])
    if eng is None:
        raise ValueError(f"engine {spec['engine']!r} is not registered (ENGINES: {', '.join(ENGINES)})")
    params = eng.params(spec, st, system, messages, tools, max_tokens, schema, tool_choice)
    if gate is None:
        from pflab.hq import egress
        gate = egress.load(con)
    c = client or client_override or eng.make_client()
    turn = 1 + sum(1 for m in messages if m.get("role") == "assistant")
    sent = eng.send(con, agent=agent, params=params, client=c, now=now, mode=mode, private_text=_first_user_text(messages) if private_text is None else private_text, gate=gate,
                    topic=topic or f"{agent}:{purpose or role}", question=(question or f"{agent} {purpose or role}")[:300] + (f" (case #{case_id})" if case_id else ""), cfg=cfg,
                    approved=approved, turn=turn)
    r = eng.read(sent)
    model = r["model"] or spec["model"]
    con.execute("UPDATE api_calls SET role=?, engine=?, thinking=?, cached_tokens=?, case_id=?, purpose=? WHERE call_id=?",
                [role, eng.name, spec["thinking"], r["cached_tokens"], case_id, purpose[:200], sent.call_id])
    parsed = None
    err = None
    if schema:
        from pflab.hq import llm
        try:
            parsed = llm.json_of(r["text"])
        except ValueError as e:
            parsed, err = {}, f"the answer was not valid JSON ({e})"
        if not parsed and not err:
            err = "the answer was not valid JSON (none found)"
    return {"text": r["text"], "json": parsed, "json_error": err, "tool_calls": r["tool_calls"], "assistant_content": r["assistant_content"], "cost_rupees": float(sent.cost_inr),
            "cached_tokens": r["cached_tokens"], "cache_written_tokens": r["cache_written_tokens"], "engine": eng.name, "model": model, "requested_model": spec["model"],
            "thinking": spec["thinking"], "role": role, "role_used": spec["role_used"], "stop_reason": r["stop_reason"], "truncated": r["stop_reason"] == "max_tokens",
            "call_id": sent.call_id, "warnings": list(sent.warnings), "note": spec["note"]}


def refusal_reason(e: BaseException) -> Optional[str]:
    """Plain words for a refusal a caller should wait out (with the time it may be different), or None for any other error."""
    if isinstance(e, refusals()):
        when = getattr(e, "resume_at", None)
        return f"{type(e).__name__}: {str(e)[:300]}" + (f" (can change at {when:%Y-%m-%d %H:%M})" if when else "")
    return None


def spent(con, since: datetime, *, agent: Optional[str] = None, case_id: Optional[int] = None, purpose: Optional[str] = None) -> float:
    """Rupees the door's calls cost since `since` (the day's desk budget reads it), by agent, case or purpose. Counts what the governor counts (done, sending, refused, queued, submitted)."""
    sql = "SELECT coalesce(sum(cost_inr),0) FROM api_calls WHERE created_at >= ? AND status IN ('done','sending','refused','queued','submitted') AND (engine IS NOT NULL OR agent IN ('think','desk'))"
    args: List[Any] = [since]
    for col, v in (("agent", agent), ("case_id", case_id), ("purpose", purpose)):
        if v is not None:
            sql += f" AND {col} = ?"
            args.append(v)
    return float(con.execute(sql, args).fetchone()[0])
