"""The replay bench (S64 Phase 5 item 8; the loop engineering): re-run a journaled pass to see what a changed prompt, tool
or model would have done, without touching the world.

The brain runs again on the same trigger and events, and every tool call is answered from the pass's journal
(`hq_tool_calls`): a call with the same tool and arguments gets the recorded result, anything else gets "not in replay".
Nothing is executed: no action, no journal write by a tool, no memory (the pass is a journal-only rival row, marked
"replay of #N"). The model calls are real and priced against the cap like any pass. What differs from the original: the
portfolio and watch-list view at the top of the input is today's, not that day's, and a result recorded before S64 was cut
at 2,000 characters (shown to the model with that note). Rule: a change to the brain's prompt or tools is replayed on the
last 5 passes before it is merged.
"""
from __future__ import annotations

import json
import textwrap
from typing import Dict, List, Optional, Tuple

NOT_IN_REPLAY = "not in replay: this call was not made in the original pass"
CUT_NOTE = " ... (recorded cut here; the original result was longer)"
OLD_CUT = 2000


def _key(tool: str, args) -> Tuple[str, str]:
    return tool, json.dumps(args or {}, sort_keys=True, default=str)


class LogTools:
    """A `run_tool(ctx, name, args, turn)` that answers from a journaled pass. A repeated call gets the next recorded result."""

    def __init__(self, calls: List[dict]):
        self.pool: Dict[Tuple[str, str], List[dict]] = {}
        for c in calls:
            self.pool.setdefault(_key(c["tool"], c["args"]), []).append(c)
        self.served, self.missed = 0, []

    def __call__(self, ctx, name: str, args, turn: int = 1) -> Tuple[str, bool]:
        hit = self.pool.get(_key(name, args))
        if not hit:
            self.missed.append(name)
            return NOT_IN_REPLAY, True
        c = hit.pop(0) if len(hit) > 1 else hit[0]
        self.served += 1
        text = c["result"] or ""
        if len(text) == OLD_CUT:
            text += CUT_NOTE
        return text, c["status"] in ("error", "refused", "withheld")


def calls_of(con, pass_id: int) -> List[dict]:
    rows = con.execute("SELECT turn, tool, kind, args_json, status, result FROM hq_tool_calls WHERE pass_id=? ORDER BY call_no",
                       [pass_id]).fetchall()
    return [{"turn": t, "tool": n, "kind": k, "args": json.loads(a or "{}"), "status": s, "result": r or ""}
            for t, n, k, a, s, r in rows]


def replay(rt, client, gate, pass_id: int, model: Optional[str] = None, cfg=None) -> dict:
    """Run it again. Returns the old and new notes, the new pass id, the cost and what the log could not answer."""
    from pflab.hq import brain
    con = rt.cursor()
    row = con.execute("SELECT trigger, events_json, model, note, cost_inr, status FROM hq_passes WHERE pass_id=?", [pass_id]).fetchone()
    if row is None:
        raise LookupError(f"no pass #{pass_id}")
    trigger, events, old_model, old_note, old_cost, _status = row
    if trigger.startswith("replay of"):
        raise ValueError("that pass is itself a replay")
    log = LogTools(calls_of(con, pass_id))
    if not log.pool:
        raise ValueError(f"pass #{pass_id} made no tool calls to replay")
    new_id = brain.think(rt, trigger, json.loads(events or "[]"), client, gate, model=model or old_model, role="rival", cfg=cfg,
                         run_tool=log)
    con.execute("UPDATE hq_passes SET trigger=? WHERE pass_id=?", [f"replay of #{pass_id}: {trigger}", new_id])
    new = con.execute("SELECT note, cost_inr, status, error FROM hq_passes WHERE pass_id=?", [new_id]).fetchone()
    return {"old_pass": pass_id, "old_model": old_model, "old_note": old_note, "old_cost": old_cost,
            "new_pass": new_id, "new_model": model or old_model, "new_note": new[0], "new_cost": new[1], "status": new[2],
            "error": new[3], "served": log.served, "not_in_replay": log.missed}


def side_by_side(r: dict, width: int = 72) -> str:
    a = textwrap.wrap(r["old_note"] or "(no note)", width) or [""]
    b = textwrap.wrap(r["new_note"] or "(no note)", width) or [""]
    n = max(len(a), len(b))
    a += [""] * (n - len(a))
    b += [""] * (n - len(b))
    left = f"OLD pass #{r['old_pass']} {r['old_model']} Rs {r['old_cost'] or 0:.2f}"
    head = f"{left:<{width}} | NEW pass #{r['new_pass']} {r['new_model']} Rs {r['new_cost'] or 0:.2f}"
    lines = [head, "-" * (width + 3 + width)] + [f"{x:<{width}} | {y}" for x, y in zip(a, b)]
    missed = f" ({', '.join(sorted(set(r['not_in_replay'])))})" if r["not_in_replay"] else ""
    lines.append(f"tool calls answered from the log: {r['served']}; not in replay: {len(r['not_in_replay'])}{missed}"
                 + (f"; status {r['status']}: {r['error']}" if r["status"] != "done" else ""))
    return "\n".join(lines)
