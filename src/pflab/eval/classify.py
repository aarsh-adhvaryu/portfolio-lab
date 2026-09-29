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


# GATE.md 2026-09-25: a short-window row that has no question to ask in a
# period is reported, not counted. It is excluded from the DENOMINATOR as
# well as the numerator -- counting it as a row that failed would penalise a
# charter for declaring a row honestly, and counting it as one that held
# would be a free pass. E1d's S11 in validation is the case that prompted it.
def _countable(rows: dict) -> dict:
    return {k: v for k, v in (rows or {}).items() if not v.get("not_applicable")}


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
    rows = _countable(rows)
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
    rows = _countable(cand.get("rows") or {})
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
    rows = _countable(rows)
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


def classify_e1d(dev_sweep_dir, val_sweep_dir,
                 stack_dev_dir, stack_val_dir) -> dict:
    """E1d §6: GATE vs E1 base, E1 §13's C1-C4, and the mandate block.

    The same three blocks as `classify_e1c` without its §6 block, which
    existed only to report E1c's gap to B3 and its base-vs-S1 weighting
    bound. E1d changes the ranking signal and nothing about weighting, so
    neither has anything to say here.

    STACK is E1 base read from `experiments/E1/regression/` -- the
    2026-09-21 re-run under the measurement correction (E1 §15: buys sized
    net of costs, expense drag by calendar days). Comparing against the
    ORIGINAL E1 sweeps would put the candidate's corrected numbers against
    the stack's uncorrected ones and hand E1d a gap it did not earn.

    §7 travels with the verdict: E1d's hypothesis came from E1c's S6 on
    these same development and validation years, so a pass here is weaker
    evidence than a pass on a fresh hypothesis. The note below is carried
    into the verdict file so no reader can pick up the number without it.
    """
    load = lambda d: json.loads((Path(d) / "criteria.json").read_text(encoding="utf-8"))
    cand_dev, cand_val = load(dev_sweep_dir), load(val_sweep_dir)
    st_dev, st_val = load(stack_dev_dir), load(stack_val_dir)

    g_dev, g_val = gate_for_period(cand_dev, st_dev), gate_for_period(cand_val, st_val)
    c_dev, c_val = criteria_for_period(cand_dev), criteria_for_period(cand_val)

    return {
        "gate": {"development": g_dev, "validation": g_val,
                 "verdict": gate_verdict(g_dev, g_val),
                 "thresholds": GATE_THRESHOLDS, "stack": "E1 base"},
        "charter_c1_c4": {"development": c_dev, "validation": c_val,
                          "verdict": verdict(c_dev, c_val),
                          "thresholds": THRESHOLDS,
                          "note": ("reported per E1d §6 because E1d is a "
                                   "candidate base; from 2026-09-21 ADVANCE "
                                   "is decided by the mandate block, not by "
                                   "this. No experiment may move C1-C4.")},
        "mandate": _mandate_block(cand_dev, cand_val),
        "section7": {
            "prior_exposure": ("E1d's hypothesis came from E1c's S6, run on "
                               "these same development and validation years. "
                               "Those years are no longer unseen for this "
                               "question."),
            "consequence": ("A pass here is weaker evidence than a pass on a "
                            "fresh hypothesis. The only clean test left is "
                            "the sealed period, which MANDATE §14 reserves "
                            "for a stack that meets §3 and §5."),
        },
    }


