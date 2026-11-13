"""Small helpers shared by the chat's tool loop (`entrance/intake.converse`), the strategist and the gateway: a response block as a request block, his name masked, ids scrubbed.

S85 (G3): the governed tool loop that lived here (`converse()`, run on `hq/llm.call`) had no caller left since the chat's loop moved to the gateway (`entrance/intake.converse`,
agent "chat"); it was deleted, so the chat has ONE loop.
"""
from __future__ import annotations

import re
from typing import Optional, Sequence

KEEP_BLOCKS = ("text", "thinking", "redacted_thinking", "tool_use")


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
