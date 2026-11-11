"""S54e: preset checklists. The investor starts one for a company, a buy or the month; each item is a note in a named list,
ticked off on the Schedule screen. The items are reminders of the system's own checks, not advice."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List

TEMPLATES: Dict[str, List[str]] = {
    "Company research": [
        "Read the last four quarterly results (Research and plans: results and the analyst's note)",
        "Check surveillance, pledges and the guards for it",
        "Look at its price range (an estimate, not a tested signal) and whether the price is rich for its growth",
        "Read the latest filings and news in the knowledge graph",
        "Write or update the thesis: why, what would prove it wrong, by when",
        "Ask deep research only if the local answers leave a question open",
    ],
    "Before a buy": [
        "The guards pass and it is on the stock list",
        "The reason for this price is written in the thesis (the buy zone failed its test: it is no condition)",
        "The amount fits the plan and the bucket's band after the buy",
        "No results or big event due in the next few days (or that is the point)",
        "Enter the order yourself in Kite; the system never places one",
        "Log why in the thesis the same day",
    ],
    "Month-end": [
        "Drop the month's Console tradebook, funds ledger, contract notes, CAS and bank statements in Inbox and files",
        "Add them to the ledger once every check passes",
        "Look at the mix against the targets and the bands",
        "Check FD maturities and where the money goes next",
        "Read the month's simulations: the fall chance and the fan",
        "Answer the system's open questions",
    ],
    "New IPO": [
        "Read the red herring prospectus summary and the price band",
        "Check the grey-market noise is not the reason",
        "Decide the amount within the IPO budget",
        "After allotment, drop the screenshot in Inbox and files",
    ],
}


def start(con, template: str, subject: str, now: datetime) -> str:
    from pflab.pm.store import next_id
    if template not in TEMPLATES:
        raise ValueError(f"no checklist called {template!r}")
    name = f"{template}: {subject.strip()[:60]}" if subject.strip() else template
    if con.execute("SELECT 1 FROM app_notes WHERE list_name=? AND deleted = false", [name]).fetchone():
        raise ValueError(f"{name} is already open")
    for item in TEMPLATES[template]:
        con.execute("INSERT INTO app_notes (note_id, text, created_at, list_name) VALUES (?,?,?,?)",
                    [next_id(con, "app_notes", "note_id"), item, now, name])
    return name


def lists(con) -> List[dict]:
    rows = con.execute("SELECT list_name, note_id, text, done FROM app_notes WHERE deleted = false AND list_name IS NOT NULL "
                       "ORDER BY list_name, note_id").fetchall()
    out: Dict[str, dict] = {}
    for name, nid, text, done in rows:
        out.setdefault(name, {"name": name, "items": []})["items"].append({"id": nid, "text": text, "done": bool(done)})
    return list(out.values())


def close(con, name: str) -> None:
    con.execute("UPDATE app_notes SET deleted = true WHERE list_name=?", [name])
