"""The learner's second input (S62, PLAN A22): the system's own record -> dated proposals, each with its evidence and n.

Weekly (Saturday, after the brain's reflection), or sooner when NEW_OUTCOMES outcomes were scored since the last run.
Rules in code; no conclusion under MIN_N (the small-numbers rule); nothing here retires a kind of suggestion.

    rule                      evidence                                         passes ->
    suggestion record         a kind's good rate, Wilson 95% interval, n>=20   a lesson (live at once)
    declined record           a kind he declined in >=70% of n>=20 answers     a lesson (live at once)
    prediction calibration    Brier against the base rate, paired bootstrap    a lesson (live at once)
    tool errors               a tool failing >=20% of n>=20 calls in 30 days   a lesson (live) and a fix for the investor
    his marks                 passes marked 'did not matter' >=60% of n>=20    a lower tell_investor limit: asked
    limits reached            an action held at its limit on >=8 of 30 days    a higher limit (at most double): asked
    brain model               rival's Brier lower by >=0.01, P>=0.9, n>=20     cheaper: applied (his Settings win);
                                                                               dearer: asked
    instructions (a model)    weekly, after >=5 passes: up to 2 changes worded asked (no code rule can pass free text)
                              from the record by the learner_proposals model
Asked = a question under Needs from you; his yes applies it, his no declines it. Money limits are never changed here.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np

from pflab.learner import live

MIN_N = 20
NEW_OUTCOMES = 20
DAY, AT = 5, (10, 0)                     # Saturday 10:00, after the reflection (9:00)
WILSON_Z = 1.96
BOOT, SEED = 2000, 7
P_SURE = 0.9


def wilson(k: int, n: int, z: float = WILSON_Z) -> tuple:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def p_better(a: np.ndarray, b: np.ndarray, boot: int = BOOT, seed: int = SEED) -> float:
    """Share of paired bootstrap draws in which the mean of `a` (a loss, e.g. Brier) is below `b`'s."""
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(a), (boot, len(a)))
    return float(np.mean(a[idx].mean(axis=1) < b[idx].mean(axis=1)))


# --- when ----------------------------------------------------------------------------------------------------------------

def last_run(con) -> Optional[datetime]:
    return con.execute("SELECT max(made_at) FROM learn_proposals WHERE kind='run'").fetchone()[0]


def new_outcomes(con, since: Optional[datetime]) -> int:
    since = since or datetime(2000, 1, 1)
    a = con.execute("SELECT count(*) FROM hq_suggestions WHERE scored_at >= ? AND outcome IN ('good','bad')", [since]).fetchone()[0]
    b = con.execute("SELECT count(*) FROM hq_predictions WHERE scored_at >= ? AND outcome IS NOT NULL", [since]).fetchone()[0]
    return int(a + b)


def due(con, now: datetime) -> Optional[str]:
    last = last_run(con)
    if new_outcomes(con, last) >= NEW_OUTCOMES:
        return "outcomes"
    if now.weekday() == DAY and (now.hour, now.minute) >= AT and (last is None or last.date() < now.date()):
        return "weekly"
    return None


# --- the rules -----------------------------------------------------------------------------------------------------------

def _p(kind: str, target: str, text: str, evidence: dict, n: int, rule: str, passed: bool, value: Optional[str] = None,
       to: str = "live") -> dict:
    return {"kind": kind, "target": target, "text": text, "evidence": evidence, "n": n, "rule": rule, "passed": passed,
            "value": value, "to": to}


def tool_rules(con, now: datetime) -> List[dict]:
    out = []
    rows = con.execute("SELECT tool, count(*), sum(CASE WHEN status='error' THEN 1 ELSE 0 END) FROM hq_tool_calls WHERE "
                       "called_at >= ? GROUP BY tool", [now - timedelta(days=30)]).fetchall()
    for tool, n, e in rows:
        if n >= MIN_N and e / n >= 0.2:
            ev = {"errors": int(e), "n": int(n), "days": 30}
            out.append(_p("lesson", f"tool:{tool}", f"The tool {tool} failed in {e} of {n} calls in 30 days: check its "
                          "result, and use another tool where one gives the same fact.", ev, n, "errors in 20% of 20+ calls", True))
            out.append(_p("fix", f"tool:{tool}", f"The brain's tool {tool} failed in {e} of {n} calls in 30 days; its code "
                          "needs a look (the errors are in hq_tool_calls).", ev, n, "errors in 20% of 20+ calls", True,
                          to="investor"))
    return out


