"""S80 phase 2: the lab's store, runs, screens, challengers and notes (synthetic panel; the uncontained subprocess stands in for Docker in the suite)."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from pflab.lab import service
from pflab.pm import store
from tests.test_s80_lab import MOMENTUM, make_data

NOW = datetime(2026, 11, 9, 1, 0)


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    monkeypatch.setenv("PFLAB_SANDBOX", "local")
    monkeypatch.setattr("pflab.lab.runner.HISTORY", ("2012-06-01", "2015-12-31"))          # the suite's panel is short
    return store.connect(tmp_path / "l.duckdb")


@pytest.fixture(scope="module")
def data():
    return make_data()


def test_a_variant_is_validated_stored_with_its_lineage_and_never_overwritten(con, tmp_path):
    ok = service.add_variant(con, tmp_path, NOW, "momentum_a", MOMENTUM, "lean toward the strongest 12-1 momentum, sized by risk")
    assert ok["ok"] and ok["combinations"] == 2 and (tmp_path / "policies" / "momentum_a" / "policy.py").exists()
    assert service.add_variant(con, tmp_path, NOW, "momentum_a", MOMENTUM, "the same id again, for a second time")["ok"] is False
    assert service.add_variant(con, tmp_path, NOW, "Bad Id", MOMENTUM, "an id that is not allowed at all here")["ok"] is False
    assert "refused" in service.add_variant(con, tmp_path, NOW, "evil_one", "import os\ndef decide(a, b, c, d, e=None):\n    return {}\n", "tries to import a forbidden module")["problem"]
    assert service.add_variant(con, tmp_path, NOW, "momentum_b", MOMENTUM, "an edit of the first: fewer names please", parent="momentum_a")["ok"]
    assert service.add_variant(con, tmp_path, NOW, "orphan_x", MOMENTUM, "names a parent that does not exist at all", parent="nope")["ok"] is False
    assert service.add_variant(con, tmp_path, NOW, "short_h", MOMENTUM, "too short")["ok"] is False


def test_run_lab_scores_every_combination_counts_trials_and_keeps_a_small_card(con, tmp_path, data):
    service.add_variant(con, tmp_path, NOW, "momentum_a", MOMENTUM, "lean toward the strongest 12-1 momentum, sized by risk")
    res = service.run_lab(con, tmp_path, None, NOW, "momentum_a", n_shuffles=4, data=data)
    assert res["ok"] and res["trials_so_far"] == 2 and len(res["scorecards"]) == 2
    c = res["scorecards"][0]
    assert {"cagr_after_tax_costs", "worst_fall", "deflated_sharpe", "shuffled_beat_it_share", "monte_carlo_1y_p5_p50_p95", "tax_paid"} <= set(c)
    assert "baseline" in res and res["baseline"]["cagr"] is not None
    assert len(json.dumps(res)) < 6000                                                    # a scorecard, never raw output
    first = {r["params"]["n"]: r["deflated_sharpe"] for r in res["scorecards"]}
    service.add_variant(con, tmp_path, NOW, "momentum_c", MOMENTUM, "the same idea again to raise the number of trials")
    service.run_lab(con, tmp_path, None, NOW, "momentum_c", n_shuffles=2, data=data)
    assert service.n_trials(con) == 4
    after = {json.loads(p)["n"]: d for p, d in con.execute("SELECT params_json, dsr FROM lab_runs_s80 WHERE policy_id='momentum_a'").fetchall()}
    assert all(after[n] <= first[n] + 1e-9 or abs(after[n] - first[n]) < 0.5 for n in first)       # more tries never raises the bar's clearance of the same result by itself


def test_a_failing_policy_returns_the_error_and_the_last_lines(con, tmp_path, data):
    service.add_variant(con, tmp_path, NOW, "broken_one", "def decide(state, forecasts, sims, storylines, params=None):\n    return {}['x']\n", "a policy that always fails at its first decision")
    res = service.run_lab(con, tmp_path, None, NOW, "broken_one", n_shuffles=1, data=data)
    assert res["ok"] is False and "KeyError" in res["problem"] and len(res["last_lines"]) <= 30


def test_a_challenger_needs_a_scored_run_and_at_most_five_at_once(con, tmp_path, data):
    service.add_variant(con, tmp_path, NOW, "momentum_a", MOMENTUM, "lean toward the strongest 12-1 momentum, sized by risk")
    assert service.make_challenger(con, NOW, "momentum_a")["ok"] is False                 # no run yet
    service.run_lab(con, tmp_path, None, NOW, "momentum_a", n_shuffles=2, data=data)
    r = service.make_challenger(con, NOW, "momentum_a", {"n": 5}, "the fewer-names arm")
    assert r["ok"] and r["params"] == {"n": 5} and service.get(con, "momentum_a")["status"] == "challenger"
    for i in range(4):
        service.add_variant(con, tmp_path, NOW, f"filler_{i}x", MOMENTUM, "a filler variant to reach the limit of challengers")
        service.run_lab(con, tmp_path, None, NOW, f"filler_{i}x", n_shuffles=1, data=data)
        assert service.make_challenger(con, NOW, f"filler_{i}x", {"n": 5})["ok"]
    service.add_variant(con, tmp_path, NOW, "one_toomany", MOMENTUM, "the sixth challenger must be refused here")
    service.run_lab(con, tmp_path, None, NOW, "one_toomany", n_shuffles=1, data=data)
    assert "5 challengers" in service.make_challenger(con, NOW, "one_toomany", {"n": 5})["problem"]
    assert service.retire(con, NOW, "filler_0x", "weak")["ok"] and service.make_challenger(con, NOW, "one_toomany", {"n": 5})["ok"]


def test_the_screen_names_each_failed_measure():
    base = {"cagr": 0.10, "max_drawdown": -0.20}
    good = {"cagr": 0.13, "dsr": 0.97, "max_drawdown": -0.22}
    assert service.screen(good, {"beats_real_frac": 0.05}, base)["ok"]
    bad = service.screen({"cagr": 0.10, "dsr": 0.6, "max_drawdown": -0.40}, {"beats_real_frac": 0.5}, base)
    assert not bad["ok"] and len(bad["failed"]) == 4
    assert not service.screen(good, {}, base)["ok"]                                       # luck not measured


def test_notes_are_the_next_sessions_memory(con):
    assert service.write_note(con, NOW, 1, "too short")["ok"] is False
    service.write_note(con, NOW, 1, "Tried momentum over 126 days: beat the baseline but 30% of shuffles did as well; next try a volatility filter.")
    assert "volatility filter" in service.notes(con)[0]["text"]
