"""S64 Phase 1: the learner's test counter (protocol amendment 4): the Bonferroni bar, the deflated Sharpe ratio, the seed,
the claims wiring, re-registering stale claims and re-deciding old passes. Synthetic data only."""
from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pytest

from pflab.learner import claims, counter, live, run, templates as tp
from pflab.pm import store

from test_s62_learner import CLAIM, NOW, TEXT, _source  # noqa: F401


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "c.duckdb")


def test_the_bar_rises_with_the_count_and_never_falls_under_two():
    assert counter.t_needed(1) == 2.0 and counter.t_needed(2) == 2.0
    assert counter.t_needed(5) == pytest.approx(2.33, abs=0.01)
    assert counter.t_needed(20) == pytest.approx(2.81, abs=0.01)
    assert counter.t_needed(100) == pytest.approx(3.29, abs=0.01)
    assert counter.t_needed(0) == 2.0                                      # a count under one is read as one


def test_pure_noise_passes_at_most_once_in_200_trials_but_a_strong_drift_passes():
    rng = np.random.default_rng(64)
    lucky = 0
    for k in range(1, 201):                                                # the k-th test of the family
        x = rng.normal(0.0, 0.04, 96)                                      # 96 months of nothing
        _, t, _ = tp.nw_t(x, 0)
        lucky += int(t >= counter.t_needed(k))
    assert lucky <= 1
    drift = rng.normal(0.02, 0.04, 96)                                     # a real edge, N = 200 trials in
    _, t, _ = tp.nw_t(drift, 0)
    assert t >= counter.t_needed(200)


def test_decide_uses_the_raised_development_bar_and_keeps_validation_at_1_65():
    dev, val = {"mean": 0.01, "t": 2.5, "n": 60}, {"mean": 0.008, "t": 1.7, "n": 48}
    assert tp.decide(dev, val, 1, 36, 0.0, "months")[0] == "pass"            # the old default bar of 2.0
    d, why = tp.decide(dev, val, 1, 36, 0.0, "months", threshold_dev=counter.t_needed(100))
    assert d == "fail" and "development: t +2.50, under 3.2" in why
    assert tp.decide(dev, {"mean": 0.008, "t": 1.6, "n": 48}, 1, 36, 0.0, "months")[0] == "fail"


def test_deflated_sharpe_is_high_for_a_real_edge_and_low_for_noise_among_many_trials():
    rng = np.random.default_rng(1)
    trials = list(rng.normal(0.0, 0.1, 100))                               # 100 tried strategies' Sharpe ratios
    edge = rng.normal(0.05, 0.04, 96)
    noise = rng.normal(0.0, 0.04, 96)
    assert counter.deflated_sharpe(edge, trials) > 0.95
    assert counter.deflated_sharpe(noise, trials) < 0.5
    assert np.isnan(counter.deflated_sharpe([0.1, 0.2], trials))


def test_seed_is_idempotent_and_includes_decided_claims(con, tmp_path):
    sid = _source(con, tmp_path)
    [cid] = claims.read(con, [("local", lambda s, p, sc: {"claims": [CLAIM]})], sid, TEXT, NOW)
    claims.register(con, cid, tmp_path / "proto", NOW)
    claims.test(con, cid, tmp_path, NOW, run=lambda *a: {"decision": "pass", "why": "ok",
                                                         "development": {"t": 2.2, "n": 60, "mean": 0.01}, "validation": {}})
    n_learner = counter.n_tests(con)
    assert n_learner == 1                                                  # the learner's own run is counted
    added = counter.seed(con, NOW)
    assert added == len(counter.SEED) + len(counter.CARRIED) + 1           # the studies, the carried tests, plus the claim as a seed row
    assert counter.seed(con, NOW) == 0                                     # run again: nothing new
    assert counter.n_tests(con) == n_learner + added


def test_a_fresh_install_starts_with_the_same_count_and_bar_as_the_system_that_ran_the_tests(con):
    assert counter.seed(con, NOW) == len(counter.SEED) + len(counter.CARRIED) == 33
    assert counter.n_tests(con) == 33 and round(counter.t_needed(34), 2) == 2.97          # the next development bar the old system had
    assert sum(1 for *_, passed, _w in counter.CARRIED if passed) == 1                    # the one rule that passed (below the 200-day average)


