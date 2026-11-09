"""The autonomy check (S81): it MEASURES autonomy instead of claiming it, over a period, counting no human action.

    closes          closes run by the loop and their outcome (traded or held)
    allocation      allocation proposals made and adopted
    strategist      sessions started on their own triggers (a session he asked for in the chat is not counted as the system's own), lab runs, challengers, probation slices
                    granted, grown or withdrawn
    exits           exit-manager actions by kind, each scored after tax against holding
    storylines      opened, confirmed, faded, broken
    views           issued and scored
    questions       sent to him, answered, defaulted
    money           rupees spent per lab run and per promoted change

A period with no strategist session of the system's own, no adopted change and only "held" closes is flagged NOT AUTONOMOUS with the reason, so a frozen system can never
look busy. Every part reads the store and tolerates a table that does not exist yet (a part that cannot be read is named in `left_out`, never guessed). Code only.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional

HUMAN_REASONS = ("chat", "investor", "his request", "asked by him")      # a session whose reason starts like this was his, not the system's


def _q(con, sql: str, args: list):
    return con.execute(sql, args).fetchall()


def _closes(con, start: date, end: date) -> dict:
    rows = _q(con, "SELECT status, count(*) FROM core_runs_s80 WHERE day >= ? AND day <= ? GROUP BY 1", [start, end])
    by = {r[0]: int(r[1]) for r in rows}
    traded = sum(n for k, n in by.items() if k == "traded")
    return {"run": sum(by.values()), "traded": traded, "held": sum(n for k, n in by.items() if k != "traded"), "by_status": by}


def _allocation(con, since: datetime, until: datetime) -> dict:
    made = _q(con, "SELECT status, count(*) FROM system_allocation_s79 WHERE proposed_at >= ? AND proposed_at <= ? GROUP BY 1", [since, until])
    adopted = con.execute("SELECT count(*) FROM system_allocation_s79 WHERE activated_at >= ? AND activated_at <= ?", [since, until]).fetchone()[0]
    return {"proposed": sum(int(n) for _, n in made), "adopted": int(adopted), "by_status": {k: int(n) for k, n in made}}


def _strategist(con, since: datetime, until: datetime) -> dict:
    rows = _q(con, "SELECT session_id, reason, status, lab_runs, challengers, cost_inr FROM core_sessions_s80 WHERE started_at >= ? AND started_at <= ?", [since, until])
    own = [r for r in rows if not str(r[1] or "").lower().startswith(HUMAN_REASONS)]
    out = {"sessions": len(rows), "own_trigger": len(own), "asked_by_him": len(rows) - len(own),
           "lab_runs": sum(int(r[3] or 0) for r in own), "challengers": sum(int(r[4] or 0) for r in own),
           "wasted": sum(1 for r in own if r[2] == "wasted"), "rupees": round(sum(float(r[5] or 0) for r in rows), 2)}
    promos = _q(con, "SELECT kind, count(*) FROM core_promotions_s80 WHERE happened_at >= ? AND happened_at <= ? GROUP BY 1", [since, until])
    out["promotions"] = {k: int(n) for k, n in promos}
    return out


def _probation(con, since: datetime, until: datetime) -> dict:
    rows = _q(con, "SELECT kind, count(*) FROM probation_changes_s81 WHERE changed_at >= ? AND changed_at <= ? GROUP BY 1", [since, until])
    return {k: int(n) for k, n in rows}


def _exits(con, since: datetime, until: datetime) -> dict:
    rows = _q(con, "SELECT kind, count(*), sum(CASE WHEN diff_after_tax > 0 THEN 1 ELSE 0 END), sum(diff_after_tax) FROM exit_scores_s81 WHERE sold_at >= ? AND sold_at <= ? GROUP BY 1", [since, until])
    return {k: {"n": int(n), "better_than_holding": int(b or 0), "after_tax_difference": round(float(d or 0), 2)} for k, n, b, d in rows}


def _storylines(con, start: date, end: date) -> dict:
    opened = con.execute("SELECT count(*) FROM storylines_s80 WHERE opened_on >= ? AND opened_on <= ?", [start, end]).fetchone()[0]
    rows = _q(con, "SELECT status, count(*) FROM storylines_s80 WHERE status_on >= ? AND status_on <= ? AND status <> 'open' GROUP BY 1", [start, end])
    return {"opened": int(opened), "closed_by_outcome": {k: int(n) for k, n in rows}}


def _views(con, start: date, end: date) -> dict:
    made = con.execute("SELECT count(*) FROM core_views_s80 WHERE made_on >= ? AND made_on <= ?", [start, end]).fetchone()[0]
    rows = _q(con, "SELECT outcome, count(*) FROM core_views_s80 WHERE made_on >= ? AND made_on <= ? AND outcome IS NOT NULL GROUP BY 1", [start, end])
    return {"issued": int(made), "scored": {k: int(n) for k, n in rows}}


def _questions(con, since: datetime, until: datetime) -> dict:
    rows = _q(con, "SELECT status, count(*) FROM questions WHERE created_at >= ? AND created_at <= ? GROUP BY 1", [since, until])
    return {"asked": sum(int(n) for _, n in rows), "by_status": {k: int(n) for k, n in rows}}


def _money(strategist: dict, closes: dict) -> dict:
    runs = max(0, int(strategist.get("lab_runs", 0)))
    promoted = int((strategist.get("promotions") or {}).get("promote", 0))
    r = float(strategist.get("rupees", 0.0))
    return {"rupees": r, "per_lab_run": None if not runs else round(r / runs, 2), "per_promoted_change": None if not promoted else round(r / promoted, 2)}


def verdict(parts: dict) -> dict:
    """AUTONOMOUS or NOT AUTONOMOUS with the reason: no strategist session of its own, no adopted change and only held closes."""
    closes, strat, alloc = parts.get("closes") or {}, parts.get("strategist") or {}, parts.get("allocation") or {}
    own_sessions = int(strat.get("own_trigger", 0))
    adopted = int(alloc.get("adopted", 0)) + int((strat.get("promotions") or {}).get("promote", 0))
    traded = int(closes.get("traded", 0))
    probation = sum((parts.get("probation") or {}).values())
    exits = sum(v["n"] for v in (parts.get("exits") or {}).values())
    active = own_sessions > 0 or adopted > 0 or traded > 0 or probation > 0 or exits > 0
    if active:
        return {"autonomous": True, "why": f"{own_sessions} strategist session(s) of its own, {adopted} adopted change(s), {traded} traded close(s), {exits} exit action(s)"}
    reasons = []
    if not closes.get("run"):
        reasons.append("no close ran (the app was closed, or the loop failed or is switched off)")
    else:
        reasons.append("every close was a hold")
    reasons.append("no strategist session started on its own trigger (no trigger fired, a gate, the budget, or a failure)")
    return {"autonomous": False, "why": "NOT AUTONOMOUS: " + "; ".join(reasons)}


def report(con, now: datetime, days: int = 7) -> dict:
    """The check over the last `days` days up to `now`."""
    end, start = now.date(), now.date() - timedelta(days=days)
    since, until = datetime.combine(start, datetime.min.time()), now
    parts: Dict[str, object] = {"period": {"from": str(start), "to": str(end), "days": days}}
    left_out: List[str] = []
    fns: Dict[str, Callable[[], dict]] = {
        "closes": lambda: _closes(con, start, end), "allocation": lambda: _allocation(con, since, until), "strategist": lambda: _strategist(con, since, until),
        "probation": lambda: _probation(con, since, until), "exits": lambda: _exits(con, since, until), "storylines": lambda: _storylines(con, start, end),
        "views": lambda: _views(con, start, end), "questions": lambda: _questions(con, since, until)}
    for name, fn in fns.items():
        try:
            parts[name] = fn()
        except Exception as e:                                         # a table that is not there yet is named, never hidden
            parts[name] = {}
            left_out.append(f"{name} ({type(e).__name__})")
    parts["money"] = _money(parts.get("strategist") or {}, parts.get("closes") or {})
    parts["verdict"] = verdict(parts)
    parts["left_out"] = left_out
    return parts


def text(rep: dict) -> str:
    """The plain-words message (Telegram after the fifth real close, then weekly; Today)."""
    p = rep["period"]
    c, a, s, st, v, q, m = (rep.get(k) or {} for k in ("closes", "allocation", "strategist", "storylines", "views", "questions", "money"))
    lines = [f"Autonomy check, {p['from']} to {p['to']}: " + rep["verdict"]["why"],
             f"Closes run by the loop: {c.get('run', 0)} ({c.get('traded', 0)} traded, {c.get('held', 0)} held).",
             f"Allocation: {a.get('proposed', 0)} proposed, {a.get('adopted', 0)} adopted.",
             f"Strategist: {s.get('own_trigger', 0)} session(s) on its own triggers ({s.get('asked_by_him', 0)} asked by you), {s.get('lab_runs', 0)} lab runs, {s.get('challengers', 0)} challengers; "
             f"promotions {s.get('promotions', {})}; probation {rep.get('probation') or {}}.",
             "Exits: " + (", ".join(f"{k} {d['n']} ({d['better_than_holding']} better than holding after tax)" for k, d in (rep.get('exits') or {}).items()) or "none") + ".",
             f"Storylines: {st.get('opened', 0)} opened, closed {st.get('closed_by_outcome', {})}. Views: {v.get('issued', 0)} issued, scored {v.get('scored', {})}.",
             f"Questions to you: {q.get('asked', 0)} {q.get('by_status', {})}.",
             f"Money: Rs {m.get('rupees', 0):,.0f}" + (f", Rs {m['per_lab_run']:,.0f} a lab run" if m.get('per_lab_run') else "") + (f", Rs {m['per_promoted_change']:,.0f} a promoted change" if m.get('per_promoted_change') else "") + "."]
    if rep.get("left_out"):
        lines.append("Could not be read: " + ", ".join(rep["left_out"]) + ".")
    return "\n".join(lines)
