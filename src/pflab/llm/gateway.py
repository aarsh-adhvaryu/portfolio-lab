"""The one door for model calls (S84 first version; S85 generalised: any engine behind it): every model call in the app goes through `call` and nowhere else.

A thin, honest layer over what exists. The call still goes through, in this order and unchanged: the workshop's paid-call guard (`guard.require("paid")`, when the door makes the client itself), the egress
gate (`hq/egress`, `hq/llm.body_check`), the price (count_tokens, or a labelled estimate where a vendor has none; worst-case output), the governor (`hq/governor.check`: tokens, passes, the layer's day and
month, his monthly cap, the acceptance window), the send and the record of the real cost in `api_calls` (cache reads and writes priced). What the door adds:

    ROLE        `decide` (a decision), `read` (reading, connecting), `quick` (short checks): each engine gives each role a model and a THINKING level (`[engines.<name>.<role>]` in configs/core.toml).
    ENGINE      a named set in `[engines.<name>]`: a provider (`anthropic` | `openai_compat`), its base URL and the NAME of its key in the secrets file, per role a model and a thinking level, its prices (with source
                and date), and a feature table. The engine in use is stored (`engine_state_s85`, changed by `use`): a switch takes effect at the next call, no restart; the loops, rules, tools and prompts are the same.
    THINKING    one scale for every vendor: low / medium / high / max, mapped by `[engines.<name>.effort]` to the vendor's own control. Anthropic (SDK 1.15.0, Opus 5.5 / Sonnet 5.5 / Haiku 5.5): `thinking:
                {"type": "adaptive"}` plus `output_config.effort` (a fixed budget is rejected, HTTP 400). OpenAI: `reasoning.effort`. A model without such a control ignores it, and the result says so.
    CACHE       Anthropic: the fixed part is marked cacheable; OpenAI caches by itself. Cached tokens come back and are logged beside the cost.
    OVERRIDES   `model`, `thinking`, `engine` change ONE call (the chat's picker and Auto). `agent` is the governor's name for the caller (AGENTS).
    GUARDS      consent before anything is sent to a vendor (`engine_consent_s85`: exam / shadow / use); three failures in a row on a role send that call to the fallback engine, put a line on the Problems list and
                tell him once a day; a case in progress finishes its step on the engine that began it; an engine whose model has no price cannot be used.
    RECORD      api_calls.role / engine / thinking / cached_tokens / case_id / purpose / chat_id / reply_msg_id / vendor / fallback_from, and the same words in the result, so a caller stores them with its step.

Rule 8 is the caller's: the door moves words, never numbers. Failures are raised as they come (see `refusals()`); the caller keeps its case open and tries again later (`refusal_reason`).

How S85 adds a vendor: (1) if it speaks the Anthropic or the OpenAI wire format, only config: add `[engines.<name>]` with `provider`, `base_url`, `key_name` (a field in `pm/secrets_setup.FIELDS`), roles, `[engines.<name>.prices.<key>]`
(read from the vendor's own price page, with `source` and `date`) and `[engines.<name>.features]`; (2) if it needs another wire format, write a class with the methods of `OpenAICompatEngine`, register it in `ENGINES`
under a provider name. `call` does not change, and neither do the callers: they read `engine`, `model` and `thinking` off the result.
Tests inject a scripted fake with `set_client(fake)` (an injected client is a test double: the workshop guard applies to the client the door makes itself); everything else is the real path.
"""
from __future__ import annotations

import copy
import os
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pflab import guard

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "core.toml"
ROLES = ("quick", "read", "decide")                    # ordered: a role that is not configured falls back to the next one up
LEVELS = ("low", "medium", "high", "max")
SCOPES = ("exam", "shadow", "use")                     # what his Yes covers: `use` covers the other two
DEFAULT_ENGINE = "claude"
_ANTHROPIC_FEATURES = {"tools": True, "structured": True, "thinking_effort": True, "caching": True, "documents": True, "images": True, "web_search": True, "token_count": True, "batch": True}
DEFAULTS: Dict[str, Any] = {
    "default": DEFAULT_ENGINE, "fallback": DEFAULT_ENGINE, "fail_streak": 3, "fallback_minutes": 30, "case_pin_minutes": 30,
    "claude": {
        "provider": "anthropic", "vendor": "anthropic", "key_name": "anthropic.api_key", "cache": True,
        "decide": {"model": "claude-opus-5-5", "thinking": "high", "min_tokens": 8000},
        "read": {"model": "claude-sonnet-5-5", "thinking": "medium", "min_tokens": 4000},
        "quick": {"model": "claude-sonnet-5-5", "thinking": "low", "min_tokens": 1500},
        "effort": {"low": "low", "medium": "medium", "high": "high", "max": "max"},
        "features": dict(_ANTHROPIC_FEATURES),
        "prices": {
            "haiku": {"model": "claude-haiku-5-5", "tier": "quick", "input": 0.10, "output": 0.50, "cached_input": 0.01, "source": "Anthropic price list via the claude-api reference (prompts up to 100K tokens)", "date": "2026-11-03"},
            "sonnet": {"model": "claude-sonnet-5-5", "tier": "read", "input": 2.00, "output": 10.00, "cached_input": 0.20, "source": "Anthropic price list via the claude-api reference", "date": "2026-11-03"},
            "opus": {"model": "claude-opus-5-5", "tier": "decide", "input": 4.00, "output": 20.00, "cached_input": 0.20, "source": "Anthropic price list via the claude-api reference", "date": "2026-11-03"},
        },
    },
}
AGENTS = ("think", "desk", "chat", "strategist", "checker", "reading")      # the governor's names for what the door serves (`hq/governor.LIMITS`)
MAX_BREAKPOINTS = 4                                     # the vendor's limit of cache markers in one request
WEB_USD_PER_SEARCH = 0.01                               # Anthropic's server web search, on top of tokens ($10 per 1,000)
client_override: Any = None                             # a scripted fake (tests) for every engine; `set_client(None)` removes it
client_overrides: Dict[str, Any] = {}                   # a scripted fake for one engine (tests with two vendors): `set_client(fake, engine="x")`
_lock = threading.Lock()


class ConsentMissing(RuntimeError):
    """Nothing is sent to a vendor before his Yes (the first use or shadow of a vendor shows what goes and needs it)."""


