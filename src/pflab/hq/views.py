"""The Agent HQ screen's data (S59): the roster with each agent's last task and spend, the board, the spend against
the limits, the brain's journal and scorecard, the keeper's follow-ups, reminders and the drop folder."""
from __future__ import annotations

import json
from datetime import timedelta


def hq(rt) -> dict:
    from pflab.hq import board, brain, governor as gv, keeper, messenger, roster, suggestions as sg, watcher
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
        "readings": [{"at": str(r[0])[:16], "material": r[1], "summary": r[2], "title": r[3], "kind": r[4], "dropped": r[5]}
                     for r in readings],
        "reminders": [{"id": i, "text": t, "due": str(d)[:16]} for i, t, d in messenger.upcoming(con)],
        "drop": {"folder": str(watcher.folder(rt.repo)), "on": rt.settings.get("drop_watch", True)},
        "since_week": str(now - timedelta(days=7))[:10],
    }


def as_json(d: dict) -> dict:
    return json.loads(json.dumps(d, default=str))