def classify_e2a(dev_sweep_dir, val_sweep_dir, stack_dev_dir, stack_val_dir,
                 event_study: Optional[dict] = None) -> dict:
    """E2-A §6 and §8a: GATE vs E1 base, the mandate block, and the
    pre-registered event study.

    **ADOPT requires GATE and §8a together.** E2-A §6's window is five years
    of a 25-name portfolio and the charter declares it a low-power test, so
    GATE alone cannot separate "flags carry no information" from "this
    portfolio could not detect it". §8a tests the information on every
    flagged name; GATE tests whether acting on it helps the fund. Neither
    substitutes for the other, and `verdict` here is ADOPT only when both
    pass.

    C1-C4 are NOT reported: E2-A is a change on the adopted stack, not a
    candidate base, so E1 §13's bar does not apply to it.

    **Change-log entries that apply** (CLAUDE.md non-negotiable 1): E2-A §6,
    §7, §8 and §8a as amended 2026-09-25 -- window moved to 2017-2019 /
    2020-2021 on input availability, S13 removed, the suspension/delisting
    lead-time extra added, and §8a added as a second ADOPT requirement.
    """
    load = lambda d: json.loads((Path(d) / "criteria.json").read_text(encoding="utf-8"))
    cand_dev, cand_val = load(dev_sweep_dir), load(val_sweep_dir)
    st_dev, st_val = load(stack_dev_dir), load(stack_val_dir)

    g_dev, g_val = gate_for_period(cand_dev, st_dev), gate_for_period(cand_val, st_val)
    gate = gate_verdict(g_dev, g_val)

    es = dict(event_study or {})
    es_pass = bool(es.get("passes")) if es else None

    if es_pass is None:
        overall = "INCOMPLETE"
        why = "§8a has not been run; ADOPT requires it alongside GATE"
    elif gate == "ADOPT" and es_pass:
        overall, why = "ADOPT", "GATE and §8a both pass"
    elif gate == "REJECT" and es_pass is False:
        overall, why = "REJECT", "GATE and §8a both fail"
    else:
        overall = "INCONCLUSIVE"
        why = f"GATE says {gate}; §8a {'passes' if es_pass else 'does not pass'}"

    return {
        "verdict": overall,
        "verdict_reason": why,
        "gate": {"development": g_dev, "validation": g_val, "verdict": gate,
                 "thresholds": GATE_THRESHOLDS, "stack": "E1 base"},
        "event_study_8a": es or {"run": False,
                                 "note": "required for ADOPT (E2-A §8a)"},
        "mandate": _mandate_block(cand_dev, cand_val),
        "window": {
            "development": "2017-01-01..2019-12-31",
            "validation": "2020-01-01..2021-12-31",
            "why": ("set by when the rule's inputs exist, before any return "
                    "was computed: IBC from December 2016, SEBI encumbrance "
                    "and default disclosures from 2019"),
            "declared_limitation": (
                "five years of a 25-name portfolio is a LOW-POWER test; a "
                "null result means 'not shown', never 'no effect'"),
        },
    }


def classify_e2d1(dev_sweep_dir, val_sweep_dir, stack_dev_dir, stack_val_dir) -> dict:
    """E2-D1: GATE vs E1 base on the charter's own window, plus the mandate
    block.

    C1-C4 are NOT reported: E2-D1 is a change on the adopted stack, not a
    candidate base. STACK development is E1 base re-run on 2010-2016
    (`e2d1_development`); STACK validation is E1's own regression run on
    2017-2021.

    **Change-log entries that apply** (CLAUDE.md non-negotiable 1): E2-D1
    §10 (2026-09-27, the split from E2-D and the decisions made with it)
    and, carried over from E2-D, the 2026-09-24 amendments to data and
    dating.
    """
    load = lambda d: json.loads((Path(d) / "criteria.json").read_text(encoding="utf-8"))
    cand_dev, cand_val = load(dev_sweep_dir), load(val_sweep_dir)
    st_dev, st_val = load(stack_dev_dir), load(stack_val_dir)
    g_dev, g_val = gate_for_period(cand_dev, st_dev), gate_for_period(cand_val, st_val)
    return {
        "verdict": gate_verdict(g_dev, g_val),
        "gate": {"development": g_dev, "validation": g_val,
                 "verdict": gate_verdict(g_dev, g_val),
                 "thresholds": GATE_THRESHOLDS, "stack": "E1 base"},
        "mandate": _mandate_block(cand_dev, cand_val),
        "window": {
            "development": "2010-01-01..2016-12-31",
            "validation": "2017-01-01..2021-12-31",
            "declared": ("2010-2015 quarters are dated by the second-month-end "
                         "convention, 2016 onward by filing date; the rule is "
                         "inert until 2010-11-30, when the first two-quarter "
                         "comparison becomes usable"),
        },
    }


def classify_e3r(dev_sweep_dir, val_sweep_dir, stack_dev_dir, stack_val_dir) -> dict:
    """E3-R §7: GATE vs the stack (E1 base, read from experiments/E1/regression/)
    and the mandate block. C1-C4 are not reported: E3-R replaces one rule of
    the stack and is not a candidate base.

    **Change-log entries that apply** (CLAUDE.md non-negotiable 1): §11,
    2026-09-25 (the prediction below, recorded before any run) and
    2026-09-27 (Aarsh's four decisions: undefined = not firing; the
    sell-down ranks names by FIFO tax cost; the high gear holds NIFTYBEES;
    its disposal and what interrupts it).
    """
    load = lambda d: json.loads((Path(d) / "criteria.json").read_text(encoding="utf-8"))
    cand_dev, cand_val = load(dev_sweep_dir), load(val_sweep_dir)
    st_dev, st_val = load(stack_dev_dir), load(stack_val_dir)
    g_dev, g_val = gate_for_period(cand_dev, st_dev), gate_for_period(cand_val, st_val)
    return {
        "verdict": gate_verdict(g_dev, g_val),
        "gate": {"development": g_dev, "validation": g_val,
                 "verdict": gate_verdict(g_dev, g_val),
                 "thresholds": GATE_THRESHOLDS, "stack": "E1 base"},
        "mandate": _mandate_block(cand_dev, cand_val),
        "prediction_2026_09_25": (
            "Recorded before any E3-R run: E3-R passes only if the high gear's "
            "recovery return exceeds the cautious gear's cost in 2017-2021."),
        "declared": [
            "NIFTYBEES carries no dividend rows; where its dividends were paid "
            "out (2008-2013 on the evidence in docs/notes/E3-readiness.md) the "
            "high gear is understated",
            "the cost model charges the stock STT schedule on NIFTYBEES",
        ],
    }


