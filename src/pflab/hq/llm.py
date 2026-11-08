"""The one road to the API for HQ agents (S59): gate, price, govern, log, send, record the real cost.

    1 egress    `egress.check` on the text built from the investor's data or written by him; documents by provenance
    2 price     count_tokens for the input, max_tokens for the output (the worst case), no cache credit assumed
    3 govern    `governor.check`: tokens, passes, the layer's day and month, the system cap; refused -> `over_limit`
    4 send      Opus and Sonnet with the server-side fallback; Haiku plainly (it has none)
    5 record    the real cost from the usage (cache reads and writes priced), the agent on the row

Only this module and `agents/analyst.py` talk to the API. Tests pass a fake client.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from pflab.agents import analyst as an
from pflab.hq import egress, governor as gv


@dataclass
class Sent:
    message: Any
    call_id: int
    cost_inr: float
    warnings: List[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return text_of(self.message)

    def json(self) -> dict:
        return json_of(self.text)


def text_of(message) -> str:
    return "".join(getattr(b, "text", "") or "" for b in message.content if getattr(b, "type", "") == "text").strip()


def json_of(text: str) -> dict:
    """Structured output is JSON already; a stray fence or preamble is tolerated, nothing else."""
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else {}


def _strip_images(x):
    """A copy with every image's base64 data replaced by its size (S78: a chart the model looked at is not text to scan, and its bytes do not belong in the request log)."""
    if isinstance(x, dict):
        if x.get("type") == "image" and isinstance(x.get("source"), dict) and "data" in x["source"]:
            return {"type": "image", "source": {"type": "base64", "media_type": x["source"].get("media_type"), "omitted_chars": len(x["source"]["data"])}}
        return {k: _strip_images(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_strip_images(v) for v in x]
    return x


def body_check(params: Dict[str, Any], gate: egress.Gate) -> None:
    """S62: the whole request as it will be sent (system prompt, earlier turns, the model's own words) carries neither
    his name nor a long account id. The security agent's first look back found both: a system prompt that named him,
    and the brain repeating his name from its own tool names. Short ids are left to the text check above (a filing's
    numbers would match them)."""
    from pflab.hq import security
    body = json.dumps(_strip_images(params), default=str, ensure_ascii=False)
    long_ids = egress.Gate(ids={i for i in gate.ids if len(i) >= 8}, names=gate.names)
    found = security.hits(body, long_ids, pan=False)
    if found:
        raise egress.EgressBlocked("not sent: the request carries " + ", ".join(found))


def _outgoing_text(p: Dict[str, Any]) -> str:
    """Every text block of the messages as they would be counted and sent."""
    out = []
    for m in p.get("messages") or []:
        c = m.get("content")
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, list):
            out += [b.get("text", "") for b in c if isinstance(b, dict)]
    return "\n".join(out)


def _count_kwargs(p: Dict[str, Any]) -> Dict[str, Any]:
    return {k: p[k] for k in ("model", "system", "messages", "tools", "thinking") if k in p}


def call(con, agent: str, params: Dict[str, Any], client, *, now: datetime, mode: str, private_text: str,
         gate: egress.Gate, doc_kinds: Sequence[str] = (), topic: str = "", question: str = "",
         cfg: Optional[dict] = None, approved: bool = False, turn: int = 1, extra_in: int = 0, his_order: bool = False,
         egress_skip: Sequence[str] = ()) -> Sent:
    """Raises egress.EgressBlocked, governor.BudgetRefused (logged as over_limit) or analyst.NeedsApproval. `extra_in`:
    input the count cannot see (a page web fetch will read, at its cap), priced as the worst case."""
    cfg = cfg or an.config()
    egress.check(private_text, gate, doc_kinds, skip=egress_skip)
    if any(k in ("dataset", "email") for k in doc_kinds):  # (audit 2026-10-30) an upload is never sent on its kind alone
        egress.check(_outgoing_text(params), gate)
    body_check(params, gate)
    model = params["model"]
    n_in = int(client.messages.count_tokens(**_count_kwargs(params)).input_tokens) + int(extra_in)
    est = gv.cost_inr(model, n_in, int(params["max_tokens"]), cfg["usd_inr"])
    from pflab.pm.store import next_id
    body = json.dumps(_strip_images(params), sort_keys=True, default=str)
    policy = "acceptance" if an.acceptance(cfg, now) else "normal"
    with an.ADMIT:                                           # S69: parallel workers: the check and the reserving row (counted at its estimate) are one step
        try:
            warn = gv.check(con, agent, est, n_in, int(params["max_tokens"]), now, mode, cfg, approved, turn, his_order=his_order)
        except gv.BudgetRefused as e:
            gv.log_refusal(con, agent, model, topic, question or topic, str(e), now)
            raise
        cid = next_id(con, "api_calls", "call_id")
        con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, topic, question, request_sha, request_json, "
                    "status, cost_inr, agent, turn, policy, his_order, task_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [cid, now, "live", model, topic, (question or topic)[:2000], hashlib.sha256(body.encode()).hexdigest(),
                     body, "sending", est, agent, turn, policy, bool(his_order), an.CURRENT_TASK.get()])
    try:
        if model == gv.HAIKU:
            msg = client.messages.create(**params)
        else:
            msg = client.beta.messages.create(**params, betas=[an.FALLBACK_BETA], fallbacks="default")
    except Exception as e:                                   # recorded on the row, then raised to the agent
        con.execute("UPDATE api_calls SET status='failed', cost_inr=0, error=?, finished_at=? WHERE call_id=?",
                    [f"{type(e).__name__}: {str(e)[:400]}", now, cid])
        raise
    u = msg.usage
    it, ot = int(getattr(u, "input_tokens", 0) or 0), int(getattr(u, "output_tokens", 0) or 0)
    cr, cw = int(getattr(u, "cache_read_input_tokens", 0) or 0), int(getattr(u, "cache_creation_input_tokens", 0) or 0)
    inr = gv.cost_inr(getattr(msg, "model", model) if getattr(msg, "model", None) in gv.PRICES else model, it, ot,
                      cfg["usd_inr"], cr, cw)
    status = "refused" if getattr(msg, "stop_reason", "") == "refusal" else "done"
    con.execute("UPDATE api_calls SET status=?, input_tokens=?, output_tokens=?, cost_usd=?, cost_inr=?, finished_at=? "
                "WHERE call_id=?", [status, it + cr + cw, ot, inr / cfg["usd_inr"], inr, now, cid])
    if status == "refused":
        raise RuntimeError(f"{agent}: the model declined this request (call #{cid})")
    try:                                                     # S79b item 17: the teacher log (redacted input/output of every cloud call, for later distillation); never blocks a call
        from pflab.llm import teacher
        teacher.record_message(con, cid, params, msg, "hq", now, agent=agent, cost_inr=inr, gate=gate)
    except Exception:
        pass
    return Sent(msg, cid, inr, warn)


def client(secrets):
    """The SDK client, made the analyst's way (the key from secrets.toml, the workspace header)."""
    return an.make_client(secrets)
