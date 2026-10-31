"""S68 P3: the three evaluation contracts kept apart. A calculation and a scenario are trusted code, reproducible by the reviewer; a historical strategy
experiment is judged by its own registered contract against its own baseline; a hypothesis no contract fits is recorded as unsupported and never run
through another template. Synthetic data only."""
from __future__ import annotations

import json
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from pflab.hq import cases
from pflab.learner import contracts, experiments as ex
from pflab.learner import templates as tp
from pflab.pm import store
from pflab.quant import ipo_policy, policies, trusted

NOW = datetime(2026, 10, 31, 15, 0)


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


# --- the scenario study -----------------------------------------------------------------------------------------------------------------------

def test_the_study_is_deterministic_and_states_its_assumptions():
    a, b = policies.run(n_noise=40), policies.run(n_noise=40)
    assert a == b
    assert a["assumptions"]["note"].startswith("every one of these is an assumption")
    assert set(a["best_terminal_by_path"]) == set(policies.SHAPES) and len(a["table"]) == len(policies.SHAPES) * len(policies.POLICIES)
    assert all(r["invested_by_end_pct"] <= 100.0 for r in a["table"])


def test_each_policy_does_what_its_rule_says_on_a_stated_path():
    r = {(x["path"], x["policy"]): x for x in policies.run(n_noise=10, sensitivity=False)["table"]}
    # a 20% sharp fall: all-in-now suffers the whole fall; waiting cash is untouched until it triggers
    assert r[("sharp_fall", "lump_now")]["max_drawdown_pct"] == pytest.approx(-20.0, abs=0.2)
    assert r[("sharp_fall", "current_staged")]["max_drawdown_pct"] > r[("sharp_fall", "lump_now")]["max_drawdown_pct"]
    # no crash: the earlier money is in, the more it earns; cash earns less than shares in a rising market
    assert r[("no_crash", "lump_now")]["return_pct"] > r[("no_crash", "current_staged")]["return_pct"] > r[("no_crash", "cash_until_fall")]["return_pct"]
    # a fall that recovers rewards patience; a decline that never recovers punishes being in
    assert r[("fall_and_recovery", "current_staged")]["return_pct"] > r[("fall_and_recovery", "lump_now")]["return_pct"]
    assert r[("prolonged_decline", "cash_until_fall")]["return_pct"] > r[("prolonged_decline", "lump_now")]["return_pct"]


def test_weights_are_labelled_assumptions_and_absent_unless_given():
    assert "weighted" not in policies.run(n_noise=5, sensitivity=False)
    w = policies.run(n_noise=5, sensitivity=False, weights={"sharp_fall": 1, "no_crash": 3})
    assert w["weighted"]["weights_are"].startswith("assumptions")


# --- trusted calculations are reproducible by the reviewer -----------------------------------------------------------------------------------------

def test_a_trusted_calculation_is_kept_with_its_parameters_and_reproduced_from_them(con):
    cid, _ = cases.open_case(con, NOW, "phased or cash?", subject="AAA")
    prm = {"amount": 500000.0, "horizon_months": 18, "n_noise": 20, "sensitivity": False}
    res = trusted.plain(policies.run(**prm))
    kid = trusted.record(con, cid, NOW, "policy_scenarios", "phased or cash across paths", prm, {}, res)
    out = cases.reproduce(con, kid)
    assert out["reproduced"] is True and out["differences"] == [] and out["label"] == "reproduced from the original data"
    con.execute("UPDATE hq_calcs SET result_json=replace(result_json, '\"policy\": \"lump_now\"', '\"policy\": \"lump_nowx\"') WHERE calc_id=?", [kid])
    assert cases.reproduce(con, kid)["reproduced"] is False                                       # a changed kept result is caught, not accepted


