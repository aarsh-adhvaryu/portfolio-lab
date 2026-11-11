"""The registered C4 studies of S82 (protocol `docs/protocols/s82_harvest_stops_protocol.md`): harvesting where it can help (claim A, two arms) and stops on long-term stocks (claim B).

    register(con, now)             count the three tests in the learner's counter (idempotent by note key; the protocol's SHA is stored; `learner.s79.register_c4` calls it at start-up)
    protocol_ok(con)               {registered, unchanged}: was it counted, and is the file the one that was counted
    claim_a_verdict / claim_b_verdict   the rule of the protocol in code (a test pins the numbers to the protocol's JSON block)
    run(con, pm_dir, root, now)    THE run, once, in the lab's sandbox on the real panel; refuses unless registered and unchanged, and refuses a second run
    apply_recorded(con, now)       the verdicts of THE run (recorded in `docs/research/c4_study_results_s82.json`) written onto a store once
    switches(result)               what the verdicts switch in `configs/core.toml` (the config file itself is edited by hand from this, in the commit that records the run)

The 2018-2021 window is NOT touched by this study. Nothing is wired live by this module: a passing arm is a line in the config, a failing one changes nothing (or, for the stops, turns them off).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[3]
PROTOCOL = REPO / "docs" / "protocols" / "s82_harvest_stops_protocol.md"
RESULTS = REPO / "docs" / "research" / "c4_study_results_s82.json"
TEMPLATE = "c4_s82"
NOTES = {"a_index": "s82:c4a:index", "a_stocks": "s82:c4a:stocks", "b_stops": "s82:c4b:stops"}

# The rule of the protocol, in code (section 4). tests/test_s82_lab.py reads the protocol's JSON block and compares.
RULE = {
    "history": ["2005-01-01", "2017-12-31"],
    "final_window_used": False,
    "capital": 1000000,
    "cash_rate": 0.065,
    "bootstrap": {"block": 21, "resamples": 5000, "seed": 82},
    "stock_book": {"n_names": 20, "turnover_window": 250, "min_history": 300, "vol_window": 250, "max_weight": 0.10, "rebalance": "never", "max_positions": 20, "max_new_per_day": 20},
    "stops": {"sigmas": 2.0, "horizon_days": 63, "vol_window": 250, "min_pct": 0.12, "max_pct": 0.35, "fallback_vol": 0.30, "target": "none", "time_stop": "none"},
    "slippage": {"half_spread_base": 0.0005, "half_spread_cap": 0.005, "turnover_ref": 100000000, "impact_y": 1.0, "sigma_window": 20, "sigma_floor": 0.005},
    "harvest": {"window_months": [1, 2, 3], "fill_fraction": 0.98, "round_trip_cost": 0.004, "guard_days": 30, "lt_months": 12},
    "claim_a_pass": {"min_dL_per_arm": 0.0005, "tax_saved_must_exceed_extra_costs": True, "min_t_vs_off": "counter.t_needed(N after registration)"},
    "claim_b_keep_stops": {"min_worst_fall_cut_relative": 0.20, "max_return_cost_per_year": 0.01},
    "switches": {"a_index_pass": "[exits] harvest_core = true", "a_stocks_pass": "[exits] harvest_longterm = true", "b_fail": "[exits.longterm] stop = false"},
}
RULE_A1 = {"stock_book_invested": 0.98, "deploy_once": True}


def protocol_sha() -> str:
    """SHA-256 of the protocol with its line ends normalised (a checkout that turns LF into CRLF must not look like an edit)."""
    if not PROTOCOL.exists():
        raise FileNotFoundError(f"the protocol file is missing: {PROTOCOL}")
    return hashlib.sha256(PROTOCOL.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def studies() -> tuple:
    return ((NOTES["a_index"], f"{TEMPLATE}:a_index", "harvesting adds after-tax return to the index ETFs held buy-and-hold, 2005-2017"),
            (NOTES["a_stocks"], f"{TEMPLATE}:a_stocks", "harvesting adds after-tax return to a buy-and-hold stock book, 2005-2017"),
            (NOTES["b_stops"], f"{TEMPLATE}:b_stops", "risk-sized stops on long-term stocks cut the worst fall by 20% at under 1 point a year of return, 2005-2017"))


def register(con, now: datetime) -> List[str]:
    """Count the three tests in the learner's counter (origin 'study'); idempotent by note key. The protocol file must exist and was committed before any run."""
    from pflab.learner import counter
    if not PROTOCOL.exists():
        return []
    sha, done = protocol_sha(), []
    for note, template, _ in studies():
        if con.execute("SELECT 1 FROM learn_tests WHERE note=?", [note]).fetchone():
            continue
        counter.record(con, now, "study", template, {"protocol": "docs/protocols/s82_harvest_stops_protocol.md", "protocol_sha256": sha}, note=note)
        done.append(note)
    return done


