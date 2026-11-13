"""The Auto table (A70, S85): which model answers a chat message, decided by CODE in one table, with the reason written down.

    Haiku   a short reply, nothing to look up, nothing attached           role quick,  thinking low
    Sonnet  a file, a link, a claim, anything that needs a tool           role read,   thinking medium
    Opus    only when a decision is at stake: whether something should change the plan, the allocation, a pick or a standing rule that changes buying or selling
                                                                          role decide, thinking high

His picker (laptop and Telegram) overrides Auto for that message: the model ("haiku", "sonnet", "opus", or any key of the engine in use) and the thinking level (low / medium / high / max).
`route` is pure: the same words give the same answer; `why` is shown in the reply's meta. Words and limits below are the table; change them here and in the test.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Sequence

LEVELS = ("low", "medium", "high", "max")
SHORT_CHARS = 280

# model key -> (model id, role, default thinking, display name)
MODELS: Dict[str, tuple] = {
    "haiku": ("claude-haiku-5-5", "quick", "low", "Haiku 5.5"),
    "sonnet": ("claude-sonnet-5-5", "read", "medium", "Sonnet 5.5"),
    "opus": ("claude-opus-5-5", "decide", "high", "Opus 5.5"),
}

# a decision is at stake: the plan, the allocation, a pick, or a standing rule that changes buying or selling
DECISION = re.compile(
    r"\b(should (i|we|you|it)\b|is it (time|worth|right) to|do you (think|recommend)|what would you do|"
    r"change (the|my|our) (plan|allocation|split|picks?|policy|strategy|rules?)|re-?balance|re-?allocate|(raise|lower|cut|increase|reduce) (the )?(allocation|share|weight)|"
    r"from now on|until i say|(do not|don't|dont|stop|no more|never|pause|freeze|hold off)\W+(\w+\W+){0,3}(buy|buying|buys|sell|selling|sells|purchases)|"
    r"(pause|stop|freeze|halt)\W+(\w+\W+){0,3}(buys?|buying|sales?|selling)|no new (names?|stocks?|picks?|positions?)|cash floor|keep (at least )?\d+ ?%? ?(in )?cash|"
    r"(hold|keep) (on to )?(it|the stock|\w+) (no matter|whatever)|(add|drop|swap|replace) .{0,30}(pick|picks)|pick (it|this|that)|make it a pick|sell (it|all|everything)|buy (it|more|some))", re.I)

# something to look up or compute: needs a tool, so not Haiku
TOOL_WORDS = re.compile(
    r"\b(portfolio|book|holdings?|positions?|cash|balance|value|worth|price|prices|quote|nav|returns?|profit|loss|pnl|drawdown|allocation|weights?|tax|taxes|gain|gains|"
    r"picks?|scorecard|case|cases|thesis|storyline|storylines|watch(list)?|rules?|instruction|score|stock|stocks|share|shares|nifty|sensex|s&p|gold|etf|fund|bond|"
    r"news|search|look (up|into)|find|check|verify|compare|explain why|why did|what happened|how much|how many|what do you know|recall|filing|results|earnings|"
    r"show|list|tell me about|report|usage|cost|spent|status|working on|queue)\b", re.I)

CLAIM_WORDS = re.compile(r"\b(i read|i heard|i saw|they say|it is said|is it true|claim|rumou?r|according to|reported|announced|says that|source says)\b", re.I)
URL = re.compile(r"https?://|www\.", re.I)


def model_ids() -> Dict[str, str]:
    """key -> model id of the built-in table (the engine in use may name others: `gateway.models_of`)."""
    return {k: v[0] for k, v in MODELS.items()}


def display_name(model_key: Optional[str], model_id: Optional[str] = None) -> str:
    if model_key in MODELS:
        return MODELS[model_key][3]
    return model_id or model_key or ""


def _decision_at_stake(text: str) -> bool:
    return bool(DECISION.search(text or ""))


def _needs_tool(text: str) -> bool:
    return bool(TOOL_WORDS.search(text or ""))


def route(text: str, attachments: Optional[Sequence[Any]] = None, override: Optional[dict] = None) -> Dict[str, Any]:
    """-> {"model_key", "role", "thinking", "tools" ("none" | "all"), "why", "auto": bool}. `override`: {"model_key": ..., "thinking": ...} from the picker (either may be None = Auto)."""
    text = (text or "").strip()
    atts = list(attachments or [])
    ov = override or {}
    okey = ov.get("model_key") or ov.get("model")
    othink = ov.get("thinking")
    if othink is not None and othink not in LEVELS:
        raise ValueError(f"thinking must be one of {', '.join(LEVELS)}")
    if okey in (None, "", "auto"):
        okey = None

    if _decision_at_stake(text):
        key, why = "opus", "a decision is at stake (plan, allocation, a pick or a standing rule that changes buying or selling)"
        tools = "all"
    elif atts or URL.search(text) or CLAIM_WORDS.search(text) or _needs_tool(text) or len(text) > SHORT_CHARS:
        why_bits = [w for w, hit in (("a file", bool(atts)), ("a link", bool(URL.search(text))), ("a claim to check", bool(CLAIM_WORDS.search(text))),
                                     ("something to look up", _needs_tool(text)), ("a long message", len(text) > SHORT_CHARS)) if hit]
        key, why, tools = "sonnet", "needs " + " and ".join(why_bits[:2]), "all"
    else:
        key, why, tools = "haiku", "a short reply with nothing to look up", "none"

    if okey is not None:
        spec = MODELS.get(okey)
        role = spec[1] if spec else "read"
        thinking = othink or (spec[2] if spec else "medium")
        return {"model_key": okey, "role": role, "thinking": thinking, "tools": "all", "auto": False,
                "why": f"your pick: {display_name(okey)}, thinking {thinking}" + f" (Auto would have used {display_name(key)}: {why})"}
    thinking = othink or MODELS[key][2]
    return {"model_key": key, "role": MODELS[key][1], "thinking": thinking, "tools": tools, "auto": True,
            "why": f"Auto: {display_name(key)} ({why})" + (f", your thinking level {othink}" if othink else "")}