def classify_e2d2(dev_sweep_dir, val_sweep_dir, stack_dev_dir, stack_val_dir) -> dict:
    """E2-D2: GATE vs E1 base on E2-A's windows (2017-2019 / 2020-2021) and
    the mandate block. STACK is E1 base on those windows -- the same stack
    E2-A was judged against (experiments/E2-A/_stack_sd, _stack_sv).

    **Change-log entries that apply** (CLAUDE.md non-negotiable 1): E2-D2 §9
    (2026-09-27, the split and the denominator) and, from E2-D, 2026-09-24
    (the PIT limb from 2016-01-01; NSE's feed the only source with values).
    """
    load = lambda d: json.loads((Path(d) / "criteria.json").read_text(encoding="utf-8"))
    cand_dev, cand_val = load(dev_sweep_dir), load(val_sweep_dir)
    st_dev, st_val = load(stack_dev_dir), load(stack_val_dir)
    g_dev, g_val = gate_for_period(cand_dev, st_dev), gate_for_period(cand_val, st_val)
    return {
        "verdict": gate_verdict(g_dev, g_val),
        "gate": {"development": g_dev, "validation": g_val,
                 "verdict": gate_verdict(g_dev, g_val),
                 "thresholds": GATE_THRESHOLDS, "stack": "E1 base"},
        "mandate": _mandate_block(cand_dev, cand_val),
        "window": {"development": "2017-01-01..2019-12-31",
                   "validation": "2020-01-01..2021-12-31",
                   "declared_limitation": (
                       "five years of a 25-name portfolio is a LOW-POWER test; "
                       "a null result means 'not shown', never 'no effect'"),
                   "declared": ("market cap uses TOTAL shares outstanding; free "
                                "float exists in no dataset here")},
    }


# -- E5-A §10 ------------------------------------------------------------
E5A_PERIODS = {"development": "e5a_development", "validation": "validation"}


def gate_rowwise(cand: dict, control: dict) -> dict:
    """GATE G1-G4 with each candidate row k compared with the CONTROL's row
    k, not with its base row (E5-A §9: "a family's row k is compared with
    A0's row k -- the perturbation applies to both sides"). G1, G2 and G4
    compare the two base rows, exactly as `gate_for_period` does."""
    out = gate_for_period(cand, control)
    if not out.get("usable"):
        return out
    crow = control.get("rows") or {}
    per_row, held = {}, 0
    rows = _countable(cand.get("rows") or {})
    for name, r in rows.items():
        s_ = crow.get(name) or {}
        if r.get("error") or "cagr" not in r:
            per_row[name] = {"holds": False, "reason": r.get("error") or "no metrics"}
            continue
        if s_.get("error") or "cagr" not in s_:
            per_row[name] = {"holds": False, "reason": f"control row {name} missing or halted"}
            continue
        rc = _pp(r["cagr"]) - _pp(s_["cagr"])
        rd = abs(_pp(r["max_drawdown"])) - abs(_pp(s_["max_drawdown"]))
        ok = ((rc >= GATE_THRESHOLDS["G1_cagr_pp"]) or (rd <= -GATE_THRESHOLDS["G1_dd_pp"])) \
            and (rc >= -GATE_THRESHOLDS["G2_cagr_pp"]) and (rd <= GATE_THRESHOLDS["G2_dd_pp"])
        per_row[name] = {"holds": bool(ok), "cagr_gap_pp": rc, "maxdd_gap_pp": rd}
        held += bool(ok)
    out["G3"] = bool(rows) and (held / len(rows)) >= GATE_THRESHOLDS["G3_fraction"]
    out["rows_holding"], out["rows_total"], out["rows"] = held, len(rows), per_row
    out["comparison"] = "row k vs control row k"
    return out