class EngineUnusable(RuntimeError):
    """The engine named is not configured, has no key, or a model of it has no price."""


# the refusals a caller expects and handles (the case stays open, only thesis-break sales still act); the vendor's own failures are other exceptions
def refusals() -> tuple:
    from pflab.agents import analyst as an
    from pflab.hq import egress
    return (egress.EgressBlocked, an.BudgetRefused, an.NeedsApproval, guard.OutwardBlocked, ConsentMissing, EngineUnusable)


def set_client(fake: Any, engine: Optional[str] = None) -> None:
    """Tests: every `call` uses this client (a scripted fake with `messages.count_tokens` and the vendor's create method); None removes it. With `engine`, only that engine's calls use it."""
    global client_override
    if engine:
        if fake is None:
            client_overrides.pop(engine, None)
        else:
            client_overrides[engine] = fake
    else:
        client_override = fake
        if fake is None:
            client_overrides.clear()


# --- settings, engines and roles -----------------------------------------------------------------------------------------------------

def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def settings(path: Optional[Path] = None) -> dict:
    """`[engines]` of configs/core.toml over the defaults: {"default", "fallback", ..., "<engine>": {provider, vendor, key_name, cache, decide, read, quick, effort, features, prices}}. An unreadable
    file leaves the defaults. A legacy `engine = "<provider>"` key in an engine's table is read as its provider."""
    out = copy.deepcopy(DEFAULTS)
    try:
        from pflab import _toml
        out = _merge(out, _toml.load(path or CONFIG).get("engines") or {})
    except Exception:
        pass
    return out


def engine_names(st: Optional[dict] = None) -> List[str]:
    """The engines configured: every table under [engines] that names a provider (the claude engine first)."""
    st = st or settings()
    names = [k for k, v in st.items() if isinstance(v, dict) and (v.get("provider") or v.get("engine"))]
    return sorted(names, key=lambda n: (n != DEFAULT_ENGINE, n))


def econf(st: dict, name: str) -> dict:
    e = st.get(name)
    if not isinstance(e, dict) or not (e.get("provider") or e.get("engine")):
        raise EngineUnusable(f"engine {name!r} is not configured (engines: {', '.join(engine_names(st))})")
    return e


def provider_of(st: dict, name: str) -> str:
    e = econf(st, name)
    return str(e.get("engine") or e.get("provider"))                       # a legacy `engine = "<provider>"` key (S84) wins, so an old table still works


def vendor_of(st: dict, name: str) -> str:
    e = econf(st, name)
    if e.get("vendor"):
        return str(e["vendor"])
    kn = str(e.get("key_name") or "")
    return kn.partition(".")[0] or name


def features_of(st: dict, name: str) -> dict:
    e = econf(st, name)
    base = _ANTHROPIC_FEATURES if provider_of(st, name) == "anthropic" else {"tools": True, "structured": True, "thinking_effort": True, "caching": "automatic", "documents": False, "images": True,
                                                                              "web_search": False, "token_count": False, "batch": True, "wire": "responses"}
    return {**base, **(e.get("features") or {})}


def prices_of(st: dict, name: str) -> Dict[str, dict]:
    return {k: v for k, v in (econf(st, name).get("prices") or {}).items() if isinstance(v, dict)}


def register_prices(st: Optional[dict] = None) -> None:
    """Every engine's models into the governor's price table (a vendor's own list, dollars per million tokens). A model the governor already prices (Anthropic's) is left as it is."""
    from pflab.hq import governor as gv
    st = st or settings()
    for name in engine_names(st):
        for p in prices_of(st, name).values():
            m = p.get("model")
            if m and m not in gv.PRICES and p.get("input") is not None and p.get("output") is not None:
                gv.register_model(str(m), float(p["input"]), float(p["output"]), p.get("cached_input"), p.get("cache_write"))


def resolve(role: str, st: Optional[dict] = None, *, engine: Optional[str] = None, model: Optional[str] = None, thinking: Optional[str] = None) -> dict:
    """The role as it will run: {"role" (asked), "role_used", "engine", "provider", "vendor", "model", "thinking", "min_tokens", "note"}. A role that is switched off (`enabled = false`) or has no model
    falls back to the next role up, with a note. `engine` (default: the configured default), `model` (a key or an id in the engine's price table) and `thinking` override for one call."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}: one of {', '.join(ROLES)}")
    st = st or settings()
    name = engine or str(st.get("default") or DEFAULT_ENGINE)
    eng = econf(st, name)
    notes = []
    if thinking is not None and str(thinking).lower() not in LEVELS:
        raise ValueError(f"thinking {thinking!r} is not on the scale {'/'.join(LEVELS)}")
    for r in ROLES[ROLES.index(role):]:
        spec = eng.get(r)
        if isinstance(spec, dict) and spec.get("model") and spec.get("enabled", True):
            level = str(thinking or spec.get("thinking", "medium")).lower()
            if level not in LEVELS:
                raise ValueError(f"role {r}: thinking {level!r} is not on the scale {'/'.join(LEVELS)}")
            if r != role:
                notes.append(f"role '{role}' is not configured: '{r}' ran instead")
            m = str(spec["model"])
            if model:
                m = model_id(st, name, model)
                notes.append(f"model {m} chosen for this call")
            return {"role": role, "role_used": r, "engine": name, "provider": provider_of(st, name), "vendor": vendor_of(st, name), "model": m, "thinking": level,
                    "min_tokens": int(spec.get("min_tokens", 1500)), "note": "; ".join(notes)}
        notes.append(f"role '{r}' is off or has no model")
    raise ValueError(f"no role from '{role}' up is configured in [engines.{name}]")


def model_id(st: dict, engine: str, model: str) -> str:
    """A key (`opus`) or an id (`claude-opus-5-5`) of the engine's price table -> the id. Any other model is refused: a model without a price cannot be used."""
    pr = prices_of(st, engine)
    if model in pr:
        return str(pr[model]["model"])
    for p in pr.values():
        if p.get("model") == model:
            return str(model)
    for r in ROLES:
        if (econf(st, engine).get(r) or {}).get("model") == model and model in {p.get("model") for p in pr.values()}:
            return model
    raise ValueError(f"model {model!r} is not one of {engine}'s priced models ({', '.join(sorted(p['model'] for p in pr.values()))})")


