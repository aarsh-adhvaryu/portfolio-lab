"""The governed tool loop that every chat answer runs on (S68 workers, S80 phase 4: moved out of `hq/workers.py` and `hq/brain.py` when those were cut).

Each turn is priced, checked and logged by `llm.call` (the governor, the egress gate); each tool call goes through `tools.run` (only the role's allowed tools, redaction,
egress, the sourced-numbers rule). The loop ends with the model's final text, a wait named by a tool (`ctx.wait_for`), a refusal or provider failure (returned in
`stop_exc`, never swallowed), or the turn limit. Model-written words never change permissions; fetched pages and documents are data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

MAX_TURNS = 10
NUDGES = 2                                  # times a model is told its promise is unmet before the run ends
CACHE = {"type": "ephemeral"}               # top-level automatic caching: composes with the system block's own breakpoint (S70)
KEEP_BLOCKS = ("text", "thinking", "redacted_thinking", "tool_use")


@dataclass
class Conv:
    note: str = ""
    cost: float = 0.0
    nudges: int = 0
    turns: int = 0
    stop_exc: Optional[Exception] = None
    first_call: Optional[int] = None


def as_param(block) -> dict:
    """A response block as a request block (the SDK's model, or a test's namespace)."""
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    return {k: v for k, v in vars(block).items() if v is not None}


def unnamed(text: str, names: Optional[Sequence[str]] = None) -> str:
    """S62: his name, if the model wrote it, becomes 'the investor' (it is never sent; see llm.body_check)."""
    from pflab.hq import egress
    for n in (egress.names() if names is None else names):
        text = re.sub(r"\b" + re.escape(n) + r"\b", "the investor", text, flags=re.I)
    return text


def _scrub_ids(text: str, gate) -> str:
    """The model's own words with any of his account, depository, folio or deposit ids replaced (the privacy gate would otherwise refuse the next request
    and the run would stop on a number the model itself had copied)."""
    from pflab.hq import redact
    out, _ = redact.redact(text, gate, lines=False)
    return out


def _scrub_obj(x, gate):
    if isinstance(x, str):
        return _scrub_ids(x, gate)
    if isinstance(x, dict):
        return {k: _scrub_obj(v, gate) for k, v in x.items()}
    if isinstance(x, list):
        return [_scrub_obj(v, gate) for v in x]
    return x


def converse(rt, con, ctx, messages: list, *, system: str, tools: list, model: str, agent: str, effort: str, max_out: int, client, gate, cfg: dict, mode: str,
             his: bool, private_first: str, question: str, check=None, max_turns: int = MAX_TURNS, on_step=None, extra_system: str = "") -> Conv:
    """The governed tool loop. `check(note)` may return a reminder to send back when the model stops before its promise is met (at most NUDGES times).
    `on_step(text)` lets a screen show what is being done."""
    from pflab.hq import llm, tools as tl
    out = Conv()
    sys_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    if extra_system:                                         # S77: skills, after the role's own instructions, cached as a block of their own
        sys_blocks.append({"type": "text", "text": extra_system, "cache_control": {"type": "ephemeral"}})
    for turn in range(1, max_turns + 1):
        out.turns = turn
        p = {"model": model, "max_tokens": max_out, "system": sys_blocks, "thinking": {"type": "adaptive"}, "output_config": {"effort": effort},
             "tools": tools, "messages": messages,
             "cache_control": CACHE}                      # S70: the growing conversation is cached (it was re-sent at full price on every turn)
        if turn == max_turns:
            p["tool_choice"] = {"type": "none"}
        try:
            s = llm.call(con, agent, p, client, now=rt.clock(), mode=mode, private_text=private_first if turn == 1 else "", gate=gate,
                         doc_kinds=("portfolio",), topic="mission", question=f"{question}, turn {turn}", cfg=cfg, turn=turn, his_order=his,
                         egress_skip=("address_word",))   # S69: "Address the dip rule" is English; his address words, PIN codes, flat/house numbers, name and ids still block
        except Exception as e:                                # refused, blocked, or the provider failed: the caller decides (wait or fail)
            out.stop_exc = e
            return out
        out.cost += s.cost_inr
        out.first_call = out.first_call or s.call_id
        msg = s.message
        uses = [b for b in msg.content if getattr(b, "type", "") == "tool_use"]
        if getattr(msg, "stop_reason", "") != "tool_use" or not uses:
            out.note = llm.text_of(msg)
            reminder = check(out.note) if check else None
            if reminder and out.nudges < NUDGES and turn < max_turns and not ctx.wait_for:
                out.nudges += 1
                messages.append({"role": "assistant", "content": [{"type": "text", "text": _scrub_ids(unnamed(out.note, gate.names), gate) or "(done)"}]})
                messages.append({"role": "user", "content": [{"type": "text", "text": reminder}]})
                continue
            return out
        kept = [as_param(b) for b in msg.content if getattr(b, "type", "") in KEEP_BLOCKS]
        for b in kept:
            if b.get("type") == "text":
                b["text"] = _scrub_ids(unnamed(b["text"], gate.names), gate)
            elif b.get("type") == "tool_use":                  # what the model wrote INTO a call goes back to it next turn: his ids are replaced there too
                b["input"] = _scrub_obj(b.get("input"), gate)
        messages.append({"role": "assistant", "content": kept})
        results = []
        for b in uses:
            if on_step:
                try:
                    on_step(b.name)
                except Exception:
                    pass
            text, err = tl.run(ctx, b.name, b.input, turn)
            pics, ctx.images = list(ctx.images), []             # S78: a tool's picture goes back to the model INSIDE its result (vision), with the text beside it
            content = [{"type": "text", "text": text}] + pics if pics and not err else text
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": content, **({"is_error": True} if err else {})})
        messages.append({"role": "user", "content": results})
        if ctx.wait_for:                                      # parked on the sandbox or on another worker's task: the caller checkpoints
            return out
    return out
