"""Probation slices (S81, A50c): how a lab variant earns the right to trade real (paper) money.

A variant that clears the history screen (with the two-dimension index rule) and the once-only 2018-2021 check (`promotion.check`) is granted a satellite slice of 5% of the book AT ONCE;
shadow no longer blocks acting. The slice grows to 10% and then 20% while its live record is not worse than the champion's over 20 and then 40 sessions since the grant, and is WITHDRAWN
automatically when it is worse. Every change is stored with its reason and its record (`probation_s81`); the screens show each challenger's slice and why.

The live record is the shadow record (`core_shadow_s80`: the variant's weights and the champion's stand-in's, scored at the next close, flat charges, no tax: both sides on the same footing)
over the sessions after the grant. The loop asks `slices(con, day)` and runs the champion plus each slice's policy on its share (`blend`).
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Dict, List, Optional

from pflab import core
from pflab.lab import shadow


def cfg() -> dict:
    return core.settings()["probation"]


def history(con, policy_id: str) -> List[dict]:
    """Every change of this variant's slice, oldest first: {kind (grant | grow | withdraw), on, share, reason, record}."""
    rows = con.execute("SELECT kind, changed_on, share, reason, record_json FROM probation_s81 WHERE policy_id=? ORDER BY change_id", [policy_id]).fetchall()
    return [{"kind": k, "on": d, "share": float(s), "reason": r, "record": json.loads(j or "{}")} for k, d, s, r, j in rows]


def _latest(con, policy_id: str, day: date) -> Optional[dict]:
    rows = [h for h in history(con, policy_id) if h["on"] <= day]
    return rows[-1] if rows else None


def _since(con, policy_id: str) -> Optional[date]:
    g = [h for h in history(con, policy_id) if h["kind"] == "grant"]
    return g[-1]["on"] if g else None


def slices(con, day: date) -> List[dict]:
    """The slices in force on `day`: [{policy_id, share, since}] (share a fraction of the book; withdrawn ones are not listed). The close loop runs the champion on what is left."""
    out = []
    for (pid,) in con.execute("SELECT DISTINCT policy_id FROM probation_s81 ORDER BY policy_id").fetchall():
        last = _latest(con, pid, day)
        if last is None or last["kind"] == "withdraw":
            continue
        out.append({"policy_id": pid, "share": last["share"], "since": _since(con, pid)})
    return out


def total_share(con, day: date) -> float:
    return round(sum(s["share"] for s in slices(con, day)), 6)


def _log(con, now: datetime, day: date, pid: str, kind: str, share: float, reason: str, record: Optional[dict] = None) -> None:
    from pflab.pm.store import next_id
    con.execute("INSERT INTO probation_s81 VALUES (?,?,?,?,?,?,?,?)", [next_id(con, "probation_s81", "change_id"), pid, day, kind, float(share), reason[:600], json.dumps(record or {}, default=str), now])


def grant(con, now: datetime, day: date, policy_id: str, verdict: Optional[dict] = None) -> dict:
    """The start slice (5% of the book by default) for a variant that cleared history and the final check. Refused when it is already on probation, or when the slices already take the
    most the book may give them (`max_total_share`: the satellite room)."""
    c = cfg()
    if slices_for(con, policy_id, day):
        return {"granted": False, "why": f"{policy_id} already has a slice"}
    room = float(c["max_total_share"]) - total_share(con, day)
    if room + 1e-9 < float(c["start_share"]):
        return {"granted": False, "why": f"no room: the slices already take {total_share(con, day):.0%} of the book (at most {float(c['max_total_share']):.0%})"}
    v = verdict or {}
    fin = v.get("final") or {}
    why = ("cleared the history screen and the index rule" + (f" (via {v['index_rule']['via']}: it trails the index by {v['index_rule']['lag']:+.1%} a year after tax and charges, "
                                                              f"worst fall {v['index_rule']['fall']:.1%} against the index's {v['index_rule']['index_fall']:.1%})" if (v.get("index_rule") or {}).get("lag") is not None else "")
           + ("; the once-only 2018-2021 check was passed" + (f" ({fin['cagr']:.1%} a year)" if fin.get("cagr") is not None else "")) + f": a probation slice of {float(c['start_share']):.0%} of the book at once")
    _log(con, now, day, policy_id, "grant", float(c["start_share"]), why, {"history": v.get("history"), "final": fin})
    return {"granted": True, "share": float(c["start_share"]), "why": why}


