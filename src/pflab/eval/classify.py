"""Verdict — Phase 2 task 2.7.

Applies charter E1 §13 to a development sweep and a validation sweep. Never
accepts a typed-in result: every number comes from a sweep's criteria.json,
which the sweep wrote from the engine's own metrics.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

THRESHOLDS = {"C1_pp": 2.0, "C2_pp": 2.0, "C3_pp": 5.0, "C4_min_rows": 6}

PRIMARY = "B2"          # Nifty 500 TRI (§10)
MOMENTUM_FUND = "B3"    # Nifty 200 Momentum 30 TRI with drag (§10)


def _pp(x) -> float:
    return 100.0 * float(x)


def criteria_for_period(crit: dict) -> dict:
    """C1-C4 for one period, from one sweep's criteria.json."""
    rows = crit.get("rows", {})
    bench = crit.get("benchmarks", {})
    base = rows.get("base") or {}
    b2 = bench.get(PRIMARY) or {}
    b3 = bench.get(MOMENTUM_FUND) or {}

    missing = [n for n, v in (("base", base), (PRIMARY, b2), (MOMENTUM_FUND, b3)) if not v]
    if missing or base.get("error"):
        return {"usable": False,
                "reason": f"missing {missing}" if missing else f"base halted: {base['error']}",
                "C1": None, "C2": None, "C3": None, "C4": None}

    c1_gap = _pp(base["cagr"]) - _pp(b2["cagr"])
    c2_gap = _pp(base["cagr"]) - _pp(b3["cagr"])
    # max_drawdown is negative; §3 compares magnitudes.
    c3_gap = abs(_pp(base["max_drawdown"])) - abs(_pp(b2["max_drawdown"]))
    c1 = c1_gap >= THRESHOLDS["C1_pp"]
    c2 = c2_gap >= THRESHOLDS["C2_pp"]
    c3 = c3_gap <= THRESHOLDS["C3_pp"]

    per_row = {}
    for name, r in rows.items():
        if r.get("error") or "cagr" not in r:
            per_row[name] = {"holds": False, "reason": r.get("error") or "no metrics"}
            continue
        g1 = _pp(r["cagr"]) - _pp(b2["cagr"]) >= THRESHOLDS["C1_pp"]
        g2 = _pp(r["cagr"]) - _pp(b3["cagr"]) >= THRESHOLDS["C2_pp"]
        g3 = abs(_pp(r["max_drawdown"])) - abs(_pp(b2["max_drawdown"])) <= THRESHOLDS["C3_pp"]
        per_row[name] = {"holds": bool(g1 and g2 and g3), "C1": g1, "C2": g2, "C3": g3}
    n_hold = sum(1 for v in per_row.values() if v["holds"])
    c4 = n_hold >= THRESHOLDS["C4_min_rows"]

    return {"usable": True, "reason": None,
            "C1": c1, "C1_gap_pp": c1_gap,
            "C2": c2, "C2_gap_pp": c2_gap,
            "C3": c3, "C3_gap_pp": c3_gap,
            "C4": c4, "C4_rows_holding": n_hold, "C4_of": len(per_row),
            "rows": per_row}


def verdict(dev: dict, val: dict) -> str:
    """§13. ADVANCE if C1-C4 hold in both; REJECT if C1 fails in both;
    INCONCLUSIVE otherwise."""
    if not (dev.get("usable") and val.get("usable")):
        return "INCONCLUSIVE"
    both = all(dev[c] and val[c] for c in ("C1", "C2", "C3", "C4"))
    if both:
        return "ADVANCE"
    if dev["C1"] is False and val["C1"] is False:
        return "REJECT"
    return "INCONCLUSIVE"


def classify(dev_sweep_dir, val_sweep_dir, bootstrap: Optional[dict] = None) -> dict:
    dev = json.loads((Path(dev_sweep_dir) / "criteria.json").read_text(encoding="utf-8"))
    val = json.loads((Path(val_sweep_dir) / "criteria.json").read_text(encoding="utf-8"))
    d, v = criteria_for_period(dev), criteria_for_period(val)
    out = {"development": d, "validation": v, "verdict": verdict(d, v),
           "thresholds": THRESHOLDS}
    if bootstrap is not None:
        out["C5_bootstrap"] = bootstrap        # reported, never gating (§13)
    return out


def write_verdict(out_path, result: dict) -> Path:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return p


# -- GATE.md, for experiments after E1 ---------------------------------
GATE_THRESHOLDS = {"G1_cagr_pp": 0.5, "G1_dd_pp": 2.0,
                   "G2_cagr_pp": 0.5, "G2_dd_pp": 2.0,
                   "G3_fraction": 2.0 / 3.0, "G4_turnover_multiple": 2.0}