def _listings(n_dev=40, n_val=30, n_spent=25, seed=1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for k, (a, n) in enumerate((("2016-02-01", n_dev), ("2020-02-01", n_val), ("2022-03-01", n_spent))):
        for i in range(n):
            gc = rng.normal(0.08, 0.15)
            rows.append({"isin": f"INE{k}{i:07d}", "date": pd.Timestamp(a) + pd.Timedelta(days=int(i * 6)), "gain_open": gc + rng.normal(0, 0.03), "gain_close": gc,
                         "r5": rng.normal(0, 0.05), "r20": rng.normal(0.01, 0.1), "r60": rng.normal(0.02, 0.2)})
    return pd.DataFrame(rows)


def test_the_ipo_study_never_reads_the_spent_period_and_keeps_the_small_numbers_rule():
    t = _listings()
    r = ipo_policy.run(t)
    assert r["periods"]["development"]["listings"] == 40 and r["periods"]["validation"]["listings"] == 30
    all_dates = pd.to_datetime(t["date"])
    assert (all_dates >= "2022-01-01").sum() == 25                       # the spent listings are in the input...
    assert sum(v["listings"] for v in r["periods"].values()) == 70       # ...and not in the study
    few = ipo_policy.run(_listings(n_dev=12, n_val=30))
    assert "too few" in few["periods"]["development"]["policies"]["hold_20"]["note"]
    assert all("too few" in v["reading"] for v in few["verdict"])         # no conclusion from a thin period


def test_the_ipo_study_is_reproducible_through_the_trusted_record(con):
    t = _listings()[["isin", "date", "gain_open", "gain_close", "r5", "r20", "r60"]]
    cid, _ = cases.open_case(con, NOW, "IPO policy?", subject="AAA")
    res = trusted.plain(ipo_policy.run(t, qty=22, issue=1191.0))
    kid = trusted.record(con, cid, NOW, "ipo_policy", "sell or hold", {"qty": 22, "issue": 1191.0}, {"listings": t}, res)
    assert cases.reproduce(con, kid)["reproduced"] is True


# --- the experiment contracts -------------------------------------------------------------------------------------------------------------------------

def test_a_hypothesis_no_contract_fits_is_recorded_as_unsupported_and_never_evaluated(con, tmp_path):
    eid = ex.register(con, tmp_path / "proto", NOW, hypothesis="Selling IPO allotments on listing day beats holding them", why_it_matters="w", disproof="d",
                      source_kind="investor")
    st, why, proto = con.execute("SELECT status, decision_why, protocol_path FROM learn_experiments WHERE exp_id=?", [eid]).fetchone()
    assert st == "unsupported" and "supported contracts" in why and proto == ""
    with pytest.raises(ValueError, match="not run again"):
        ex._verify_protocol(con, eid)
    assert ex.select(con) is None                                         # the loop never picks it up
    with pytest.raises(contracts.Unsupported):
        contracts.resolve("anything", "ipo_policy")                       # a contract that does not exist is refused by name
    bad = ex.register(con, tmp_path / "proto", NOW, hypothesis="x second one", why_it_matters="w", disproof="d", source_kind="investor", contract="china_special")
    assert con.execute("SELECT status FROM learn_experiments WHERE exp_id=?", [bad]).fetchone()[0] == "unsupported"


def test_each_contract_is_registered_with_its_own_comparator_and_assumptions(con, tmp_path):
    a = ex.register(con, tmp_path / "proto", NOW, hypothesis="Put money in after dips", why_it_matters="w", disproof="d", source_kind="investor", contract="deployment")
    b = ex.register(con, tmp_path / "proto", NOW, hypothesis="Momentum timing", why_it_matters="w", disproof="d", source_kind="investor", contract="index_timing")
    pa = json.loads((tmp_path / "proto" / f"experiment_{a}.json").read_text(encoding="utf-8"))
    pb = json.loads((tmp_path / "proto" / f"experiment_{b}.json").read_text(encoding="utf-8"))
    assert pa["contract"] == "deployment" and "lump sum" in pa["comparator"] and pa["assumptions"]["cash_rate_pa"] == contracts.CASH_RATE_PA
    assert pb["contract"] == "index_timing" and pb["comparator"] == "always invested"
    assert ex.contract_of(con, a) == "deployment" and ex.contract_of(con, b) == "index_timing"


def _prices(drift: float, n_years=14, seed=5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2009-01-01", "2021-12-31")
    r = rng.normal(drift, 0.008, len(days))
    return pd.DataFrame({"date": [d.date() for d in days], "close": 100 * np.cumprod(1 + r)})


def _signals(df, f):
    return {d.isoformat(): f for d in ex.walk_dates(df)}


def test_the_deployment_baseline_is_the_lump_sum_and_a_slow_rule_loses_in_a_rising_market():
    up = _prices(0.0008)
    base = contracts.score_deployment(up, _signals(up, 1.0), tp.DEV, ex.month_ends)
    assert base["mean_excess"] == pytest.approx(0.0, abs=1e-12)                      # all in at once IS the baseline
    slow = contracts.score_deployment(up, _signals(up, 0.1), tp.DEV, ex.month_ends)
    assert slow["mean_excess"] < 0 and slow["t"] < -2                                 # waiting costs in a rising market: it fails its baseline
    down = _prices(-0.0006)
    s2 = contracts.score_deployment(down, _signals(down, 0.1), tp.DEV, ex.month_ends)
    assert s2["mean_excess"] > 0
    assert s2["cand_worst_fall_mean"] > s2["base_worst_fall_mean"]                    # in a falling market it also fell less: the risk is reported beside the return


def test_overlapping_windows_do_not_inflate_the_t_statistic():
    up = _prices(0.0008)
    r = contracts.score_deployment(up, _signals(up, 0.1), tp.DEV, ex.month_ends)
    assert r["effective_windows"] == pytest.approx(r["n_months"] / contracts.HORIZON, abs=0.1)


def test_a_missing_signal_is_an_error_not_a_zero():
    up = _prices(0.0008)
    sig = _signals(up, 0.5)
    sig.pop(sorted(sig)[10])
    with pytest.raises(ValueError, match="no signal"):
        contracts.score_deployment(up, sig, tp.DEV, ex.month_ends)


def test_the_candidate_sees_no_row_after_a_decision_date(monkeypatch):
    """The walk is cut by the runner (as for index timing); the deployment trades the NEXT session's close, so a decision never uses its own day's price."""
    up = _prices(0.0008)
    dates = ex.month_ends(up, *tp.DEV)
    days = sorted(up["date"])
    ex_px = contracts._exec_prices(up, dates, days)
    px = dict(zip(up["date"], up["close"]))
    d = dates[10]
    assert ex_px[d] != px[d] and ex.next_day(days, d) is not None and ex_px[d] == px[ex.next_day(days, d)]


def test_the_evaluator_hash_covers_the_contracts(tmp_path):
    h1 = ex.evaluator_sha()
    assert isinstance(h1, str) and len(h1) == 64


def test_exposure_shock_is_arithmetic_the_reviewer_can_rerun(con):
    """Found live: a quant asked the code writers for pure arithmetic of a fall 17 times and every try failed."""
    res = policies.exposure_shock([{"symbol": "AAA", "value": 600000.0}, {"symbol": "BBB", "value": 400000.0}], 1000000.0, [10, 20], betas={"AAA": 1.2}, default_beta=1.0)
    t = {r["index_fall_pct"]: r for r in res["table"]}
    assert t[10.0]["loss_rupees"] == pytest.approx(-(600000 * 0.1 * 1.2 + 400000 * 0.1))                 # cash does not fall
    assert t[20.0]["loss_pct_of_total"] == pytest.approx(-(600000 * 0.2 * 1.2 + 400000 * 0.2) / 2000000 * 100)
    pos = pd.DataFrame({"symbol": ["AAA", "BBB"], "value": [600000.0, 400000.0]})
    cid, _ = cases.open_case(con, NOW, "loss in a fall?", subject="AAA")
    prm = {"cash": 1000000.0, "falls_pct": [10, 20], "betas": {"AAA": 1.2}, "default_beta": 1.0, "label": "t"}
    kid = trusted.record(con, cid, NOW, "exposure_shock", "loss in a fall", prm, {"positions": pos}, trusted.plain(trusted.TRUSTED["exposure_shock"]({"positions": pos}, prm)))
    assert cases.reproduce(con, kid)["reproduced"] is True


def test_two_calculations_that_did_not_run_stop_the_third(con):
    from types import SimpleNamespace
    from pflab.hq import tools as tl
    ctx = SimpleNamespace(task_id=7, con=con)
    for k in range(2):
        con.execute("INSERT INTO hq_artifacts VALUES (?, 1, 7, 'calc', ?, 'failed', ?)", [k + 1, str(k), NOW])
    msg = tl.task_cap_reached(ctx, "case_calculate")
    assert msg and "did not run" in msg and "exposure_shock" in msg
    assert tl.task_cap_reached(SimpleNamespace(task_id=8, con=con), "case_calculate") is None             # another task is not affected