def test_a_test_already_in_the_store_is_not_counted_twice(con):
    for k in ("claim:16", "ranges_ewma_vs_plain", "claim:21"):
        counter.record(con, NOW, "learner" if k.startswith("claim") else "study", "x", note=k)
    counter.seed(con, NOW)
    assert counter.n_tests(con) == 3 + len(counter.SEED) + len(counter.CARRIED) - 3       # those three are already there under another key


def test_test_records_its_n_and_bar_and_the_bar_rises(con, tmp_path):
    counter.seed(con, NOW)
    n0 = counter.n_tests(con)
    sid = _source(con, tmp_path)
    [cid] = claims.read(con, [("local", lambda s, p, sc: {"claims": [CLAIM]})], sid, TEXT, NOW)
    claims.register(con, cid, tmp_path / "proto", NOW)
    proto = json.loads((tmp_path / "proto" / f"claim_{cid}.json").read_text(encoding="utf-8"))
    assert proto["tests_run_at_registration"] == n0 and "amendment 4" in proto["rule"]
    seen = {}

    def fake(root, t, prm):
        return {"decision": "fail", "why": "x", "development": {"t": 1.0, "n": 60, "mean": 0.0, "_returns": [0.01, -0.02] * 30},
                "validation": {"t": 0.5, "n": 40}}
    claims.test(con, cid, tmp_path, NOW, run=fake)
    row = con.execute("SELECT origin, threshold_dev, passed, n_dev FROM learn_tests WHERE claim_id=? AND origin='learner'",
                      [cid]).fetchone()
    assert row[0] == "learner" and row[1] == pytest.approx(counter.t_needed(n0 + 1)) and row[2] is False and row[3] == 60
    stored = json.loads(con.execute("SELECT result_json FROM learn_claims WHERE claim_id=?", [cid]).fetchone()[0])
    assert "_returns" not in stored["development"] and stored["tests_in_family"] == n0 + 1
    assert counter.n_tests(con) == n0 + 1
    assert f"Tests run {n0 + 1}" in run.status(con)


def test_reregister_stale_leaves_tested_claims_alone(con, tmp_path):
    sid = _source(con, tmp_path)
    [a] = claims.read(con, [("local", lambda s, p, sc: {"claims": [CLAIM]})], sid, TEXT, NOW)
    other = dict(CLAIM, claim="Past 6-month winners outperform.", signal="momentum_6_1")
    [b] = claims.read(con, [("local", lambda s, p, sc: {"claims": [other]})], sid, TEXT, NOW)
    for c in (a, b):
        claims.register(con, c, tmp_path / "proto", NOW)
    claims.test(con, a, tmp_path, NOW, run=lambda *x: {"decision": "fail", "why": "no"})
    con.execute("UPDATE learn_claims SET code_sha='old' WHERE claim_id IN (?, ?)", [a, b])      # templates.py "changed"
    assert claims.reregister_stale(con, tmp_path / "proto", NOW) == 1                           # only b was untested
    st = dict(con.execute("SELECT claim_id, status FROM learn_claims").fetchall())
    assert st[a] == "failed" and st[b] == "registered"
    assert con.execute("SELECT code_sha FROM learn_claims WHERE claim_id=?", [b]).fetchone()[0] == claims.code_sha()
    assert con.execute("SELECT code_sha FROM learn_claims WHERE claim_id=?", [a]).fetchone()[0] == "old"


def test_an_old_pass_below_the_new_bar_is_failed_and_its_finding_ends(con, tmp_path):
    sid = _source(con, tmp_path)
    [cid] = claims.read(con, [("local", lambda s, p, sc: {"claims": [CLAIM]})], sid, TEXT, NOW)
    claims.register(con, cid, tmp_path / "proto", NOW)
    claims.test(con, cid, tmp_path, NOW, run=lambda *x: {"decision": "pass", "why": "ok",
                                                         "development": {"t": 2.3, "n": 60, "mean": 0.01},
                                                         "validation": {"t": 1.8, "n": 48, "mean": 0.01}})
    assert live.current(con, ("finding",))
    assert claims.redecide_passed(con, NOW) == []                          # N is 1: the bar is still 2.0, t 2.3 holds
    counter.seed(con, NOW)                                                 # now N is about 22: the bar is about 2.8
    [ch] = claims.redecide_passed(con, NOW)
    assert ch["claim_id"] == cid and ch["bar"] > 2.7
    assert live.current(con, ("finding",)) == []
    assert con.execute("SELECT status, decision FROM learn_claims WHERE claim_id=?", [cid]).fetchone() == ("failed", "fail")