def roles(st: Optional[dict] = None, engine: Optional[str] = None) -> Dict[str, dict]:
    """Every role as it will run, for the screens and the notes: {role: resolve(role)} (a role with nothing above it to fall back to is left out)."""
    out = {}
    for r in ROLES:
        try:
            out[r] = resolve(r, st, engine=engine)
        except ValueError:
            pass
    return out


def models_of(engine: Optional[str] = None, st: Optional[dict] = None) -> List[dict]:
    """The models of an engine for the chat's picker (Auto is the picker's own first entry): [{"key", "model", "price_in", "price_out", "tier"}], cheapest first. Prices are dollars per million tokens."""
    st = st or settings()
    name = engine or current_engine(st=st)
    rows = [{"key": k, "model": str(p["model"]), "price_in": float(p.get("input") or 0.0), "price_out": float(p.get("output") or 0.0), "tier": str(p.get("tier") or "")}
            for k, p in prices_of(st, name).items() if p.get("model")]
    return sorted(rows, key=lambda r: (r["price_out"], r["key"]))


# --- the engines (providers) --------------------------------------------------------------------------------------------------------

class AnthropicEngine:
    """The Anthropic wire format: the SDK client behind `hq/llm.call` (egress, price, governor, record)."""
    name = "anthropic"

    def effort(self, level: str, st: dict, engine: str = DEFAULT_ENGINE) -> str:
        table = (st.get(engine) or {}).get("effort") or DEFAULTS["claude"]["effort"]
        return str(table.get(level, level))

    def params(self, spec: dict, st: dict, system, messages: list, tools: Optional[list], max_tokens: int, schema: Optional[dict], tool_choice: Optional[str], *, web: bool = False) -> dict:
        name = spec.get("engine", DEFAULT_ENGINE)
        conf = st.get(name) or st.get(DEFAULT_ENGINE) or {}
        cache = bool(conf.get("cache", True))
        sys_blocks = [{"type": "text", "text": system}] if isinstance(system, str) else copy.deepcopy(list(system or []))
        tool_defs = copy.deepcopy(list(tools)) if tools else None
        if web:
            tool_defs = (tool_defs or []) + [{"type": str((conf.get("features") or {}).get("web_tool") or "web_search_20250305"), "name": "web_search", "max_uses": int(spec.get("web_max_uses", 5))}]
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
        out_cfg: Dict[str, Any] = {"effort": self.effort(spec["thinking"], st, name)}
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

    def make_client(self, econf: Optional[dict] = None):
        from pflab.agents import analyst as an
        try:
            from pflab.pm import secrets as sec
            secrets = sec.load()
        except Exception:
            secrets = None
        return an.make_client(secrets)                                     # applies the workshop's paid-call guard (--paid) before any key is read

    def send(self, con, *, agent: str, params: dict, client, now: datetime, mode: str, private_text: str, gate, topic: str, question: str, cfg: Optional[dict], approved: bool,
             turn: int, his_order: bool = False, extra_in: int = 0):
        from pflab.hq import llm
        return llm.call(con, agent, params, client, now=now, mode=mode, private_text=private_text, gate=gate, doc_kinds=("portfolio",), topic=topic, question=question, cfg=cfg,
                        approved=approved, turn=turn, extra_in=extra_in, his_order=his_order, egress_skip=("address_word",))

    def read(self, sent) -> dict:
        from pflab.hq import converse, llm
        msg = sent.message
        u = getattr(msg, "usage", None)
        blocks = list(getattr(msg, "content", None) or [])
        tb = []
        for b in blocks:
            if getattr(b, "type", "") == "text":
                cites = [{"url": getattr(c, "url", None), "title": getattr(c, "title", None) or getattr(c, "document_title", None), "document_index": getattr(c, "document_index", None),
                          "cited_text": getattr(c, "cited_text", None)} for c in (getattr(b, "citations", None) or [])]
                tb.append({"text": getattr(b, "text", "") or "", "citations": cites})
        searches = int(getattr(getattr(u, "server_tool_use", None), "web_search_requests", 0) or 0)
        return {"text": llm.text_of(msg), "stop_reason": getattr(msg, "stop_reason", ""), "model": getattr(msg, "model", None),
                "tool_calls": [{"id": getattr(b, "id", ""), "name": b.name, "input": dict(getattr(b, "input", None) or {})} for b in blocks if getattr(b, "type", "") == "tool_use"],
                "assistant_content": [converse.as_param(b) for b in blocks if getattr(b, "type", "") in converse.KEEP_BLOCKS],
                "raw_content": blocks,
                "cached_tokens": int(getattr(u, "cache_read_input_tokens", 0) or 0), "cache_written_tokens": int(getattr(u, "cache_creation_input_tokens", 0) or 0),
                "web_searches": searches, "text_blocks": tb}


def _openai_engine():
    from pflab.llm.openai_compat import OpenAICompatEngine
    return OpenAICompatEngine()


ENGINES: Dict[str, Any] = {"anthropic": AnthropicEngine(), "openai_compat": _openai_engine()}      # provider name -> wire-format class


# --- state: the engine in use, shadows, consent ---------------------------------------------------------------------------------------------

def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now()


def _get_state(con, key: str) -> Optional[str]:
    try:
        r = con.execute("SELECT value FROM engine_state_s85 WHERE key=?", [key]).fetchone()
    except Exception:
        return None
    return r[0] if r else None


def _set_state(con, key: str, value: str, now: datetime, note: str = "") -> None:
    con.execute("DELETE FROM engine_state_s85 WHERE key=?", [key])
    con.execute("INSERT INTO engine_state_s85 VALUES (?,?,?,?)", [key, value, now, note])


def current_engine(con=None, st: Optional[dict] = None) -> str:
    """The engine in use: the stored one (set by `use`), else the configured default. A stored engine that is no longer configured falls back to the default."""
    st = st or settings()
    name = _get_state(con, "in_use") if con is not None else None
    if name and name in engine_names(st):
        return name
    d = str(st.get("default") or DEFAULT_ENGINE)
    return d if d in engine_names(st) else DEFAULT_ENGINE