def slices_for(con, policy_id: str, day: date) -> Optional[dict]:
    last = _latest(con, policy_id, day)
    return None if last is None or last["kind"] == "withdraw" else last


def record(con, policy_id: str, since: date, window: int, day: Optional[date] = None) -> dict:
    """The live record over the last `window` sessions after `since`: the variant's and the champion's stand-in's compounded shadow returns on the sessions both were scored."""
    against = shadow.standin(con)
    rows = con.execute("SELECT a.day, a.ret, b.ret FROM core_shadow_s80 a JOIN core_shadow_s80 b ON a.day=b.day AND b.policy_id=? WHERE a.policy_id=? AND a.day > ? "
                       "AND a.day <= ? AND a.ret IS NOT NULL AND b.ret IS NOT NULL ORDER BY a.day", [against, policy_id, since, day or date.max]).fetchall()
    n_all = len(rows)
    rows = rows[-int(window):] if window else rows
    ca = cb = 1.0
    for _, a, b in rows:
        ca *= 1 + a
        cb *= 1 + b
    return {"sessions_since": n_all, "window": len(rows), "variant_return": ca - 1, "champion_standin_return": cb - 1, "excess": (ca - 1) - (cb - 1), "against": against}


def review(con, now: datetime, day: date) -> List[dict]:
    """Grow or withdraw every slice by its live record. Idempotent for a day. -> the changes made, each with its reason."""
    c = cfg()
    steps = [float(x) for x in c["steps"]]
    gates = [int(x) for x in c["sessions_to_grow"]]
    tol, min_n = float(c["tolerance"]), int(c["min_sessions_to_judge"])
    out = []
    for s in slices(con, day):
        pid, share, since = s["policy_id"], s["share"], s["since"]
        if since is None or any(h["on"] == day and h["kind"] in ("grow", "withdraw") for h in history(con, pid)):
            continue
        i = min(range(len(steps)), key=lambda j: abs(steps[j] - share))
        gate = gates[min(i, len(gates) - 1)]
        rec = record(con, pid, since, gate, day)
        n = rec["sessions_since"]
        if n < min_n:
            continue
        worse = rec["excess"] < -tol
        if worse:
            why = (f"withdrawn: over its last {rec['window']} live sessions it returned {rec['variant_return']:+.2%} against the champion's stand-in {rec['champion_standin_return']:+.2%} "
                   f"({rec['excess']:+.2%}, more than {tol:.1%} behind)")
            _log(con, now, day, pid, "withdraw", 0.0, why, rec)
            out.append({"policy_id": pid, "change": "withdraw", "share": 0.0, "why": why})
        elif n >= gate and i + 1 < len(steps):
            nxt = steps[i + 1]
            room = float(c["max_total_share"]) - total_share(con, day) + share
            if nxt > room + 1e-9:
                continue
            why = (f"grown to {nxt:.0%}: over {rec['window']} live sessions it returned {rec['variant_return']:+.2%} against the champion's stand-in {rec['champion_standin_return']:+.2%} "
                   f"({rec['excess']:+.2%}, not worse)")
            _log(con, now, day, pid, "grow", nxt, why, rec)
            out.append({"policy_id": pid, "change": "grow", "share": nxt, "why": why})
    return out


def blend(champion: Dict[str, float], slice_weights: Dict[str, Dict[str, float]], slices_now: List[dict]) -> Dict[str, float]:
    """The book's target weights: the champion's on what the slices leave, plus each slice's policy weights on its share. A slice with no weights this close leaves its share to the champion."""
    live = [s for s in slices_now if slice_weights.get(s["policy_id"])]
    used = sum(s["share"] for s in live)
    out: Dict[str, float] = {k: v * (1.0 - used) for k, v in champion.items()}
    for s in live:
        for k, v in slice_weights[s["policy_id"]].items():
            out[k] = out.get(k, 0.0) + v * s["share"]
    return out


def explain(con, day: date, policy_id: str) -> dict:
    """What the Today screen shows for one challenger: its slice (a fraction, 0 when none) and why, in the code-written reason of the latest change (or why it has none yet)."""
    h = history(con, policy_id)
    last = _latest(con, policy_id, day)
    if last is None:
        return {"share": 0.0, "since": None, "why": "no slice yet: it has not cleared the history screen and the once-only final check"}
    return {"share": 0.0 if last["kind"] == "withdraw" else last["share"], "since": str(_since(con, policy_id)) if _since(con, policy_id) else None, "why": last["reason"],
            "changes": len(h)}
