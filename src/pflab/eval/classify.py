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
CONTROL_ROWS = ("N1", "N2")     # E1-P §4: reported, never adoptable

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


def classify_e1p(dev_sweep_dir, val_sweep_dir,
                 stack_dev_dir, stack_val_dir) -> dict:
    """E1-P §1: judged by GATE.md. GATE only, and that is the whole verdict.

    Unlike E1b and E1c, E1-P is NOT a candidate base -- it is one rule on top
    of the adopted stack -- so there is no C1-C4 half to report.

    §4's N1/N2 are stripped before the arithmetic sees the rows. They are
    negative controls: "run alongside, never adoptable". Leaving them in
    would let a control that happened to score well contribute to G3's
    two-thirds count and push the experiment through the gate.
    """
    cand_dev = json.loads((Path(dev_sweep_dir) / "criteria.json").read_text(encoding="utf-8"))
    cand_val = json.loads((Path(val_sweep_dir) / "criteria.json").read_text(encoding="utf-8"))
    st_dev = json.loads((Path(stack_dev_dir) / "criteria.json").read_text(encoding="utf-8"))
    st_val = json.loads((Path(stack_val_dir) / "criteria.json").read_text(encoding="utf-8"))

    def _without_controls(crit):
        rows = {k: v for k, v in (crit.get("rows") or {}).items()
                if k not in CONTROL_ROWS}
        return {**crit, "rows": rows}

    g_dev = gate_for_period(_without_controls(cand_dev), st_dev)
    g_val = gate_for_period(_without_controls(cand_val), st_val)
    return {
        "gate": {"development": g_dev, "validation": g_val,
                 "verdict": gate_verdict(g_dev, g_val),
                 "thresholds": GATE_THRESHOLDS, "stack": "E1 base"},
        "controls": {
            "note": ("E1-P §4: N1/N2 are negative controls, reported with the "
                     "same metrics and never adoptable. Excluded from G3."),
            "development": {k: (cand_dev.get("rows") or {}).get(k)
                            for k in CONTROL_ROWS},
            "validation": {k: (cand_val.get("rows") or {}).get(k)
                           for k in CONTROL_ROWS}},
    }


# -- MANDATE §3 and §5, effective 2026-09-21 ----------------------------
# GATE still decides ADOPTION (does a change join the stack). From
# 2026-09-21 MANDATE §3 and §5 decide ADVANCE (sealed reveal, live paper year,
# real money), replacing E1 §13's C1-C4 in that role. Recorded verdicts are
# unchanged. The block is reported from E1c onward.
MANDATE_EFFECTIVE = "2026-09-21"
MANDATE_THRESHOLDS = {"M3_dd_pp": 5.0,        # worst fall <= B2's + 5 pp
                      "M3_cagr_pp": 3.0,      # return >= B2 + 3 pp/yr
                      "M3_fraction": 2.0 / 3.0,
                      "M5_cagr_pp": 2.0}      # return >= B5 + 2 pp/yr
MARKET = "B2"            # Nifty 500 TRI
ONE_CLICK = "B5"         # Nifty 500 Momentum 50 TRI


def mandate_for_period(crit: dict) -> dict:
    """MANDATE §3 and §5 for one period, from one sweep's criteria.json.

    §3: the base row's worst fall no more than 5 pp deeper than B2's AND its
    after-tax CAGR at least 3 pp/yr above B2's, and the same two tests hold
    in at least two thirds of the sweep's rows. §5: the base row's after-tax
    CAGR at least 2 pp/yr above B5's. Rows are measured against the same
    full-window benchmarks as C4 and G3 are (a short-window row is compared
    with the full-window benchmark, as it always has been).

    E1-P's negative controls (CONTROL_ROWS) are never counted.
    """
    rows = {k: v for k, v in (crit.get("rows") or {}).items()
            if k not in CONTROL_ROWS}
    bench = crit.get("benchmarks") or {}
    base, b2, b5 = rows.get("base") or {}, bench.get(MARKET) or {}, bench.get(ONE_CLICK) or {}
    if not base or base.get("error") or not b2:
        return {"usable": False,
                "reason": "base row missing or halted" if not b2 else "no base row",
                "M3": None, "M5": None}

    def m3_ok(r):
        dd = abs(_pp(r["max_drawdown"])) - abs(_pp(b2["max_drawdown"]))
        gap = _pp(r["cagr"]) - _pp(b2["cagr"])
        return (dd <= MANDATE_THRESHOLDS["M3_dd_pp"]
                and gap >= MANDATE_THRESHOLDS["M3_cagr_pp"]), dd, gap

    base_ok, dd_gap, cagr_gap = m3_ok(base)
    per_row, held = {}, 0
    for name, r in rows.items():
        if r.get("error") or "cagr" not in r:
            per_row[name] = {"holds": False, "reason": r.get("error") or "no metrics"}
            continue
        ok = m3_ok(r)[0]
        per_row[name] = {"holds": bool(ok)}
        held += bool(ok)
    rows_ok = bool(rows) and held / len(rows) >= MANDATE_THRESHOLDS["M3_fraction"]

    if b5:
        m5_gap = _pp(base["cagr"]) - _pp(b5["cagr"])
        m5 = m5_gap >= MANDATE_THRESHOLDS["M5_cagr_pp"]
    else:
        m5_gap, m5 = None, None             # reported as unavailable, never guessed
    return {"usable": True, "reason": None,
            "M3": bool(base_ok and rows_ok),
            "M3_maxdd_gap_vs_B2_pp": dd_gap, "M3_cagr_gap_vs_B2_pp": cagr_gap,
            "M3_base_holds": bool(base_ok),
            "M3_rows_holding": held, "M3_rows_total": len(rows),
            "M5": m5, "M5_cagr_gap_vs_B5_pp": m5_gap,
            "M5_available": bool(b5), "rows": per_row}