def fallback_engine(con=None, st: Optional[dict] = None) -> str:
    """The engine a failing role's call goes to: `[engines] fallback`, else the engine in use before the last switch, else claude."""
    st = st or settings()
    f = str(st.get("fallback") or "")
    if f and f in engine_names(st):
        return f
    prev = _get_state(con, "previous") if con is not None else None
    return prev if prev and prev in engine_names(st) else DEFAULT_ENGINE


def shadows(con) -> List[str]:
    try:
        return [r[0] for r in con.execute("SELECT engine FROM engine_shadow_s85 WHERE active ORDER BY engine").fetchall()]
    except Exception:
        return []


def consent_rows(con, vendor: Optional[str] = None) -> List[dict]:
    q = "SELECT consent_id, vendor, scope, given_at, given_by, wording, active FROM engine_consent_s85 WHERE active" + (" AND vendor=?" if vendor else "") + " ORDER BY consent_id"
    return [dict(zip(("consent_id", "vendor", "scope", "given_at", "given_by", "wording", "active"), r)) for r in con.execute(q, [vendor] if vendor else []).fetchall()]


def has_consent(con, vendor: str, scope: str) -> bool:
    """His Yes for this vendor covers `scope`: his Yes to `use` covers `shadow` and `exam`; a Yes to `shadow` does not cover `exam` or `use`."""
    have = {r["scope"] for r in consent_rows(con, vendor)}
    return scope in have or "use" in have


def grant(con, vendor: str, scope: str, *, now: Optional[datetime] = None, given_by: str = "his Yes", wording: str = "") -> int:
    """Record his Yes (dated, with the words he was shown). Only called with his Yes: `use` / `shadow` below, the Settings button, the CLI's --yes."""
    if scope not in SCOPES:
        raise ValueError(f"scope {scope!r}: one of {', '.join(SCOPES)}")
    from pflab.pm.store import next_id
    cid = next_id(con, "engine_consent_s85", "consent_id")
    con.execute("INSERT INTO engine_consent_s85 VALUES (?,?,?,?,?,?,?)", [cid, vendor, scope, _now(now), given_by, wording[:600], True])
    return cid


def notice(st: dict, name: str, scope: str = "use") -> str:
    """The one line he is shown before an engine is used or shadowed: exactly what goes where."""
    v = vendor_of(st, name)
    what = {"use": f"use it for the roles decide, read and quick", "shadow": "think every live case beside the engine in use (it never acts)", "exam": "take the exam"}[scope]
    return (f"{name} ({v}) will {what}: that sends {v} what each role needs, which includes your holdings, amounts and weights, never your identity or banking details. "
            f"Cost follows {v}'s own price list. Say Yes to go on.")


def key_set(st: dict, name: str) -> bool:
    kn = str(econf(st, name).get("key_name") or "")
    sec_, _, key = kn.partition(".")
    try:
        from pflab.pm import secrets_setup as ss
        if ss.status().get(kn):
            return True
    except Exception:
        pass
    if provider_of(st, name) == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))                  # the SDK's own resolution
    return bool(key and os.environ.get(f"{sec_.upper()}_API_KEY"))


def engine_problems(st: dict, name: str, *, need_key: bool = True) -> List[str]:
    """Why an engine cannot be used, in plain words (empty: nothing in the way): provider unknown, a role's model without a price, no key."""
    out: List[str] = []
    try:
        prov = provider_of(st, name)
    except EngineUnusable as e:
        return [str(e)]
    if prov not in ENGINES:
        out.append(f"provider {prov!r} is not one the app can speak (providers: {', '.join(ENGINES)})")
    priced = {p.get("model") for p in prices_of(st, name).values() if p.get("input") is not None and p.get("output") is not None}
    for r in ROLES:
        spec = econf(st, name).get(r)
        if isinstance(spec, dict) and spec.get("enabled", True) and spec.get("model") and spec["model"] not in priced:
            out.append(f"the {r} model {spec['model']} has no price in the engine's table (an engine without a priced model cannot be used)")
    if not any(isinstance(econf(st, name).get(r), dict) and econf(st, name)[r].get("model") for r in ROLES):
        out.append("no role has a model")
    if need_key and prov != "anthropic" and not key_set(st, name):                       # Anthropic's SDK finds its key by itself (env, profile): its absence surfaces at the guard / the call
        out.append(f"no key: {econf(st, name).get('key_name') or 'none named'} is not set (pflab setup secrets --only {vendor_of(st, name)})")
    return out


def record_exam(con, engine: str, *, thinking: str = "", form_pass: bool, grade: str = "", cost_rupees: float = 0.0, detail: Optional[dict] = None, now: Optional[datetime] = None) -> int:
    """The exam module's verdict (form pass or fail, the grade in words, the cost): `use` reads it. Written by `llm/exam.py`."""
    import json
    from pflab.pm.store import next_id
    eid = next_id(con, "engine_exam_s85", "exam_id")
    con.execute("INSERT INTO engine_exam_s85 VALUES (?,?,?,?,?,?,?,?)", [eid, engine, _now(now), thinking, bool(form_pass), grade[:600], float(cost_rupees), json.dumps(detail or {}, default=str)])
    return eid


def exam_state(con, engine: str) -> Optional[dict]:
    """The newest exam of an engine: {"form_pass", "grade", "thinking", "cost_rupees", "ts"} or None when none was run."""
    try:
        r = con.execute("SELECT form_pass, grade, thinking, cost_rupees, ts FROM engine_exam_s85 WHERE engine=? ORDER BY exam_id DESC LIMIT 1", [engine]).fetchone()
    except Exception:
        return None
    return dict(zip(("form_pass", "grade", "thinking", "cost_rupees", "ts"), r)) if r else None


