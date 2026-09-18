"""E1b's sweep rows, GATE verdict and extras (charter E1b §6, §7, §8).

Nothing here runs E1b. These tests assert that when Aarsh locks it, the rows
reach every consumer, the two verdicts are computed from disk, and the overlap
extra refuses to invent a number.
"""
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from conftest import flat_index, random_walk_panel
from pflab.data import index_membership as im
from pflab.eval import artifacts, classify as C, sweep as S
from pflab.eval.periods import Period


def _index(sessions, annual=0.10, level=1000.0):
    g = (1 + annual) ** (1 / 252.0)
    return pd.DataFrame({"date": sessions,
                         "close": level * g ** np.arange(len(sessions))})


# -- §6 rows ------------------------------------------------------------
def test_e1b_adds_its_own_rows_and_changes_none_of_e1s():
    assert list(S.ROWS) == ["base", "S1", "S2", "S3", "S4", "S5", "S6", "S7",
                            "S8", "S9"]
    rows = S.e1b_rows()
    assert list(rows) == list(S.ROWS) + ["S10", "S11", "S12", "S13"]
    for r in S.ROWS:
        assert rows[r] == S.ROWS[r]        # E1's nine, unchanged (§6)
    assert rows["S10"]["universe.index"] == "NIFTY500"
    assert rows["S11"]["universe.mode"] == "turnover_top_n"
    assert rows["S11"]["universe.top_n_by_turnover"] == 200
    # §6 as amended 2026-09-18: S12 brackets rather than drops, S13 runs the
    # published-only window
    assert rows["S12"]["universe.membership_bound"] == "latest"
    assert rows["S13"]["period.start"] == "2012-01-01"


def test_apply_row_reaches_the_e1b_rows(base_config):
    cfg = dict(base_config)
    cfg["universe"] = {**base_config["universe"], "mode": "index_members",
                       "index": "NIFTY200"}
    s10 = S.apply_row(cfg, "S10")
    assert s10["universe"]["index"] == "NIFTY500"
    assert s10["universe"]["mode"] == "index_members"     # still membership (§6)
    s11 = S.apply_row(cfg, "S11")
    assert s11["universe"]["mode"] == "turnover_top_n"
    assert s11["universe"]["top_n_by_turnover"] == 200
    assert cfg["universe"]["index"] == "NIFTY200"          # original untouched


def test_extra_rows_reach_every_consumer(tmp_path):
    """The bug this guards: every writer below used to iterate `ROWS`, so S10
    and S11 would have vanished from summary.md, extras.json, adv_skips.json
    and criteria.json -- and criteria.json is what §13's C4 and GATE's G3
    count rows from."""
    def fake(cagr):
        return {"result": None, "error": None,
                "metrics": {"paths": {"nav_liq": {"cagr": cagr, "max_drawdown": -0.3,
                                                  "sharpe": 0.5}},
                            "turnover_annual": 1.2, "trades": {"n": 10}},
                "adv_skips": {"skips": 0}, "extras": None}

    results = {r: fake(0.12) for r in S.e1b_rows()}
    results["_benchmarks"] = {"B2": {"paths": {"nav_liq": {"cagr": 0.08,
                                                           "max_drawdown": -0.3}}}}
    assert S.rows_present(results) == list(S.e1b_rows())

    S.write_summary(results, tmp_path, Period("dev", date(2007, 1, 1),
                                              date(2016, 12, 31)),
                    experiment="E1b")
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert text.startswith("# E1b sweep")
    assert "| S10 |" in text and "| S11 |" in text
    crit = json.loads((tmp_path / "criteria.json").read_text(encoding="utf-8"))
    assert "S10" in crit["rows"] and "S11" in crit["rows"]
    assert crit["rows"]["S10"]["turnover_annual"] == 1.2      # G4 needs this
    for f in ("extras.json", "adv_skips.json"):
        assert set(json.loads((tmp_path / f).read_text(encoding="utf-8"))) \
            == set(S.e1b_rows())


