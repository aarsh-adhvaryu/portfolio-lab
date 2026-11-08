"""The lab's operations (S80 phase 2): the policy store, the lab runs and their scorecards, the notes, the challengers. These are the strategist's hands; the system's own bookkeeping
(shadow, promotion, rollback) lives in `shadow.py` and `promotion.py`. Everything returns small dicts: a scorecard row and an id, never raw output (the doc's context rule).

The rules here are the lab's registered tests (rule 10 as amended by A47): a variant must clear them to be promoted, and every variant ever tried counts as a trial in the deflated
Sharpe, so the bar rises with the number of tries. The 2018-2021 final check is NOT a strategist tool: `promotion.check` runs it once per variant, when the live shadow record is
long enough, so the holdout cannot be looked at again and again.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from pflab.lab import engine, policy_api, runner

BASELINE_ID = "baseline_lab"
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
MAX_CHALLENGERS = 5
SHADOW_SESSIONS = 20                       # live sessions a challenger must not do worse in before it can replace the champion
# The registered history screen (vs the plain baseline over the same window, after the many-trials penalty):
SCREEN = {"min_dsr": 0.90, "min_excess_vs_baseline": 0.005, "max_beats_real_frac": 0.10, "max_extra_drawdown": 0.05}


def now_or(now: Optional[datetime]) -> datetime:
    return now or datetime.now()


def policies_dir(pm_dir: Path) -> Path:
    p = Path(pm_dir) / "policies"
    p.mkdir(parents=True, exist_ok=True)
    return p


def baseline_code() -> str:
    return (Path(__file__).resolve().parent / "policies" / "baseline_lab.py").read_text(encoding="utf-8")


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]


def ensure_baseline(con, now: datetime) -> None:
    """The plain rule book the lab measures against: registered once, status 'reference' (it is never a challenger; the live baseline's lab stand-in)."""
    code = baseline_code()
    r = con.execute("SELECT code_hash FROM core_policies_s80 WHERE policy_id=?", [BASELINE_ID]).fetchone()
    if r is None:
        con.execute("INSERT INTO core_policies_s80 (policy_id, status, code_hash, created_at, note, code, params_json) VALUES (?,?,?,?,?,?,?)",
                    [BASELINE_ID, "reference", code_hash(code), now, "the plain rule book: liquid names and the index ETFs sized by risk, caps, a fall gauge", code, "{}"])
    elif r[0] != code_hash(code):
        con.execute("UPDATE core_policies_s80 SET code=?, code_hash=? WHERE policy_id=?", [code, code_hash(code), BASELINE_ID])


def get(con, policy_id: str) -> Optional[dict]:
    r = con.execute("SELECT policy_id, status, code_hash, created_at, promoted_at, note, parent_id, hypothesis, session_id, code, params_json FROM core_policies_s80 WHERE policy_id=?",
                    [policy_id]).fetchone()
    if not r:
        return None
    d = dict(zip(("policy_id", "status", "code_hash", "created_at", "promoted_at", "note", "parent_id", "hypothesis", "session_id", "code", "params_json"), r))
    d["params"] = json.loads(d["params_json"] or "{}")
    return d


def listing(con, statuses=("draft", "challenger", "champion", "reference")) -> List[dict]:
    ph = ",".join("?" for _ in statuses)
    rows = con.execute(f"SELECT policy_id, status, hypothesis, parent_id, created_at FROM core_policies_s80 WHERE status IN ({ph}) ORDER BY created_at DESC", list(statuses)).fetchall()
    return [{"policy_id": a, "status": b, "hypothesis": (c or "")[:140], "parent": d, "created": str(e)[:10]} for a, b, c, d, e in rows]


def add_variant(con, pm_dir: Path, now: datetime, policy_id: str, code: str, hypothesis: str, parent: Optional[str] = None, session_id: Optional[int] = None) -> dict:
    """Validate and store a policy (status 'draft'). A new id each time: an edit is a new variant with `parent` set, so the lineage and the trial count stay honest."""
    if not ID_RE.match(policy_id or ""):
        return {"ok": False, "problem": "policy_id must be lowercase letters, digits and underscores, 3-41 characters, starting with a letter"}
    if policy_id in (BASELINE_ID, "baseline_v1") or get(con, policy_id):
        return {"ok": False, "problem": f"{policy_id} already exists: give an edit a new id and name its parent"}
    if len(" ".join((hypothesis or "").split())) < 15:
        return {"ok": False, "problem": "state the hypothesis in one line (what this variant leans on and why)"}
    if parent and not get(con, parent):
        return {"ok": False, "problem": f"parent {parent} is not a known policy"}
    bad = policy_api.validate(code)
    if bad:
        return {"ok": False, "problem": "the policy was refused: " + "; ".join(bad[:4])}
    try:
        _, grid = policy_api.load(code)
        combos = policy_api.expand_grid(grid)
    except Exception as e:
        return {"ok": False, "problem": f"the policy does not load: {type(e).__name__}: {str(e)[:200]}"}
    d = policies_dir(pm_dir) / policy_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "policy.py").write_text(code, encoding="utf-8")
    con.execute("INSERT INTO core_policies_s80 (policy_id, status, code_hash, created_at, note, parent_id, hypothesis, session_id, code, params_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [policy_id, "draft", code_hash(code), now, None, parent, " ".join(hypothesis.split())[:300], session_id, code, "{}"])
    return {"ok": True, "policy_id": policy_id, "combinations": len(combos), "next": "run_lab on it; a challenger needs a scored history run"}


# --- lab runs ---------------------------------------------------------------------------------------------------------------------

def _trial_sharpes(con) -> List[float]:
    """Every distinct variant (policy x params) ever scored on the history window: the many-trials count the deflated Sharpe corrects for."""
    rows = con.execute("SELECT policy_id, params_json, sharpe_daily FROM lab_runs_s80 WHERE win='history' AND sharpe_daily IS NOT NULL AND policy_id <> ?", [BASELINE_ID]).fetchall()
    seen = {}
    for p, pj, s in rows:
        seen[(p, pj)] = float(s)
    return list(seen.values())


def n_trials(con) -> int:
    return len(_trial_sharpes(con))


def record_rows(con, now: datetime, policy_id: str, win: str, res: dict, session_id: Optional[int], contained: bool, seconds: float) -> List[dict]:
    from pflab.pm.store import next_id
    out = []
    for row in res["runs"]:
        s = row["score"]
        rid = next_id(con, "lab_runs_s80", "run_id")
        con.execute("INSERT INTO lab_runs_s80 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [rid, policy_id, win, json.dumps(row["params"], sort_keys=True), now, session_id, json.dumps(s), json.dumps(row.get("shuffled") or {}), json.dumps(row.get("mc") or {}),
                     float(s.get("dsr", 0.0)), float(s["sharpe_daily"]), res.get("n_trials"), seconds, bool(contained)])
        out.append({"run_id": rid, "params": row["params"], "score": s, "shuffled": row.get("shuffled") or {}, "mc": row.get("mc") or {}})
    return out