def use(con, name: str, *, yes: bool = False, now: Optional[datetime] = None, st: Optional[dict] = None) -> dict:
    """Make `name` the engine in use (the next call, no restart). -> {"ok", "engine", "needs_yes", "notice", "reason"}. The default engine can always be returned to. Any other engine needs: a key, a price
    for each model, an exam whose form part passed (`record_exam`), and his Yes to `use` for its vendor (the notice is shown every time he has not said Yes to `use` for that vendor)."""
    st = st or settings()
    now = _now(now)
    try:
        econf(st, name)
    except EngineUnusable as e:
        return {"ok": False, "engine": name, "needs_yes": False, "notice": "", "reason": str(e)}
    cur = current_engine(con, st)
    if name == cur:
        return {"ok": True, "engine": name, "needs_yes": False, "notice": "", "reason": "already in use"}
    why = engine_problems(st, name)
    if name != DEFAULT_ENGINE:
        ex = exam_state(con, name)
        if not ex:
            why.append("no exam has been run: pflab engine test " + name)
        elif not ex["form_pass"]:
            why.append(f"it failed the exam's form part ({ex['grade'] or 'see pflab engine test'}): it cannot be switched on")
    if why:
        return {"ok": False, "engine": name, "needs_yes": False, "notice": "", "reason": "; ".join(why)}
    vendor = vendor_of(st, name)
    note = notice(st, name, "use")
    if not any(r["scope"] == "use" for r in consent_rows(con, vendor)):
        if not yes:
            return {"ok": False, "engine": name, "needs_yes": True, "notice": note, "reason": "his Yes is needed first"}
        grant(con, vendor, "use", now=now, wording=note)
    _set_state(con, "previous", cur, now)
    _set_state(con, "in_use", name, now, f"switched from {cur}")
    return {"ok": True, "engine": name, "needs_yes": False, "notice": note, "reason": f"{name} is in use from the next call (before: {cur})"}


def shadow(con, name: str, *, yes: bool = False, now: Optional[datetime] = None, st: Optional[dict] = None) -> dict:
    """Put `name` in shadow: it thinks every live case beside the engine in use, stored and scored, never acting. Needs a key, priced models and his Yes for the vendor's `shadow` scope."""
    st = st or settings()
    now = _now(now)
    try:
        econf(st, name)
    except EngineUnusable as e:
        return {"ok": False, "engine": name, "needs_yes": False, "notice": "", "reason": str(e)}
    if name == current_engine(con, st):
        return {"ok": False, "engine": name, "needs_yes": False, "notice": "", "reason": "it is the engine in use: nothing to shadow"}
    why = engine_problems(st, name)
    if why:
        return {"ok": False, "engine": name, "needs_yes": False, "notice": "", "reason": "; ".join(why)}
    vendor = vendor_of(st, name)
    note = notice(st, name, "shadow")
    if not has_consent(con, vendor, "shadow"):
        if not yes:
            return {"ok": False, "engine": name, "needs_yes": True, "notice": note, "reason": "his Yes is needed first"}
        grant(con, vendor, "shadow", now=now, wording=note)
    con.execute("DELETE FROM engine_shadow_s85 WHERE engine=?", [name])
    con.execute("INSERT INTO engine_shadow_s85 VALUES (?,?,?)", [name, now, True])
    return {"ok": True, "engine": name, "needs_yes": False, "notice": note, "reason": f"{name} is in shadow: it thinks the live cases beside {current_engine(con, st)} and never acts"}


def unshadow(con, name: str) -> dict:
    con.execute("UPDATE engine_shadow_s85 SET active=FALSE WHERE engine=?", [name])
    return {"ok": True, "engine": name, "reason": f"{name} is no longer in shadow"}


# --- failures, the fallback and the Problems list --------------------------------------------------------------------------------------

def _event(con, now: datetime, engine: str, role: str, agent: str, model: str, ok: bool, kind: str = "", detail: str = "", call_id: Optional[int] = None) -> None:
    try:
        from pflab.hq import llm
        from pflab.pm.store import next_id
        con.execute("INSERT INTO engine_events_s85 VALUES (?,?,?,?,?,?,?,?,?,?)", [next_id(con, "engine_events_s85", "event_id"), now, engine, role, agent, model, bool(ok), kind, llm.scrub(detail)[:300], call_id])
    except Exception:
        pass


def failure_streak(con, engine: str, role: str) -> Tuple[int, Optional[datetime]]:
    """(failures in a row, the time of the newest one) for an engine on a role."""
    try:
        rows = con.execute("SELECT ok, ts FROM engine_events_s85 WHERE engine=? AND role=? ORDER BY event_id DESC LIMIT 20", [engine, role]).fetchall()
    except Exception:
        return 0, None
    n, last = 0, None
    for ok, ts in rows:
        if ok:
            break
        n += 1
        last = last or ts
    return n, last


def _problem(con, now: datetime, engine: str, role: str, text: str) -> None:
    """A line on the Problems list (once a day per engine and role), and one Telegram line a day at most."""
    try:
        from pflab.pm.store import next_id
        day = now.date()
        if con.execute("SELECT 1 FROM engine_problems_s85 WHERE engine=? AND role=? AND CAST(ts AS DATE)=?", [engine, role, day]).fetchone():
            return
        con.execute("INSERT INTO engine_problems_s85 VALUES (?,?,?,?,?,?)", [next_id(con, "engine_problems_s85", "problem_id"), now, engine, role, text[:400], None])
        from pflab.service import telegram
        if telegram.enqueue(con, text, kind="alert", dedup_key=f"engine_fallback:{day}", now=now):
            con.execute("UPDATE engine_problems_s85 SET told_on=? WHERE engine=? AND role=? AND CAST(ts AS DATE)=?", [day, engine, role, day])
    except Exception:
        pass


def open_problems(con, days: int = 7) -> List[dict]:
    """The engine problems of the last days for the Problems list: [{"ts", "engine", "role", "text", "told_on"}]."""
    try:
        since = datetime.now() - timedelta(days=days)
        return [dict(zip(("ts", "engine", "role", "text", "told_on"), r)) for r in con.execute("SELECT ts, engine, role, text, told_on FROM engine_problems_s85 WHERE ts >= ? ORDER BY ts DESC", [since]).fetchall()]
    except Exception:
        return []


def case_engine(con, case_id: Optional[int], now: datetime, minutes: float) -> Optional[str]:
    """The engine that made the case's newest step, if that step is recent: the case finishes its current step on the engine that began it, whatever he switched to meanwhile."""
    if not case_id or minutes <= 0:
        return None
    try:
        r = con.execute("SELECT engine, step_at FROM think_steps_s84 WHERE case_id=? AND coalesce(engine,'') <> '' ORDER BY step_id DESC LIMIT 1", [case_id]).fetchone()
    except Exception:
        return None
    if r and r[1] is not None and now - r[1] <= timedelta(minutes=float(minutes)):
        return str(r[0])
    return None