def gate_for_period(cand: dict, stack: dict) -> dict:
    """GATE.md G1-G4 for one period. `cand` and `stack` are criteria.json
    dicts (rows + benchmarks) for the candidate and the adopted stack."""
    c = (cand.get("rows") or {}).get("base") or {}
    s_ = (stack.get("rows") or {}).get("base") or {}
    if not c or not s_ or c.get("error") or s_.get("error"):
        return {"usable": False, "reason": "base row missing or halted",
                "G1": None, "G2": None, "G3": None, "G4": None}

    d_cagr = _pp(c["cagr"]) - _pp(s_["cagr"])
    # max_drawdown is negative; compare magnitudes
    d_dd = abs(_pp(c["max_drawdown"])) - abs(_pp(s_["max_drawdown"]))
    g1 = (d_cagr >= GATE_THRESHOLDS["G1_cagr_pp"]) or (d_dd <= -GATE_THRESHOLDS["G1_dd_pp"])
    g2 = (d_cagr >= -GATE_THRESHOLDS["G2_cagr_pp"]) and (d_dd <= GATE_THRESHOLDS["G2_dd_pp"])

    per_row, held = {}, 0
    rows = cand.get("rows") or {}
    for name, r in rows.items():
        if r.get("error") or "cagr" not in r:
            per_row[name] = {"holds": False, "reason": r.get("error") or "no metrics"}
            continue
        rc = _pp(r["cagr"]) - _pp(s_["cagr"])
        rd = abs(_pp(r["max_drawdown"])) - abs(_pp(s_["max_drawdown"]))
        ok = ((rc >= GATE_THRESHOLDS["G1_cagr_pp"]) or (rd <= -GATE_THRESHOLDS["G1_dd_pp"])) \
            and (rc >= -GATE_THRESHOLDS["G2_cagr_pp"]) and (rd <= GATE_THRESHOLDS["G2_dd_pp"])
        per_row[name] = {"holds": bool(ok)}
        held += bool(ok)
    g3 = bool(rows) and (held / len(rows)) >= GATE_THRESHOLDS["G3_fraction"]

    ct, st = c.get("turnover_annual"), s_.get("turnover_annual")
    g4 = True if (ct is None or not st) else (ct <= GATE_THRESHOLDS["G4_turnover_multiple"] * st)

    return {"usable": True, "reason": None,
            "G1": bool(g1), "G2": bool(g2), "G3": bool(g3), "G4": bool(g4),
            "cagr_gap_pp": d_cagr, "maxdd_gap_pp": d_dd,
            "rows_holding": held, "rows_total": len(rows),
            "turnover_cand": ct, "turnover_stack": st, "rows": per_row}


def gate_verdict(dev: dict, val: dict) -> str:
    """ADOPT if G1-G4 hold in both; REJECT if G1 fails in both or G2 is
    violated in both; INCONCLUSIVE otherwise."""
    if not (dev.get("usable") and val.get("usable")):
        return "INCONCLUSIVE"
    if all(dev[g] and val[g] for g in ("G1", "G2", "G3", "G4")):
        return "ADOPT"
    if (dev["G1"] is False and val["G1"] is False) or \
       (dev["G2"] is False and val["G2"] is False):
        return "REJECT"
    return "INCONCLUSIVE"


def classify_e1b(dev_sweep_dir, val_sweep_dir,
                 stack_dev_dir, stack_val_dir) -> dict:
    """E1b §7: TWO outputs, because E1b is a candidate base.

    1. the GATE verdict against STACK = E1 base (G1-G4, both periods)
    2. E1 §13's C1-C4 for both periods, since ADVANCE is a property of
       whichever base is current, not of any single experiment
    """
    cand_dev = json.loads((Path(dev_sweep_dir) / "criteria.json").read_text(encoding="utf-8"))
    cand_val = json.loads((Path(val_sweep_dir) / "criteria.json").read_text(encoding="utf-8"))
    st_dev = json.loads((Path(stack_dev_dir) / "criteria.json").read_text(encoding="utf-8"))
    st_val = json.loads((Path(stack_val_dir) / "criteria.json").read_text(encoding="utf-8"))

    g_dev, g_val = gate_for_period(cand_dev, st_dev), gate_for_period(cand_val, st_val)
    c_dev, c_val = criteria_for_period(cand_dev), criteria_for_period(cand_val)
    return {
        "gate": {"development": g_dev, "validation": g_val,
                 "verdict": gate_verdict(g_dev, g_val),
                 "thresholds": GATE_THRESHOLDS,
                 "stack": "E1 base"},
        "charter_c1_c4": {"development": c_dev, "validation": c_val,
                          "verdict": verdict(c_dev, c_val),
                          "thresholds": THRESHOLDS,
                          "note": ("ADVANCE is a property of the current base, "
                                   "not of one experiment (E1b §7)")},
    }
