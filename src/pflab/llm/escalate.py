"""S79b item 17: local first, the cloud only when the local answers do not settle it. (Not `agents/escalate.py`, which routes a question local -> agents -> Opus.)

The rule, for a JUDGMENT call (a verdict, a classification the system will act on):

    1. ask the local model `samples` times (default 3; each call gets its index, so a caller can vary the seed or the sampling)
    2. the valid answers all agree and the confidence is not low  ->  rule "agree": accept the local answer, no cloud
    3. they disagree                                              ->  rule "disagree": cloud
       they agree but the confidence is under `min_confidence`    ->  rule "low_confidence": cloud
       fewer than `min_valid` samples came back valid             ->  rule "local_unavailable": cloud
    4. the cloud is used only if `cap_ok()` says the caps allow it; with the cap used up, or no cloud function, or a failing one, the plurality local answer is
       returned and `outcome` says it was degraded, never silently

Which rule fired, how many samples and what it cost are kept in `escalation_log_s79` when a store connection is passed. The cloud function is injected (it is the
caller's doorbell, inside the caps; this module never imports the API client and never spends money by itself). Nothing here makes a number: the answers are the callers'.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any, Callable, List, Optional


def canon(x: Any) -> str:
    """A key for 'the same answer': JSON with sorted keys; strings compared trimmed and case-folded."""
    if isinstance(x, str):
        return json.dumps(x.strip().lower())
    try:
        return json.dumps(x, sort_keys=True, default=str)
    except Exception:
        return repr(x)


def all_equal(answers: List[Any]) -> bool:
    return len({canon(a) for a in answers}) <= 1


def plurality(answers: List[Any]) -> Any:
    if not answers:
        return None
    c = Counter(canon(a) for a in answers)
    top = c.most_common(1)[0][0]
    return next(a for a in answers if canon(a) == top)


def _cap(cap_ok: Optional[Callable]) -> tuple:
    if cap_ok is None:
        return True, ""
    try:
        r = cap_ok()
    except Exception as e:                                   # a cap check that fails is a closed door
        return False, f"cap check failed: {type(e).__name__}"
    if isinstance(r, tuple):
        return bool(r[0]), str(r[1]) if len(r) > 1 else ""
    return bool(r), ""


def decide(local: Callable[[int], Any], *, samples: int = 3, agree_fn: Optional[Callable[[List[Any]], bool]] = None,
           confidence_fn: Optional[Callable[[Any], Optional[float]]] = None, cloud_fn: Optional[Callable[[List[Any], str], Any]] = None,
           cap_ok: Optional[Callable[[], Any]] = None, min_confidence: float = 0.6, min_valid: int = 2, con=None, market: str = "IN", kind: str = "",
           subject: str = "", now: Optional[datetime] = None, seat: str = "fast") -> dict:
    """Run the escalation rule. `local(i)`: one local sample (raise or return None for a failed one). `agree_fn(valid_answers) -> bool` (default: all equal after
    canonical form). `confidence_fn(answer) -> 0..1 or None` (None: no confidence rule). `cloud_fn(valid_answers, rule) -> answer or {"answer": ..., "cost_rupees": ...}`.
    `cap_ok() -> bool or (bool, why)`. Returns {answer, rule, outcome, samples, n_valid, agreed, confidence, cloud_used, cost_rupees, note}."""
    n = max(1, int(samples))
    answers: List[Any] = []
    errors = 0
    for i in range(n):
        try:
            a = local(i)
        except Exception:
            a, errors = None, errors + 1
        answers.append(a)
    valid = [a for a in answers if a is not None]
    need = min(max(1, int(min_valid)), n)
    agreed: Optional[bool] = None
    conf: Optional[float] = None
    if len(valid) < need:
        rule = "local_unavailable"
    else:
        agreed = bool(agree_fn(valid)) if agree_fn else all_equal(valid)
        if confidence_fn:
            cs = []
            for a in valid:
                try:
                    c = confidence_fn(a)
                except Exception:
                    c = None
                if c is not None:
                    cs.append(float(c))
            conf = sum(cs) / len(cs) if cs else None
        if not agreed:
            rule = "disagree"
        elif conf is not None and conf < float(min_confidence):
            rule = "low_confidence"
        else:
            rule = "agree"
    out = {"answer": None, "rule": rule, "outcome": "", "samples": answers, "n_valid": len(valid), "agreed": agreed, "confidence": conf, "cloud_used": False,
           "cost_rupees": 0.0, "note": f"{errors} local call(s) failed" if errors else "", "cap_ok": None}
    local_answer = plurality(valid)
    if rule == "agree":
        out.update(answer=local_answer, outcome="accepted_local")
    else:
        ok, why = _cap(cap_ok)
        out["cap_ok"] = ok
        if cloud_fn is None:
            out.update(answer=local_answer, outcome="no_cloud_local", note=(out["note"] + "; no cloud function").strip("; "))
        elif not ok:
            out.update(answer=local_answer, outcome="cap_exhausted_local", note=(out["note"] + "; " + (why or "the cloud caps are used up")).strip("; "))
        else:
            try:
                r = cloud_fn(valid, rule)
                if isinstance(r, dict) and "answer" in r:
                    out.update(answer=r["answer"], cost_rupees=float(r.get("cost_rupees") or 0.0))
                else:
                    out["answer"] = r
                out.update(cloud_used=True, outcome="cloud")
            except Exception as e:                           # the cloud failing must not lose the local answer
                out.update(answer=local_answer, outcome="cloud_failed_local", note=(out["note"] + f"; cloud failed: {type(e).__name__}: {str(e)[:120]}").strip("; "))
    if con is not None:
        try:
            log(con, market, now or datetime.now(), kind, subject, out, seat)
        except Exception:                                    # keeping the record must never lose the answer
            pass
    return out


def log(con, market: str, now: datetime, kind: str, subject: str, res: dict, seat: str = "fast") -> int:
    from pflab.pm.store import next_id
    eid = next_id(con, "escalation_log_s79", "esc_id")
    ans = res.get("answer")
    try:
        txt = json.dumps(ans, default=str)[:1000]
    except Exception:
        txt = str(ans)[:1000]
    con.execute("INSERT INTO escalation_log_s79 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [eid, market, now, kind, subject[:200], res["rule"], len(res["samples"]), res["n_valid"], res["agreed"], res["confidence"], bool(res["cloud_used"]),
                 res.get("cap_ok"), float(res.get("cost_rupees") or 0.0), txt, seat, (res.get("outcome", "") + (": " + res["note"] if res.get("note") else ""))[:300]])
    return eid


def summary(con, market: str = "IN", since: Optional[datetime] = None) -> dict:
    """Counts by rule and outcome (for the cost screen): how often local settled it, how often the cloud was needed, how often the cap stopped it."""
    q = "SELECT rule, count(*), sum(CASE WHEN cloud_used THEN 1 ELSE 0 END), coalesce(sum(cost_rupees),0) FROM escalation_log_s79 WHERE market=?"
    args: list = [market]
    if since is not None:
        q += " AND created_at >= ?"
        args.append(since)
    rows = con.execute(q + " GROUP BY rule", args).fetchall()
    return {"by_rule": {r: {"n": int(n), "cloud": int(c or 0), "rupees": round(float(s), 2)} for r, n, c, s in rows}, "n": sum(int(n) for _, n, _, _ in rows)}