def redeflate(con, policy_id: str) -> None:
    """After new trials, the deflated Sharpe of this policy's history rows is recomputed against ALL trials (the bar rose)."""
    srs = _trial_sharpes(con)
    for rid, sj in con.execute("SELECT run_id, score_json FROM lab_runs_s80 WHERE policy_id=? AND win='history'", [policy_id]).fetchall():
        s = json.loads(sj)
        dsr = engine.deflated_sharpe(s["sharpe_daily"], s["n_obs"], s["skew"], s["kurt"], srs or [s["sharpe_daily"]])
        s["dsr"] = dsr
        con.execute("UPDATE lab_runs_s80 SET score_json=?, dsr=?, n_trials=? WHERE run_id=?", [json.dumps(s), dsr, len(srs), rid])


def card_row(r: dict) -> dict:
    """The small result the strategist reads for one variant: a scorecard row, never raw output."""
    s, sh, mc = r["score"], r.get("shuffled") or {}, r.get("mc") or {}
    return {"run_id": r["run_id"], "params": r["params"], "cagr_after_tax_costs": round(s["cagr"], 4), "benchmark_cagr": round(s["bench_cagr"], 4), "excess": round(s["excess_cagr"], 4),
            "worst_fall": round(s["max_drawdown"], 4), "days_to_recover": s["recovery_days"], "turnover_per_year": round(s["turnover_per_year"], 2), "tax_paid": round(s["tax_paid"]),
            "charges": round(s["charges"]), "sharpe": round(s["sharpe"], 3), "deflated_sharpe": round(s.get("dsr", 0.0), 3),
            "shuffled_beat_it_share": sh.get("beats_real_frac"), "shuffled_cagr_mean": None if not sh else round(sh["cagr_mean"], 4),
            "monte_carlo_1y_p5_p50_p95": [round(mc[k], 3) for k in ("mc_1y_p5", "mc_1y_p50", "mc_1y_p95")] if mc else None}