# --- the door ---------------------------------------------------------------------------------------------------------------------------

def _text_of_content(c) -> str:
    if isinstance(c, str):
        return c
    return "\n".join(b.get("text", "") for b in (c or []) if isinstance(b, dict) and b.get("type") == "text")


def _first_user_text(messages: Sequence[dict]) -> str:
    for m in messages:
        if m.get("role") == "user":
            return _text_of_content(m.get("content"))
    return ""


def _attach(messages: list, documents: Optional[list], images: Optional[list]) -> list:
    """The documents and images to the LAST user message as canonical blocks (documents first, then the text). A document: {"title", "text"} or {"title", "media_type", "data"} (base64);
    an image: {"media_type", "data"} (base64) or {"url"}. The caller's own list is not changed."""
    if not documents and not images:
        return messages
    blocks: List[dict] = []
    for d in documents or []:
        if d.get("text") is not None:
            blocks.append({"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": d["text"]}, "title": str(d.get("title") or "")[:500],
                           **({"citations": {"enabled": True}} if d.get("citations", True) else {})})
        else:
            blocks.append({"type": "document", "source": {"type": "base64", "media_type": d.get("media_type", "application/pdf"), "data": d["data"]}, "title": str(d.get("title") or "")[:500]})
    for im in images or []:
        blocks.append({"type": "image", "source": ({"type": "url", "url": im["url"]} if im.get("url") else {"type": "base64", "media_type": im.get("media_type", "image/png"), "data": im["data"]})})
    msgs = copy.deepcopy(list(messages))
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].get("role") == "user":
            c = msgs[i]["content"]
            msgs[i]["content"] = blocks + ([{"type": "text", "text": c}] if isinstance(c, str) else list(c or []))
            return msgs
    return [{"role": "user", "content": blocks}] + msgs


def _client_for(eng, engine_name: str, ec: dict, client: Any):
    if client is not None:
        return client
    if engine_name in client_overrides:
        return client_overrides[engine_name]
    if client_override is not None:
        return client_override
    return eng.make_client(ec)


