"""MANDATE §3 and §5 arithmetic (effective 2026-09-21).

Synthetic criteria.json dicts only. The mandate decides ADVANCE; GATE still
decides adoption; neither recomputes a recorded verdict.
"""
import json

from pflab.eval import classify as C


def _crit(base_cagr, base_dd, b2=(0.10, 0.40), b5=(0.12, 0.45), rows=None):
    r = {"base": {"cagr": base_cagr, "max_drawdown": base_dd, "turnover_annual": 1.0}}
    for k, (c, d) in (rows or {}).items():
        r[k] = {"cagr": c, "max_drawdown": d, "turnover_annual": 1.0}
    bench = {"B2": {"cagr": b2[0], "max_drawdown": b2[1]},
             "B3": {"cagr": 0.13, "max_drawdown": 0.5}}
    if b5 is not None:
        bench["B5"] = {"cagr": b5[0], "max_drawdown": b5[1]}
    return {"rows": r, "benchmarks": bench}


def test_section3_needs_both_the_return_and_the_drawdown_test():
    ok = C.mandate_for_period(_crit(0.135, 0.44))          # +3.5 pp, +4 pp deeper
    assert ok["M3"] is True
    thin = C.mandate_for_period(_crit(0.125, 0.44))        # only +2.5 pp
    assert thin["M3"] is False
    deep = C.mandate_for_period(_crit(0.20, 0.46))         # 6 pp deeper
    assert deep["M3"] is False


def test_section3_needs_two_thirds_of_the_rows():
    rows = {"S1": (0.135, 0.44), "S2": (0.08, 0.44)}       # base + S1 hold, S2 fails
    assert C.mandate_for_period(_crit(0.135, 0.44, rows=rows))["M3"] is True
    rows = {"S1": (0.08, 0.44), "S2": (0.08, 0.44)}        # 1 of 3 holds
    assert C.mandate_for_period(_crit(0.135, 0.44, rows=rows))["M3"] is False


def test_section5_is_two_points_over_b5():
    assert C.mandate_for_period(_crit(0.145, 0.44))["M5"] is True     # +2.5 over 12%
    assert C.mandate_for_period(_crit(0.135, 0.44))["M5"] is False    # +1.5


def test_missing_b5_is_reported_not_guessed():
    m = C.mandate_for_period(_crit(0.145, 0.44, b5=None))
    assert m["M5"] is None and m["M5_available"] is False
    v = C.mandate_verdict(m, m)
    assert v["meets"] is False and v["M5"] is None


def test_meeting_the_mandate_needs_both_sections_in_both_periods():
    good = C.mandate_for_period(_crit(0.145, 0.44))
    bad = C.mandate_for_period(_crit(0.11, 0.44))
    assert C.mandate_verdict(good, good)["meets"] is True
    assert C.mandate_verdict(good, bad)["meets"] is False


def test_negative_controls_are_never_counted():
    rows = {"N1": (0.0, 0.9), "N2": (0.0, 0.9)}
    m = C.mandate_for_period(_crit(0.135, 0.44, rows=rows))
    assert m["M3_rows_total"] == 1 and m["M3"] is True


def test_classify_e1c_carries_gate_c1_c4_mandate_and_section6(tmp_path):
    def w(d, crit):
        d.mkdir()
        (d / "criteria.json").write_text(json.dumps(crit), encoding="utf-8")
        return d
    cand = _crit(0.145, 0.44, rows={"S1": (0.14, 0.43)})
    stack = _crit(0.10, 0.45)
    out = C.classify_e1c(w(tmp_path / "cd", cand), w(tmp_path / "cv", cand),
                         w(tmp_path / "sd", stack), w(tmp_path / "sv", stack))
    assert set(out) == {"gate", "charter_c1_c4", "mandate", "section6"}
    assert out["mandate"]["verdict"]["meets"] is True
    s6 = out["section6"]["development"]
    assert abs(s6["base_minus_S1_cagr_pp"] - 0.5) < 1e-9
    assert abs(s6["gap_to_B3_pp"] - 1.5) < 1e-9