def run_lab(con, pm_dir: Path, root, now: datetime, policy_id: str, n_shuffles: int = 10, session_id: Optional[int] = None, data: Optional[dict] = None, box=None,
            time_limit: int = 1800) -> dict:
    """Walk-forward replay of every combination of the policy's grid over the HISTORY window (2005-2017), with its shuffled-signal runs and Monte Carlo, in the sandbox. Each
    combination is a trial. Returns the scorecard rows (small), with the run ids of the full records."""
    ensure_baseline(con, now)
    p = get(con, policy_id)
    if not p or p["status"] in ("retired",):
        return {"ok": False, "problem": f"{policy_id} is not a policy you can run"}
    try:
        fn, grid = policy_api.load(p["code"])
        combos = policy_api.expand_grid(grid)
    except Exception as e:
        return {"ok": False, "problem": f"the policy does not load: {str(e)[:200]}"}
    data = data if data is not None else runner.panel_data(root, pm_dir)
    box = box
    out = runner.run(data, [{"id": policy_id, "code": p["code"]}], runner.HISTORY, {policy_id: combos}, None, n_shuffles=int(n_shuffles), n_mc=500, time_limit=time_limit, box=box)
    if out.get("error"):
        return {"ok": False, "problem": out["error"], "contained": out.get("contained")}
    if policy_id in out.get("errors", {}):
        return {"ok": False, "problem": out["errors"][policy_id][-500:], "last_lines": out["errors"][policy_id].splitlines()[-30:]}
    rows = record_rows(con, now, policy_id, "history", out["results"][policy_id], session_id, bool(out.get("contained")), float(out.get("seconds") or 0.0))
    redeflate(con, policy_id)
    fresh = []
    for r in rows:
        again = con.execute("SELECT score_json, shuffled_json, mc_json FROM lab_runs_s80 WHERE run_id=?", [r["run_id"]]).fetchone()
        r["score"], r["shuffled"], r["mc"] = json.loads(again[0]), json.loads(again[1]), json.loads(again[2])
        fresh.append(card_row(r))
    base = baseline_history(con, pm_dir, root, now, data=data, box=box)
    return {"ok": True, "policy_id": policy_id, "window": [str(runner.HISTORY[0]), str(runner.HISTORY[1])], "trials_so_far": n_trials(con), "scorecards": fresh,
            "baseline": base, "contained": bool(out.get("contained")), "seconds": out.get("seconds"),
            "note": "walk-forward replay, after tax and charges; deflated Sharpe counts every variant tried so far; a challenger needs a clean screen (see screen_rules)"}


def latest_run(con, policy_id: str, win: str = "history", params: Optional[dict] = None) -> Optional[dict]:
    q = "SELECT run_id, params_json, score_json, shuffled_json, mc_json, dsr FROM lab_runs_s80 WHERE policy_id=? AND win=?"
    a: list = [policy_id, win]
    if params is not None:
        q += " AND params_json=?"
        a.append(json.dumps(params, sort_keys=True))
    r = con.execute(q + " ORDER BY run_id DESC LIMIT 1", a).fetchone()
    if not r:
        return None
    return {"run_id": r[0], "params": json.loads(r[1]), "score": json.loads(r[2]), "shuffled": json.loads(r[3] or "{}"), "mc": json.loads(r[4] or "{}")}


def baseline_history(con, pm_dir: Path, root, now: datetime, data: Optional[dict] = None, box=None, win: str = "history") -> dict:
    """The plain baseline's scorecard over the same window (run once and kept; it is not a trial)."""
    ensure_baseline(con, now)
    r = latest_run(con, BASELINE_ID, win)
    if r is None:
        data = data if data is not None else runner.panel_data(root, pm_dir)
        window = runner.HISTORY if win == "history" else runner.FINAL
        out = runner.run(data, [{"id": BASELINE_ID, "code": baseline_code()}], window, {BASELINE_ID: [{}]}, None, n_shuffles=0, n_mc=300, box=box)
        if out.get("error") or BASELINE_ID in out.get("errors", {}):
            return {"error": out.get("error") or out["errors"][BASELINE_ID][-300:]}
        rows = record_rows(con, now, BASELINE_ID, win, out["results"][BASELINE_ID], None, bool(out.get("contained")), float(out.get("seconds") or 0.0))
        r = {"run_id": rows[0]["run_id"], "params": {}, "score": rows[0]["score"], "shuffled": {}, "mc": rows[0]["mc"]}
    s = r["score"]
    return {"cagr": round(s["cagr"], 4), "benchmark_cagr": round(s["bench_cagr"], 4), "worst_fall": round(s["max_drawdown"], 4), "sharpe": round(s["sharpe"], 3)}


