"""S85 L1 (4): BOUNDED THRESHOLD TUNING (T8's automatic half). Once a week the loop may move ONE `[think]` threshold by at most 10% toward fewer misses at the same cases-per-day, from the evidence the
loop itself keeps: the misses ("what did I miss", `missed.py`: `below_threshold` rows name the threshold that would have caught them) and the false alarms (cases closed "quiet": nothing happened).
This is a registered rule (`docs/protocols/s84_thinking_live_protocol.md`, Amendment A2, 2026-11-13); `RULE` below is that block in code and `tests/test_s85_wide.py` pins the two together.

    run_weekly(con, now, root=None) -> dict   the job's entry: gate, propose, apply (at most once a week); `{"changed": False, "why": ...}` when it does not
    propose(con, day) -> dict | None          the one change the rule would make today (pure: reads, writes nothing)
    apply(con, day, proposal) -> tuning_id    a dated row in `think_tuning_s84` and the override `think.settings()` reads on top of the config (the config FILE is never edited)
    revert(con, tuning_id=None, day=None, why="") -> dict    undo the change (the latest applied one when no id is given); the row stays, marked reverted
    status(con) -> dict                       the overrides, the counts against the gates, the last changes; plain text for the reports

The rule (every number is `RULE`):
  gate      never on fewer than `min_scored` (40) scored decisions at 20 sessions AND fewer than `min_misses` (60) stored misses (either count opens the gate); the amendment must be registered;
  rhythm    one threshold a week (no change if one was applied in the last 7 days);
  evidence  per threshold over the last `window_days` (90): misses = `below_threshold` misses it would have caught, alarms = quiet cases whose strongest signal it governs; it needs at least
            `min_param_evidence` (5) of the two together, and the threshold with the largest |misses - alarms| is the one changed;
  direction misses ahead of alarms: LOWER it (more cases), but only when the cases-per-day is under 90% of the daily cap (a lower line adds nothing the cap would not drop), and never lower than the
            25th percentile of the values that would have caught the misses; alarms ahead: RAISE it;
  step      at most `step_max` (10%) of today's value, and never outside `band` [0.5x, 2x] of the CONFIG value; a threshold that is already at the edge of its band is not moved;
  record    a dated row (the numbers it saw, the direction, the reason), applied through an override table, reversible (`revert`).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import numpy as np

from pflab import think

RULE = {
    "step_max": 0.10,
    "band": [0.5, 2.0],
    "per_week": 1,
    "min_scored": 40,
    "min_misses": 60,
    "window_days": 90,
    "min_param_evidence": 5,
    "cap_binding_share": 0.9,
    "lower_to_percentile": 25,
    "tunable": ["move_sigmas", "fall_pct_10d", "rel_pts_5d", "news_burst_x", "storyline_jump_pts", "market_down_20d", "missed_run_pts", "wide_run_pts"],
}
SIGNAL_PARAM = {"move_1d": "move_sigmas", "move_5d": "move_sigmas", "rel_1d": "move_sigmas", "rel_5d": "move_sigmas", "fall_10d": "fall_pct_10d", "rel_fall_5d": "rel_pts_5d",
                "news_burst": "news_burst_x", "storyline_jump": "storyline_jump_pts", "market_down_20d": "market_down_20d", "missed_run": "missed_run_pts", "wide_run_20d": "wide_run_pts"}
AMENDMENT_NOTE = "s84:thinking_live_a2"


def _tid(con) -> int:
    from pflab.pm.store import next_id
    return next_id(con, "think_tuning_s84", "tuning_id")


def config_value(param: str) -> Optional[float]:
    """The value the CONFIG (file over the defaults) gives, without any override."""
    v = think.settings(raw=True).get(param)
    if v is None:
        from pflab.think import wide
        v = wide.WIDE_DEFAULTS.get(param)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def effective_value(param: str) -> Optional[float]:
    v = think.settings().get(param)
    if v is None:
        return config_value(param)
    try:
        return float(v)
    except (TypeError, ValueError):
        return config_value(param)


# --- the counts, the evidence ---------------------------------------------------------------------------------------------------------------------------------------------------

def counts(con) -> dict:
    try:
        scored = int(con.execute("SELECT count(DISTINCT decision_id) FROM think_scores_s84 WHERE horizon_sessions=20").fetchone()[0])
    except Exception:
        scored = 0
    try:
        misses = int(con.execute("SELECT count(*) FROM think_misses_s84 WHERE kind IN ('cap','below_threshold','outside_scope','no_event')").fetchone()[0])
    except Exception:
        misses = 0
    return {"scored": scored, "misses": misses, "min_scored": RULE["min_scored"], "min_misses": RULE["min_misses"],
            "gate_open": scored >= RULE["min_scored"] or misses >= RULE["min_misses"]}


def false_alarms(con, since: date) -> List[dict]:
    """Cases that were thought through and closed 'quiet' (nothing happened) since `since`: [{case_id, param}] (the threshold that governs the case's strongest signal)."""
    out = []
    try:
        rows = con.execute("SELECT case_id FROM think_cases_s84 WHERE state='closed' AND closed_reason LIKE 'quiet for%' AND closed_on > ? ORDER BY case_id", [since]).fetchall()
    except Exception:
        return out
    for (cid,) in rows:
        r = con.execute("SELECT signal FROM think_signals_s84 WHERE case_id=? ORDER BY score DESC LIMIT 1", [cid]).fetchone()
        p = SIGNAL_PARAM.get(r[0]) if r else None
        if p:
            out.append({"case_id": int(cid), "param": p, "signal": r[0]})
    return out


def misses_by_param(con, since: date) -> Dict[str, List[float]]:
    """param -> the values that would have caught each `below_threshold` miss since `since`."""
    out: Dict[str, List[float]] = {}
    try:
        rows = con.execute("SELECT detail FROM think_misses_s84 WHERE kind='below_threshold' AND day > ?", [since]).fetchall()
    except Exception:
        return out
    for (d,) in rows:
        try:
            wc = (json.loads(d or "{}") or {}).get("would_catch")
        except Exception:
            wc = None
        if wc and wc.get("param") in RULE["tunable"] and wc.get("value") is not None:
            out.setdefault(wc["param"], []).append(float(wc["value"]))
    return out


def cases_per_day(con, day: date, days: int = 20) -> float:
    r = con.execute("SELECT count(*), count(DISTINCT opened_on) FROM think_cases_s84 WHERE state <> 'noticed' AND opened_on > ? AND opened_on <= ?", [day - timedelta(days=days), day]).fetchone()
    passes = int(con.execute("SELECT count(DISTINCT day) FROM think_watch_runs_s84 WHERE day > ? AND day <= ?", [day - timedelta(days=days), day]).fetchone()[0]) or int(r[1] or 0)
    return float(r[0]) / passes if passes else 0.0


# --- the rule ------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def propose(con, day: date) -> Optional[dict]:
    """The ONE change the rule would make on `day`, or None. Pure."""
    since = day - timedelta(days=int(RULE["window_days"]))
    miss = misses_by_param(con, since)
    alarms: Dict[str, int] = {}
    for a in false_alarms(con, since):
        alarms[a["param"]] = alarms.get(a["param"], 0) + 1
    cap = float(think.settings()["max_cases_per_day"])
    cpd = cases_per_day(con, day)
    cands = []
    for p in RULE["tunable"]:
        m, a = len(miss.get(p, [])), alarms.get(p, 0)
        if m + a < int(RULE["min_param_evidence"]):
            continue
        cands.append((abs(m - a), -RULE["tunable"].index(p), p, m, a))
    cands.sort(reverse=True)
    for _w, _i, p, m, a in cands:
        if m == a:
            continue
        cfg_v, cur = config_value(p), effective_value(p)
        if cfg_v is None or cur is None or cfg_v <= 0:
            continue
        lo, hi = cfg_v * RULE["band"][0], cfg_v * RULE["band"][1]
        if m > a:
            if cpd >= cap * float(RULE["cap_binding_share"]):
                continue                                          # the cap already binds: a lower line adds nothing
            new = cur * (1.0 - RULE["step_max"])
            vals = miss.get(p) or []
            if vals:
                new = max(new, float(np.percentile(vals, RULE["lower_to_percentile"])))
            direction = "lower"
            why = f"{m} missed move(s) a lower {p} would have caught against {a} false alarm(s); {cpd:.1f} cases a day against a cap of {cap:g}"
        else:
            new = cur * (1.0 + RULE["step_max"])
            direction = "raise"
            why = f"{a} false alarm(s) (cases that closed quiet) against {m} missed move(s) a lower {p} would have caught"
        new = min(max(new, lo), hi)
        if abs(new - cur) < 1e-9 * max(1.0, abs(cur)) or (direction == "lower" and new >= cur) or (direction == "raise" and new <= cur):
            continue                                              # at the edge of its band, or nothing to gain
        return {"param": p, "old_value": float(cur), "new_value": float(new), "config_value": float(cfg_v), "direction": direction, "reason": why,
                "counts": {"misses_for": m, "false_alarms": a, "cases_per_day": round(cpd, 2), "cap": cap, **counts(con)}}
    return None


# --- apply, revert, the override the settings read --------------------------------------------------------------------------------------------------------------------------

def sync_file(con) -> dict:
    """Write the active overrides where `think.settings()` reads them (a small JSON beside the store). The table is the record; the file is its copy. Returns what was written."""
    rows = con.execute("SELECT param, value FROM think_overrides_s84 WHERE active").fetchall()
    data = {p: float(v) for p, v in rows}
    think.write_overrides(data)
    return data


def apply(con, day: date, proposal: dict) -> int:
    p = proposal["param"]
    if p not in RULE["tunable"]:
        raise ValueError(f"{p} is not a tunable threshold")
    cfg_v = float(proposal["config_value"])
    new = float(proposal["new_value"])
    if not (cfg_v * RULE["band"][0] - 1e-12 <= new <= cfg_v * RULE["band"][1] + 1e-12):
        raise ValueError(f"{p} {new} is outside [{RULE['band'][0]}x, {RULE['band'][1]}x] of the config value {cfg_v}")
    tid = _tid(con)
    con.execute("INSERT INTO think_tuning_s84 VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [tid, day, p, float(proposal["old_value"]), new, cfg_v, proposal["direction"], proposal["reason"][:400],
                                                                                    json.dumps(proposal.get("counts") or {}, default=str), "applied", None, None])
    con.execute("DELETE FROM think_overrides_s84 WHERE param=?", [p])
    con.execute("INSERT INTO think_overrides_s84 VALUES (?,?,?,?,?)", [p, new, day, tid, True])
    sync_file(con)
    return tid


