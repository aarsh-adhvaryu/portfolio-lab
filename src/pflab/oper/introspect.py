"""S87 O3/O5: the weekly introspection, run by the first desk pass after the weekly close (Friday 15:30 IST). The model READS the facts code gathers (the scorecard after tax against doing nothing, the
calibration of the likelihood words, the picks' scores) and writes what worked, what did not, how the words held up and what to test next. It goes to the strategist's note (the next session's memory)
and to a table the operator's monthly review reads. A new idea is only a CANDIDATE: it becomes a registered study in the lab, never a live change (rule 10). Thresholds are tuned only after 40 scored
decisions or 60 misses (the learner's rule, unchanged)."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Optional

from pflab.llm import claude_plan as cp
from pflab.llm import gateway as gw

DDL = """CREATE TABLE IF NOT EXISTS operator_weekly_s87 (week_key DATE PRIMARY KEY, written_at TIMESTAMP NOT NULL, note_id INTEGER, worked VARCHAR, not_worked VARCHAR, calibration VARCHAR,
         candidates_json VARCHAR, tokens INTEGER)"""
SCHEMA = {"type": "object", "properties": {"worked": {"type": "array", "items": {"type": "string"}, "maxItems": 5}, "not_worked": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                                          "calibration": {"type": "string"}, "learned": {"type": "string"},
                                          "test_next": {"type": "array", "maxItems": 3, "items": {"type": "object", "properties": {"idea": {"type": "string"}, "why": {"type": "string"}}, "required": ["idea", "why"]}}},
          "required": ["worked", "not_worked", "calibration", "learned", "test_next"]}
SYSTEM = ("You are the weekly introspection of a paper portfolio that tries to beat the index after tax. You are given FACTS from code: the scored decisions, the likelihood words' calibration and the "
          "picks' scores. Say what worked, what did not, how the likelihood words held up, what you learned and at most three things to TEST next (each a candidate study, never a live change). "
          "Every number must be in the facts; if the facts are thin (few scored decisions), say that and do not draw conclusions. Plain words, short.")


def week_key(now: datetime) -> Optional[date]:
    """The most recent Friday whose Indian close (15:30) has passed, as of `now`; None before the first one."""
    d = now.date()
    back = (d.weekday() - 4) % 7
    fri = d - timedelta(days=back)
    if back == 0 and now.time() < time(15, 45):
        fri -= timedelta(days=7)
    return fri


def due(con, now: datetime) -> bool:
    con.execute(DDL)
    k = week_key(now)
    return bool(k) and con.execute("SELECT 1 FROM operator_weekly_s87 WHERE week_key=?", [k]).fetchone() is None


def facts(con, now: datetime) -> str:
    from pflab.think import score
    out = {"decision_track": None, "calibration": None, "picks_IN": None, "picks_US": None}
    try:
        out["decision_track"] = score.scorecard(con)
    except Exception as e:
        out["decision_track"] = f"unavailable ({type(e).__name__})"
    try:
        out["calibration"] = [dict(zip(("word", "probability", "updated_on"), (r[0], r[1], str(r[2])))) for r in con.execute("SELECT word, probability, updated_on FROM think_calibration_s84").fetchall()]
    except Exception:
        pass
    try:
        from pflab.core import pick_score
        out["picks_IN"], out["picks_US"] = pick_score.scorecard_text(con, "IN")[:1500], pick_score.scorecard_text(con, "US")[:1500]
    except Exception:
        pass
    return json.dumps(out, default=str, ensure_ascii=False)[:9000]


def run(con, now: datetime) -> dict:
    from pflab.agents import analyst as an
    from pflab.lab import service
    con.execute(DDL)
    k = week_key(now)
    if k is None or not due(con, now):
        return {"skipped": "already written for this week"}
    f = facts(con, now)
    spec = gw.resolve("read", engine="claude_plan")
    try:
        res = cp.run(con, prompt=f"FACTS (from code, dated {now:%Y-%m-%d}):\n{f}", system=SYSTEM, model=spec["model"], effort=spec["thinking"], klass="desk", purpose="desk_weekly", agent="desk", now=now,
                     tools=[], schema=SCHEMA, max_turns=3, timeout=600)
    except (cp.PlanPaused, cp.PlanBudgetSpent, cp.PlanUnusable) as e:
        return {"waits": str(e)[:200]}
    o = res.structured if isinstance(res.structured, dict) else {}
    if not o:
        return {"failed": "no structured answer"}

    def clean(t: str) -> str:
        c, _ = an.only_sourced_numbers(str(t), an.Request(f, "assistant"))
        return c
    worked, nw = [clean(x) for x in o.get("worked", [])], [clean(x) for x in o.get("not_worked", [])]
    cal, learned = clean(o.get("calibration", "")), clean(o.get("learned", ""))
    cands = [{"idea": str(c.get("idea", ""))[:200], "why": str(c.get("why", ""))[:300], "status": "candidate"} for c in o.get("test_next", [])][:3]
    text = f"Weekly introspection ({k}). Worked: {'; '.join(worked) or 'nothing yet'}. Did not: {'; '.join(nw) or 'nothing yet'}. Words: {cal}. To test next (candidates, not live): " + "; ".join(c["idea"] for c in cands)
    w = service.write_note(con, now, None, text, learned=learned or None)
    con.execute("INSERT INTO operator_weekly_s87 VALUES (?,?,?,?,?,?,?,?)", [k, now, w.get("note_id"), json.dumps(worked), json.dumps(nw), cal, json.dumps(cands), res.input_tokens + res.output_tokens])
    return {"week": str(k), "note_id": w.get("note_id"), "candidates": len(cands), "tokens": res.input_tokens + res.output_tokens}
