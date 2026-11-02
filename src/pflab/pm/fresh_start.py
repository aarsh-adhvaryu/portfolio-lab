"""S78: a fresh start for the system's mind, never for its account (his decision 2026-11-02: "clear chat, clear the knowledge graph, clear the working-on part ... all it has is the
information that this is the original, the bonds and all, then it starts again; get rid of the stale").

CLEARED: the chat, the knowledge graph (rebuilt by its own nightly job from the collected documents), every investigation and what hangs on it (plans, tasks, calculations, evidence, reviews,
proposals, triggers, journals of the team), the questions and notes, the paper team's decisions, orders, claims, lessons, watchlist and acts, and the paper clock (restarted today).
KEPT: the account itself (ledger, lots, cash, his Zerodha starting holdings with the inherited bonds), prices and every collected document, the API call record (the money cap needs it), the
learner and its test counter (the bar must keep rising), the house rules and policies he adopted, the settings, the self-check history.
Nothing here is undone by the code: the CLI (`tools/fresh_start.py`) copies the store first."""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List

GROUPS: Dict[str, List[str]] = {
    "chat": ["chat_messages", "chat_summary", "chats"],
    "knowledge graph": ["kg_nodes", "kg_edges", "kg_docs", "kg_aliases", "kg_hypotheses"],
    "investigations and the team's work": ["hq_missions", "hq_tasks", "hq_cases", "hq_case_deps", "hq_case_evidence", "hq_case_log", "hq_case_reviews", "hq_calcs", "hq_calc_inputs",
                                           "hq_artifacts", "hq_plan_versions", "hq_triggers", "hq_proposals", "hq_proposal_log", "hq_effects", "hq_claims", "hq_readings", "hq_passes",
                                           "hq_predictions", "hq_reminders", "hq_tool_calls", "hq_suggestions", "hq_issues", "hq_objectives", "hq_routing", "hq_memory_effects"],
    "questions, notes and memory": ["questions", "app_notes", "ready_plans", "briefs", "inbox_items", "memory"],
    "the paper team's decisions": ["paper_decisions", "paper_orders", "paper_inputs", "paper_claims", "paper_acts", "paper_lessons", "paper_watch"],
}


def _have(con, table: str) -> bool:
    return bool(con.execute("SELECT 1 FROM information_schema.tables WHERE table_name=?", [table]).fetchone())


def plan(con) -> Dict[str, int]:
    """Rows per group that would go."""
    out = {}
    for g, tables in GROUPS.items():
        out[g] = sum(int(con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]) for t in tables if _have(con, t))
    out["paper clock (days marked)"] = int(con.execute("SELECT count(*) FROM paper_days").fetchone()[0]) if _have(con, "paper_days") else 0
    return out


def apply(con, today: date, now: datetime) -> dict:
    """Delete the groups above and restart the paper clock today. Returns what was removed and the new start."""
    removed = plan(con)
    for tables in GROUPS.values():
        for t in tables:
            if _have(con, t):
                con.execute(f'DELETE FROM "{t}"')
    started = None
    if _have(con, "paper_days"):
        con.execute("DELETE FROM paper_days")
        from pflab.paper import book
        book.seed(con, today, now)                            # in the system's own account this marks today's value as the first day
        if not con.execute("SELECT count(*) FROM paper_days").fetchone()[0]:
            book.mark(con, today)                             # (the workshop's copy keeps its seed cash row: mark the day directly)
        started = str(con.execute("SELECT min(day) FROM paper_days").fetchone()[0])
    return {"removed": removed, "paper_started": started}
