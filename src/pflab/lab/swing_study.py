"""The registered swing / harvesting study (S81 B5; protocol `docs/protocols/s81_selling_swing_protocol.md`, with its amendment A1).

    register(con, now)                        count the four tests in the learner's counter (idempotent; the protocol's SHA is stored; called from `learner.s79.register_all`)
    protocol_ok(con)                          {registered, unchanged}: was it counted, and is the file the one that was counted
    seed_variants(con, pm_dir, now)           the three variants as lab drafts (candidates only: they never act without the A50 promotion)
    run(con, pm_dir, root, now, box=None)     THE run for the record: refuses unless registered and unchanged, and refuses a second run (a changed rerun is a new registered study)
    final_check(...)                          the 2018-2021 check, once per variant, only for a variant that passed; the strategist is told "cleared" or "did not clear"
    screen_variant / harvest_verdict          the rule of the protocol in code (a test pins the numbers to the protocol's text)
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[3]
PROTOCOL = REPO / "docs" / "protocols" / "s81_selling_swing_protocol.md"
POLICIES = Path(__file__).resolve().parent / "policies"
TEMPLATE = "swing_s81"
VARIANTS = {"swing_momentum_continuation": "s81:swing:momentum_continuation", "swing_pullback_in_uptrend": "s81:swing:pullback_in_uptrend", "swing_post_results_drift": "s81:swing:post_results_drift"}
HARVEST_NOTE = "s81:harvest"
HYPOTHESES = {
    "swing_momentum_continuation": "a liquid share closing at a new 55-session high with a positive 126-session return runs further; stop 8%, target 16%, time exit 30 sessions",
    "swing_pullback_in_uptrend": "in an uptrend a sharp 5-session fall (-5% or worse) is bought back; stop 7%, target 10%, time exit 15 sessions",
    "swing_post_results_drift": "a share up 4% or more on its results day on twice its usual traded value keeps drifting up for weeks; stop 8%, target 15%, time exit 30 sessions",
}

# The rule of the protocol, in code (docs/protocols/s81_selling_swing_protocol.md section 6 and A1). tests/test_s81_swing.py reads the protocol's JSON blocks and compares.
RULE = {
    "history": ["2005-01-01", "2017-12-31"],
    "final": ["2018-01-01", "2021-11-30"],
    "capital": 1000000,
    "cash_rate": 0.065,
    "n_shuffles": 20,
    "shuffle_seed": 80,
    "bootstrap": {"block": 21, "resamples": 5000, "seed": 81},
    "swing_pass": {"min_excess_L_cagr_vs_index": 0.01, "min_t_vs_index": "counter.t_needed(N after registration)", "max_shuffled_beats_real_frac": 0.10, "min_dsr": 0.90,
                   "max_extra_drawdown_vs_index": 0.05},
    "harvest_pass": {"min_dL_each_arm": 0.0005, "tax_saved_must_exceed_extra_costs": True},
    "slippage": {"half_spread_base": 0.0005, "half_spread_cap": 0.005, "turnover_ref": 100000000, "impact_y": 1.0, "sigma_window": 20, "sigma_floor": 0.005},
    "sizing": {"weight": 0.09, "max_positions": 10, "max_new_per_day": 3},
    "index_expense_ratio": 0.002,
    "variants": {
        "swing_momentum_continuation": {"high_window": 55, "trend_window": 126, "stop": 0.08, "target": 0.16, "max_days": 30},
        "swing_pullback_in_uptrend": {"sma_fast": 50, "sma_slow": 200, "pullback_days": 5, "pullback": -0.05, "stop": 0.07, "target": 0.10, "max_days": 15},
        "swing_post_results_drift": {"react": 0.04, "volume_mult": 2.0, "volume_window": 60, "stop": 0.08, "target": 0.15, "max_days": 30},
    },
    "harvest": {"window_months": [1, 2, 3], "fill_fraction": 0.98, "round_trip_cost": 0.004, "guard_days": 30, "lt_months": 12},
}
RULE_A1 = {"final_pass": {"min_excess_L_cagr_vs_index": 0.0, "max_extra_drawdown_vs_index": 0.05, "min_trades": 20}, "shuffled_cagr_is": "liquidation_cagr", "min_trades_forwarded": 40}


def protocol_sha() -> str:
    """SHA-256 of the protocol with its line ends normalised (a checkout that turns LF into CRLF must not look like an edit)."""
    if not PROTOCOL.exists():
        raise FileNotFoundError(f"the protocol file is missing: {PROTOCOL}")
    return hashlib.sha256(PROTOCOL.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def studies() -> tuple:
    out = [(note, f"{TEMPLATE}:{vid}", f"swing variant {vid} beats holding the Nifty 500 ETF after tax and charges, 2005-2017") for vid, note in VARIANTS.items()]
    out.append((HARVEST_NOTE, f"{TEMPLATE}:harvest", "exemption harvesting adds after-tax return vs no harvesting over the same window"))
    return tuple(out)


def register(con, now: datetime) -> List[str]:
    """Count the four tests in the learner's counter (origin 'study'); idempotent by note key. The protocol file must exist and was committed before any run."""
    from pflab.learner import counter
    if not PROTOCOL.exists():
        return []
    sha, done = protocol_sha(), []
    for note, template, _ in studies():
        if con.execute("SELECT 1 FROM learn_tests WHERE note=?", [note]).fetchone():
            continue
        counter.record(con, now, "study", template, {"protocol": "docs/protocols/s81_selling_swing_protocol.md", "protocol_sha256": sha}, note=note)
        done.append(note)
    return done