def call(con, role: str, system, messages: list, *, tools: Optional[list] = None, case_id: Optional[int] = None, purpose: str = "", now: Optional[datetime] = None,
         max_tokens: int = 1500, schema: Optional[dict] = None, agent: str = "think", client: Any = None, gate=None, cfg: Optional[dict] = None, approved: bool = False,
         mode: str = "normal", private_text: Optional[str] = None, tool_choice: Optional[str] = None, topic: str = "", question: str = "", st: Optional[dict] = None,
         model: Optional[str] = None, thinking: Optional[str] = None, engine: Optional[str] = None, chat_id: Optional[int] = None, reply_msg_id: Optional[int] = None,
         documents: Optional[list] = None, images: Optional[list] = None, web: bool = False, web_max_uses: int = 5, his_order: Optional[bool] = None, scope: Optional[str] = None,
         _fallback_from: Optional[str] = None) -> dict:
    """One model call for a ROLE. Returns {"text", "json" (parsed when `schema` was asked, else None), "tool_calls" ([{id, name, input}]), "assistant_content" (what to append as the assistant turn
    of a tool loop), "cost_rupees", "cached_tokens", "engine", "model", "thinking" (the level), "role", "role_used", "stop_reason", "truncated", "call_id", "warnings", "note", "input_tokens",
    "output_tokens", "provider", "vendor", "fallback_from", "web_searches", "text_blocks" ([{text, citations}])}.

    `system`: a string or a list of text blocks. `messages`: the conversation (canonical blocks: text, tool_use, tool_result, image, document; a caller may put its own `cache_control` on a book card).
    `max_tokens` is raised to the role's `min_tokens` (thinking counts as output). `tool_choice` may only be None (auto) or "none": a forced tool is rejected by these models. `agent` is the governor's
    name for the caller (AGENTS). `private_text`: what the egress gate reads; None means the first user message; pass "" when the first message is public text. The conversation's turn is counted from its
    assistant messages, so a tool loop is one pass for the governor.
    One-call overrides: `engine`, `model` (a key or id of that engine's priced models), `thinking` (low / medium / high / max). `documents` / `images` are added to the last user message; `web=True` asks for
    a web search (an engine without one: that call stays on the fallback engine and says so in `note`). `chat_id` / `reply_msg_id` are written to the call's row. `scope` ("exam" | "shadow") says what a
    call for a non-default engine is for (consent and the fallback rule); None means live use.

    Raises what the old road raises: egress.EgressBlocked, analyst.BudgetRefused (logged `over_limit`, with `resume_at`), analyst.NeedsApproval, guard.OutwardBlocked (the workshop without --paid),
    ConsentMissing, EngineUnusable, and the vendor's own errors. A refusal by the model is a RuntimeError. See `refusals()` and `refusal_reason`. Nothing is sent before the consent, the egress gate,
    the price and the governor have passed."""
    if agent not in AGENTS:
        raise ValueError(f"agent {agent!r} is not one the door serves: {', '.join(AGENTS)}")
    if tool_choice not in (None, "auto", "none"):
        raise ValueError("a forced tool choice (any / a named tool) is rejected by these models: leave tool_choice unset or 'none'")
    if scope is not None and scope not in SCOPES:
        raise ValueError(f"scope {scope!r}: one of {', '.join(SCOPES)}")
    from pflab.agents import analyst as an
    now = now or datetime.now()
    st = st or settings()
    cfg = cfg or an.config()
    in_use = current_engine(con, st)
    notes: List[str] = []
    # which engine: the caller's, else the one that began this case's current step, else the one in use; a failing role goes to the fallback; a call that needs the web stays where there is one
    name = engine or case_engine(con, case_id, now, float(st.get("case_pin_minutes", 30))) or in_use
    if name not in engine_names(st):
        raise EngineUnusable(f"engine {name!r} is not configured (engines: {', '.join(engine_names(st))})")
    if scope is None and _fallback_from is None:
        n, last = failure_streak(con, name, role)
        fb = fallback_engine(con, st)
        if n >= int(st.get("fail_streak", 3)) and name != fb and last is not None and now - last <= timedelta(minutes=float(st.get("fallback_minutes", 30))):
            notes.append(f"{name} failed {n} times in a row on {role}: this call went to {fb}")
            _fallback_from, name = name, fb
    if web and not features_of(st, name).get("web_search"):
        alt = next((e for e in [fallback_engine(con, st), DEFAULT_ENGINE, *engine_names(st)] if e in engine_names(st) and features_of(st, e).get("web_search")), None)
        if alt is None:
            raise EngineUnusable("no engine with a web search tool is configured")
        notes.append(f"{name} has no web search: this call stayed on {alt}")
        _fallback_from, name = _fallback_from or name, alt
    spec = resolve(role, st, engine=name, model=model if _fallback_from is None else None, thinking=thinking)
    spec["engine"] = name
    spec["web_max_uses"] = web_max_uses
    ec = econf(st, name)
    eng = ENGINES.get(spec["provider"])
    if eng is None:
        raise ValueError(f"engine {spec['provider']!r} is not registered (ENGINES: {', '.join(ENGINES)})")
    why = engine_problems(st, name, need_key=client is None and name not in client_overrides and client_override is None)
    if why:
        raise EngineUnusable(f"engine {name} cannot be used: " + "; ".join(why))
    vendor = spec["vendor"]
    need = scope or "use"
    if not has_consent(con, vendor, need):
        raise ConsentMissing(f"nothing is sent to {vendor} before his Yes ({need}): {notice(st, name, need)}")
    register_prices(st)
    msgs = _attach(messages, documents, images)
    params = eng.params(spec, st, system, msgs, tools, max_tokens, schema, tool_choice, web=web)
    if gate is None:
        from pflab.hq import egress
        gate = egress.load(con)
    c = _client_for(eng, name, ec, client)
    turn = 1 + sum(1 for m in messages if m.get("role") == "assistant")
    his = (agent == "chat") if his_order is None else bool(his_order)
    extra_in = 0
    if web:
        from pflab.hq import governor as gv
        pin = gv.PRICES.get(spec["model"], gv.PRICES[gv.OPUS])[0]
        extra_in = int(web_max_uses * WEB_USD_PER_SEARCH / (pin / 1e6)) if pin else 0
    kw = dict(agent=agent, params=params, client=c, now=now, mode=mode, private_text=_first_user_text(msgs) if private_text is None else private_text, gate=gate,
              topic=topic or f"{agent}:{purpose or role}", question=(question or f"{agent} {purpose or role}")[:300] + (f" (case #{case_id})" if case_id else ""), cfg=cfg, approved=approved, turn=turn,
              his_order=his, extra_in=extra_in)
    try:
        sent = eng.send(con, **kw)
    except refusals():
        raise
    except RuntimeError as e:
        if "declined this request" in str(e):                          # the model's own refusal is not an engine fault
            raise
        return _failed(con, e, now, name, role, agent, spec, st, locals_=locals())
    except Exception as e:
        return _failed(con, e, now, name, role, agent, spec, st, locals_=locals())
    r = eng.read(sent)
    cost = float(sent.cost_inr)
    searches = int(r.get("web_searches") or 0)
    if searches:                                                           # the server-side web tool is billed per search, on top of tokens
        extra = searches * WEB_USD_PER_SEARCH
        con.execute("UPDATE api_calls SET cost_usd = coalesce(cost_usd, 0) + ?, cost_inr = coalesce(cost_inr, 0) + ? WHERE call_id=?", [extra, extra * cfg["usd_inr"], sent.call_id])
        cost += extra * cfg["usd_inr"]
    answered = r["model"] or spec["model"]
    con.execute("UPDATE api_calls SET role=?, engine=?, thinking=?, cached_tokens=?, case_id=?, purpose=?, chat_id=?, reply_msg_id=?, vendor=?, fallback_from=? WHERE call_id=?",
                [role, name, spec["thinking"], r["cached_tokens"], case_id, purpose[:200], chat_id, reply_msg_id, vendor, _fallback_from, sent.call_id])
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
    row = con.execute("SELECT input_tokens, output_tokens FROM api_calls WHERE call_id=?", [sent.call_id]).fetchone() or (0, 0)
    out = {"text": r["text"], "json": parsed, "json_error": err, "tool_calls": r["tool_calls"], "assistant_content": r["assistant_content"], "cost_rupees": cost,
           "cached_tokens": r["cached_tokens"], "cache_written_tokens": r.get("cache_written_tokens", 0), "engine": name, "provider": spec["provider"], "vendor": vendor, "model": answered,
           "requested_model": spec["model"], "thinking": spec["thinking"], "role": role, "role_used": spec["role_used"], "stop_reason": r["stop_reason"], "truncated": r["stop_reason"] == "max_tokens",
           "call_id": sent.call_id, "warnings": list(sent.warnings), "note": "; ".join([n for n in [spec["note"], *notes] if n]), "input_tokens": int(row[0] or 0), "output_tokens": int(row[1] or 0),
           "fallback_from": _fallback_from, "web_searches": searches, "text_blocks": r.get("text_blocks", []), "chat_id": chat_id}
    if web and spec["provider"] == "anthropic" and r["stop_reason"] == "pause_turn":
        out = _continue_pause(con, eng, kw, params, r, out, now, cfg)
    if err and scope is None:                                              # a malformed answer counts like an error
        _event(con, now, name, role, agent, spec["model"], False, "malformed", err, sent.call_id)
        n, _ = failure_streak(con, name, role)
        fb = fallback_engine(con, st)
        if n >= int(st.get("fail_streak", 3)) and _fallback_from is None and name != fb:
            return _to_fallback(con, name, fb, n, role, agent, now, st, locals_=locals(), why="malformed answers")
    else:
        _event(con, now, name, role, agent, spec["model"], True, "", "", sent.call_id)
    return out