def screen(score: dict, shuffled: dict, base: dict) -> dict:
    """The registered history screen against the baseline's scorecard over the same window. -> {ok, failed: [...], measures}"""
    failed = []
    if score.get("dsr", 0.0) < SCREEN["min_dsr"]:
        failed.append(f"deflated Sharpe {score.get('dsr', 0.0):.2f} is under {SCREEN['min_dsr']}")
    if score["cagr"] - base["cagr"] < SCREEN["min_excess_vs_baseline"]:
        failed.append(f"after-tax return {score['cagr']:.1%} does not beat the baseline's {base['cagr']:.1%} by {SCREEN['min_excess_vs_baseline']:.1%}")
    if shuffled and shuffled.get("beats_real_frac", 1.0) > SCREEN["max_beats_real_frac"]:
        failed.append(f"{shuffled['beats_real_frac']:.0%} of shuffled-signal runs did as well (limit {SCREEN['max_beats_real_frac']:.0%})")
    if not shuffled:
        failed.append("no shuffled-signal runs: luck was not measured")
    if score["max_drawdown"] < base["max_drawdown"] - SCREEN["max_extra_drawdown"]:
        failed.append(f"worst fall {score['max_drawdown']:.1%} is more than {SCREEN['max_extra_drawdown']:.0%} deeper than the baseline's {base['max_drawdown']:.1%}")
    return {"ok": not failed, "failed": failed}


def screen_rules() -> dict:
    return {**SCREEN, "shadow_sessions": SHADOW_SESSIONS, "note": "all four must hold on the history window; then the final check (2018-2021, once, by code) and 20 live shadow sessions not worse than the champion's"}


# --- challengers, notes -----------------------------------------------------------------------------------------------------------

def make_challenger(con, now: datetime, policy_id: str, params: Optional[dict] = None, why: str = "") -> dict:
    """A variant with a scored history run enters live shadow as a challenger (at most MAX_CHALLENGERS at once). It does not need to have cleared the screen (the screen guards
    promotion), but a run with a failed policy or no shuffled runs cannot be a challenger."""
    p = get(con, policy_id)
    if not p or p["status"] not in ("draft", "challenger"):
        return {"ok": False, "problem": f"{policy_id} is not a draft variant"}
    r = latest_run(con, policy_id, "history", params if params is not None else None)
    if r is None:
        return {"ok": False, "problem": "run_lab on it first (and name the params you mean if it has a grid)"}
    if not r["shuffled"]:
        return {"ok": False, "problem": "that run has no shuffled-signal measurement"}
    n = con.execute("SELECT count(*) FROM core_policies_s80 WHERE status='challenger'").fetchone()[0]
    if p["status"] != "challenger" and n >= MAX_CHALLENGERS:
        return {"ok": False, "problem": f"there are already {MAX_CHALLENGERS} challengers: retire one first"}
    con.execute("UPDATE core_policies_s80 SET status='challenger', params_json=?, note=? WHERE policy_id=?", [json.dumps(r["params"], sort_keys=True), (why or "")[:300], policy_id])
    return {"ok": True, "policy_id": policy_id, "params": r["params"], "status": "challenger", "next": "it runs in shadow at every close and is scored daily"}


def retire(con, now: datetime, policy_id: str, why: str) -> dict:
    p = get(con, policy_id)
    if not p or p["status"] in ("champion", "reference"):
        return {"ok": False, "problem": "the champion and the reference cannot be retired this way"}
    con.execute("UPDATE core_policies_s80 SET status='retired', note=? WHERE policy_id=?", [(why or "")[:300], policy_id])
    return {"ok": True, "policy_id": policy_id, "status": "retired"}


def write_note(con, now: datetime, session_id: Optional[int], text: str) -> dict:
    from pflab.pm.store import next_id
    text = " ".join((text or "").split())
    if len(text) < 20:
        return {"ok": False, "problem": "the note must say what was tried, what won and what was learned"}
    nid = next_id(con, "core_notes_s80", "note_id")
    con.execute("INSERT INTO core_notes_s80 VALUES (?,?,?,?)", [nid, session_id, now, text[:2500]])
    return {"ok": True, "note_id": nid}


def notes(con, limit: int = 5) -> List[dict]:
    return [{"note_id": a, "session_id": b, "at": str(c)[:16], "text": d} for a, b, c, d in con.execute(
        "SELECT note_id, session_id, written_at, text FROM core_notes_s80 ORDER BY note_id DESC LIMIT ?", [limit]).fetchall()]
