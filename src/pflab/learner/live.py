"""What is live from the learner (S62, PLAN A22): one table, `learned`, read by the brain and the system.

    finding      a claim from outside reading that passed its registered test (the brain's cached part; `findings`)
    lesson       a lesson from the system's own record that passed its rule (the brain's cached part)
    instruction  a change to the brain's instructions the investor said yes to (the brain's cached part)
    daily_cap    an action's daily limit (tools.DAILY) the investor said yes to
    model        a job's model by a registered comparison (below the investor's own Settings choice, above the defaults)
    experiment   (S67) the outcome of a bounded experiment: kept (shadow research only) or rejected, with its limit stated; never a rule
A newer row of the same kind and key ends the older one (kept, with its dates); nothing is deleted.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

KINDS = ("finding", "lesson", "instruction", "daily_cap", "model", "experiment")
BRAIN_KINDS = ("finding", "lesson", "instruction", "experiment")


def put(con, kind: str, key: str, text: str, value: Optional[str], source: str, now: datetime) -> int:
    from pflab.pm.store import next_id
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    con.execute("UPDATE learned SET valid_to=? WHERE kind=? AND key=? AND valid_to IS NULL", [now, kind, key])
    lid = next_id(con, "learned", "learn_id")
    con.execute("INSERT INTO learned (learn_id, kind, key, text, value, source, valid_from) VALUES (?,?,?,?,?,?,?)",
                [lid, kind, key, text[:1500], value, source, now])
    return lid


def end(con, kind: str, key: str, now: datetime) -> int:
    n = con.execute("SELECT count(*) FROM learned WHERE kind=? AND key=? AND valid_to IS NULL", [kind, key]).fetchone()[0]
    con.execute("UPDATE learned SET valid_to=? WHERE kind=? AND key=? AND valid_to IS NULL", [now, kind, key])
    return int(n)


def current(con, kinds=KINDS) -> List[dict]:
    try:
        rows = con.execute(f"SELECT learn_id, kind, key, text, value, source, valid_from FROM learned WHERE valid_to IS NULL "
                           f"AND kind IN ({','.join('?' * len(kinds))}) ORDER BY learn_id", list(kinds)).fetchall()
    except Exception:                                   # a store before v34 (tests with an old fixture)
        return []
    return [dict(zip(["id", "kind", "key", "text", "value", "source", "since"], r)) for r in rows]


def values(con, kind: str) -> Dict[str, str]:
    return {r["key"]: r["value"] for r in current(con, (kind,))}


def brain_text(con) -> str:
    """For the brain's cached part: what the learner made live, by kind."""
    rows = current(con, BRAIN_KINDS)
    if not rows:
        return "LEARNED: nothing yet (tested findings from reading and lessons from your record appear here)."
    head = {"finding": "TESTED FINDINGS (claims from reading that passed a registered test on this system's data; history, "
                       "never a forecast)",
            "lesson": "LESSONS FROM YOUR RECORD (each passed its rule, n at least 20)",
            "instruction": "INSTRUCTIONS ADDED (the investor said yes)",
            "experiment": "EXPERIMENTS (outcomes of bounded tests with their limits; a rejection is a result, a kept candidate is shadow "
                          "research only and never a rule)"}
    out = []
    for k in BRAIN_KINDS:
        mine = [r for r in rows if r["kind"] == k]
        if mine:
            out.append(head[k] + ":\n" + "\n".join(f"- {r['text']}" for r in mine))
    return "\n".join(out)
