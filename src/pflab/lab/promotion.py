"""Promotion and rollback (S80 phase 2).

A challenger replaces the champion only when ALL of these hold (registered in code; every variant tried counts as a trial in the deflated Sharpe):
  1. history      on 2005-2017 it clears the screen against the plain baseline (deflated Sharpe, excess return, shuffled-signal share, worst fall) AND is not behind the champion
  2. shadow       at least 20 live shadow sessions, and over them it has not done worse than the champion's stand-in (cumulative excess >= -SHADOW_TOLERANCE)
  3. final        the 2018-2021 check, run ONCE by code (never by the strategist), is not worse than the baseline's over the same window
A promotion is logged with the code diff and the scorecard; the old champion is kept so a bad switch can be undone, and a champion that falls below its own history range for
ROLLBACK_SESSIONS sessions in a row is replaced by the previous one automatically.
"""
from __future__ import annotations

import difflib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from pflab.lab import runner, service, shadow

SHADOW_TOLERANCE = 0.002
ROLLBACK_SESSIONS = 10


def _code_of(con, policy_id: str) -> str:
    if policy_id == "baseline_v1":
        import inspect
        from pflab.core import policy
        return inspect.getsource(policy)
    p = service.get(con, policy_id)
    return (p or {}).get("code") or ""


def diff(con, old_id: str, new_id: str) -> str:
    a, b = _code_of(con, old_id).splitlines(), _code_of(con, new_id).splitlines()
    return "\n".join(difflib.unified_diff(a, b, f"{old_id}", f"{new_id}", lineterm="", n=2))[:12000]


def final_run(con, pm_dir: Path, root, now: datetime, policy_id: str, params: dict, data: Optional[dict] = None, box=None) -> dict:
    """The one final check of (policy, params): recorded, and refused a second time. Returns the final scorecard and the baseline's over the same window."""
    had = service.latest_run(con, policy_id, "final", params)
    base = service.baseline_history(con, pm_dir, root, now, data=data, box=box, win="final")
    if had:
        return {"score": had["score"], "baseline": base, "repeat": True}
    p = service.get(con, policy_id)
    from pflab.lab import policy_api
    data = data if data is not None else runner.panel_data(root, pm_dir)
    out = runner.run(data, [{"id": policy_id, "code": p["code"]}], runner.FINAL, {policy_id: [params]}, None, n_shuffles=0, n_mc=0, time_limit=1200, box=box)
    if out.get("error") or policy_id in out.get("errors", {}):
        return {"error": out.get("error") or out["errors"][policy_id][-300:]}
    rows = service.record_rows(con, now, policy_id, "final", out["results"][policy_id], None, bool(out.get("contained")), float(out.get("seconds") or 0.0))
    return {"score": rows[0]["score"], "baseline": base, "repeat": False}


def check(con, pm_dir: Path, root, now: datetime, challenger_id: str, data: Optional[dict] = None, box=None, run_final: bool = True) -> dict:
    """Is the challenger ready to replace the champion? Returns {ready, reasons: [...], history, shadow, final}. Runs the final check once when the other two hold."""
    p = service.get(con, challenger_id)
    if not p or p["status"] != "challenger":
        return {"ready": False, "reasons": [f"{challenger_id} is not a challenger"]}
    hist = service.latest_run(con, challenger_id, "history", p["params"])
    if hist is None:
        return {"ready": False, "reasons": ["no scored history run"]}
    base = service.baseline_history(con, pm_dir, root, now, data=data, box=box)
    base_score = service.latest_run(con, service.BASELINE_ID, "history")["score"]
    sc = service.screen(hist["score"], hist["shuffled"], base_score)
    reasons = list(sc["failed"])
    idx = service.index_clause(hist["score"])
    reasons += idx["failed"]
    champ = shadow.champion_row(con)
    if champ and champ["policy_id"] != "baseline_v1" and champ["code"]:
        ch = service.latest_run(con, champ["policy_id"], "history", champ["params"])
        if ch and hist["score"]["cagr"] <= ch["score"]["cagr"]:
            reasons.append(f"its history return {hist['score']['cagr']:.1%} is not above the champion's {ch['score']['cagr']:.1%}")
    rec = shadow.record(con, challenger_id)
    if rec["sessions"] < service.SHADOW_SESSIONS:
        reasons.append(f"{rec['sessions']} of {service.SHADOW_SESSIONS} live shadow sessions so far")
    elif rec["excess"] < -SHADOW_TOLERANCE:
        reasons.append(f"over {rec['sessions']} shadow sessions it did worse than the champion's stand-in ({rec['excess']:+.2%})")
    final = None
    if not reasons and run_final:
        final = final_run(con, pm_dir, root, now, challenger_id, p["params"], data=data, box=box)
        if final.get("error"):
            reasons.append("the final check could not run: " + final["error"])
        else:
            fs, fb = final["score"], final["baseline"]
            if fs["cagr"] < fb["cagr"]:
                reasons.append(f"final check 2018-2021: {fs['cagr']:.1%} against the baseline's {fb['cagr']:.1%}")
            if fs["max_drawdown"] < fb["worst_fall"] - service.SCREEN["max_extra_drawdown"]:
                reasons.append(f"final check worst fall {fs['max_drawdown']:.1%} is far deeper than the baseline's {fb['worst_fall']:.1%}")
    return {"ready": not reasons, "reasons": reasons, "index_clause": idx, "held_back_only_by_index": bool(sc["ok"] and not idx["ok"]), "history": {"cagr": hist["score"]["cagr"], "dsr": hist["score"].get("dsr"), "max_drawdown": hist["score"]["max_drawdown"]},
            "shadow": rec, "final": None if final is None else {k: v for k, v in final.items() if k != "score"} | ({"cagr": final["score"]["cagr"]} if final.get("score") else {})}