def protocol_ok(con) -> dict:
    notes = [n for n, _, _ in studies()]
    rows = con.execute("SELECT note, params_json FROM learn_tests WHERE note IN (%s)" % ",".join("?" for _ in notes), notes).fetchall()
    shas = {n: json.loads(p or "{}").get("protocol_sha256") for n, p in rows}
    try:
        now = protocol_sha()
    except FileNotFoundError:
        return {"registered": len(shas) == len(notes), "unchanged": False, "why": "the protocol file is missing"}
    ok = len(shas) == len(notes)
    same = ok and all(v == now for v in shas.values())
    return {"registered": ok, "unchanged": same, "why": None if same else ("not registered yet" if not ok else "the protocol file changed after it was registered")}


# --- the config the study runs under ----------------------------------------------------------------------------------------------------------------

def study_cfg() -> dict:
    """The tax rows (read from the tax engine, never typed), capital and cash rate: the S81 study's own configuration, which this study reuses."""
    from pflab.lab import swing_study
    cfg = swing_study.study_cfg()
    cfg["capital"], cfg["cash_rate"] = RULE["capital"], RULE["cash_rate"]
    return cfg


# --- the rule ---------------------------------------------------------------------------------------------------------------------------------------

def claim_a_verdict(arm: dict, n_tests: int) -> dict:
    """The protocol's section 4, claim A, for one arm of `c4_replay.claim_a`'s output. `n_tests`: the learner's N after registration."""
    from pflab.learner import counter
    r = RULE["claim_a_pass"]
    bar = counter.t_needed(n_tests)
    failed = []
    if arm["dL"] < r["min_dL_per_arm"]:
        failed.append(f"harvesting changes the liquidation return by {arm['dL']:+.3%} a year (needs {r['min_dL_per_arm']:+.3%})")
    if r["tax_saved_must_exceed_extra_costs"] and not arm["tax_saved"] > arm["extra_costs"]:
        failed.append(f"the tax saved (Rs {arm['tax_saved']:,.0f}) does not exceed the extra charges and slippage (Rs {arm['extra_costs']:,.0f})")
    if arm["t"] < bar:
        failed.append(f"paired t {arm['t']:.2f} on the liquidation-marked paths is under the learner's bar {bar:.2f} (N={n_tests})")
    return {"ok": not failed, "verdict": "pass" if not failed else "fail", "failed": failed, "t_bar": bar, "n_tests": n_tests}


def claim_b_verdict(b: dict) -> dict:
    """Claim B: keep the stops only if they cut the worst fall by at least 20% (relative) while costing at most 1 point a year of return after tax. `b`: `c4_replay.claim_b`'s output."""
    r = RULE["claim_b_keep_stops"]
    w, wo = b["with_stops"], b["without_stops"]
    cut = 1.0 - w["worst_fall"] / wo["worst_fall"] if wo["worst_fall"] > 0 else 0.0
    cost = wo["liq_cagr"] - w["liq_cagr"]
    failed = []
    if cut < r["min_worst_fall_cut_relative"]:
        failed.append(f"the worst fall is {w['worst_fall']:.1%} with stops and {wo['worst_fall']:.1%} without: a cut of {cut:.0%} (needs {r['min_worst_fall_cut_relative']:.0%})")
    if cost > r["max_return_cost_per_year"]:
        failed.append(f"the stops cost {cost:+.2%} a year of return after tax (limit {r['max_return_cost_per_year']:.2%})")
    return {"ok": not failed, "verdict": "pass" if not failed else "fail", "failed": failed, "worst_fall_cut_relative": cut, "return_cost_per_year": cost,
            "worst_fall_with": w["worst_fall"], "worst_fall_without": wo["worst_fall"], "liq_cagr_with": w["liq_cagr"], "liq_cagr_without": wo["liq_cagr"]}


def switches(result: dict) -> dict:
    """What the verdicts switch in `configs/core.toml`: harvest_core / harvest_longterm true only for a passing arm; `[exits.longterm] stop` false only when the stops failed."""
    return {"exits.harvest_core": bool(result["a_index"]["verdict"]["ok"]), "exits.harvest_longterm": bool(result["a_stocks"]["verdict"]["ok"]),
            "exits.longterm.stop": bool(result["b"]["verdict"]["ok"])}