def limit_rules(con, now: datetime) -> List[dict]:
    from pflab.hq import passes, tools as tl
    out = []
    marks = passes.marks(con)
    tells = {pid for (pid,) in con.execute("SELECT DISTINCT pass_id FROM hq_tool_calls WHERE tool='tell_investor' AND status='ran'").fetchall()}
    m = [v for pid, v in marks.items() if pid in tells]
    caps = {**tl.DAILY, **{k: int(v) for k, v in live.values(con, "daily_cap").items()}}
    if len(m) >= MIN_N and m.count(False) / len(m) >= 0.6 and caps["tell_investor"] > 1:
        out.append(_p("daily_cap", "tell_investor", f"You marked {m.count(False)} of {len(m)} passes that messaged you as "
                      f"'did not matter': lower the brain's messages from {caps['tell_investor']} to "
                      f"{caps['tell_investor'] - 1} a day.", {"did_not_matter": m.count(False), "n": len(m)}, len(m),
                      "60% or more of 20+ marked passes", True, str(caps["tell_investor"] - 1), "investor"))
    for tool, cap in caps.items():
        days = con.execute("SELECT count(DISTINCT CAST(called_at AS DATE)) FROM hq_tool_calls WHERE tool=? AND status='held' "
                           "AND called_at >= ?", [tool, now - timedelta(days=30)]).fetchone()[0]
        if days >= 8 and cap < 2 * tl.DAILY.get(tool, cap):
            out.append(_p("daily_cap", tool, f"The brain reached its limit of {cap} '{tool}' a day on {days} of the last 30 "
                          f"days: raise it to {cap + 1}.", {"days_at_limit": int(days), "of_days": 30}, int(days),
                          "held at the limit on 8 or more of 30 days; at most double the default", True, str(cap + 1),
                          "investor"))
    return out


# --- the model's part: instructions -------------------------------------------------------------------------------------

PROPOSE_SYSTEM = (
    "You improve how a portfolio system's brain works, from its own record. You see the brain's current instructions and "
    "a record built by code: its suggestions and predictions with outcomes and n, the investor's answers and marks, tool "
    "errors, and recent journal notes. Propose at most 2 changes to the brain's instructions, each a short instruction it "
    "would follow, with the evidence from the record (copy its numbers and n) and why. Rules: nothing may trade, move "
    "money, or change targets or limits; under 20 observations a pattern is a count, not a conclusion, so propose from "
    "those only if the change is cautious; one failure never retires a kind of suggestion. If nothing in the record calls "
    "for a change, return no changes. Reply with JSON only.")
PROPOSE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["changes"],
                  "properties": {"changes": {"type": "array", "items": {
                      "type": "object", "additionalProperties": False, "required": ["instruction", "evidence", "n", "why"],
                      "properties": {"instruction": {"type": "string"}, "evidence": {"type": "string"},
                                     "n": {"type": "integer"}, "why": {"type": "string"}}}}}}
MIN_PASSES = 5


def record_text(con, model: str, now: datetime) -> str:
    from pflab.hq import keeper, passes
    notes = [p for p in passes.journal(con, 40) if p["model"] == model and p["status"] == "done"][:10]
    errs = con.execute("SELECT tool, count(*) FROM hq_tool_calls WHERE status='error' AND called_at >= ? GROUP BY tool",
                       [now - timedelta(days=30)]).fetchall()
    m = passes.marks(con)
    return "\n".join([keeper.scorecard_text(con, model),
                      f"MARKS by the investor: {sum(m.values())} mattered, {len(m) - sum(m.values())} did not",
                      "TOOL ERRORS (30 days): " + (", ".join(f"{t} {n}" for t, n in errs) or "none"),
                      live.brain_text(con), "RECENT NOTES:"] + [f"- {str(p['at'])[:10]} {p['trigger']}: {(p['note'] or '')[:300]}"
                                                                 for p in notes])


def _same_pending(con, p: dict) -> bool:
    return bool(con.execute("SELECT 1 FROM learn_proposals WHERE kind=? AND coalesce(target,'')=? AND coalesce(value,'')=? "
                            "AND status IN ('to_investor','applied') AND text=?",
                            [p["kind"], p["target"] or "", p["value"] or "", p["text"]]).fetchone())


