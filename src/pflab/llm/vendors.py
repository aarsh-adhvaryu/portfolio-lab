"""The vendors' own SDKs (S85, rule 4 as A70 rewrote it): the ONLY place in the app that imports `anthropic` or `openai`. Every call goes through `llm/gateway.py`; these two functions only make
the client objects. Keys come from `pm/secrets.py` (never printed, never logged); the workshop's paid-call guard is applied by the caller before a key is read.
"""
from __future__ import annotations

from typing import Any, Optional


def anthropic_client(secrets=None, *, timeout: Optional[float] = None):
    """The Anthropic SDK client: the key from secrets.toml [anthropic] api_key if present, else the SDK's own resolution (ANTHROPIC_API_KEY or an `ant auth login` profile)."""
    import anthropic
    headers = {}
    kw: dict = {}
    if timeout:
        kw["timeout"] = float(timeout)
    if secrets is not None and secrets.has("anthropic", "workspace_id"):
        # a key not scoped to a workspace must name one on every request (API error seen 2026-10-17)
        headers["anthropic-workspace-id"] = secrets.get("anthropic", "workspace_id")
    if secrets is not None and secrets.has("anthropic", "api_key"):
        return anthropic.Anthropic(api_key=secrets.get("anthropic", "api_key"), default_headers=headers or None, **kw)
    return anthropic.Anthropic(default_headers=headers or None, **kw)


def openai_client(secrets, key_name: str, *, base_url: Optional[str] = None, timeout: float = 120.0, max_retries: int = 1) -> Any:
    """An OpenAI-compatible client (OpenAI itself, or any vendor offering that wire format). `key_name` is "section.key" in the secrets file; a missing key is a plain error that names the field
    (never a value). One retry at the SDK level; the door's fallback rule does the rest."""
    import openai
    section, _, key = key_name.partition(".")
    if secrets is None or not secrets.has(section, key):
        raise RuntimeError(f"no key for this engine: set [{section}] {key} with `pflab setup secrets --only {section}`")
    return openai.OpenAI(api_key=secrets.get(section, key), base_url=base_url or None, timeout=float(timeout), max_retries=int(max_retries))
