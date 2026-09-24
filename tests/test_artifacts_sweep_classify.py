"""Benchmarks, artifacts, sweep and verdict — Phase 2 tasks 2.2, 2.3, 2.6, 2.7."""
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from conftest import flat_index, random_walk_panel
from pflab.backtest import engine
from pflab.eval import artifacts, classify as C, sweep as S
from pflab.eval.periods import Period


def _index(sessions, annual=0.10, level=1000.0):
    g = (1 + annual) ** (1 / 252.0)
    return pd.DataFrame({"date": sessions,
                         "close": level * g ** np.arange(len(sessions))})


# -- 2.2 benchmarks -----------------------------------------------------
def test_benchmark_runs_through_the_same_loop(base_config, cost_model, tax_policy):
    sessions, _, _ = random_walk_panel(seed=30, n_names=3,
                                       start="2015-01-01", end="2019-12-31")
    per = Period("t", date(2016, 1, 1), date(2019, 12, 31))
    r = engine.run_benchmark(base_config, per, _index(sessions), cost_model,
                             tax_policy, name="NIFTY500_TRI")
    assert len(r.equity) > 0
    assert len(r.trades) > 0 and set(r.trades["side"]) == {"BUY"}   # never sold (§10)
    nav = pd.Series(r.equity["nav_liq"].values,
                    index=pd.to_datetime(r.equity["date"])).dropna()
    from pflab.eval.metrics import cagr
    assert 0.05 < cagr(nav) < 0.11        # tracks the index, less costs and tax


def test_benchmark_expense_drag_lowers_the_result(base_config, cost_model, tax_policy):
    """B3 carries a 0.30% p.a. expense ratio (§10)."""
    sessions, _, _ = random_walk_panel(seed=31, n_names=3,
                                       start="2015-01-01", end="2019-12-31")
    per = Period("t", date(2016, 1, 1), date(2019, 12, 31))
    idx = _index(sessions)
    plain = engine.run_benchmark(base_config, per, idx, cost_model, tax_policy, "X", 0.0)
    drag = engine.run_benchmark(base_config, per, idx, cost_model, tax_policy, "X", 0.003)
    assert drag.equity["total"].iloc[-1] < plain.equity["total"].iloc[-1]


# -- 2.3 artifacts ------------------------------------------------------
def _small_run(base_config, cost_model, tax_policy):
    sessions, _, panel = random_walk_panel(seed=32, n_names=12,
                                           start="2014-01-01", end="2018-12-31")
    per = Period("t", date(2016, 1, 1), date(2018, 12, 31))
    return engine.run(base_config, per, panel, flat_index(sessions),
                      cost_model, tax_policy), panel, per


def test_write_run_produces_every_artifact(tmp_path, base_config, cost_model, tax_policy):
    res, panel, per = _small_run(base_config, cost_model, tax_policy)
    man = {"run_id": "abc", "period": per.name}
    artifacts.write_run(tmp_path / "run", res, man)
    for f in ("manifest.json", "metrics.json", "decisions.json", "equity.csv",
              "trades.csv", "taxes.csv", "provenance.jsonl"):
        assert (tmp_path / "run" / f).exists(), f


def test_rerunning_identical_inputs_verifies_and_does_not_overwrite(
        tmp_path, base_config, cost_model, tax_policy):
    """Principle 9: artifacts are immutable; re-running verifies."""
    res, _, per = _small_run(base_config, cost_model, tax_policy)
    man = {"run_id": "abc", "period": per.name}
    d = artifacts.write_run(tmp_path / "run", res, man)
    (d / "equity.csv").write_text("SENTINEL", encoding="utf-8")
    artifacts.write_run(tmp_path / "run", res, man)
    assert (d / "equity.csv").read_text(encoding="utf-8") == "SENTINEL"


def test_a_different_run_id_in_the_same_directory_is_refused(
        tmp_path, base_config, cost_model, tax_policy):
    res, _, per = _small_run(base_config, cost_model, tax_policy)
    artifacts.write_run(tmp_path / "run", res, {"run_id": "abc", "period": per.name})
    with pytest.raises(artifacts.ArtifactConflict):
        artifacts.write_run(tmp_path / "run", res, {"run_id": "xyz", "period": per.name})


