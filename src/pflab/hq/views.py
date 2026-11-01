"""The Agent HQ screen's data (S59): the roster with each agent's last task and spend, the board, the spend against
the limits, the brain's journal and scorecard, the keeper's follow-ups, reminders and the drop folder."""
from __future__ import annotations

import json
from datetime import timedelta


def hq(rt) -> dict:
    from pflab.hq import board, brain, cases, governor as gv, keeper, messenger, roster, suggestions as sg, watcher
    con, now = rt.cursor(), rt.clock()
    sp = gv.spend(con, now)
    by_agent = {a["agent"]: a for a in sp["agents"]}
    last = {r[0]: {"id": r[1], "status": r[2], "at": str(r[3])[:16]} for r in con.execute(
        "SELECT to_agent, max(task_id), arg_max(status, task_id), max(created_at) FROM hq_tasks GROUP BY to_agent").fetchall()}
    alias = {"research": ["analyst (research)"], "web": ["web search"], "calc": ["workshop", "workshop (second writing)"],
             "brain": ["brain_rival", "gatekeeper", "reflection"], "portfolio": ["wording"], "reader": [], "ask": []}
    agents = []
    for a in roster.listing():
        rows = [by_agent.pop(n) for n in [a["name"], *alias.get(a["name"], [])] if n in by_agent]
        agents.append({**a, "last": last.get(a["name"]), "month": sum(r["month"] for r in rows),
                       "today": sum(r["today"] for r in rows), "calls": sum(r["calls"] for r in rows),
                       "over_limit": sum(r["over_limit"] for r in rows)})
    sp["others"] = list(by_agent.values())                  # spent by paths no HQ agent owns (harness editor, notes)
    tasks = board.recent(con, 30)
    for t in tasks:
        t["title"] = roster.title(t["to"])[0]
        t["route"] = (t["result_json"] or {}).get("route", [])
    readings = con.execute("""SELECT r.read_at, r.material, r.summary, d.title, d.kind, r.dropped FROM hq_readings r
                              JOIN kg_docs d ON d.doc_id = r.doc_id ORDER BY r.read_at DESC LIMIT 12""").fetchall()
    preds = con.execute("SELECT pred_id, model, made_at, claim, due, confidence, base_rate, outcome, detail FROM hq_predictions "
                        "ORDER BY pred_id DESC LIMIT 30").fetchall()
    fu = keeper.followups(con, now.date())
    return {
        "agents": agents, "tasks": tasks, "spend": sp,
        "limits": {k: {"layer": v.layer, "per_day": v.per_day, "max_in": v.max_in, "max_out": v.max_out}
                   for k, v in gv.LIMITS.items()},
        "brain": {"mode": rt.settings.get("brain", "economy"), "shadow": brain.SHADOW,
                  "shadow_since": str(con.execute("SELECT min(passed_at) FROM hq_passes WHERE role='brain'").fetchone()[0] or "")[:10],
                  "journal": brain.journal(con, 30), "scorecard": keeper.scorecard(con)},
        "predictions": [{"id": p[0], "model": p[1], "made": str(p[2])[:16], "claim": p[3], "due": str(p[4]),
                         "confidence": p[5], "base_rate": p[6], "outcome": p[7], "detail": p[8]} for p in preds],
        "suggestions": sg.recent(con, 30), "suggestion_record": sg.record_table(con),      # S60 the suggestion ledger
        "followups": [{**f, "at": str(f["at"])[:10]} for f in fu if f["since"]][:20],   # decisions about a company
        "other_decisions": sum(1 for f in fu if not f["since"]),
        "readings": [{"at": str(r[0])[:16], "material": r[1], "summary": r[2], "title": r[3], "kind": r[4], "dropped": r[5],
                      "where": "stayed on this PC (withheld)" if str(r[2] or "") == "" and r[1] == "no" and r[4] == "email"
                      else "cloud: a redacted copy of an email that named none of his ids" if r[4] == "email" else "cloud: a public document"}
                     for r in readings],
        "reminders": [{"id": i, "text": t, "due": str(d)[:16]} for i, t, d in messenger.upcoming(con)],
        "drop": {"folder": str(watcher.folder(rt.repo)), "on": rt.settings.get("drop_watch", True)},
        "since_week": str(now - timedelta(days=7))[:10],
        "cases": cases.listing(con, 25), "held": board.held(con), "task_counts": board.counts(con),
    }


def case_detail(con, cid: int) -> dict:
    """One investigation in full: question, assumptions, evidence with its times and stance, requests, calculations, the log (why it
    changed) and the process reviews."""
    from pflab.hq import cases
    c = cases.get(con, cid)
    if c is None:
        raise LookupError(f"no case #{cid}")
    deps = [dict(zip(("key", "kind", "request", "status", "requested", "arrived"), r)) for r in con.execute(
        "SELECT dep_key, kind, request, status, requested_at, arrived_at FROM hq_case_deps WHERE case_id=? ORDER BY dep_id", [cid]).fetchall()]
    from pflab.hq import containment
    calcs = [{**dict(zip(("id", "question", "status", "contained", "datasets", "result", "code_sha"), (r[0], r[1], r[2], r[3], json.loads(r[4] or "[]"),
              json.loads(r[5] or "{}"), r[6]))),
              "ran": containment.state_of(r[3], containment.is_reviewed(r[7])), "where": containment.WORDS[containment.state_of(r[3], containment.is_reviewed(r[7]))]}
             for r in con.execute(
        "SELECT calc_id, question, status, contained, datasets_json, result_json, code_sha, check_json FROM hq_calcs WHERE case_id=? ORDER BY calc_id", [cid]).fetchall()]   # S70: where it ran, four ways
    log = [{"at": str(a)[:16], "event": e, "detail": d} for a, e, d in con.execute(
        "SELECT logged_at, event, detail FROM hq_case_log WHERE case_id=? ORDER BY log_id", [cid]).fetchall()]
    reviews = [{"at": str(a)[:16], **json.loads(p), "outcome": o, "note": n} for a, p, o, n in con.execute(
        "SELECT reviewed_at, process_json, outcome, note FROM hq_case_reviews WHERE case_id=? ORDER BY review_id", [cid]).fetchall()]
    return as_json({**c, "evidence": cases.evidence(con, cid), "dependencies": deps, "calculations": calcs, "log": log, "reviews": reviews,
                    "assessment": cases.assess(con, cid)})


def as_json(d: dict) -> dict:
    return json.loads(json.dumps(d, default=str))