def test_e1b_sweep_runs_end_to_end_on_a_membership_universe(tmp_path, base_config,
                                                            cost_model, tax_policy):
    sessions, names, panel = random_walk_panel(seed=41, n_names=16,
                                               start="2013-01-01", end="2018-12-31")
    n200, n500 = names[:6], names[:12]
    table = pd.concat([
        pd.DataFrame([{"index": "NIFTY200", "isin": n, "symbol": f"S{i}",
                       "from_date": date(2013, 1, 1), "to_date": None}
                      for i, n in enumerate(n200)], columns=im.COLUMNS),
        pd.DataFrame([{"index": "NIFTY500", "isin": n, "symbol": f"S{i}",
                       "from_date": date(2013, 1, 1), "to_date": None}
                      for i, n in enumerate(n500)], columns=im.COLUMNS)],
        ignore_index=True)

    cfg = dict(base_config)
    cfg["universe"] = {**base_config["universe"], "mode": "index_members",
                       "index": "NIFTY200"}
    per = Period("dev", date(2015, 1, 1), date(2018, 12, 31))
    idx = {"NIFTY50_TRI": _index(sessions, 0.09),
           "NIFTY500_TRI": _index(sessions, 0.08),
           "NIFTY200_MOMENTUM30_TRI": _index(sessions, 0.11),
           "NIFTY50_PRICE": _index(sessions, 0.09)}

    out = S.run_sweep(cfg, per, panel, idx, lambda m: cost_model.scaled(m),
                      tax_policy, out_dir=tmp_path, membership=table,
                      experiment="E1b", rows=list(S.e1b_rows()),
                      overlap_membership=table, overlap_index="NIFTY200")

    for row in S.e1b_rows():
        assert out[row]["error"] is None, f"{row}: {out[row]['error']}"

    # S10 draws from the wider list, so it can hold names the base row cannot
    base_held = {i for d in out["base"]["result"].decisions for i in (d.get("held") or [])}
    s10_held = {i for d in out["S10"]["result"].decisions for i in (d.get("held") or [])}
    assert base_held <= set(n200)
    assert s10_held <= set(n500)

    # §3: no name is ever eligible outside its membership window
    im.assert_no_membership_leak(
        table, "NIFTY200",
        {d["month_end"]: d.get("held") or [] for d in out["base"]["result"].decisions})

    # S11 is turnover-ranked, so it is NOT bound by membership -- that is the
    # separation of "large" from "index member" the row exists for
    assert out["S11"]["result"].universe_pre["mode"] == "turnover_top_n"


# -- §8 overlap extra ---------------------------------------------------
def test_overlap_reports_a_sentence_when_there_is_no_pit_table(base_config, cost_model,
                                                               tax_policy):
    """Overlap against TODAY's momentum-30 list would read as a real number
    while being a survivorship artefact. A blank is safer than a wrong number."""
    from pflab.backtest import engine
    sessions, _, panel = random_walk_panel(seed=44, n_names=10,
                                           start="2014-01-01", end="2017-12-31")
    res = engine.run(base_config, Period("t", date(2016, 1, 1), date(2017, 12, 31)),
                     panel, flat_index(sessions), cost_model, tax_policy)
    ov = artifacts.extras_report(res)["index_overlap"]
    assert isinstance(ov, str) and "survivorship" in ov


def test_overlap_counts_holding_months_against_the_window(base_config, cost_model,
                                                          tax_policy):
    from pflab.backtest import engine
    sessions, names, panel = random_walk_panel(seed=45, n_names=10,
                                              start="2014-01-01", end="2017-12-31")
    all_in = pd.DataFrame(
        [{"index": "NIFTY200_MOMENTUM30", "isin": n, "symbol": f"S{i}",
          "from_date": date(2014, 1, 1), "to_date": None}
         for i, n in enumerate(names)], columns=im.COLUMNS)
    none_in = all_in.assign(to_date=date(2014, 6, 1))

    per = Period("t", date(2016, 1, 1), date(2017, 12, 31))
    res = engine.run(base_config, per, panel, flat_index(sessions), cost_model,
                     tax_policy)
    full = artifacts.extras_report(res, membership=all_in)["index_overlap"]
    empty = artifacts.extras_report(res, membership=none_in)["index_overlap"]
    assert full["overall_pct"] == 100.0
    assert empty["overall_pct"] == 0.0
    assert set(full["by_year"]) == {2016, 2017}


