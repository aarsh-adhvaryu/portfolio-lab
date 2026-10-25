"""Smoke test for a local model (PLAN S21). Criteria fixed before running: the model is installed in Ollama,
answers one fixed question with a non-empty reply within 180 seconds and reports output tokens. Whether the
reply also passes the numeric guard on the first try is recorded and printed, but is not part of "smoke
passes": that is the evaluation's job."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pflab.llm import client, guard
from pflab.llm import registry as reg

NAME = "smoke_v1"
FACTS = {"revenue_ttm": (5687490.0, "million"), "net_margin": 0.069}
PROMPT = ("Use ONLY these facts: revenue_ttm = 5,687,490 million rupees; net_margin = 6.9%. Write ONE sentence "
          "stating both, with numbers as digits, and end it with the citations [F:revenue_ttm] [F:net_margin]. "
          "Do not calculate anything.")
LIMIT_SECONDS = 180


def run(con, model: str, role: str = "smoke", transport=client.http_transport, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now()
    started = datetime.now()
    try:
        r = client.chat(model, [{"role": "user", "content": PROMPT}], transport=transport, timeout=LIMIT_SECONDS + 30)
    except client.OllamaError as e:
        reg.log_run(con, started, model, role=role, prompt_name=NAME, prompt_sha=reg.sha(PROMPT), status="failed", note=str(e)[:300])
        return {"model": model, "passed": False, "reason": str(e)}
    g = guard.check_all(r.text, FACTS, {})
    passed = bool(r.text.strip()) and r.tokens_out > 0 and r.seconds <= LIMIT_SECONDS
    rid = reg.log_run(con, started, r.model, role=role, model_digest=r.digest, prompt_name=NAME, prompt_sha=reg.sha(PROMPT),
                      guard_result="pass" if g.ok else "fail: " + "; ".join(f"{v.kind} {v.text}" for v in g.violations)[:200],
                      tokens_in=r.tokens_in, tokens_out=r.tokens_out, seconds=r.seconds, status="ok" if passed else "failed")
    return {"model": r.model, "digest": r.digest, "passed": passed, "seconds": r.seconds, "tokens_out": r.tokens_out,
            "tokens_per_second": round(r.tokens_out / r.seconds, 1) if r.seconds else None, "guard_first_try": g.ok,
            "reply": r.text.strip(), "run_id": rid}