def test_metrics_cover_the_three_nav_paths(base_config, cost_model, tax_policy):
    res, _, _ = _small_run(base_config, cost_model, tax_policy)
    m = artifacts.metrics_of(res)
    assert set(m["paths"]) == {"nav_pre", "nav_post", "nav_liq"}
    for p in m["paths"].values():
        assert {"cagr", "max_drawdown", "sharpe"} <= set(p)
    assert m["trades"]["n"] == len(res.trades)
    assert "tax_drag_pct_of_flow" in m["tax"]


def test_pre_tax_nav_is_at_least_after_tax_nav(base_config, cost_model, tax_policy):
    res, _, _ = _small_run(base_config, cost_model, tax_policy)
    both = res.equity[["nav_pre", "nav_post"]].dropna()   # NaN before capital exists
    assert len(both) > 100
    assert (both["nav_pre"] >= both["nav_post"] - 1e-9).all()


# -- 2.6 sweep ----------------------------------------------------------
def test_sweep_rows_are_the_charter_rows():
    """§12 is nine rows plus the base. Adding one after a run is forbidden."""
    assert list(S.ROWS) == ["base", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"]


def test_apply_row_changes_only_its_own_setting(base_config):
    s3 = S.apply_row(base_config, "S3")
    assert s3["strategy"]["n_hold"] == 20 and s3["strategy"]["band_exit_rank"] == 40
    assert base_config["strategy"]["n_hold"] == 10        # original untouched
    assert s3["strategy"]["sip_amount"] == base_config["strategy"]["sip_amount"]


def test_sweep_runs_every_row_and_writes_a_summary(tmp_path, base_config,
                                                   cost_model, tax_policy):
    sessions, _, panel = random_walk_panel(seed=33, n_names=14,
                                           start="2014-01-01", end="2018-12-31")
    per = Period("dev", date(2016, 1, 1), date(2018, 12, 31))
    idx = {"NIFTY50_TRI": _index(sessions, 0.09),
           "NIFTY500_TRI": _index(sessions, 0.08),
           "NIFTY200_MOMENTUM30_TRI": _index(sessions, 0.11)}
    idx["NIFTY50_PRICE"] = _index(sessions, 0.09)
    out = S.run_sweep(base_config, per, panel, idx,
                      lambda m: cost_model.scaled(m), tax_policy, out_dir=tmp_path)
    for row in S.ROWS:
        assert row in out
        # a row that merely APPEARS proves nothing; the first sweep on real
        # data had every row present and every row halted.
        assert out[row]["error"] is None, f"{row}: {out[row]['error']}"
        assert out[row]["metrics"]["paths"]["nav_liq"]["cagr"] is not None
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert text.index("Base row") < text.index("S1")      # base leads
    assert "stability check" in text
    crit = json.loads((tmp_path / "criteria.json").read_text(encoding="utf-8"))
    assert "base" in crit["rows"] and "B2" in crit["benchmarks"]


def test_a_halted_row_is_recorded_not_dropped(tmp_path, base_config,
                                              cost_model, tax_policy):
    sessions, _, panel = random_walk_panel(seed=34, n_names=12,
                                           start="2014-01-01", end="2017-12-31")
    panel["turnover"] = 0.0              # ADV 0: the one remaining §7 halt
    per = Period("dev", date(2016, 1, 1), date(2017, 12, 31))
    out = S.run_sweep(base_config, per, panel, {}, lambda m: cost_model.scaled(m),
                      tax_policy, out_dir=tmp_path, rows=["base"])
    assert out["base"]["error"] and "ADVDataError" in out["base"]["error"]
    assert "HALTED" in (tmp_path / "summary.md").read_text(encoding="utf-8")


# -- 2.7 classify -------------------------------------------------------
def _crit(cagr, dd, b2=(0.08, -0.30), b3=(0.09, -0.32), rows_hold=9):
    rows = {"base": {"cagr": cagr, "max_drawdown": dd, "error": None}}
    for i in range(1, 10):
        name = f"S{i}"
        good = i <= rows_hold - 1
        rows[name] = {"cagr": cagr if good else 0.0,
                      "max_drawdown": dd if good else -0.9, "error": None}
    return {"rows": rows,
            "benchmarks": {"B2": {"cagr": b2[0], "max_drawdown": b2[1]},
                           "B3": {"cagr": b3[0], "max_drawdown": b3[1]}}}


def test_advance_when_every_criterion_holds():
    c = C.criteria_for_period(_crit(0.13, -0.32))
    assert c["C1"] and c["C2"] and c["C3"] and c["C4"]
    assert C.verdict(c, c) == "ADVANCE"


def test_reject_when_c1_fails_in_both_periods():
    c = C.criteria_for_period(_crit(0.081, -0.30))
    assert c["C1"] is False
    assert C.verdict(c, c) == "REJECT"


def test_inconclusive_when_only_one_period_fails():
    good = C.criteria_for_period(_crit(0.13, -0.32))
    bad = C.criteria_for_period(_crit(0.081, -0.30))
    assert C.verdict(good, bad) == "INCONCLUSIVE"
    assert C.verdict(bad, good) == "INCONCLUSIVE"


def test_c3_compares_drawdown_magnitudes():
    """MaxDD is negative; §13 allows E1 to be 5 pp worse than B2."""
    ok = C.criteria_for_period(_crit(0.13, -0.34))     # 4 pp worse than -0.30
    bad = C.criteria_for_period(_crit(0.13, -0.36))    # 6 pp worse
    assert ok["C3"] is True and bad["C3"] is False


def test_c4_needs_six_of_nine_rows():
    five = C.criteria_for_period(_crit(0.13, -0.32, rows_hold=5))
    assert five["C4"] is False
    seven = C.criteria_for_period(_crit(0.13, -0.32, rows_hold=7))
    assert seven["C4"] is True


def test_a_halted_base_row_is_not_a_verdict():
    crit = _crit(0.13, -0.32)
    crit["rows"]["base"]["error"] = "ADVDataError: ..."
    c = C.criteria_for_period(crit)
    assert c["usable"] is False
    assert C.verdict(c, c) == "INCONCLUSIVE"


def test_missing_benchmark_is_not_a_verdict():
    crit = _crit(0.13, -0.32)
    crit["benchmarks"].pop("B2")
    c = C.criteria_for_period(crit)
    assert c["usable"] is False and "B2" in c["reason"]


def test_classify_reads_only_from_disk(tmp_path):
    """Verdicts are computed, never typed (principle 4)."""
    for name, crit in (("dev", _crit(0.13, -0.32)), ("val", _crit(0.13, -0.32))):
        d = tmp_path / name
        d.mkdir()
        (d / "criteria.json").write_text(json.dumps(crit), encoding="utf-8")
    out = C.classify(tmp_path / "dev", tmp_path / "val")
    assert out["verdict"] == "ADVANCE"
    assert out["thresholds"] == C.THRESHOLDS


# -- 2.2 B4 equal-weight universe ---------------------------------------
def test_b4_equal_weight_universe_runs_and_rebalances(base_config, cost_model, tax_policy):
    """§10 B4: equal weight of the eligible universe, rebalanced monthly. It
    is the one benchmark that sells to rebalance, which is the point."""
    sessions, _, panel = random_walk_panel(seed=35, n_names=12,
                                           start="2014-01-01", end="2018-12-31")
    per = Period("t", date(2016, 1, 1), date(2018, 12, 31))
    r = engine.run_equal_weight_universe(base_config, per, panel, cost_model, tax_policy)
    assert len(r.equity) > 0 and len(r.trades) > 0
    sides = set(r.trades["side"])
    assert "BUY_REBAL" in sides
    assert {"nav_pre", "nav_post", "nav_liq"} <= set(r.equity.columns)


def test_b4_turns_over_more_than_e1(base_config, cost_model, tax_policy):
    """A stated expectation of the benchmark: rebalancing costs turnover."""
    sessions, _, panel = random_walk_panel(seed=36, n_names=12,
                                           start="2014-01-01", end="2018-12-31")
    per = Period("t", date(2016, 1, 1), date(2018, 12, 31))
    e1 = engine.run(base_config, per, panel, flat_index(sessions), cost_model, tax_policy)
    b4 = engine.run_equal_weight_universe(base_config, per, panel, cost_model, tax_policy)
    assert len(b4.trades) > len(e1.trades)


def test_b4_refuses_a_panel_past_the_period_end(base_config, cost_model, tax_policy):
    sessions, _, panel = random_walk_panel(seed=37, n_names=8,
                                           start="2014-01-01", end="2018-12-31")
    per = Period("t", date(2016, 1, 1), date(2017, 12, 31))
    with pytest.raises(ValueError, match="past the period end"):
        engine.run_equal_weight_universe(base_config, per, panel, cost_model, tax_policy)


def test_summary_carries_the_skip_section_and_a_skip_file(
        tmp_path, base_config, cost_model, tax_policy):
    """§15 requires the skips to be reported, not just counted. The first
    amended sweep wrote the counts but lost the section."""
    sessions, _, panel = random_walk_panel(seed=38, n_names=25,
                                           start="2014-01-01", end="2018-12-31")
    panel = panel.copy()
    panel["turnover"] = 3_000_000.0          # thin enough to force skips
    per = Period("dev", date(2016, 1, 1), date(2018, 12, 31))
    idx = {"NIFTY50_PRICE": _index(sessions, 0.09),
           "NIFTY500_TRI": _index(sessions, 0.08),
           "NIFTY200_MOMENTUM30_TRI": _index(sessions, 0.11)}
    out = S.run_sweep(base_config, per, panel, idx,
                      lambda m: cost_model.scaled(m), tax_policy,
                      out_dir=tmp_path, rows=["base"])
    assert out["base"]["adv_skips"]["skips"] > 0
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "ADV skips" in text
    assert "attempted" in text
    assert "Months where every planned buy was skipped" in text
    saved = json.loads((tmp_path / "adv_skips.json").read_text(encoding="utf-8"))
    assert saved["base"]["skips"] == out["base"]["adv_skips"]["skips"]


# -- development-review extras (reporting only) -------------------------
def test_extras_report_covers_the_four_requested_items(base_config, cost_model,
                                                       tax_policy):
    res, _, _ = _small_run(base_config, cost_model, tax_policy)
    x = artifacts.extras_report(res)
    assert {"tax", "delisting", "regime", "holdings_turnover_rank",
            "market_cap_proxy"} <= set(x)
    t = x["tax"]
    assert t["cagr_pre_tax_liq"] >= t["cagr_after_tax_liq"] - 1e-9
    assert t["tax_drag_pp"] >= -1e-9
    assert t["tax_paid_total"] == pytest.approx(
        t["tax_paid_running"] + t["tax_paid_liquidation"])
    r = x["regime"]
    assert 0 <= r["risk_off_months_total"] <= r["months_total"]
    # cash share may be NEGATIVE: section 8 lets the FY tax bill overdraw the
    # sleeve, refilled by later SIPs. Only the upper bound is structural.
    assert all(v["mean_cash_share_pct"] <= 100 for v in r["by_year"].values())
    assert all(v["max_cash_share_pct"] <= 100 for v in r["by_year"].values())
    assert x["holdings_turnover_rank"], "turnover ranks should be computed"
    assert "unavailable" in x["market_cap_proxy"]


def test_extras_are_reporting_only_and_change_no_decision(base_config, cost_model,
                                                          tax_policy):
    """Computing the extras must not mutate the run it reads."""
    res, _, _ = _small_run(base_config, cost_model, tax_policy)
    before_eq = res.equity.copy()
    before_trades = res.trades.copy()
    artifacts.extras_report(res)
    artifacts.extras_report(res)
    pd.testing.assert_frame_equal(res.equity, before_eq)
    pd.testing.assert_frame_equal(res.trades, before_trades)


def test_summary_carries_the_extras_section(tmp_path, base_config, cost_model,
                                            tax_policy):
    sessions, _, panel = random_walk_panel(seed=39, n_names=14,
                                           start="2014-01-01", end="2018-12-31")
    per = Period("dev", date(2016, 1, 1), date(2018, 12, 31))
    idx = {"NIFTY50_PRICE": _index(sessions, 0.09),
           "NIFTY500_TRI": _index(sessions, 0.08),
           "NIFTY200_MOMENTUM30_TRI": _index(sessions, 0.11)}
    S.run_sweep(base_config, per, panel, idx, lambda m: cost_model.scaled(m),
                tax_policy, out_dir=tmp_path, rows=["base"])
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "Extras (reporting only" in text
    assert "Pre-tax CAGR and tax paid" in text
    assert "RISK_OFF months and cash share" in text
    assert "Median turnover rank" in text
    saved = json.loads((tmp_path / "extras.json").read_text(encoding="utf-8"))
    assert saved["base"]["tax"]["cagr_pre_tax_liq"] is not None


# -- invested-equity return (E1b development review) --------------------
def test_equity_sleeve_return_strips_the_cash_carry(base_config, cost_model,
                                                    tax_policy):
    """The base row held a mean 22.4% in cash at 6% while the benchmark
    compounded at 13.5%, so the headline CAGR mixes what the signal picked
    with what the seat belt cost. The sleeve return separates them."""
    sessions, _, panel = random_walk_panel(seed=61, n_names=12,
                                           start="2014-01-01", end="2019-12-31")
    per = Period("t", date(2016, 1, 1), date(2019, 12, 31))
    res = engine.run(base_config, per, panel, flat_index(sessions), cost_model,
                     tax_policy)
    e = artifacts.extras_report(res)["equity_sleeve"]

    assert e["available"] is True
    # the decomposition must RECONCILE: equity + cash contribution is the
    # portfolio's own pre-tax return, which is what makes it an attribution
    # rather than two unrelated numbers
    assert e["contribution_sum_pp"] == pytest.approx(
        100 * e["cagr_pre_tax_for_reconciliation"], abs=0.5)


def test_equity_sleeve_beats_the_total_when_cash_earns_less_than_equity(
        base_config, cost_model, tax_policy):
    """A drifting market with a low cash rate: the invested portion must earn
    more than the blended portfolio, or the split is not doing anything."""
    sessions, _, panel = random_walk_panel(seed=62, n_names=12, annual_drift=0.15,
                                           start="2014-01-01", end="2019-12-31")
    cfg = {**base_config,
           "strategy": {**base_config["strategy"], "cash_rate_annual": 0.0}}
    per = Period("t", date(2016, 1, 1), date(2019, 12, 31))
    res = engine.run(cfg, per, panel, flat_index(sessions), cost_model, tax_policy)
    e = artifacts.extras_report(res)["equity_sleeve"]
    # a drifting market with zero cash rate: essentially all of the return
    # has to come from equity, and cash must contribute ~nothing
    assert e["contribution_equity_pp"] > 0
    assert abs(e["contribution_cash_pp"]) < 0.5
    assert e["contribution_sum_pp"] == pytest.approx(
        100 * e["cagr_pre_tax_for_reconciliation"], abs=0.5)


def test_dividends_are_added_back_to_the_sleeve(base_config, cost_model,
                                                tax_policy):
    """A dividend leaves `equity_value` for cash on the ex-date. Without
    adding it back the sleeve would report a price return and call it a total
    return."""
    sessions, names, panel = random_walk_panel(seed=63, n_names=8,
                                               start="2014-01-01", end="2018-12-31")
    per = Period("t", date(2016, 1, 1), date(2018, 12, 31))
    res = engine.run(base_config, per, panel, flat_index(sessions), cost_model,
                     tax_policy)
    assert "dividends" in res.equity.columns          # recorded per session
    e = artifacts.extras_report(res)["equity_sleeve"]
    assert e["dividends_received"] is not None


def test_most_traded_ranks_by_notional(base_config, cost_model, tax_policy):
    sessions, _, panel = random_walk_panel(seed=64, n_names=10,
                                           start="2014-01-01", end="2017-12-31")
    res = engine.run(base_config, Period("t", date(2016, 1, 1), date(2017, 12, 31)),
                     panel, flat_index(sessions), cost_model, tax_policy)
    top = artifacts.most_traded(res, n=5)
    assert 0 < len(top) <= 5
    assert [x["notional"] for x in top] == sorted(
        [x["notional"] for x in top], reverse=True)
    assert all(x["trades"] >= x["buys"] >= 0 for x in top)


def test_equity_sleeve_survives_going_fully_to_cash():
    """§6 sells everything to cash in a crash, so the sleeve's value hits zero
    -- 100% cash in 2007 and 2009 on E1b's base row. A unitised NAV returns
    NaN from the first such day onward, and annualising what survives measures
    a short prefix and calls it the answer. The time-weighted form must chain
    straight through the gap."""
    import numpy as np
    from pflab.eval import artifacts as A

    idx = pd.date_range("2020-01-01", periods=5, freq="D")

    class R:
        equity = pd.DataFrame({"date": idx,
                               "equity_value": [100.0, 110.0, 0.0, 0.0, 120.0],
                               "cash": [0.0, 0.0, 110.0, 110.0, 0.0],
                               "flow": [0.0] * 5,
                               "dividends": [0.0] * 5,
                               "nav_liq": [100.0, 110.0, 110.0, 110.0, 120.0],
                               "nav_liq_pre": [100.0, 110.0, 110.0, 110.0, 120.0]})
        trades = pd.DataFrame([
            {"date": idx[0], "isin": "X", "side": "BUY", "qty": 1.0,
             "fill_price": 100.0, "costs": 0.0},
            {"date": idx[2], "isin": "X", "side": "SELL_BAND", "qty": 1.0,
             "fill_price": 110.0, "costs": 0.0},
            {"date": idx[4], "isin": "X", "side": "BUY", "qty": 1.0,
             "fill_price": 110.0, "costs": 0.0},
        ])

    e = A.equity_sleeve_return(R())
    assert e["available"] is True
    # +10% then flat then +9.09% = 1.20x, not NaN and not a truncated prefix
    growth = (1 + e["time_weighted_sleeve_cagr"]) ** (4 / 365.25)
    assert growth == pytest.approx(1.20, rel=1e-6)
    # day 0 has no prior close, so no return is defined for it: of the four
    # days that can have one, two had capital at risk
    assert e["share_of_days_invested"] == pytest.approx(0.4, abs=0.01)


# -- 2026-09-19: sweeps persist per-row curves and verify their manifest ----
def test_sweep_persists_per_row_equity_and_trades(tmp_path, base_config,
                                                  cost_model, tax_policy):
    """Every row's curve survives the process.

    The 2026-09-18 session lost three sweeps because an extra thought of
    afterwards needed a curve that only existed in memory. A sweep that keeps
    its curves makes any later §7 extra a file read, not a re-run.
    """
    sessions, _, panel = random_walk_panel(seed=71, n_names=14,
                                           start="2014-01-01", end="2018-12-31")
    per = Period("dev", date(2016, 1, 1), date(2018, 12, 31))
    idx = {"NIFTY50_TRI": _index(sessions, 0.09),
           "NIFTY500_TRI": _index(sessions, 0.08),
           "NIFTY200_MOMENTUM30_TRI": _index(sessions, 0.11)}
    idx["NIFTY50_PRICE"] = _index(sessions, 0.09)
    out = S.run_sweep(base_config, per, panel, idx,
                      lambda m: cost_model.scaled(m), tax_policy,
                      out_dir=tmp_path, rows=["base", "S1"])
    for row in ("base", "S1"):
        eq = pd.read_parquet(tmp_path / "rows" / row / "equity.parquet")
        assert len(eq) and "equity_value" in eq.columns and "cash" in eq.columns
        # the persisted curve is the one the metrics were computed from
        assert list(eq["date"]) == list(out[row]["result"].equity["date"])
        assert (tmp_path / "rows" / row / "trades.parquet").exists()
    # benchmarks are engine runs too and cost as much to recover
    assert (tmp_path / "rows" / "_B2" / "equity.parquet").exists()


def test_sweep_refuses_to_overwrite_a_different_run(tmp_path, base_config,
                                                    cost_model, tax_policy):
    """Principle 5 for sweeps: different inputs must not share a directory.

    `write_run` has always verified-or-refused; `write_summary` overwrote
    unconditionally, and the run id does not carry the dirty flag, so a
    re-run from the same HEAD with edited code silently replaced the sweep.
    """
    sessions, _, panel = random_walk_panel(seed=72, n_names=12,
                                           start="2014-01-01", end="2017-12-31")
    per = Period("dev", date(2016, 1, 1), date(2017, 12, 31))
    idx = {"NIFTY50_PRICE": _index(sessions, 0.09)}
    man = {"config_sha": "aaa", "data_fingerprint": "bbb",
           "code": {"commit": "c0ffee", "dirty": False},
           "period": "dev", "rows": ["base"]}
    S.run_sweep(base_config, per, panel, idx, lambda m: cost_model.scaled(m),
                tax_policy, out_dir=tmp_path, rows=["base"], manifest=man)
    assert json.loads((tmp_path / "manifest.json").read_text(
        encoding="utf-8"))["code"]["commit"] == "c0ffee"

    # same inputs: verifies and proceeds
    S.run_sweep(base_config, per, panel, idx, lambda m: cost_model.scaled(m),
                tax_policy, out_dir=tmp_path, rows=["base"], manifest=man)

    # different code: refuses, and leaves the prior sweep intact
    before = (tmp_path / "summary.md").read_text(encoding="utf-8")
    dirty = {**man, "code": {"commit": "c0ffee", "dirty": True}}
    with pytest.raises(S.SweepConflict) as e:
        S.run_sweep(base_config, per, panel, idx, lambda m: cost_model.scaled(m),
                    tax_policy, out_dir=tmp_path, rows=["base"], manifest=dirty)
    assert "code" in str(e.value)
    assert (tmp_path / "summary.md").read_text(encoding="utf-8") == before


# -- a formatting bug must not destroy a run (2026-09-25) ---------------
def test_summary_sections_cannot_lose_the_run(tmp_path, monkeypatch):
    """E1d's validation sweep died on `100 * None` in one extras column and
    took twelve rows and five benchmarks with it: summary.md was written
    BEFORE criteria.json and rows/, so the directory was left empty and a
    30-minute run had to be recomputed to recover numbers it already held.
    """
    from pflab.eval import sweep as S

    def boom(*a, **k):
        raise TypeError("unsupported operand type(s) for *: 'int' and 'NoneType'")

    monkeypatch.setattr(S, "_extras_section", boom)
    results = {"base": {"metrics": {"paths": {"nav_liq": {"cagr": 0.11,
                                                          "max_drawdown": 0.49}},
                                    "turnover_annual": 1.8,
                                    "trades": {"n": 800}},
                        "extras": {"x": 1}, "adv_skips": {"skips": 0}}}
    out = S.write_summary(results, tmp_path, _P("development"), table={"base": {}})

    # the durable artifacts exist despite the section blowing up
    assert (tmp_path / "criteria.json").exists()
    assert (tmp_path / "extras.json").exists()
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "SECTION FAILED" in text
    assert "11.00%" in text          # the rows still made it into the summary


class _P:
    def __init__(self, name):
        self.name = name
        self.start = date(2007, 1, 1)
        self.end = date(2016, 12, 31)


def test_extras_table_renders_none_as_a_dash(tmp_path):
    """`_ann` returns None when a series compounds to zero or below, which a
    wiped sleeve does. Formatting that None killed E1d's validation sweep."""
    import json
    from pflab.eval import sweep as S

    src = Path("experiments/E1d/sweeps/development-a8d5d7cda901a63f/extras.json")
    if not src.exists():
        pytest.skip("needs a real sweep's extras.json")
    ex = json.loads(src.read_text(encoding="utf-8"))
    base = ex["base"]
    base["equity_sleeve"]["time_weighted_sleeve_cagr"] = None
    lines = S._extras_section({"base": {"extras": base}}, {"base": {}})
    row = [l for l in lines if l.startswith("| base |")][0]
    assert row.rstrip().endswith("— |")          # the None column
    assert "10.90" in row or "11.01" in row           # the equity leg still renders