# -- §7 GATE ------------------------------------------------------------
def _crit(cagr, dd, turnover=1.0, n_rows=12):
    rows = {"base": {"cagr": cagr, "max_drawdown": dd, "error": None,
                     "turnover_annual": turnover}}
    for i in range(1, n_rows):
        rows[f"S{i}"] = {"cagr": cagr, "max_drawdown": dd, "error": None,
                         "turnover_annual": turnover}
    return {"rows": rows,
            "benchmarks": {"B2": {"cagr": 0.08, "max_drawdown": -0.30},
                           "B3": {"cagr": 0.09, "max_drawdown": -0.32}}}


def test_gate_adopts_when_the_candidate_beats_the_stack():
    g = C.gate_for_period(_crit(0.13, -0.30), _crit(0.11, -0.30))
    assert g["usable"] and g["G1"] and g["G2"] and g["G3"] and g["G4"]
    assert C.gate_verdict(g, g) == "ADOPT"


def test_gate_g1_also_passes_on_a_much_smaller_drawdown():
    """G1 is 'better return OR materially smaller drawdown'."""
    g = C.gate_for_period(_crit(0.11, -0.25), _crit(0.11, -0.30))
    assert g["G1"] and g["cagr_gap_pp"] == pytest.approx(0.0)


def test_gate_rejects_when_g1_fails_in_both_periods():
    g = C.gate_for_period(_crit(0.11, -0.30), _crit(0.11, -0.30))
    assert not g["G1"]
    assert C.gate_verdict(g, g) == "REJECT"


def test_gate_g2_forbids_a_materially_worse_drawdown():
    g = C.gate_for_period(_crit(0.14, -0.35), _crit(0.11, -0.30))
    assert g["G1"] and not g["G2"]      # 5 pp worse drawdown
    assert C.gate_verdict(g, g) == "REJECT"


def test_gate_g4_caps_turnover_at_twice_the_stack():
    ok = C.gate_for_period(_crit(0.13, -0.30, turnover=2.0),
                           _crit(0.11, -0.30, turnover=1.0))
    bad = C.gate_for_period(_crit(0.13, -0.30, turnover=2.5),
                            _crit(0.11, -0.30, turnover=1.0))
    assert ok["G4"] and not bad["G4"]


def test_gate_is_inconclusive_when_only_one_period_holds():
    good = C.gate_for_period(_crit(0.13, -0.30), _crit(0.11, -0.30))
    bad = C.gate_for_period(_crit(0.105, -0.30), _crit(0.11, -0.30))
    assert C.gate_verdict(good, bad) == "INCONCLUSIVE"
    assert C.gate_verdict(bad, good) == "INCONCLUSIVE"


def test_gate_counts_every_row_including_s10_and_s11():
    cand = _crit(0.13, -0.30, n_rows=12)
    # S10 and S11 fail; 10 of 12 still clears the two-thirds bar
    cand["rows"]["S10"] = {"cagr": 0.05, "max_drawdown": -0.5, "error": None}
    cand["rows"]["S11"] = {"cagr": 0.05, "max_drawdown": -0.5, "error": None}
    g = C.gate_for_period(cand, _crit(0.11, -0.30))
    assert g["rows_total"] == 12 and g["rows_holding"] == 10 and g["G3"]


def test_a_halted_candidate_base_is_not_a_gate_verdict():
    cand = _crit(0.13, -0.30)
    cand["rows"]["base"] = {"error": "ADVDataError: ..."}
    g = C.gate_for_period(cand, _crit(0.11, -0.30))
    assert not g["usable"]
    assert C.gate_verdict(g, g) == "INCONCLUSIVE"