def protocol_ok(con) -> dict:
    rows = con.execute("SELECT note, params_json FROM learn_tests WHERE note IN (%s)" % ",".join("?" for _ in studies()), [n for n, _, _ in studies()]).fetchall()
    shas = {n: json.loads(p or "{}").get("protocol_sha256") for n, p in rows}
    try:
        now = protocol_sha()
    except FileNotFoundError:
        return {"registered": len(shas) == len(studies()), "unchanged": False, "why": "the protocol file is missing"}
    ok = len(shas) == len(studies())
    same = ok and all(v == now for v in shas.values())
    return {"registered": ok, "unchanged": same, "why": None if same else ("not registered yet" if not ok else "the protocol file changed after it was registered")}


# --- the tax rows ----------------------------------------------------------------------------------------------------------------

def tax_params() -> dict:
    """The rates and the exemption from the tax engine's dated rows (`configs/tax`), never typed here. The latest dated rows are applied to the whole window (protocol section 3)."""
    from pflab.tax import rules
    r = rules.lookup("EQUITY", date(2025, 4, 1), date(2024, 8, 1), stt_paid=True, listed=True)
    from pflab.lab import engine
    return {"st_rate": float(r.stcg_rate), "lt_rate": float(r.ltcg_rate), "lt_exempt": float(rules.exemption(2026)), "lt_months": int(r.lt_months), "slab": engine.SLAB}


def study_cfg() -> dict:
    return {"tax": tax_params(), "capital": RULE["capital"], "cash_rate": RULE["cash_rate"]}


# --- the rule ---------------------------------------------------------------------------------------------------------------------

def screen_variant(score: dict, shuffled: dict, n_tests: int) -> dict:
    """The protocol's section 6 for one variant, from its history scorecard (with the vs-index measures) and its shuffled runs. `n_tests`: the learner's N after registration."""
    from pflab.learner import counter
    r = RULE["swing_pass"]
    bar = counter.t_needed(n_tests)
    failed = []
    ex = score.get("excess_L_vs_index")
    if ex is None:
        return {"ok": False, "verdict": "fail", "failed": ["no comparison with the index arm"], "t_bar": bar}
    if ex < r["min_excess_L_cagr_vs_index"]:
        failed.append(f"liquidation return beats the index ETF by {ex:+.2%} a year (needs {r['min_excess_L_cagr_vs_index']:+.2%})")
    if score.get("t_vs_index", 0.0) < bar:
        failed.append(f"paired t against the index ETF {score.get('t_vs_index', 0.0):.2f} is under the learner's bar {bar:.2f} (N={n_tests})")
    if not shuffled:
        failed.append("no shuffled-signal runs: luck was not measured")
    else:
        if shuffled.get("beats_real_frac", 1.0) > r["max_shuffled_beats_real_frac"]:
            failed.append(f"{shuffled['beats_real_frac']:.0%} of shuffled-signal runs reached the real Sharpe (limit {r['max_shuffled_beats_real_frac']:.0%})")
        if score.get("liq_cagr", -1.0) <= shuffled.get("liq_cagr_p95", 9.0):
            failed.append(f"liquidation return {score.get('liq_cagr', 0.0):.2%} is not above the shuffled runs' 95th percentile {shuffled.get('liq_cagr_p95', 0.0):.2%}")
    if score.get("dsr", 0.0) < r["min_dsr"]:
        failed.append(f"deflated Sharpe {score.get('dsr', 0.0):.2f} is under {r['min_dsr']}")
    if score.get("extra_drawdown_vs_index", -1.0) < -r["max_extra_drawdown_vs_index"]:
        failed.append(f"worst fall {score['max_drawdown']:.1%} is {-score['extra_drawdown_vs_index']:.1%} deeper than the index ETF's (limit {r['max_extra_drawdown_vs_index']:.0%})")
    thin = score.get("n_trades", 0.0) < RULE_A1["min_trades_forwarded"]
    return {"ok": not failed, "verdict": "fail" if failed else ("pass_thin" if thin else "pass"), "failed": failed, "t_bar": bar, "n_tests": n_tests}