def mandate_verdict(dev: dict, val: dict) -> dict:
    """MEETS only if §3 and §5 both hold in BOTH periods.

    Meeting the mandate is necessary for ADVANCE, not sufficient: ADVANCE is
    a property of the adopted stack, so a candidate that meets the mandate but
    is not ADOPTED by GATE advances nothing.
    """
    if not (dev.get("usable") and val.get("usable")):
        return {"meets": False, "M3": None, "M5": None,
                "reason": "a period is unusable"}
    m3 = bool(dev["M3"] and val["M3"])
    m5 = (None if (dev["M5"] is None or val["M5"] is None)
          else bool(dev["M5"] and val["M5"]))
    return {"meets": bool(m3 and m5), "M3": m3, "M5": m5,
            "reason": ("B5 unavailable in a period" if m5 is None else None)}


def _mandate_block(cand_dev: dict, cand_val: dict) -> dict:
    d, v = mandate_for_period(cand_dev), mandate_for_period(cand_val)
    return {"development": d, "validation": v,
            "verdict": mandate_verdict(d, v),
            "thresholds": MANDATE_THRESHOLDS,
            "effective": MANDATE_EFFECTIVE,
            "note": ("MANDATE §3 and §5 decide ADVANCE from 2026-09-21; GATE "
                     "still decides adoption. ADVANCE requires the ADOPTED "
                     "stack to meet the mandate.")}


def classify_e1c(dev_sweep_dir, val_sweep_dir,
                 stack_dev_dir, stack_val_dir) -> dict:
    """E1c §6: GATE vs E1 base, E1 §13's C1-C4 (E1c is a candidate base), the
    mandate block, and §6's own report -- the gap to B3 and base-vs-S1 as the
    bound on how much weighting matters.

    §6 as amended: E1c reports its gap to B3 but MAY NOT restate C2, so the
    gap below is reporting only and feeds no verdict.
    """
    load = lambda d: json.loads((Path(d) / "criteria.json").read_text(encoding="utf-8"))
    cand_dev, cand_val = load(dev_sweep_dir), load(val_sweep_dir)
    st_dev, st_val = load(stack_dev_dir), load(stack_val_dir)

    g_dev, g_val = gate_for_period(cand_dev, st_dev), gate_for_period(cand_val, st_val)
    c_dev, c_val = criteria_for_period(cand_dev), criteria_for_period(cand_val)

    def section6(crit):
        rows, bench = crit.get("rows") or {}, crit.get("benchmarks") or {}
        base, s1, b3 = rows.get("base") or {}, rows.get("S1") or {}, bench.get(MOMENTUM_FUND) or {}
        ok = lambda r: bool(r) and not r.get("error") and "cagr" in r
        return {
            "gap_to_B3_pp": (_pp(base["cagr"]) - _pp(b3["cagr"])) if ok(base) and b3 else None,
            "base_minus_S1_cagr_pp": (_pp(base["cagr"]) - _pp(s1["cagr"])) if ok(base) and ok(s1) else None,
            "base_minus_S1_maxdd_pp": ((abs(_pp(base["max_drawdown"])) - abs(_pp(s1["max_drawdown"])))
                                       if ok(base) and ok(s1) else None),
        }

    return {
        "gate": {"development": g_dev, "validation": g_val,
                 "verdict": gate_verdict(g_dev, g_val),
                 "thresholds": GATE_THRESHOLDS, "stack": "E1 base"},
        "charter_c1_c4": {"development": c_dev, "validation": c_val,
                          "verdict": verdict(c_dev, c_val),
                          "thresholds": THRESHOLDS,
                          "note": ("reported per E1c §6; from 2026-09-21 ADVANCE "
                                   "is decided by the mandate block, not by this")},
        "mandate": _mandate_block(cand_dev, cand_val),
        "section6": {"development": section6(cand_dev),
                     "validation": section6(cand_val),
                     "note": ("E1c may not restate E1 §13's C2 (§6, amended "
                              "2026-09-19). Base vs S1 bounds how much the "
                              "weighting scheme matters; free-float weights "
                              "are unavailable.")},
    }
