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


def suggestion_rules(con, model: str) -> List[dict]:
    out = []
    rows = con.execute("SELECT kind, outcome, answer FROM hq_suggestions WHERE model=? AND outcome IN ('good','bad')",
                       [model]).fetchall()
    for kind in sorted({r[0] for r in rows}):
        mine = [r for r in rows if r[0] == kind]
        n, k = len(mine), sum(r[1] == "good" for r in mine)
        if n < MIN_N:
            continue
        lo, hi = wilson(k, n)
        ev = {"good": k, "n": n, "wilson95": [round(lo, 3), round(hi, 3)]}
        if hi < 0.5:
            out.append(_p("lesson", f"suggest:{kind}", f"Your '{kind}' suggestions went well in {k} of {n} (95% range "
                          f"{lo:.0%}-{hi:.0%}, below even): make them only when the facts are strong, and say which.", ev, n,
                          "Wilson 95% upper bound under 50%", True))
        elif lo > 0.5:
            out.append(_p("lesson", f"suggest:{kind}", f"Your '{kind}' suggestions went well in {k} of {n} (95% range "
                          f"{lo:.0%}-{hi:.0%}, above even): the facts you used for them have worked so far.", ev, n,
                          "Wilson 95% lower bound over 50%", True))
    ans = con.execute("SELECT kind, answer FROM hq_suggestions WHERE model=? AND answer IN ('taken','declined')",
                      [model]).fetchall()
    for kind in sorted({r[0] for r in ans}):
        mine = [r for r in ans if r[0] == kind]
        n, d = len(mine), sum(r[1] == "declined" for r in mine)
        if n >= MIN_N and d / n >= 0.7:
            out.append(_p("lesson", f"declined:{kind}", f"The investor declined {d} of {n} of your '{kind}' suggestions: "
                          "make one only when it clearly matters to his portfolio.", {"declined": d, "n": n}, n,
                          "declined in at least 70% of 20 or more answers", True))
    return out


def prediction_rules(con, main: str, rival: str) -> List[dict]:
    def arr(m):
        r = con.execute("SELECT confidence, base_rate, outcome FROM hq_predictions WHERE model=? AND outcome IS NOT NULL "
                        "AND base_rate IS NOT NULL ORDER BY pred_id", [m]).fetchall()
        y = np.array([float(x[2]) for x in r])
        return (np.array([x[0] for x in r]) - y) ** 2, (np.array([x[1] for x in r]) - y) ** 2
    out = []
    bm, bb = arr(main)
    n = len(bm)
    if n >= MIN_N:
        pw = p_better(bb, bm)                                    # base rate's loss below the brain's
        ev = {"brier_brain": round(float(bm.mean()), 4), "brier_base": round(float(bb.mean()), 4), "n": n,
              "p_base_better": round(pw, 3)}
        if pw >= P_SURE:
            out.append(_p("lesson", "predictions", f"Your predictions scored worse than each stock's own base rate (Brier "
                          f"{bm.mean():.3f} against {bb.mean():.3f}, n {n}): predict only with a reason the base rate "
                          "does not already hold, and stay near it.", ev, n, "paired bootstrap P >= 0.9", True))
        elif pw <= 1 - P_SURE:
            out.append(_p("lesson", "predictions", f"Your predictions beat the base rate (Brier {bm.mean():.3f} against "
                          f"{bb.mean():.3f}, n {n}).", ev, n, "paired bootstrap P >= 0.9", True))
    rm, _ = arr(rival)
    if n >= MIN_N and len(rm) >= MIN_N:
        rng = np.random.default_rng(SEED)                        # different passes: an unpaired bootstrap
        p = float(np.mean(rng.choice(rm, (BOOT, len(rm))).mean(axis=1) < rng.choice(bm, (BOOT, n)).mean(axis=1)))
        if rm.mean() <= bm.mean() - 0.01 and p >= P_SURE:
            from pflab.hq import governor as gv
            cheaper = gv.PRICES.get(rival, (9, 9))[0] < gv.PRICES.get(main, (9, 9))[0]
            short = {gv.OPUS: "opus", gv.SONNET: "sonnet"}.get(rival, rival)
            out.append(_p("model", "brain", f"The brain's rival ({rival}) predicted better than the brain ({main}): Brier "
                          f"{rm.mean():.3f} against {bm.mean():.3f} (n {len(rm)} and {n}, P {p:.2f}). Make it the brain.",
                          {"brier_rival": round(float(rm.mean()), 4), "brier_brain": round(float(bm.mean()), 4),
                           "n_rival": len(rm), "n_brain": n, "p": round(p, 3), "cheaper": cheaper}, min(n, len(rm)),
                          "rival's Brier lower by 0.01 or more, bootstrap P >= 0.9, 20 or more each", True, short,
                          "live" if cheaper else "investor"))
    return out


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
    from pflab.hq import brain, tools as tl
    out = []
    marks = brain.marks(con)
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
    from pflab.hq import brain, keeper
    notes = [p for p in brain.journal(con, 40) if p["model"] == model and p["status"] == "done"][:10]
    errs = con.execute("SELECT tool, count(*) FROM hq_tool_calls WHERE status='error' AND called_at >= ? GROUP BY tool",
                       [now - timedelta(days=30)]).fetchall()
    m = brain.marks(con)
    return "\n".join([keeper.scorecard_text(con, model),
                      f"MARKS by the investor: {sum(m.values())} mattered, {len(m) - sum(m.values())} did not",
                      "TOOL ERRORS (30 days): " + (", ".join(f"{t} {n}" for t, n in errs) or "none"),
                      live.brain_text(con), "RECENT NOTES:"] + [f"- {str(p['at'])[:10]} {p['trigger']}: {(p['note'] or '')[:300]}"
                                                                 for p in notes])


def instruction_rules(con, model: str, now: datetime, draft) -> List[dict]:
    """Worded by a model (the learner_proposals job); each goes to the investor. None without MIN_PASSES new passes."""
    from pflab.hq import brain
    since = con.execute("SELECT max(made_at) FROM learn_proposals WHERE kind='instruction'").fetchone()[0] or datetime(2000, 1, 1)
    n = con.execute("SELECT count(*) FROM hq_passes WHERE role='brain' AND status='done' AND passed_at >= ?", [since]).fetchone()[0]
    if n < MIN_PASSES or draft is None:
        return []
    rec = record_text(con, model, now)
    out = draft(PROPOSE_SYSTEM, f"CURRENT INSTRUCTIONS:\n{brain.SYSTEM}\n\nRECORD:\n{rec}", PROPOSE_SCHEMA)
    res = []
    for c in (out.get("changes") or [])[:2]:
        ins = str(c.get("instruction", "")).strip()
        if not ins or re.search(r"\b(trade|buy now|sell now|order|transfer|target|limit|cap)\b", ins, re.I):
            continue                                             # never a trade, money, a target or a limit
        res.append(_p("instruction", "brain", ins[:500], {"evidence": str(c.get("evidence", ""))[:600],
                                                          "why": str(c.get("why", ""))[:400]}, int(c.get("n") or 0),
                      "worded by a model from the record: needs the investor's yes", True, None, "investor"))
    return res


# --- proposals kept, applied, asked --------------------------------------------------------------------------------------

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
    from pflab.hq import brain
    from pflab.pm.store import next_id
    main, rival = brain.pair()
    props = suggestion_rules(con, main) + prediction_rules(con, main, rival) + tool_rules(con, now) + limit_rules(con, now)
    props = [p for p in props if not (p["kind"] == "model" and _settings_chose("brain"))]
    model_props = instruction_rules(con, main, now, draft) if why == "weekly" else []
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
