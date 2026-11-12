"""The chat's tools (S85 E2). One list for the laptop and Telegram.

    The read tools of the system (`hq/tools.py`: the ledger, the graph, prices, the picks book, the rules, `recall`...), a few that act only through the door that exists for them (a standing
    instruction, a note for the strategist, a watch), and `web_search` / `fetch_cited` for public facts. The retired v1 layers (missions, investigation cases, experiments, hypotheses and their
    workspace) are not offered: see CORE_RETIRED. The tool modules themselves stay in `hq/tools.py` (the strategist's lab and the S82 cut own them).

    OTHER AGENTS ADD TOOLS HERE: `REGISTRY[name] = (definition, function)`, or `register(name, definition, function)`.
        definition  an Anthropic tool definition: {"name", "description", "input_schema": {"type": "object", "properties": {...}, "required": [...]}}
        function    fn(ctx, args: dict) -> dict (JSON-able). `ctx` is `hq.tools.Ctx` with two more attributes set by the intake: `ctx.chat_id` and `ctx.msg_id` (the answer being worked out), plus
                    `ctx.con` (a cursor), `ctx.now`, `ctx.rt`, `ctx.his_text` (what he typed in this turn: a yes is checked against it).
    A registered tool is run like a core one: its result is redacted, passed through the egress check, kept as source text for the sourced-numbers rule and journalled.
"""
from __future__ import annotations

import json
import time
from typing import Callable, Dict, List, Optional, Tuple

REGISTRY: Dict[str, Tuple[dict, Callable]] = {}

CORE_READ = ("picture", "portfolio", "stocks_overview", "stock_facts", "graph_timeline", "notes", "memory_recall", "research_flags", "price_history", "market_context", "who_is_buying",
             "growth", "findings", "comovement", "themes", "system_status", "tax_plan", "forecasts", "ipo_plan", "ready_plans", "simulation", "scenario", "measure", "quant", "recall", "rules",
             "envelope", "scorecard", "waiting", "paper_book", "chart_view", "watchlist", "files", "read_file", "file_figures", "read_document")
CORE_ACT = ("policy_scenarios", "exposure_shock", "ipo_policy_study", "remember_fact", "ask_strategist", "web_search", "fetch_cited", "add_rule", "undo_rule", "decide_rule", "answer_question",
            "watch_add", "watch_remove")
CORE_RETIRED = ("cases", "experiments", "hypotheses", "open_workspace", "case_calculate", "register_experiment", "frame_objective", "case_evidence")   # v1 layers (S68 missions, cases, experiments)
CORE = CORE_READ + CORE_ACT


def register(name: str, definition: dict, fn: Callable) -> None:
    """Add (or replace) a chat tool. The definition's name must be `name`."""
    if definition.get("name") != name:
        raise ValueError(f"tool definition is named {definition.get('name')!r}, not {name!r}")
    if "input_schema" not in definition:
        raise ValueError("a tool definition needs an input_schema")
    REGISTRY[name] = (definition, fn)


def names(kind: str = "all") -> List[str]:
    """The tool names a route may use: "none" -> [], anything else -> every core tool that exists plus the registered ones."""
    if kind == "none":
        return []
    from pflab.hq import tools as tl
    return [n for n in CORE if n in tl.TOOLS] + [n for n in REGISTRY if n not in CORE]


def definitions(kind: str = "all") -> List[dict]:
    """The API tool list in a fixed order (a changed order breaks the prompt cache): core tools first, then the registered ones."""
    if kind == "none":
        return []
    from pflab.hq import tools as tl
    core = [d for d in tl.definitions(frozenset(n for n in CORE if n in tl.TOOLS))]
    return core + [REGISTRY[n][0] for n in REGISTRY if n not in CORE]


def _validate(defn: dict, args) -> Optional[str]:
    if not isinstance(args, dict):
        return "the input must be an object"
    sch = defn.get("input_schema") or {}
    props = sch.get("properties") or {}
    extra = set(args) - set(props) if props and sch.get("additionalProperties") is False else set()
    if extra:
        return f"unknown field(s): {', '.join(sorted(extra))}"
    missing = [k for k in sch.get("required") or [] if k not in args]
    if missing:
        return f"missing field(s): {', '.join(missing)}"
    kinds = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
    for k, v in args.items():
        t = (props.get(k) or {}).get("type")
        if t in kinds and (not isinstance(v, kinds[t]) or (t in ("integer", "number") and isinstance(v, bool))):
            return f"{k}: must be {t}"
        enum = (props.get(k) or {}).get("enum")
        if enum and v not in enum:
            return f"{k}: one of {enum}"
    return None