def revert(con, tuning_id: Optional[int] = None, day: Optional[date] = None, why: str = "reverted") -> dict:
    """Undo a change: the threshold goes back to its value before (the config value when that was it). The row stays, marked reverted. Returns what was reverted or {"reverted": False}."""
    day = day or date.today()
    if tuning_id is None:
        r = con.execute("SELECT tuning_id FROM think_tuning_s84 WHERE state='applied' ORDER BY tuning_id DESC LIMIT 1").fetchone()
        if not r:
            return {"reverted": False, "why": "no applied change"}
        tuning_id = int(r[0])
    row = con.execute("SELECT param, old_value, config_value, state FROM think_tuning_s84 WHERE tuning_id=?", [tuning_id]).fetchone()
    if not row or row[3] != "applied":
        return {"reverted": False, "why": "no such applied change"}
    p, old, cfg_v, _ = row
    con.execute("UPDATE think_tuning_s84 SET state='reverted', reverted_on=?, reverted_why=? WHERE tuning_id=?", [day, why[:200], tuning_id])
    con.execute("DELETE FROM think_overrides_s84 WHERE param=? AND tuning_id=?", [p, tuning_id])
    if abs(float(old) - float(cfg_v)) > 1e-12:                                # the value before was itself a tuned one: put it back
        con.execute("DELETE FROM think_overrides_s84 WHERE param=?", [p])
        con.execute("INSERT INTO think_overrides_s84 VALUES (?,?,?,?,?)", [p, float(old), day, None, True])
    sync_file(con)
    return {"reverted": True, "tuning_id": int(tuning_id), "param": p, "back_to": float(old)}


