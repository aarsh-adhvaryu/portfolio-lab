"""S79b item 17: every local structured reply is constrained at decoding time and checked afterwards.

Constrained decoding means the model cannot produce a token that leaves the schema: Ollama takes the JSON schema as `format`; the llama.cpp server takes it as
`response_format` {"type": "json_schema"} (and turns it into a grammar). On top of that `check` verifies the parsed object against the same schema in code, so a backend
that ignored the constraint is caught, not trusted. The model still chooses; code decides what is valid.

    payload_for(backend, schema)   the request fields that carry the schema for that backend
    llama_format(schema)           the llama-server fields
    enum_grammar(choices)          a GBNF grammar for a closed list (for `grammar` calls)
    check(obj, schema)             None when `obj` fits the schema, else what is wrong (the JSON-schema subset the callers use:
                                   type, enum, const, properties, required, additionalProperties, items, minItems, maxItems, minimum, maximum, minLength, maxLength)
    generate(...)                  one constrained call on a seat, returning `structured.Result`
"""
from __future__ import annotations

import json
from typing import Any, Callable, List, Optional


def llama_format(schema: dict, name: str = "reply") -> dict:
    return {"response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}}


def payload_for(backend: str, schema: Optional[dict]) -> dict:
    """The request fields for `schema` on `backend` ('ollama' | 'llama_server'). Empty without a schema."""
    if not schema:
        return {}
    return {"format": schema} if backend == "ollama" else llama_format(schema)


def _q(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def enum_grammar(choices: List[str]) -> str:
    """GBNF for exactly one of `choices`, as a JSON string (the reply is e.g. "buy")."""
    if not choices:
        raise ValueError("enum_grammar needs at least one choice")
    alts = " | ".join(_q(json.dumps(str(c))) for c in choices)
    return f"root ::= {alts}\n"


_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict, "null": type(None)}


def _is(v: Any, t: str) -> bool:
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, _TYPES[t]) and not (t in ("string", "array", "object") and isinstance(v, bool))


def check(obj: Any, schema: dict, path: str = "$") -> Optional[str]:
    """None when `obj` fits `schema`; otherwise a short sentence naming the first thing wrong and where."""
    if not isinstance(schema, dict):
        return None
    if "const" in schema and obj != schema["const"]:
        return f"{path}: must be {schema['const']!r}"
    if "enum" in schema and obj not in schema["enum"]:
        return f"{path}: {obj!r} is not one of {schema['enum']}"
    t = schema.get("type")
    if t:
        ts = t if isinstance(t, list) else [t]
        if not any(x in _TYPES and _is(obj, x) for x in ts):
            return f"{path}: expected {'/'.join(ts)}, got {type(obj).__name__}"
    if isinstance(obj, dict):
        props = schema.get("properties") or {}
        for k in schema.get("required") or []:
            if k not in obj:
                return f"{path}: missing {k!r}"
        if schema.get("additionalProperties") is False:
            extra = [k for k in obj if k not in props]
            if extra:
                return f"{path}: unexpected {extra[0]!r}"
        for k, sub in props.items():
            if k in obj:
                e = check(obj[k], sub, f"{path}.{k}")
                if e:
                    return e
    elif isinstance(obj, list):
        if "minItems" in schema and len(obj) < schema["minItems"]:
            return f"{path}: fewer than {schema['minItems']} items"
        if "maxItems" in schema and len(obj) > schema["maxItems"]:
            return f"{path}: more than {schema['maxItems']} items"
        if isinstance(schema.get("items"), dict):
            for i, x in enumerate(obj):
                e = check(x, schema["items"], f"{path}[{i}]")
                if e:
                    return e
    elif isinstance(obj, str):
        if "minLength" in schema and len(obj) < schema["minLength"]:
            return f"{path}: shorter than {schema['minLength']}"
        if "maxLength" in schema and len(obj) > schema["maxLength"]:
            return f"{path}: longer than {schema['maxLength']}"
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        if "minimum" in schema and obj < schema["minimum"]:
            return f"{path}: {obj} is below {schema['minimum']}"
        if "maximum" in schema and obj > schema["maximum"]:
            return f"{path}: {obj} is above {schema['maximum']}"
    return None


def generate(system: str, prompt: str, schema: dict, validate: Optional[Callable[[dict], Optional[str]]] = None, *, purpose: str, seat: str = "fast",
             retries: int = 1, num_predict: int = 300, num_ctx: int = 4096, chat: Optional[Callable] = None):
    """One schema-constrained call on a seat ('fast' | 'thinker'), checked in code, one retry that names the error. The seat's model and backend come from
    `pflab.llm.seats` (client.chat resolves the "seat:<name>" alias, falling back to qwen3:8b-q8_0). Returns `structured.Result`."""
    from pflab.llm import structured
    return structured.ask_json(system, prompt, schema, validate, purpose=purpose, model=f"seat:{seat}", retries=retries, num_predict=num_predict, num_ctx=num_ctx, chat=chat)
