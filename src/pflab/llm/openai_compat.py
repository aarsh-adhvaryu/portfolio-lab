"""The OpenAI wire format behind the one door (S85, E2a): OpenAI itself through its Responses API, and every vendor offering the Chat Completions format (`wire = "chat"` in the engine's features).

The loops, the tools and the prompts are the same on every engine, so what callers hand the door is ONE canonical shape (Anthropic-style content blocks: text, tool_use, tool_result, image, document) and what
comes back is the same dict. This class maps canonical -> the vendor's request, and the vendor's answer -> canonical (`assistant_content` is what a caller appends as the assistant turn of its tool loop, so a
conversation can move from one engine to another between two calls). Features a vendor lacks are DEGRADED by rule, never errored:

    documents    a vendor without document blocks gets the text, extracted by code (pypdf for a PDF, with page numbers kept as "[page N]")
    images       sent as data URLs when the vendor takes images, else left out and the result says so in `warnings`
    thinking     the one scale low / medium / high / max is mapped by `[engines.<name>.effort]`; a vendor or model without that control ignores it (the engine's page says so)
    tokens       no count endpoint: an estimate (labelled in the result's warnings), priced at the worst case by the governor like every other call
    caching      automatic at the vendor: nothing is marked; the cached tokens come back and are priced at the vendor's cached rate

The SDK itself is made in `llm/vendors.py`; the egress gate, the price, the governor and the record are `hq/llm.call`'s, unchanged (it takes this class as its `adapter`).
Sources (read 2026-11-13): developers.openai.com/api/docs/models and /pricing, /guides/reasoning, /api/reference/resources/responses (field names). gpt-6 models: function calling needs the Responses API.
"""
from __future__ import annotations

import base64
import copy
import json
import threading
from typing import Any, Dict, List, Optional, Tuple

_tl = threading.local()        # the warnings of the request being built (the door builds and sends in one thread)
DOC_CHARS = 400_000          # the most text one document may add to a request; longer text is cut with a line saying so (never silently)


def _blocks(content) -> List[dict]:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content if isinstance(b, dict)]


def _system_text(system) -> str:
    if not system:
        return ""
    if isinstance(system, str):
        return system
    return "\n\n".join(b.get("text", "") for b in system if isinstance(b, dict) and b.get("type", "text") == "text")


def pdf_text(data_b64: str, limit: int = DOC_CHARS) -> str:
    """Text of a base64 PDF by code, page numbers kept (`[page N]`). A scanned page without text says so, so nobody mistakes silence for an empty page."""
    from io import BytesIO

    from pypdf import PdfReader
    rd = PdfReader(BytesIO(base64.b64decode(data_b64)))
    out, used = [], 0
    for n, pg in enumerate(rd.pages, 1):
        t = (pg.extract_text() or "").strip() or "(no text on this page: scanned or an image)"
        part = f"[page {n}]\n{t}"
        if used + len(part) > limit:
            out.append(f"[the document continues from page {n}: cut here at {limit:,} characters]")
            break
        out.append(part)
        used += len(part)
    return "\n\n".join(out)


def document_text(block: dict) -> str:
    """The text a document block stands for, for a vendor without document blocks."""
    src = block.get("source") or {}
    title = block.get("title") or ""
    if src.get("type") == "text":
        body = str(src.get("data") or "")
    elif src.get("type") == "base64" and "pdf" in str(src.get("media_type", "")):
        body = pdf_text(src.get("data") or "")
    elif src.get("type") == "base64":
        body = base64.b64decode(src.get("data") or "").decode("utf-8", "replace")
    else:
        body = "(a document this vendor cannot be given)"
    if len(body) > DOC_CHARS:
        body = body[:DOC_CHARS] + f"\n[cut at {DOC_CHARS:,} characters]"
    return f"[Document: {title}]\n{body}" if title else f"[Document]\n{body}"


def _image_url(block: dict) -> Optional[str]:
    src = block.get("source") or {}
    if src.get("type") == "base64":
        return f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}"
    if src.get("type") == "url":
        return src.get("url")
    return None