def final_screen(score: dict) -> dict:
    r = RULE_A1["final_pass"]
    failed = []
    if score.get("excess_L_vs_index", -1.0) < r["min_excess_L_cagr_vs_index"]:
        failed.append("its liquidation return is below the index ETF's over the final window")
    if score.get("extra_drawdown_vs_index", -1.0) < -r["max_extra_drawdown_vs_index"]:
        failed.append("its worst fall is more than 5 points deeper than the index ETF's")
    if score.get("n_trades", 0.0) < r["min_trades"]:
        failed.append("fewer than 20 trades")
    return {"ok": not failed, "failed": failed}


def harvest_verdict(h: dict) -> dict:
    """Claim B from `swing.harvest_experiment`'s output (arms 'index' and the baseline)."""
    r = RULE["harvest_pass"]
    failed = []
    for arm, v in h.items():
        if v["dL"] < r["min_dL_each_arm"]:
            failed.append(f"{arm}: harvesting changes the liquidation return by {v['dL']:+.3%} a year (needs {r['min_dL_each_arm']:+.3%})")
        if r["tax_saved_must_exceed_extra_costs"] and not v["accounting_ok"]:
            failed.append(f"{arm}: the tax saved (Rs {v['tax_saved']:,.0f}) does not exceed the extra charges and slippage (Rs {v['extra_costs']:,.0f})")
    return {"ok": not failed and bool(h), "verdict": "pass" if (not failed and h) else "fail", "failed": failed}


# --- candidates -------------------------------------------------------------------------------------------------------------------

def variant_code(vid: str) -> str:
    return (POLICIES / f"{vid}.py").read_text(encoding="utf-8")


def seed_variants(con, pm_dir: Path, now: datetime) -> List[str]:
    """The three variants as lab drafts (idempotent). Candidates only: a variant enters live shadow only through `make_challenger` after a scored history run, and acts only after the
    A50 promotion."""
    from pflab.lab import service
    added = []
    for vid in VARIANTS:
        if service.get(con, vid):
            continue
        r = service.add_variant(con, Path(pm_dir), now, vid, variant_code(vid), HYPOTHESES[vid])
        if r.get("ok"):
            added.append(vid)
    return added


# --- the run ----------------------------------------------------------------------------------------------------------------------

def _store(con, now: datetime, kind: str, subject: str, span: str, verdict: str, summary: dict) -> int:
    from pflab.pm.store import next_id
    rid = next_id(con, "swing_study_s81", "run_id")
    con.execute("INSERT INTO swing_study_s81 VALUES (?,?,?,?,?,?,?,?)", [rid, kind, subject, now, span, verdict, json.dumps(summary, default=float), protocol_sha()])
    return rid


def stored(con, kind: str, subject: str) -> Optional[dict]:
    r = con.execute("SELECT verdict, summary_json, ran_at FROM swing_study_s81 WHERE kind=? AND subject=?", [kind, subject]).fetchone()
    return None if r is None else {"verdict": r[0], "summary": json.loads(r[1] or "{}"), "ran_at": str(r[2])[:16]}


def _mark(con, note: str, passed: bool, score: Optional[dict] = None) -> None:
    s = score or {}
    con.execute("UPDATE learn_tests SET passed=?, n_dev=?, t_dev=?, sr_dev=?, dsr=?, threshold_dev=? WHERE note=? AND passed IS NULL",
                [bool(passed), int(s["n_obs"]) if s.get("n_obs") else None, s.get("t_vs_index"), s.get("sharpe_daily"), s.get("dsr"), s.get("_t_bar"), note])