def run(ctx, name: str, args, turn: int = 1) -> Tuple[str, bool]:
    """Run one tool call for the chat: (result text for the model, is_error). Core tools go through `hq.tools.run` (its allow-list, redaction, egress, journal); registered ones the same way here."""
    from pflab.hq import tools as tl
    if name not in REGISTRY or name in CORE:
        return tl.run(ctx, name, args, turn)
    from pflab.hq import egress, redact
    defn, fn = REGISTRY[name]
    t0 = time.monotonic()
    bad = _validate(defn, args)
    if bad:
        tl._log(ctx, turn, name, "read", args, "refused", bad, 0)
        return f"input refused: {bad}", True
    try:
        res, status, err = fn(ctx, args or {}), "ran", False
    except Exception as e:                                           # the model sees the failure and may try another way
        res, status, err = {"error": f"{type(e).__name__}: {str(e)[:400]}"}, "error", True
    text = json.dumps(tl._plain(res), default=str, ensure_ascii=False)
    if len(text) > tl.RESULT_CHARS:
        text = text[:tl.RESULT_CHARS] + f" ... (cut at {tl.RESULT_CHARS} characters)"
    text, _ = redact.redact(text, ctx.gate, lines=False)
    try:
        egress.check(text, ctx.gate, skip=("address",))
    except egress.EgressBlocked as e:
        text, status, err = f"withheld: the result carried identity or banking details ({e})", "withheld", True
    ctx.results[name] = text
    ctx.source += "\n" + text
    tl._log(ctx, turn, name, "read", args, status, text, int((time.monotonic() - t0) * 1000))
    ctx.call_ref = None
    return text, err


# --- tools this module brings -------------------------------------------------------------------------------------------------------------------------

def _pick_scorecard(ctx, a: dict) -> dict:
    from pflab.core import pick_score
    market = (a.get("market") or "IN").upper()
    return {"market": market, "scorecard": pick_score.scorecard_text(ctx.con, market)}


def _picks_book(ctx, a: dict) -> dict:
    from pflab.core import picks_card
    day = ctx.con.execute("SELECT max(day) FROM paper_days").fetchone()[0]
    if day is None:
        return {"note": "the paper book has not been marked yet"}
    return picks_card.build(ctx.con, day)


def _usage_today(ctx, a: dict) -> dict:
    from pflab.entrance import usage
    return {"today": usage.today(ctx.con, ctx.now.date()), "by_purpose": usage.by_purpose(ctx.con, ctx.now.date()), "text": usage.line(ctx.con, ctx.now.date())}


def _queue(ctx, a: dict) -> dict:
    from pflab.entrance import intake
    return {"working_on": intake.queue_status(ctx.con)}


register("pick_scorecard", {"name": "pick_scorecard", "description": "[read] How the system's picks, sales and skipped ideas did against the index after tax (1, 3, 6, 12 months). Use it when he asks how the picks are doing.",
                            "input_schema": {"type": "object", "properties": {"market": {"type": "string", "enum": ["IN", "US"], "description": "IN (default) or US"}}, "required": []}}, _pick_scorecard)
register("picks_book", {"name": "picks_book", "description": "[read] The picks sleeve now: what the system holds as picks, its reserve, each pick's thesis and break condition (S83).",
                        "input_schema": {"type": "object", "properties": {}, "required": []}}, _picks_book)
register("usage_today", {"name": "usage_today", "description": "[read] What the AI calls cost today, by purpose, in rupees.",
                         "input_schema": {"type": "object", "properties": {}, "required": []}}, _usage_today)
register("working_on", {"name": "working_on", "description": "[read] What the chat is working on right now for him (his messages and files in the queue).",
                        "input_schema": {"type": "object", "properties": {}, "required": []}}, _queue)