def _tool_result_text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in (content or []) if isinstance(b, dict) and b.get("type") == "text")


class OpenAICompatEngine:
    """Provider `openai_compat`: `features.wire` = "responses" (OpenAI) or "chat" (Chat Completions, the format other vendors offer)."""
    name = "openai_compat"

    # --- request ------------------------------------------------------------------------------------------------------------------------
    def effort(self, level: str, st: dict, engine: str = "openai") -> str:
        table = ((st.get(engine) or {}).get("effort")) or {}
        return str(table.get(level, level))

    def wire(self, econf: dict) -> str:
        return str(((econf or {}).get("features") or {}).get("wire", "responses"))

    def params(self, spec: dict, st: dict, system, messages: list, tools: Optional[list], max_tokens: int, schema: Optional[dict], tool_choice: Optional[str], *, web: bool = False) -> dict:
        econf = st.get(spec["engine"]) or {}
        feats = {**(econf.get("features") or {})}
        wire = self.wire(econf)
        warnings: List[str] = []
        n_out = max(int(max_tokens), int(spec["min_tokens"]))
        sys_text = _system_text(system)
        tool_defs = [t for t in (tools or []) if not str(t.get("type", "")).startswith("web_search")]
        if len(tool_defs) != len(tools or []):
            warnings.append("a web search tool was left out: this engine has no web tool")
        use_effort = bool(feats.get("thinking_effort", True)) and spec["thinking"]
        eff = self.effort(spec["thinking"], st, spec["engine"]) if use_effort else None
        if wire == "chat":
            msgs, ws = self._chat_messages(sys_text, messages, feats)
            p: Dict[str, Any] = {"model": spec["model"], feats.get("max_tokens_param", "max_completion_tokens"): n_out, "messages": msgs}
            if eff:
                p["reasoning_effort"] = eff
            if tool_defs:
                p["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t.get("input_schema") or {"type": "object", "properties": {}}}} for t in tool_defs]
                if tool_choice == "none":
                    p["tool_choice"] = "none"
            if schema:
                p["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema, "strict": False}}
        else:
            items, ws = self._response_items(messages, feats)
            p = {"model": spec["model"], "input": items, "max_output_tokens": n_out, "store": False}
            if sys_text:
                p["instructions"] = sys_text
            if eff:
                p["reasoning"] = {"effort": eff}
            if tool_defs:
                p["tools"] = [{"type": "function", "name": t["name"], "description": t.get("description", ""), "parameters": t.get("input_schema") or {"type": "object", "properties": {}}, "strict": False}
                              for t in tool_defs]
                if tool_choice == "none":
                    p["tool_choice"] = "none"
            if schema:
                p["text"] = {"format": {"type": "json_schema", "name": "answer", "schema": schema, "strict": False}}
        warnings += ws
        if not use_effort:
            warnings.append("this model has no thinking control: the thinking level is ignored")
        _tl.warnings = warnings
        return p

    def _user_parts(self, blocks: List[dict], feats: dict, kind: str) -> Tuple[List[dict], List[str]]:
        """Content parts for a user turn (text, images, documents as text). `kind` is 'responses' or 'chat'."""
        parts: List[dict] = []
        warns: List[str] = []
        for b in blocks:
            t = b.get("type")
            if t == "text":
                parts.append({"type": "input_text" if kind == "responses" else "text", "text": b.get("text", "")})
            elif t == "document":
                parts.append({"type": "input_text" if kind == "responses" else "text", "text": document_text(b)})
            elif t == "image":
                url = _image_url(b)
                if url and feats.get("images", True):
                    parts.append({"type": "input_image", "image_url": url} if kind == "responses" else {"type": "image_url", "image_url": {"url": url}})
                else:
                    warns.append("an image was left out: this engine takes no images")
        return parts, warns

    def _response_items(self, messages: list, feats: dict) -> Tuple[List[dict], List[str]]:
        items: List[dict] = []
        warns: List[str] = []
        for m in messages:
            role = m.get("role")
            blocks = _blocks(m.get("content"))
            if role == "system":
                items.append({"role": "developer", "content": "\n".join(b.get("text", "") for b in blocks)})
            elif role == "assistant":
                text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
                if text.strip():
                    items.append({"role": "assistant", "content": text})
                for b in blocks:
                    if b.get("type") == "tool_use":
                        items.append({"type": "function_call", "call_id": b["id"], "name": b["name"], "arguments": json.dumps(b.get("input") or {})})
            else:
                results = [b for b in blocks if b.get("type") == "tool_result"]
                for b in results:
                    out = _tool_result_text(b.get("content"))
                    items.append({"type": "function_call_output", "call_id": b["tool_use_id"], "output": ("ERROR: " if b.get("is_error") else "") + out})
                rest = [b for b in blocks if b.get("type") != "tool_result"]
                parts, w = self._user_parts(rest, feats, "responses")
                warns += w
                if parts:
                    items.append({"role": "user", "content": parts})
        return items, warns

    def _chat_messages(self, sys_text: str, messages: list, feats: dict) -> Tuple[List[dict], List[str]]:
        out: List[dict] = [{"role": "system", "content": sys_text}] if sys_text else []
        warns: List[str] = []
        for m in messages:
            role = m.get("role")
            blocks = _blocks(m.get("content"))
            if role == "system":
                out.append({"role": "system", "content": "\n".join(b.get("text", "") for b in blocks)})
            elif role == "assistant":
                text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
                calls = [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})}} for b in blocks if b.get("type") == "tool_use"]
                msg: Dict[str, Any] = {"role": "assistant", "content": text or None}
                if calls:
                    msg["tool_calls"] = calls
                out.append(msg)
            else:
                for b in [b for b in blocks if b.get("type") == "tool_result"]:
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": ("ERROR: " if b.get("is_error") else "") + _tool_result_text(b.get("content"))})
                parts, w = self._user_parts([b for b in blocks if b.get("type") != "tool_result"], feats, "chat")
                warns += w
                if parts:
                    out.append({"role": "user", "content": parts if len(parts) > 1 or parts[0]["type"] != "text" else parts[0]["text"]})
        return out, warns

    # --- the client and the transport (the adapter `hq/llm.call` takes) ---------------------------------------------------------------------
    def make_client(self, econf: Optional[dict] = None):
        from pflab import guard
        guard.require("paid")                                   # the workshop makes no paid call unless run with --paid
        from pflab.llm import vendors
        from pflab.pm import secrets as sec
        try:
            secrets = sec.load()
        except Exception:
            secrets = None
        econf = econf or {}
        return vendors.openai_client(secrets, str(econf.get("key_name") or "openai.api_key"), base_url=econf.get("base_url") or None, timeout=float(econf.get("timeout_s", 120)),
                                     max_retries=int(econf.get("max_retries", 1)))

    def count_tokens(self, client, params: dict) -> Tuple[int, bool]:
        """No count call: an estimate at about three characters a token (images 1,500 each), the safe side for pricing. Labelled in the call's warnings."""
        def strip(x):
            if isinstance(x, dict):
                if x.get("type") in ("input_image", "image_url"):
                    return {"type": "image", "n": "[image]"}
                return {k: strip(v) for k, v in x.items()}
            if isinstance(x, list):
                return [strip(v) for v in x]
            return x
        body = json.dumps(strip(params), default=str, ensure_ascii=False)
        images = body.count('"[image]"')
        return int(len(body) / 3.0) + 1500 * images + 50, True

    def create(self, client, params: dict):
        if "input" in params:
            return client.responses.create(**params)
        return client.chat.completions.create(**params)

    def usage(self, msg) -> Tuple[int, int, int, int]:
        """(input tokens not cached, output tokens, cache reads, cache writes): the vendor counts cached tokens inside its input figure."""
        u = getattr(msg, "usage", None)
        if u is None:
            return 0, 0, 0, 0
        total_in = int(getattr(u, "input_tokens", None) if getattr(u, "input_tokens", None) is not None else (getattr(u, "prompt_tokens", 0) or 0))
        out = int(getattr(u, "output_tokens", None) if getattr(u, "output_tokens", None) is not None else (getattr(u, "completion_tokens", 0) or 0))
        det = getattr(u, "input_tokens_details", None) or getattr(u, "prompt_tokens_details", None)
        cached = int(getattr(det, "cached_tokens", 0) or 0) if det is not None else 0
        return max(0, total_in - cached), out, cached, 0

    def refused(self, msg) -> bool:
        for it in (getattr(msg, "output", None) or []):
            for c in (getattr(it, "content", None) or []):
                if getattr(c, "type", "") == "refusal":
                    return True
        for ch in (getattr(msg, "choices", None) or []):
            if getattr(getattr(ch, "message", None), "refusal", None) or getattr(ch, "finish_reason", "") == "content_filter":
                return True
        return False

    def send(self, con, *, agent: str, params: dict, client, now, mode: str, private_text: str, gate, topic: str, question: str, cfg: Optional[dict], approved: bool, turn: int,
             his_order: bool = False, extra_in: int = 0):
        from pflab.hq import llm
        sent = llm.call(con, agent, params, client, now=now, mode=mode, private_text=private_text, gate=gate, doc_kinds=("portfolio",), topic=topic, question=question, cfg=cfg,
                        approved=approved, turn=turn, extra_in=extra_in, his_order=his_order, egress_skip=("address_word",), adapter=self)
        for w in getattr(_tl, "warnings", []):
            sent.warnings.append(w)
        return sent

    # --- answer ---------------------------------------------------------------------------------------------------------------------------
    def read(self, sent) -> dict:
        msg = sent.message
        text_parts: List[str] = []
        calls: List[dict] = []
        content: List[dict] = []
        stop = "end_turn"
        if getattr(msg, "output", None) is not None:           # Responses
            for it in msg.output:
                t = getattr(it, "type", "")
                if t == "message":
                    for c in (getattr(it, "content", None) or []):
                        if getattr(c, "type", "") == "output_text":
                            text_parts.append(getattr(c, "text", "") or "")
                elif t == "function_call":
                    try:
                        args = json.loads(getattr(it, "arguments", "") or "{}")
                    except ValueError:
                        args = {}
                    calls.append({"id": getattr(it, "call_id", "") or getattr(it, "id", ""), "name": getattr(it, "name", ""), "input": args if isinstance(args, dict) else {}})
            if getattr(msg, "status", "completed") == "incomplete":
                stop = "max_tokens"
        else:                                                    # Chat Completions
            ch = (getattr(msg, "choices", None) or [None])[0]
            m = getattr(ch, "message", None)
            if m is not None:
                if getattr(m, "content", None):
                    text_parts.append(m.content if isinstance(m.content, str) else "".join(getattr(p, "text", "") for p in m.content))
                for tc in (getattr(m, "tool_calls", None) or []):
                    fn = getattr(tc, "function", None)
                    try:
                        args = json.loads(getattr(fn, "arguments", "") or "{}")
                    except ValueError:
                        args = {}
                    calls.append({"id": getattr(tc, "id", ""), "name": getattr(fn, "name", ""), "input": args if isinstance(args, dict) else {}})
            if getattr(ch, "finish_reason", "") == "length":
                stop = "max_tokens"
        text = "".join(text_parts).strip()
        if text:
            content.append({"type": "text", "text": text})
        content += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["input"]} for c in calls]
        if calls:
            stop = "tool_use"
        _, _, cached, _ = self.usage(msg)
        return {"text": text, "stop_reason": stop, "model": getattr(msg, "model", None), "tool_calls": calls, "assistant_content": content, "cached_tokens": cached, "cache_written_tokens": 0,
                "web_searches": 0, "text_blocks": [{"text": text, "citations": []}] if text else []}