def run(con, pm_dir: Path, root, now: datetime, box=None, data: Optional[dict] = None, n_shuffles: Optional[int] = None, time_limit: int = 4 * 3600) -> dict:
    """THE run for the record. Refuses unless the protocol is registered and unchanged, and refuses a second run. The three variants go through the lab's runner (sandbox) and are
    recorded in `lab_runs_s80` (so every one is a trial in the deflated Sharpe); the harvesting arms are one more job. Returns the verdict of each claim."""
    from pflab.learner import counter
    from pflab.lab import runner, service
    ok = protocol_ok(con)
    if not (ok["registered"] and ok["unchanged"]):
        raise RuntimeError(f"the swing study will not run: {ok['why']}")
    if con.execute("SELECT 1 FROM swing_study_s81 WHERE kind='history' LIMIT 1").fetchone():
        raise RuntimeError("the swing study has already been run; a rerun with changed parameters is a new registered study")
    data = data if data is not None else runner.panel_data(root, Path(pm_dir), swing_study=True)
    service.ensure_baseline(con, now)
    seed_variants(con, Path(pm_dir), now)
    cfg = study_cfg()
    window = (RULE["history"][0], RULE["history"][1])
    nsh = RULE["n_shuffles"] if n_shuffles is None else n_shuffles
    out: Dict[str, dict] = {"variants": {}, "errors": {}}
    for vid in VARIANTS:
        res = runner.run(data, [{"id": vid, "code": variant_code(vid)}], window, {vid: [{}]}, cfg, n_shuffles=nsh, n_mc=500, seed=RULE["shuffle_seed"], time_limit=time_limit, box=box)
        if res.get("error") or vid in res.get("errors", {}):
            out["errors"][vid] = res.get("error") or res["errors"][vid][-600:]
            continue
        service.record_rows(con, now, vid, "history", res["results"][vid], None, bool(res.get("contained")), float(res.get("seconds") or 0.0))
        out["variants"][vid] = {"contained": bool(res.get("contained")), "seconds": res.get("seconds")}
    for vid in list(out["variants"]):
        service.redeflate(con, vid)                                               # the bar rose with every variant tried: the deflated Sharpe is over all of them
    n = counter.n_tests(con)
    for vid in list(out["variants"]):
        r = service.latest_run(con, vid, "history")
        sc = screen_variant(r["score"], r["shuffled"], n)
        r["score"]["_t_bar"] = sc["t_bar"]
        out["variants"][vid].update({"screen": sc, "score": r["score"], "shuffled": r["shuffled"], "mc": r["mc"]})
        _store(con, now, "history", vid, "2005-2017", sc["verdict"], {"screen": sc, "score": r["score"], "shuffled": r["shuffled"], "mc": r["mc"]})
        _mark(con, VARIANTS[vid], sc["ok"], r["score"])
    hres = runner.run(data, [{"id": service.BASELINE_ID, "code": service.baseline_code()}], window, {}, cfg, n_shuffles=0, n_mc=0, seed=RULE["shuffle_seed"], time_limit=time_limit, box=box,
                      now_spec={"mode": "harvest"})
    if hres.get("error") or hres.get("errors"):
        out["errors"]["harvest"] = hres.get("error") or str(hres.get("errors"))[:600]
    else:
        h = hres["results"]["harvest"]
        hv = harvest_verdict(h)
        out["harvest"] = {"arms": h, "verdict": hv}
        _store(con, now, "harvest", "harvest", "2005-2017", hv["verdict"], {"arms": h, "verdict": hv})
        _mark(con, HARVEST_NOTE, hv["ok"])
    out["claim_a"] = "supported" if any(v["screen"]["ok"] for v in out["variants"].values()) else "not supported"
    out["n_tests"] = n
    return out


def final_check(con, pm_dir: Path, root, now: datetime, variant: str, data: Optional[dict] = None, box=None) -> dict:
    """The 2018-2021 check of ONE variant, once, by code, only if it passed the history screen. The strategist's answer is `cleared` or not; the numbers stay in the store."""
    from pflab.lab import runner
    h = stored(con, "history", variant)
    if h is None or h["verdict"] != "pass":
        return {"ran": False, "why": "the variant has not passed the history screen"}
    if stored(con, "final", variant) is not None:
        return {"ran": False, "why": "the final check was already run once", "cleared": stored(con, "final", variant)["verdict"] == "cleared"}
    data = data if data is not None else runner.panel_data(root, Path(pm_dir), swing_study=True)
    res = runner.run(data, [{"id": variant, "code": variant_code(variant)}], tuple(RULE["final"]), {variant: [{}]}, study_cfg(), n_shuffles=0, n_mc=0, time_limit=3600, box=box)
    if res.get("error") or variant in res.get("errors", {}):
        return {"ran": False, "why": "the final check could not run: " + str(res.get("error") or res["errors"][variant])[-300:]}
    score = res["results"][variant]["runs"][0]["score"]
    fs = final_screen(score)
    _store(con, now, "final", variant, "2018-2021", "cleared" if fs["ok"] else "did_not_clear", {"screen": fs, "score": score})
    return {"ran": True, "cleared": fs["ok"]}