def _registered(con, now: datetime) -> bool:
    try:
        from pflab.learner import s84
        s84.register_thinking_amendment_a2(con, now)
        return bool(con.execute("SELECT 1 FROM learn_tests WHERE note=?", [AMENDMENT_NOTE]).fetchone())
    except Exception:
        return False


def run_weekly(con, now: datetime, root=None) -> dict:
    """The job's entry. Off unless `[think] tune_thresholds` is on; under the gate's counts it only says so. Never raises."""
    day = now.date()
    try:
        sync_file(con)
        if not think.settings().get("tune_thresholds", False):
            return {"changed": False, "why": "switched off ([think] tune_thresholds)"}
        c = counts(con)
        if not c["gate_open"]:
            return {"changed": False, "why": f"under the counts: {c['scored']} scored decisions (need {c['min_scored']}) and {c['misses']} stored misses (need {c['min_misses']})", "counts": c}
        if not _registered(con, now):
            return {"changed": False, "why": "the protocol's Amendment A2 is not registered", "counts": c}
        last = con.execute("SELECT max(proposed_on) FROM think_tuning_s84 WHERE state IN ('applied','reverted')").fetchone()[0]
        if last is not None and (day - last).days < 7:
            return {"changed": False, "why": f"one threshold a week: the last change was {last}", "counts": c}
        p = propose(con, day)
        if p is None:
            return {"changed": False, "why": "no threshold has enough evidence, or the cap binds, or every candidate is at its band's edge", "counts": c}
        tid = apply(con, day, p)
        return {"changed": True, "tuning_id": tid, **{k: p[k] for k in ("param", "old_value", "new_value", "direction", "reason")}}
    except Exception as ex:
        return {"changed": False, "error": repr(ex)[:300]}


def status(con) -> dict:
    """The overrides in force, the counts against the gates, the last changes; `text` in plain words."""
    ov = {p: float(v) for p, v in con.execute("SELECT param, value FROM think_overrides_s84 WHERE active").fetchall()}
    last = [dict(zip(("tuning_id", "proposed_on", "param", "old_value", "new_value", "direction", "state"), r)) for r in
            con.execute("SELECT tuning_id, proposed_on, param, old_value, new_value, direction, state FROM think_tuning_s84 ORDER BY tuning_id DESC LIMIT 5").fetchall()]
    c = counts(con)
    on = bool(think.settings().get("tune_thresholds", False))
    text = ((f"Threshold tuning is {'on' if on else 'off'}; {c['scored']} scored decisions and {c['misses']} stored misses so far (it needs {c['min_scored']} or {c['min_misses']}). ")
            + (("Changed: " + ", ".join(f"{p} {think.settings(raw=True).get(p, config_value(p))} -> {v:g}" for p, v in ov.items()) + ".") if ov else "No threshold has been changed."))
    return {"on": on, "overrides": ov, "counts": c, "last_changes": last, "text": text}