# --- the store --------------------------------------------------------------------------------------------------------------------------------------

def _store(con, now: datetime, kind: str, subject: str, span: str, verdict: str, summary: dict) -> int:
    from pflab.pm.store import next_id
    rid = next_id(con, "c4_study_s82", "run_id")
    con.execute("INSERT INTO c4_study_s82 VALUES (?,?,?,?,?,?,?,?)", [rid, kind, subject, now, span, verdict, json.dumps(summary, default=float), protocol_sha()])
    return rid


def stored(con, kind: str) -> Optional[dict]:
    r = con.execute("SELECT verdict, summary_json, ran_at FROM c4_study_s82 WHERE kind=?", [kind]).fetchone()
    return None if r is None else {"verdict": r[0], "summary": json.loads(r[1] or "{}"), "ran_at": str(r[2])[:16]}


def _mark(con, note: str, passed: bool, t: Optional[float] = None, t_bar: Optional[float] = None, n: Optional[float] = None) -> None:
    con.execute("UPDATE learn_tests SET passed=?, n_dev=?, t_dev=?, threshold_dev=? WHERE note=? AND passed IS NULL", [bool(passed), int(n) if n else None, t, t_bar, note])


def _record(con, now: datetime, result: dict) -> None:
    for kind, key in (("a_index", "a_index"), ("a_stocks", "a_stocks")):
        a = result[key]
        _store(con, now, kind, kind, "2005-2017", a["verdict"]["verdict"], a)
        _mark(con, NOTES[kind], a["verdict"]["ok"], a.get("t"), a["verdict"]["t_bar"], a.get("n"))
    b = result["b"]
    _store(con, now, "b_stops", "b_stops", "2005-2017", b["verdict"]["verdict"], b)
    _mark(con, NOTES["b_stops"], b["verdict"]["ok"])


def run(con, pm_dir: Path, root, now: datetime, box=None, data: Optional[dict] = None, time_limit: int = 3 * 3600) -> dict:
    """THE run for the record. Refuses unless the protocol is registered and unchanged, and refuses a second run. One sandbox job (`mode: "c4"`); the verdicts are stored and marked on
    the counter's rows. Returns the whole result (JSON-able): the figures of every arm, the verdicts, the switches, the protocol's SHA."""
    from pflab.learner import counter
    from pflab.lab import runner
    ok = protocol_ok(con)
    if not (ok["registered"] and ok["unchanged"]):
        raise RuntimeError(f"the C4 study will not run: {ok['why']}")
    if con.execute("SELECT 1 FROM c4_study_s82 LIMIT 1").fetchone():
        raise RuntimeError("the C4 study has already been run; a rerun with changed parameters is a new registered study")
    data = data if data is not None else runner.panel_data(root, Path(pm_dir), swing_study=True)
    window = (RULE["history"][0], RULE["history"][1])
    res = runner.run(data, [], window, {}, study_cfg(), n_shuffles=0, n_mc=0, seed=RULE["bootstrap"]["seed"], time_limit=time_limit, box=box, now_spec={"mode": "c4"})
    if res.get("error") or res.get("errors"):
        raise RuntimeError("the C4 run failed: " + str(res.get("error") or res.get("errors"))[:600])
    out = res["results"]["c4"]
    n = counter.n_tests(con)
    for key in ("a_index", "a_stocks"):
        out[key]["verdict"] = claim_a_verdict(out[key], n)
    out["b"]["verdict"] = claim_b_verdict(out["b"])
    out["switches"] = switches(out)
    out.update({"protocol_sha256": protocol_sha(), "n_tests": n, "contained": bool(res.get("contained")), "seconds": res.get("seconds"), "window": list(window)})
    _record(con, now, out)
    return out


def apply_recorded(con, now: datetime, path: Optional[Path] = None) -> int:
    """The verdicts of the run for the record are written onto THIS store, once: a row each in `c4_study_s82` (so `run` refuses a second run) and the verdict on the three registration rows of
    the counter. Only when the protocol is the registered one and is the one that was run. Returns the rows written."""
    p = path or RESULTS
    if not p.exists() or con.execute("SELECT 1 FROM c4_study_s82 LIMIT 1").fetchone():
        return 0
    rec = json.loads(p.read_text(encoding="utf-8"))
    ok = protocol_ok(con)
    if not (ok["registered"] and ok["unchanged"]) or rec.get("protocol_sha256") != protocol_sha():
        return 0
    _record(con, now, rec)
    return 3