def test_classify_e1b_produces_both_outputs_from_disk(tmp_path):
    """§7: the GATE verdict against E1 base AND E1 §13's C1-C4, both periods.
    ADVANCE is a property of the current base, not of one experiment."""
    dirs = {}
    for name, crit in (("cand_dev", _crit(0.13, -0.30)),
                       ("cand_val", _crit(0.13, -0.30)),
                       ("stack_dev", _crit(0.11, -0.30)),
                       ("stack_val", _crit(0.11, -0.30))):
        d = tmp_path / name
        d.mkdir()
        (d / "criteria.json").write_text(json.dumps(crit), encoding="utf-8")
        dirs[name] = d

    out = C.classify_e1b(dirs["cand_dev"], dirs["cand_val"],
                         dirs["stack_dev"], dirs["stack_val"])
    assert set(out) == {"gate", "charter_c1_c4"}
    assert out["gate"]["verdict"] == "ADOPT"
    assert out["gate"]["stack"] == "E1 base"
    for period in ("development", "validation"):
        assert out["gate"][period]["usable"]
        assert out["charter_c1_c4"][period]["usable"]
        for c in ("C1", "C2", "C3", "C4"):
            assert out["charter_c1_c4"][period][c] is not None
    # 13% vs B2 8% and B3 9%: clears §13 too, but by its own arithmetic
    assert out["charter_c1_c4"]["verdict"] == "ADVANCE"


def test_gate_and_charter_verdicts_are_independent():
    """A candidate can beat E1 by 2 pp and still miss §13's 2 pp over B3."""
    cand, stack = _crit(0.105, -0.30), _crit(0.085, -0.30)
    g = C.gate_for_period(cand, stack)
    c = C.criteria_for_period(cand)
    assert g["G1"] and C.gate_verdict(g, g) == "ADOPT"
    assert not c["C2"] and C.verdict(c, c) == "INCONCLUSIVE"


# -- S13: a row that shortens the window (E1b §6) -----------------------
def test_only_s13_changes_the_window():
    """A row that silently shortened the window would not be comparable to
    anything else in the sweep."""
    per = Period("dev", date(2007, 1, 1), date(2016, 12, 31))
    for row in S.e1b_rows():
        got = S.period_for_row(per, row)
        if row == "S13":
            assert got.start == date(2012, 1, 1) and got.end == per.end
        else:
            assert got is per, row


def test_s13_is_ignored_when_the_period_already_starts_later():
    per = Period("val", date(2017, 1, 1), date(2021, 12, 31))
    assert S.period_for_row(per, "S13") is per


def test_a_short_window_row_gets_the_stack_on_its_own_window(tmp_path, base_config,
                                                             cost_model, tax_policy):
    """E1 base is re-run on S13's window, because a row on a shorter window
    cannot be compared with the stack's full-window result."""
    sessions, names, panel = random_walk_panel(seed=52, n_names=14,
                                               start="2009-01-01", end="2016-12-31")
    table = pd.DataFrame(
        [{"index": "NIFTY200", "isin": n, "symbol": f"S{i}",
          "from_date": date(2009, 1, 1), "to_date": None,
          "from_source": "change", "to_source": "open",
          "from_date_latest": date(2009, 1, 1)}
         for i, n in enumerate(names[:8])],
        columns=im.COLUMNS + im.PROVENANCE + im.BOUNDS)

    cfg = dict(base_config)
    cfg["universe"] = {**base_config["universe"], "mode": "index_members",
                       "index": "NIFTY200"}
    per = Period("dev", date(2011, 1, 1), date(2016, 12, 31))
    idx = {"NIFTY500_TRI": _index(sessions, 0.08),
           "NIFTY200_MOMENTUM30_TRI": _index(sessions, 0.11),
           "NIFTY50_PRICE": _index(sessions, 0.09)}

    out = S.run_sweep(cfg, per, panel, idx, lambda m: cost_model.scaled(m),
                      tax_policy, out_dir=tmp_path, membership=table,
                      experiment="E1b", rows=["base", "S13"])

    assert out["base"]["error"] is None and out["S13"]["error"] is None
    stack = out["_S13_stack"]
    assert stack["period"] == "2012-01-01"
    assert stack["metrics"]["paths"]["nav_liq"]["cagr"] is not None
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "the stack on the same window" in text
    assert "2012-01-01..2016-12-31" in text