def _e5a_period_guard(sweep_dir, role: str) -> None:
    """§8: the exploratory years are never in a GATE or mandate count. A
    sweep whose manifest names another period is refused, not read."""
    mf = Path(sweep_dir) / "manifest.json"
    if not mf.exists():
        return
    got = json.loads(mf.read_text(encoding="utf-8")).get("period")
    if got != E5A_PERIODS[role]:
        raise ValueError(f"E5-A §8: the {role} verdict reads period "
                         f"{E5A_PERIODS[role]!r}; {sweep_dir} is {got!r}"
                         + (" -- exploratory results are never counted"
                            if got == "e5a_exploratory" else ""))


def _holdings_overlap(cand_dir, stack_dir) -> Optional[dict]:
    """§11: share of the candidate's month-end holdings the stack also held."""
    a, b = (Path(d) / "rows" / "base" / "decisions.json" for d in (cand_dir, stack_dir))
    if not (a.exists() and b.exists()):
        return None
    ca = {d["month_end"]: set(d.get("held") or ()) for d in json.loads(a.read_text(encoding="utf-8"))}
    sb = {d["month_end"]: set(d.get("held") or ()) for d in json.loads(b.read_text(encoding="utf-8"))}
    both = [m for m in ca if m in sb and ca[m]]
    if not both:
        return None
    shared = sum(len(ca[m] & sb[m]) for m in both)
    return {"month_ends": len(both),
            "overlap_pct": 100.0 * shared / sum(len(ca[m]) for m in both)}


def classify_e5a(dev_sweep_dir, val_sweep_dir, stack_dev_dir, stack_val_dir,
                 a0_dev_dir=None, a0_val_dir=None, candidate: str = "A0") -> dict:
    """E5-A §10.

    A0: GATE G1-G4 against STACK (E1 + E1d, re-run on `e5a_development` and
    on validation), plus the mandate block.

    A family (A1-A3): two GATE computations. *Incremental*, with STACK := A0
    and each row k compared with A0's row k; *adoption*, against the stack in
    force. It joins the stack only if BOTH are ADOPT (§14 D9). The
    incremental verdict is the recorded evidence on the information family
    whatever the adoption verdict is.

    C1-C4 are not reported: E5-A replaces the stack's ranking signal and is
    not a candidate base.

    **Change-log entries that apply** (CLAUDE.md non-negotiable 1): E5-A §14
    -- 2026-09-27 (rewrite), 2026-09-28 (D1, D3-D9; A4 parked; A2's
    precondition), 2026-09-29 (D2: the stack is E1 + E1d) -- and, for the
    stack, E1 §15 and E1d §10.
    """
    _e5a_period_guard(dev_sweep_dir, "development")
    _e5a_period_guard(val_sweep_dir, "validation")
    load = lambda d: json.loads((Path(d) / "criteria.json").read_text(encoding="utf-8"))
    cand_dev, cand_val = load(dev_sweep_dir), load(val_sweep_dir)
    st_dev, st_val = load(stack_dev_dir), load(stack_val_dir)
    g_dev, g_val = gate_for_period(cand_dev, st_dev), gate_for_period(cand_val, st_val)
    adoption = {"development": g_dev, "validation": g_val,
                "verdict": gate_verdict(g_dev, g_val),
                "thresholds": GATE_THRESHOLDS, "stack": "E1 + E1d"}
    extras = {"holdings_overlap_with_stack": {
        "development": _holdings_overlap(dev_sweep_dir, stack_dev_dir),
        "validation": _holdings_overlap(val_sweep_dir, stack_val_dir)}}
    if candidate == "A0":
        return {"candidate": "A0", "verdict": adoption["verdict"],
                "gate": adoption, "mandate": _mandate_block(cand_dev, cand_val),
                "extras": extras,
                "window": {"development": "2011-01-01..2016-12-31",
                           "validation": "2017-01-01..2021-12-31",
                           "exploratory": ("2007-01-01..2010-12-31: tuning "
                                           "only, never counted (§8)")}}
    if a0_dev_dir is None or a0_val_dir is None:
        raise ValueError(f"{candidate}: the incremental verdict needs A0's sweeps")
    a_dev, a_val = load(a0_dev_dir), load(a0_val_dir)
    i_dev, i_val = gate_rowwise(cand_dev, a_dev), gate_rowwise(cand_val, a_val)
    incremental = {"development": i_dev, "validation": i_val,
                   "verdict": gate_verdict(i_dev, i_val),
                   "thresholds": GATE_THRESHOLDS, "control": "A0"}
    joins = incremental["verdict"] == "ADOPT" and adoption["verdict"] == "ADOPT"
    # §10 defines no combined verdict: the family's evidence is the
    # incremental verdict, and it joins the stack only if both are ADOPT.
    return {"candidate": candidate,
            "family_evidence": incremental["verdict"],
            "joins_stack": joins,
            "incremental": incremental, "adoption": adoption,
            "mandate": _mandate_block(cand_dev, cand_val), "extras": extras}
