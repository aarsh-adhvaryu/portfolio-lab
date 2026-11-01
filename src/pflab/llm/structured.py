"""One way for every small local job to ask for a structured answer (S71).

The 8B model is reliable at choosing among a closed list and filling a few named slots when the answer is constrained by a JSON schema and then CHECKED BY
CODE; it is not reliable at writing numeric code or at remembering to stay inside the facts. So a small job is: a closed schema, a validator written in code,
one retry that names the error, and then nothing: the caller falls back to a rule or to the cloud. The model chooses; it never states a number of its own.
The pattern is the one `hq/arrivals.py` proved on document routing (S69).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class Result:
    value: Optional[dict]
    error: Optional[str]
    attempts: int

    @property
    def ok(self) -> bool:
        return self.value is not None


def ask_json(system: str, prompt: str, schema: dict, validate: Optional[Callable[[dict], Optional[str]]] = None, *, purpose: str,
             model: Optional[str] = None, retries: int = 1, num_predict: int = 300, num_ctx: int = 4096, chat: Optional[Callable] = None) -> Result:
    """The model's answer as a dict that passed `schema` (the model is constrained to it) and `validate` (code: returns None, or what is wrong). A reply that is
    not JSON, not an object or rejected by `validate` is asked again once with the error named; after that, or if the model cannot be reached at all, the result
    carries the error and no value. `chat` is injectable (tests)."""
    from pflab.llm import client, registry
    chat = chat or client.chat
    name = model or registry.chosen("general") or "qwen3:8b-q8_0"
    err: Optional[str] = None
    for attempt in range(1, retries + 2):
        user = prompt + (f"\nYour previous answer was invalid: {err}. Answer again with valid JSON only." if err else "")
        try:
            r = chat(name, [{"role": "system", "content": system}, {"role": "user", "content": user}], fmt=schema, num_predict=num_predict, num_ctx=num_ctx, purpose=purpose)
        except Exception as e:                           # Ollama down, the card busy, a timeout: not the model's fault and not worth a second call
            return Result(None, f"{type(e).__name__}: {str(e)[:200]}", attempt)
        try:
            obj = json.loads(r.text)
        except ValueError:
            err = "the reply was not JSON"
            continue
        if not isinstance(obj, dict):
            err = "the reply was not a JSON object"
            continue
        err = validate(obj) if validate else None
        if not err:
            return Result(obj, None, attempt)
    return Result(None, err, retries + 1)
