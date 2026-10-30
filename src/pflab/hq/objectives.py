"""From a wish to an objective (S67 local). "Higher returns" is not something to test: it is turned into explicit objectives (a measure, a
number, a horizon, a comparator), the risk he would accept for them, at least two competing explanations of any opportunity with what
would support or refute each, and what evidence would change the recommendation. Code validates the frame; the brain (or the investor in
chat) supplies the content. A frame that stays vague is NOT stored as an objective: what is missing becomes one grouped question to him,
and nothing is tested or recommended against a goal he has not stated.

The protective limits are his and stay: the fall limit (`risk.montecarlo.FALL_LIMIT`, 35 percent) is the ceiling for any acceptable risk.
A frame asking for more is stored as a PROPOSAL waiting for his yes; it never changes the limit, and the objective is held at the limit
until he answers.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from pflab.risk import montecarlo

VAGUE = ("higher returns", "more returns", "better returns", "make more money", "grow faster", "beat the market")
MEASURES = ("annualised return net of tax", "total return net of tax", "income per year", "final amount at the horizon", "probability of reaching a target")


def fall_ceiling_pct() -> float:
    return abs(float(montecarlo.FALL_LIMIT)) * 100


def validate(frame: dict) -> dict:
    """{ok, problems, questions, proposals}. Pure: no store, no model."""
    problems, questions, proposals = [], [], []
    obj = frame.get("objectives") or []
    if not obj:
        problems.append("no objective: say what number, over what time, against what")
        questions.append("What would 'higher returns' have to mean in numbers for you: how much a year, over how many years, and compared with what (for example your FDs or the Nifty 50)?")
    for i, o in enumerate(obj, 1):
        if not isinstance(o, dict):
            problems.append(f"objective {i} is not a structured objective")
            continue
        if o.get("measure") not in MEASURES:
            problems.append(f"objective {i}: the measure must be one of {', '.join(MEASURES)}")
        if not isinstance(o.get("target"), (int, float)) or isinstance(o.get("target"), bool):
            problems.append(f"objective {i}: no number for the target")
            questions.append(f"For '{o.get('measure') or 'the objective'}': what number would count as enough?")
        if not isinstance(o.get("horizon_months"), int) or not 1 <= o["horizon_months"] <= 600:
            problems.append(f"objective {i}: no horizon in months")
            questions.append("Over how many months or years do you want this to happen?")
        if not str(o.get("comparator") or "").strip():
            problems.append(f"objective {i}: nothing to compare it with")
    risk = frame.get("acceptable_risk") or {}
    mf = risk.get("max_fall_pct")
    ceil = fall_ceiling_pct()
    if not isinstance(mf, (int, float)) or isinstance(mf, bool) or not 0 < mf <= 100:
        problems.append("no acceptable fall: the largest fall from a peak you could accept without selling")
        questions.append(f"What is the largest fall from a peak you could sit through (your current limit is {ceil:.0f} percent)?")
    elif mf > ceil:
        proposals.append(f"a fall of {mf:g} percent is above your limit of {ceil:.0f} percent: kept as a proposal for your yes; the limit stands")
    if not risk.get("cash_floor_months") and risk.get("cash_floor_months") != 0:
        questions.append("How many months of expenses must stay in cash, untouched?")
    ex = [e for e in (frame.get("competing_explanations") or []) if isinstance(e, dict)]
    ok_ex = [e for e in ex if str(e.get("explanation") or "").strip() and str(e.get("supported_by") or "").strip() and str(e.get("refuted_by") or "").strip()]
    if len(ok_ex) < 2:
        problems.append("fewer than two competing explanations, each with what would support it and what would refute it")
    chg = [c for c in (frame.get("would_change_my_view") or []) if str(c).strip()]
    if not chg:
        problems.append("no statement of what evidence would change the recommendation")
    return {"ok": not problems, "problems": problems, "questions": list(dict.fromkeys(questions)), "proposals": proposals}


def store(con, now: datetime, wish: str, frame: dict, case_id: Optional[int] = None) -> dict:
    """Validate and keep. A vague or incomplete frame is kept as `draft` with its questions (asked once, grouped); a complete one is `framed`."""
    from pflab.agents import questions as qs
    from pflab.pm.store import next_id
    v = validate(frame)
    mf = (frame.get("acceptable_risk") or {}).get("max_fall_pct")
    held = dict(frame)
    if isinstance(mf, (int, float)) and not isinstance(mf, bool) and mf > fall_ceiling_pct():
        held["acceptable_risk"] = {**frame["acceptable_risk"], "max_fall_pct": fall_ceiling_pct(), "requested_max_fall_pct": mf}
    vague = wish.strip().lower().rstrip(".!") in VAGUE or v["problems"]
    status = "framed" if v["ok"] else "draft"
    oid = next_id(con, "hq_objectives", "obj_id")
    con.execute("INSERT INTO hq_objectives (obj_id, case_id, made_at, wish, status, frame_json, problems_json) VALUES (?,?,?,?,?,?,?)",
                [oid, case_id, now, wish[:300], status, json.dumps(held, default=str), json.dumps(v)])
    asked = None
    if v["questions"]:
        text = "To turn \"" + wish.strip()[:80] + "\" into something I can test, I need: " + " ".join(f"({i}) {q}" for i, q in enumerate(v["questions"], 1))
        import hashlib
        key = "objective:" + hashlib.sha1(" ".join("".join(ch for ch in wish.lower() if ch.isalnum() or ch == " ").split()).encode()).hexdigest()[:10]       # the same wish is asked about once, however often it is drafted
        asked = qs.ask(con, "investigator", key, text[:900], now)
    if case_id is not None:
        from pflab.hq import cases
        for e in (frame.get("competing_explanations") or [])[:4]:
            if isinstance(e, dict) and e.get("explanation"):
                cases.add_evidence(con, case_id, now, f"explanation to test: {str(e['explanation'])[:200]} (supported by: {str(e.get('supported_by', ''))[:120]}; "
                                                      f"refuted by: {str(e.get('refuted_by', ''))[:120]})", stance="neutral", kind="observation", source_kind="objective")
        for c in (frame.get("would_change_my_view") or [])[:4]:
            cases.add_evidence(con, case_id, now, f"would change the view: {str(c)[:200]}", stance="neutral", kind="observation", source_id=f"objective:{oid}",
                               source_kind="objective")
    return {"objective_id": oid, "status": status, "vague": bool(vague), "problems": v["problems"], "questions_asked": v["questions"],
            "question_id": asked, "proposals": v["proposals"], "max_fall_applied_pct": (held.get("acceptable_risk") or {}).get("max_fall_pct")}


def current(con) -> List[dict]:
    rows = con.execute("SELECT obj_id, case_id, made_at, wish, status, frame_json FROM hq_objectives ORDER BY obj_id DESC LIMIT 10").fetchall()
    return [{"id": r[0], "case_id": r[1], "made": str(r[2])[:16], "wish": r[3], "status": r[4], "frame": json.loads(r[5])} for r in rows]


def testable(con) -> List[dict]:
    """Only framed objectives may be tested against or recommended for: a draft is waiting for his numbers."""
    return [o for o in current(con) if o["status"] == "framed"]