def promote(con, pm_dir: Path, now: datetime, challenger_id: str, verdict: dict) -> dict:
    """Make a ready challenger the champion. Logs the diff and the scorecard. The old champion stays in the store (a lab policy becomes a challenger again)."""
    from pflab.pm.store import next_id
    if not verdict.get("ready"):
        return {"ok": False, "problem": "; ".join(verdict.get("reasons") or ["not ready"])}
    old = shadow.champion_row(con)
    old_id = old["policy_id"] if old else "baseline_v1"
    d = diff(con, old_id, challenger_id)
    con.execute("INSERT INTO core_promotions_s80 VALUES (?,?,?,?,?,?,?,?)", [next_id(con, "core_promotions_s80", "promo_id"), now, "promote", old_id, challenger_id, d,
                                                                           json.dumps(verdict, default=str), "cleared history, shadow and the final check"])
    if old and old_id != "baseline_v1":
        con.execute("UPDATE core_policies_s80 SET status='challenger' WHERE policy_id=?", [old_id])
    elif old:
        con.execute("UPDATE core_policies_s80 SET status='previous' WHERE policy_id='baseline_v1'")
    con.execute("UPDATE core_policies_s80 SET status='champion', promoted_at=? WHERE policy_id=?", [now, challenger_id])
    return {"ok": True, "champion": challenger_id, "previous": old_id}


def promote_ready(con, pm_dir: Path, root, now: datetime, data: Optional[dict] = None, box=None) -> list:
    """Every challenger is checked; the first that is ready is promoted (one promotion at a time). Returns what was found."""
    out = []
    for (pid,) in con.execute("SELECT policy_id FROM core_policies_s80 WHERE status='challenger' ORDER BY policy_id").fetchall():
        v = check(con, pm_dir, root, now, pid, data=data, box=box)
        out.append({"policy_id": pid, "ready": v["ready"], "reasons": v["reasons"][:4]})
        if v["ready"]:
            out[-1]["promoted"] = promote(con, pm_dir, now, pid, v)
            break
    return out


def rollback_check(con, now: datetime) -> Optional[dict]:
    """If the champion (a lab policy) has been below its own history range for ROLLBACK_SESSIONS sessions in a row, the previous champion replaces it. The range: the 5th
    percentile of its Monte Carlo worst fall; the live measure: the account's fall from its high since the promotion."""
    from pflab.paper import cadence
    from pflab.pm.store import next_id
    c = shadow.champion_row(con)
    if not c or c["policy_id"] == "baseline_v1" or not c["promoted_at"]:
        return None
    h = service.latest_run(con, c["policy_id"], "history", c["params"])
    floor = (h or {}).get("mc", {}).get("mc_worst_fall_p5")
    if floor is None:
        return None
    path = [(d, g) for d, g in cadence.level_path(con) if d >= c["promoted_at"].date()]
    if len(path) < ROLLBACK_SESSIONS:
        return None
    peak, below = 0.0, []
    for _, g in path:
        peak = max(peak, g)
        below.append(g / peak - 1.0 < floor)
    if not all(below[-ROLLBACK_SESSIONS:]):
        return None
    prev = con.execute("SELECT from_policy FROM core_promotions_s80 WHERE to_policy=? AND kind='promote' ORDER BY promo_id DESC LIMIT 1", [c["policy_id"]]).fetchone()
    prev_id = prev[0] if prev else "baseline_v1"
    con.execute("INSERT INTO core_promotions_s80 VALUES (?,?,?,?,?,?,?,?)", [next_id(con, "core_promotions_s80", "promo_id"), now, "rollback", c["policy_id"], prev_id, diff(con, c["policy_id"], prev_id),
                                                                           json.dumps({"floor": floor, "sessions": ROLLBACK_SESSIONS}), f"below its own history range (worst-fall 5th percentile {floor:.1%}) for {ROLLBACK_SESSIONS} sessions"])
    con.execute("UPDATE core_policies_s80 SET status='retired', note='rolled back: below its own history range' WHERE policy_id=?", [c["policy_id"]])
    con.execute("UPDATE core_policies_s80 SET status='champion', promoted_at=? WHERE policy_id=?", [now, prev_id])
    return {"rolled_back": c["policy_id"], "to": prev_id}
