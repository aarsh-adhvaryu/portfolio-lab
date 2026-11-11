"""The registered swing / harvesting study, now a RECORD (S81 B5; protocol `docs/protocols/s81_selling_swing_protocol.md`, with its amendment A1).

    register(con, now)                        count the four tests in the learner's counter (idempotent; the protocol's SHA is stored; called from `learner.s79.register_all`)
    protocol_ok(con)                          {registered, unchanged}: was it counted, and is the file the one that was counted
    apply_recorded(con, now)                  the verdicts of THE run (2026-11-09, recorded in `docs/research/swing_study_results_s81.json`) written onto a store once
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
TEMPLATE = "swing_s81"
VARIANTS = {"swing_momentum_continuation": "s81:swing:momentum_continuation", "swing_pullback_in_uptrend": "s81:swing:pullback_in_uptrend", "swing_post_results_drift": "s81:swing:post_results_drift"}
HARVEST_NOTE = "s81:harvest"

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
    loss = rules.load().t["loss_rule"][0]                                          # A2: the loss rule's carry-forward years, read from its row
    return {"st_rate": float(r.stcg_rate), "lt_rate": float(r.ltcg_rate), "lt_exempt": float(rules.exemption(2026)), "lt_months": int(r.lt_months), "slab": engine.SLAB,
            "carry_years": int(loss["carry_forward_years"])}


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


RESULTS = REPO / "docs" / "research" / "swing_study_results_s81.json"


def apply_recorded(con, now: datetime, path: Optional[Path] = None) -> int:
    """The verdicts of the run for the record (2026-11-09 night, on the workshop's real panel in the Docker sandbox) are written onto THIS store, once: the three variants' history
    scorecards as trials in `lab_runs_s80` (so the deflated Sharpe counts them), a row each in `swing_study_s81` (so `run` refuses a second run), and the verdict on the four
    registration rows of the counter. Only when the protocol is the registered one and is the one that was run. Returns the rows written."""
    from pflab.lab import service
    p = path or RESULTS
    if not p.exists() or con.execute("SELECT 1 FROM swing_study_s81 WHERE kind='history' LIMIT 1").fetchone():
        return 0
    rec = json.loads(p.read_text(encoding="utf-8"))
    ok = protocol_ok(con)
    if not (ok["registered"] and ok["unchanged"]) or rec.get("protocol_sha256") != protocol_sha():
        return 0
    n = 0
    for vid, v in rec["variants"].items():
        service.record_rows(con, now, vid, "history", {"runs": [v["run"]], "n_trials": len(rec["variants"])}, None, bool(v.get("contained")), float(v.get("seconds") or 0.0))
        service.redeflate(con, vid)
        _store(con, now, "history", vid, "2005-2017", v["verdict"], {"screen": {k: v[k] for k in ("verdict", "failed", "t_bar")}, **v["run"]})
        _mark(con, VARIANTS[vid], v["verdict"] in ("pass", "pass_thin"), {**v["run"]["score"], "_t_bar": v["t_bar"]})
        n += 1
    h = rec.get("harvest")
    if h:
        _store(con, now, "harvest", "harvest", "2005-2017", h["verdict"]["verdict"], h)
        _mark(con, HARVEST_NOTE, bool(h["verdict"]["ok"]))
        n += 1
    return n