def keep(con, p: dict, now: datetime, by_model: Optional[str] = None) -> Optional[int]:
    """Store one proposal; apply it (live) or ask the investor. None when the same one is already live or asked."""
    from pflab.agents import questions as qs
    from pflab.pm.store import next_id
    if _same_pending(con, p):
        return None
    pid = next_id(con, "learn_proposals", "prop_id")
    status = "applied" if p["passed"] and p["to"] == "live" else "to_investor"
    con.execute("INSERT INTO learn_proposals (prop_id, made_at, kind, target, text, value, evidence_json, n, rule, passed, "
                "status, by_model) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [pid, now, p["kind"], p["target"], p["text"], p["value"], json.dumps(p["evidence"], default=str), p["n"],
                 p["rule"], p["passed"], status, by_model])
    if status == "applied":
        apply(con, pid, now)
    else:
        q = qs.ask(con, "learner", f"learner:prop:{pid}", f"Learner proposal #{pid} ({p['kind']}): {p['text']} "
                   f"Evidence: {json.dumps(p['evidence'], default=str)[:400]} (n {p['n']}; rule: {p['rule']}). "
                   + ("Answer 'seen' when noted." if p["kind"] == "fix" else "Answer yes to apply it, no to decline."), now)
        con.execute("UPDATE learn_proposals SET q_id=? WHERE prop_id=?", [q, pid])
    return pid


def apply(con, prop_id: int, now: datetime) -> None:
    kind, target, text, value = con.execute("SELECT kind, target, text, value FROM learn_proposals WHERE prop_id=?",
                                            [prop_id]).fetchone()
    if kind in ("lesson", "instruction"):
        live.put(con, kind, target if kind == "lesson" else f"proposal:{prop_id}", text, value, f"proposal #{prop_id}", now)
    elif kind == "daily_cap":
        live.put(con, "daily_cap", target, text, value, f"proposal #{prop_id}", now)
    elif kind == "model":
        from pflab.hq import models
        models.write_learned(target, value, text)
        live.put(con, "model", target, text, value, f"proposal #{prop_id}", now)
    con.execute("UPDATE learn_proposals SET status='applied', decided_at=? WHERE prop_id=?", [now, prop_id])


YES = re.compile(r"^\s*(yes|y|ok|okay|sure|apply|accept|go ahead|haan|ha)\b", re.I)


def answers(con, now: datetime) -> Dict[str, int]:
    """His answers to proposals: yes applies, anything else declines ('fix' notices close as seen)."""
    out = {"applied": 0, "declined": 0, "seen": 0}
    for pid, kind, ans in con.execute("SELECT p.prop_id, p.kind, q.answer FROM learn_proposals p JOIN questions q ON "
                                      "q.q_id = p.q_id WHERE p.status='to_investor' AND q.status='answered'").fetchall():
        if kind == "fix":
            con.execute("UPDATE learn_proposals SET status='seen', decided_at=? WHERE prop_id=?", [now, pid])
            out["seen"] += 1
        elif YES.search(ans or ""):
            apply(con, pid, now)
            out["applied"] += 1
        else:
            con.execute("UPDATE learn_proposals SET status='declined', decided_at=? WHERE prop_id=?", [now, pid])
            out["declined"] += 1
    return out


def run(con, now: datetime, draft=None, why: str = "weekly") -> dict:
    """One reading of the record: the code rules, then (weekly) the model's instruction changes."""
    from pflab.hq import passes
    from pflab.pm.store import next_id
    main, rival = passes.pair()
    props = tool_rules(con, now) + limit_rules(con, now)                      # S81: the suggestion and prediction rules went with the brain's passes
    props = [p for p in props if not (p["kind"] == "model" and _settings_chose("brain"))]
    model_props: List[dict] = []                      # S80 phase 4: the brain's instructions are cut, so the model proposes none
    kept = [k for p in props if (k := keep(con, p, now)) is not None]
    kept += [k for p in model_props if (k := keep(con, p, now, by_model="learner_proposals")) is not None]
    rid = next_id(con, "learn_proposals", "prop_id")
    con.execute("INSERT INTO learn_proposals (prop_id, made_at, kind, text, evidence_json, n, rule, passed, status) VALUES "
                "(?,?,?,?,?,?,?,?,?)", [rid, now, "run", f"record read ({why})",
                                        json.dumps({"proposals": kept, "rules_checked": len(props)}), new_outcomes(con, None),
                                        "the run itself", True, "done"])
    return {"proposals": len(kept), "applied": sum(1 for k in kept if con.execute(
        "SELECT status FROM learn_proposals WHERE prop_id=?", [k]).fetchone()[0] == "applied"), "why": why}


def _settings_chose(job: str) -> bool:
    try:
        from pflab.hq import models
        return job in models.valid(models._settings(None).get("models") or {})
    except Exception:
        return False
