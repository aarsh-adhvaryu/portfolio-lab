"""A small general chat client for local Ollama models (PLAN S21).

`llm/ollama.py` (migrated from the archive) is the A1 labelling reader; this module is the general
client the guarded workflows use. Everything goes over HTTP to the local server, so tests inject a
transport and never need Ollama. Temperature defaults to 0 and a fixed seed: the same prompt on the
same model digest gives the same answer.
"""
from __future__ import annotations

import re
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
    done_reason: str = ""                 # S79: Ollama's own reason for stopping ("stop", or "length" when the token cap cut the reply)
    label: str = "ok"                     # S79: llm/diag.py's reading of the call (ok, truncated, empty, loop, format)


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


SINK: Optional[Callable[[dict], None]] = None      # S70: the app's runtime sets one that keeps every call in `llm_runs` (who used the local model, how often, how long)


def set_sink(fn: Optional[Callable[[dict], None]]) -> None:
    global SINK
    SINK = fn


def _note(**row) -> None:
    sink = SINK
    if sink is not None:
        try:
            sink(row)
        except Exception:                               # keeping the record must never break the call
            pass


# S79 item 13: Qwen's recommended sampling for the qwen3 family (model card; `ollama show qwen3:8b-q8_0` agrees on top_k 20, top_p 0.95,
# temperature 0.6 for its default thinking mode). Greedy decoding (the old default, temperature 0) is what Qwen warns loops and repeats.
# Per call kind: "text" = free text with thinking off, "think" = thinking on, "json" = a constrained (schema) reply.
# A call uses a profile only when asked (`sampling="auto"`, a kind name, or a dict of overrides) or when its kind is in
# DEFAULT_KINDS (the kinds the registered comparison adopted, docs/protocols/s79_local_model_protocol.md). The seed stays fixed, so a
# given prompt still gives the same answer on the same model digest.
SAMPLING: Dict[str, dict] = {
    "text": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0, "presence_penalty": 1.5},
    "think": {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0, "presence_penalty": 1.0},
    "json": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0, "presence_penalty": 1.5},
}
DEFAULT_KINDS: set = set()          # kinds that use their profile when the caller says nothing (empty until the comparison adopts one)
_QWEN3 = re.compile(r"^qwen3(?:[:\-]|$)")      # qwen3:8b-q8_0, qwen3:30b-a3b ... (not qwen3.5, a different family)


def call_kind(think: bool, fmt: Optional[dict]) -> str:
    return "think" if think else ("json" if fmt else "text")


def sampling_options(model: str, sampling, think: bool = False, fmt: Optional[dict] = None, temperature: float = 0.0) -> dict:
    """The extra Ollama options for one call. `sampling`: None (the adopted default for this call kind, else nothing), "off",
    "auto" (the profile of this call's kind), a kind name, or a dict of option overrides (laid over "auto" for a qwen3 model).
    The profile only applies to a qwen3 model; a caller's own non-zero `temperature` wins over the profile's."""
    kind = call_kind(think, fmt)
    qwen = bool(_QWEN3.match(model or ""))
    if sampling is None:
        spec = kind if (kind in DEFAULT_KINDS and qwen) else None
    elif sampling == "off":
        spec = None
    elif sampling == "auto":
        spec = kind if qwen else None
    elif isinstance(sampling, dict):
        spec = kind if qwen else None
    else:
        if sampling not in SAMPLING:
            raise ValueError(f"unknown sampling profile {sampling!r}; known: {sorted(SAMPLING)}")
        spec = sampling
    out = dict(SAMPLING[spec]) if spec else {}
    if isinstance(sampling, dict):
        out.update(sampling)
    if temperature and "temperature" in out and not (isinstance(sampling, dict) and "temperature" in sampling):
        out["temperature"] = temperature
    return out


def chat(model: str, messages: List[dict], *, think: bool = False, temperature: float = 0.0, seed: int = SEED,
         num_predict: int = 400, fmt: Optional[dict] = None, transport: Transport = http_transport,
         timeout: int = 600, num_ctx: Optional[int] = None, purpose: str = "", sampling=None) -> Reply:
    """One chat completion. `think=False` turns the reasoning trace off (fast, deterministic length);
    `fmt` is an optional JSON schema for constrained output. `num_ctx`: the context window to use; Ollama's
    default (4,096 tokens here) silently drops the start of a longer prompt (S44: long document prompts).
    S79b item 17: a model written "seat:fast" or "seat:thinker" is a SEAT (llm/seats.py): its model and backend come from the registered pick, falling back to qwen3:8b-q8_0;
    a seat on the llama server goes there (OpenAI-compatible, the schema as a json_schema constraint), the rest through Ollama as before."""
    seat_opts: dict = {}
    if isinstance(model, str) and model.startswith("seat:"):
        from pflab.llm import seats
        if seats.is_on() and seats.is_seat_name(model):
            tgt = seats.chat_target(model)
            if tgt["backend"] == "llama_server":
                from pflab.llm import server
                return server.chat(tgt["model"], messages, think=think, temperature=temperature, seed=seed, num_predict=num_predict, fmt=fmt, timeout=timeout,
                                   purpose=purpose, options={**tgt["options"], **sampling_options(tgt["key"], sampling, think, fmt, temperature)})
            model, seat_opts = tgt["model"], tgt["options"]
        else:
            model = seats.FALLBACK
    models = installed(transport)
    name = resolve(model, models)
    if name is None:
        raise OllamaError(f"{model} is not installed in Ollama (ollama pull {model}); installed: {sorted(models)}")
    payload = {"model": name, "stream": False, "think": think, "messages": messages,
               "options": {"temperature": temperature, "seed": seed, "num_predict": num_predict}}
    payload["options"].update(seat_opts)
    payload["options"].update(sampling_options(name, sampling, think, fmt, temperature))
    if num_ctx:
        payload["options"]["num_ctx"] = int(num_ctx)
    if fmt:
        payload["format"] = fmt
    t0 = time.time()
    try:
        from pflab.llm import duty, queue
        duty.THROTTLE.before(purpose)                    # S79: the GPU duty cycle of the mode (off until the lead sets a mode)
        try:
            with queue.GATE.slot(purpose):               # S71: one card, one call at a time, the most important first
                with duty.THROTTLE.busy():
                    j = transport("POST", "/api/chat", payload, timeout)
        except queue.Busy as b:
            raise OllamaError(str(b)) from b
    except Exception as e:
        _note(model=name, purpose=purpose, status="failed", note=f"{type(e).__name__}: {str(e)[:200]}", seconds=round(time.time() - t0, 2), tokens_in=0, tokens_out=0,
              digest=models[name].get("digest"))
        raise
    text = (j.get("message") or {}).get("content", "")
    dr = str(j.get("done_reason") or "")
    from pflab.llm import diag
    label = diag.classify(text, int(j.get("eval_count", 0)), num_predict, dr, bool(fmt))
    r = Reply(text=text, model=name, digest=models[name]["digest"],
              tokens_in=int(j.get("prompt_eval_count", 0)), tokens_out=int(j.get("eval_count", 0)), seconds=round(time.time() - t0, 2),
              done_reason=dr, label=label)
    _note(model=name, purpose=purpose, status="ok", note="" if label == "ok" else label, seconds=r.seconds, tokens_in=r.tokens_in, tokens_out=r.tokens_out, digest=r.digest)
    return r


def as_llm(model: str, system: str = "", **kw) -> Callable[[str], str]:
    """A prompt -> text callable for the guarded workflows."""
    def llm(prompt: str) -> str:
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        return chat(model, msgs, **kw).text
    return llm
