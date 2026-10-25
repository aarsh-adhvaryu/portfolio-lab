"""A small general chat client for local Ollama models (PLAN S21).

`llm/ollama.py` (migrated from the archive) is the A1 labelling reader; this module is the general
client the guarded workflows use. Everything goes over HTTP to the local server, so tests inject a
transport and never need Ollama. Temperature defaults to 0 and a fixed seed: the same prompt on the
same model digest gives the same answer.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

URL = "http://localhost:11434"
SEED = 20261006

Transport = Callable[[str, str, Optional[dict], int], dict]    # (method, path, json, timeout) -> parsed json


class OllamaError(RuntimeError):
    pass


def http_transport(method: str, path: str, payload: Optional[dict] = None, timeout: int = 600) -> dict:
    import requests
    r = requests.request(method, URL + path, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


@dataclass(frozen=True)
class Reply:
    text: str
    model: str
    digest: Optional[str]
    tokens_in: int
    tokens_out: int
    seconds: float


def installed(transport: Transport = http_transport) -> Dict[str, dict]:
    """{model name: {digest, size, parameter_size, quantization}} for every installed model."""
    try:
        tags = transport("GET", "/api/tags", None, 30)["models"]
    except Exception as e:
        raise OllamaError(f"Ollama is not reachable at {URL}: {e}") from e
    return {m["name"]: {"digest": m["digest"], "size": m.get("size"),
                        "parameter_size": (m.get("details") or {}).get("parameter_size"),
                        "quantization": (m.get("details") or {}).get("quantization_level")} for m in tags}


def resolve(model: str, models: Dict[str, dict]) -> Optional[str]:
    """The installed name for `model` (accepts a name without ':latest')."""
    for cand in (model, f"{model}:latest"):
        if cand in models:
            return cand
    return None


def chat(model: str, messages: List[dict], *, think: bool = False, temperature: float = 0.0, seed: int = SEED,
         num_predict: int = 400, fmt: Optional[dict] = None, transport: Transport = http_transport,
         timeout: int = 600, num_ctx: Optional[int] = None) -> Reply:
    """One chat completion. `think=False` turns the reasoning trace off (fast, deterministic length);
    `fmt` is an optional JSON schema for constrained output. `num_ctx`: the context window to use; Ollama's
    default (4,096 tokens here) silently drops the start of a longer prompt (S44: long document prompts)."""
    models = installed(transport)
    name = resolve(model, models)
    if name is None:
        raise OllamaError(f"{model} is not installed in Ollama (ollama pull {model}); installed: {sorted(models)}")
    payload = {"model": name, "stream": False, "think": think, "messages": messages,
               "options": {"temperature": temperature, "seed": seed, "num_predict": num_predict}}
    if num_ctx:
        payload["options"]["num_ctx"] = int(num_ctx)
    if fmt:
        payload["format"] = fmt
    t0 = time.time()
    j = transport("POST", "/api/chat", payload, timeout)
    return Reply(text=(j.get("message") or {}).get("content", ""), model=name, digest=models[name]["digest"],
                 tokens_in=int(j.get("prompt_eval_count", 0)), tokens_out=int(j.get("eval_count", 0)),
                 seconds=round(time.time() - t0, 2))


def as_llm(model: str, system: str = "", **kw) -> Callable[[str], str]:
    """A prompt -> text callable for the guarded workflows."""
    def llm(prompt: str) -> str:
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        return chat(model, msgs, **kw).text
    return llm