def _continue_pause(con, eng, kw: dict, params: dict, r: dict, out: dict, now: datetime, cfg: dict) -> dict:
    """A long server-side web search loop pauses: resume it (at most twice), as the analyst did; the costs add up and the text is the last answer's."""
    msgs = list(params["messages"])
    cur, total = r, out["cost_rupees"]
    for _ in range(2):
        if cur["stop_reason"] != "pause_turn":
            break
        msgs = msgs + [{"role": "assistant", "content": cur["raw_content"]}]
        p2 = {**params, "messages": msgs}
        sent = eng.send(con, **{**kw, "params": p2})
        cur = eng.read(sent)
        total += float(sent.cost_inr)
        out.update({"text": cur["text"], "text_blocks": cur.get("text_blocks", []), "stop_reason": cur["stop_reason"], "truncated": cur["stop_reason"] == "max_tokens",
                    "tool_calls": cur["tool_calls"], "assistant_content": cur["assistant_content"], "web_searches": out["web_searches"] + int(cur.get("web_searches") or 0)})
    out["cost_rupees"] = total
    return out


def _failed(con, e: BaseException, now: datetime, name: str, role: str, agent: str, spec: dict, st: dict, locals_: dict):
    """A vendor error or a timeout: recorded; the third in a row sends THIS call to the fallback engine (a line on the Problems list, one Telegram line a day); fewer: raised as it came."""
    kind = "timeout" if "timeout" in type(e).__name__.lower() else "error"
    _event(con, now, name, role, agent, spec["model"], False, kind, f"{type(e).__name__}: {e}")
    scope, fb_from = locals_.get("scope"), locals_.get("_fallback_from")
    n, _ = failure_streak(con, name, role)
    fb = fallback_engine(con, st)
    if scope is None and fb_from is None and name != fb and n >= int(st.get("fail_streak", 3)):
        return _to_fallback(con, name, fb, n, role, agent, now, st, locals_=locals_, why=f"{kind}s")
    raise e


def _to_fallback(con, name: str, fb: str, n: int, role: str, agent: str, now: datetime, st: dict, locals_: dict, why: str):
    _problem(con, now, name, role, f"The model engine '{name}' gave {n} {why} in a row on the {role} role; its calls go to '{fb}' for now. Nothing else changed.")
    L = locals_
    out = call(con, role, L["system"], L["messages"], tools=L["tools"], case_id=L["case_id"], purpose=L["purpose"], now=now, max_tokens=L["max_tokens"], schema=L["schema"], agent=agent,
               client=L["client"], gate=L["gate"], cfg=L["cfg"], approved=L["approved"], mode=L["mode"], private_text=L["private_text"], tool_choice=L["tool_choice"],
               topic=L["topic"], question=L["question"], st=st, thinking=L["thinking"], engine=fb, chat_id=L["chat_id"], reply_msg_id=L["reply_msg_id"], documents=L["documents"], images=L["images"],
               web=L["web"], web_max_uses=L["web_max_uses"], his_order=L["his_order"], _fallback_from=name)
    out["note"] = "; ".join(x for x in [out.get("note"), f"{name} failed {n} times in a row on {role}: this call went to {fb}"] if x)
    return out


def refusal_reason(e: BaseException) -> Optional[str]:
    """Plain words for a refusal a caller should wait out (with the time it may be different), or None for any other error."""
    if isinstance(e, refusals()):
        when = getattr(e, "resume_at", None)
        return f"{type(e).__name__}: {str(e)[:300]}" + (f" (can change at {when:%Y-%m-%d %H:%M})" if when else "")
    return None


def spent(con, since: datetime, *, agent: Optional[str] = None, case_id: Optional[int] = None, purpose: Optional[str] = None, engine: Optional[str] = None) -> float:
    """Rupees the door's calls cost since `since` (the day's desk budget reads it), by agent, case, purpose or engine. Counts what the governor counts (done, sending, refused, queued, submitted)."""
    sql = "SELECT coalesce(sum(cost_inr),0) FROM api_calls WHERE created_at >= ? AND status IN ('done','sending','refused','queued','submitted') AND (engine IS NOT NULL OR agent IN ('think','desk'))"
    args: List[Any] = [since]
    for col, v in (("agent", agent), ("case_id", case_id), ("purpose", purpose), ("engine", engine)):
        if v is not None:
            sql += f" AND {col} = ?"
            args.append(v)
    return float(con.execute(sql, args).fetchone()[0])


# --- for the screens ---------------------------------------------------------------------------------------------------------------------

def engines_status(con=None, st: Optional[dict] = None) -> List[dict]:
    """Every engine for the Settings screen and `pflab engine list` (JSON-able): name, provider, vendor, in use / shadow, whether it can be used and why not, the key (set or missing, never the value),
    each role's model, thinking level and price, the feature table (what it lacks is what the door degrades), his consents (dated), the newest exam (form verdict, grade in words, cost), the failures in
    a row per role, and the model list for the picker."""
    st = st or settings()
    in_use = current_engine(con, st) if con is not None else str(st.get("default") or DEFAULT_ENGINE)
    sh = shadows(con) if con is not None else []
    out = []
    for name in engine_names(st):
        e = econf(st, name)
        prices = prices_of(st, name)
        by_model = {p["model"]: p for p in prices.values() if p.get("model")}
        rl = {}
        for r in ROLES:
            try:
                s = resolve(r, st, engine=name)
            except ValueError:
                continue
            p = by_model.get(s["model"]) or {}
            rl[r] = {"model": s["model"], "thinking": s["thinking"], "price_in": p.get("input"), "price_out": p.get("output"), "note": s["note"]}
        feats = features_of(st, name)
        why = engine_problems(st, name)
        row = {"name": name, "provider": provider_of(st, name), "vendor": vendor_of(st, name), "in_use": name == in_use, "shadow": name in sh, "key": "set" if key_set(st, name) else "missing",
               "roles": rl, "features": feats, "lacks": sorted(k for k, v in feats.items() if v is False), "problems": why, "usable": not why, "models": models_of(name, st),
               "notes": ([] if feats.get("thinking_effort", True) else ["the thinking level is ignored by this engine"]) + ([] if feats.get("web_search") else ["web calls stay on the fallback engine"])}
        if con is not None:
            row["consent"] = [{"scope": c["scope"], "given_at": str(c["given_at"]), "given_by": c["given_by"]} for c in consent_rows(con, row["vendor"])]
            row["exam"] = exam_state(con, name)
            row["failures_in_a_row"] = {r: failure_streak(con, name, r)[0] for r in ROLES}
            if row["exam"] and row["exam"].get("ts") is not None:
                row["exam"]["ts"] = str(row["exam"]["ts"])
        out.append(row)
    return out
