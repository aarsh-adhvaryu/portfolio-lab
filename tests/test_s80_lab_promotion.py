"""S80 phase 2: challengers in shadow, the promotion rule and the rollback (synthetic data)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from pflab.lab import promotion, service, shadow
from pflab.pm import store
from tests.test_s80_lab import MOMENTUM, make_data

NOW = datetime(2026, 11, 9, 1, 0)
GOOD = {"cagr": 0.16, "bench_cagr": 0.12, "excess_cagr": 0.04, "max_drawdown": -0.22, "recovery_days": 300.0, "turnover_per_year": 2.0, "tax_paid": 1000.0, "charges": 500.0, "sharpe": 0.8,
        "sharpe_daily": 0.05, "n_obs": 3000.0, "skew": 0.0, "kurt": 3.0, "dsr": 0.97}
BASE = {**GOOD, "cagr": 0.11, "max_drawdown": -0.20, "dsr": 0.5}


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    monkeypatch.setenv("PFLAB_SANDBOX", "local")
    c = store.connect(tmp_path / "l.duckdb")
    c.execute("INSERT INTO core_policies_s80 (policy_id, status, code_hash, created_at, promoted_at) VALUES ('baseline_v1', 'champion', 'x', ?, ?)", [NOW, NOW])
    service.ensure_baseline(c, NOW)
    return c


@pytest.fixture(scope="module")
def data():
    return make_data()


def _run(con, pid, win, score, shuffled=None, params=None, mc=None):
    from pflab.pm.store import next_id
    con.execute("INSERT INTO lab_runs_s80 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [next_id(con, "lab_runs_s80", "run_id"), pid, win, json.dumps(params or {}, sort_keys=True), NOW, None, json.dumps(score),
                json.dumps(shuffled if shuffled is not None else {"beats_real_frac": 0.03, "cagr_mean": 0.05, "n": 10.0}), json.dumps(mc or {"mc_worst_fall_p5": -0.30}), score.get("dsr"),
                score["sharpe_daily"], 5, 1.0, False])


def _challenger(con, tmp_path, pid="momentum_a", params=None):
    service.add_variant(con, tmp_path, NOW, pid, MOMENTUM, "lean toward the strongest 12-1 momentum, sized by risk")
    _run(con, pid, "history", GOOD, params={"n": 5} if params is None else params)
    assert service.make_challenger(con, NOW, pid, {"n": 5} if params is None else params)["ok"]


def _shadow_days(con, pid, n, ret_c=0.001, ret_s=0.0005):
    base = date(2026, 9, 1)
    for i in range(n):
        for p, r in ((pid, ret_c), (shadow.standin(con), ret_s)):
            con.execute("INSERT OR REPLACE INTO core_shadow_s80 VALUES (?,?,?,?,?)", [base + timedelta(days=i), p, "{}", r, NOW])


def test_the_sandbox_decides_for_every_member_and_the_next_close_scores_the_day(con, tmp_path, data):
    _challenger(con, tmp_path)
    px = data["px"]
    d0, d1 = px.index[1200].date(), px.index[1201].date()
    cut = lambda d: {**data, "px": px.loc[:str(d)], "turnover": data["turnover"].loc[:str(d)]}
    a = shadow.run_shadow(con, tmp_path, None, NOW, d0, data=cut(d0))
    assert a["decided"] == 2 and not a["errors"] and set(a["members"]) == {"momentum_a", "baseline_lab"}
    w = json.loads(con.execute("SELECT weights_json FROM core_shadow_s80 WHERE day=? AND policy_id='momentum_a'", [d0]).fetchone()[0])
    assert w and all(k in px.columns for k in w) and sum(w.values()) <= 1.0 + 1e-9
    b = shadow.run_shadow(con, tmp_path, None, NOW, d1, data=cut(d1))
    assert b["scored"] == 2
    r = con.execute("SELECT ret FROM core_shadow_s80 WHERE day=? AND policy_id='momentum_a'", [d0]).fetchone()[0]
    assert r is not None and -0.2 < r < 0.2
    assert shadow.record(con, "momentum_a")["sessions"] == 1
    again = shadow.run_shadow(con, tmp_path, None, NOW, d1, data=cut(d1))
    assert again["decided"] == 0                                              # a day already stored is not decided twice


def test_the_shadow_record_compares_with_the_champions_standin_on_common_sessions(con, tmp_path):
    _challenger(con, tmp_path)
    _shadow_days(con, "momentum_a", 25)
    rec = shadow.record(con, "momentum_a")
    assert rec["sessions"] == 25 and rec["excess"] > 0 and rec["against"] == "baseline_lab"


def test_promotion_needs_history_shadow_and_the_final_check_all_three(con, tmp_path, monkeypatch):
    _challenger(con, tmp_path)
    _run(con, "baseline_lab", "history", BASE)
    monkeypatch.setattr(promotion, "final_run", lambda *a, **k: {"score": {"cagr": 0.14, "max_drawdown": -0.20}, "baseline": {"cagr": 0.12, "worst_fall": -0.19}})
    v = promotion.check(con, tmp_path, None, NOW, "momentum_a", data={})
    assert not v["ready"] and any("shadow sessions" in r for r in v["reasons"])                 # history is fine, no live record yet
    _shadow_days(con, "momentum_a", 25)
    v = promotion.check(con, tmp_path, None, NOW, "momentum_a", data={})
    assert v["ready"], v["reasons"]
    monkeypatch.setattr(promotion, "final_run", lambda *a, **k: {"score": {"cagr": 0.05, "max_drawdown": -0.20}, "baseline": {"cagr": 0.12, "worst_fall": -0.19}})
    assert "final check" in " ".join(promotion.check(con, tmp_path, None, NOW, "momentum_a", data={})["reasons"])
    _shadow_days(con, "momentum_a", 25, ret_c=0.0, ret_s=0.001)                                # worse than the champion in shadow
    assert any("did worse" in r for r in promotion.check(con, tmp_path, None, NOW, "momentum_a", data={})["reasons"])


def test_a_variant_that_fails_the_history_screen_is_never_promoted(con, tmp_path):
    service.add_variant(con, tmp_path, NOW, "weak_one", MOMENTUM, "lean toward the strongest 12-1 momentum, sized by risk")
    _run(con, "weak_one", "history", {**GOOD, "dsr": 0.4, "cagr": 0.105}, params={"n": 5})
    _run(con, "baseline_lab", "history", BASE)
    service.make_challenger(con, NOW, "weak_one", {"n": 5})
    _shadow_days(con, "weak_one", 30)
    v = promotion.check(con, tmp_path, None, NOW, "weak_one", data={})
    assert not v["ready"] and len([r for r in v["reasons"] if "deflated" in r or "does not beat" in r]) == 2
    assert promotion.promote(con, tmp_path, NOW, "weak_one", v)["ok"] is False


def test_promotion_logs_the_diff_and_keeps_the_old_champion_for_rollback(con, tmp_path, monkeypatch):
    _challenger(con, tmp_path)
    _run(con, "baseline_lab", "history", BASE)
    _shadow_days(con, "momentum_a", 25)
    monkeypatch.setattr(promotion, "final_run", lambda *a, **k: {"score": {"cagr": 0.14, "max_drawdown": -0.20}, "baseline": {"cagr": 0.12, "worst_fall": -0.19}})
    out = promotion.promote_ready(con, tmp_path, None, NOW, data={})
    assert out[0]["ready"] and out[0]["promoted"]["champion"] == "momentum_a"
    assert shadow.champion_row(con)["policy_id"] == "momentum_a"
    assert con.execute("SELECT status FROM core_policies_s80 WHERE policy_id='baseline_v1'").fetchone()[0] == "previous"
    kind, frm, to, diff = con.execute("SELECT kind, from_policy, to_policy, diff FROM core_promotions_s80").fetchone()
    assert (kind, frm, to) == ("promote", "baseline_v1", "momentum_a") and "momentum" in diff


def test_a_champion_below_its_own_history_range_is_rolled_back_automatically(con, tmp_path):
    _challenger(con, tmp_path)
    con.execute("UPDATE core_policies_s80 SET status='champion', promoted_at=? WHERE policy_id='momentum_a'", [datetime(2026, 11, 1)])
    con.execute("UPDATE core_policies_s80 SET status='previous' WHERE policy_id='baseline_v1'")
    con.execute("INSERT INTO core_promotions_s80 VALUES (1, ?, 'promote', 'baseline_v1', 'momentum_a', '', '{}', 'x')", [datetime(2026, 11, 1)])
    d0 = date(2026, 11, 1)
    for i in range(15):                                                       # the account keeps falling: 7% a day, far past the -30% floor
        v = 1_000_000 * (0.93 ** i)
        con.execute("INSERT INTO paper_days VALUES (?,?,?,?,?,?)", [d0 + timedelta(days=i), v, 0.0, v, 0.0, "{}"])
    r = promotion.rollback_check(con, NOW)
    assert r == {"rolled_back": "momentum_a", "to": "baseline_v1"}
    assert shadow.champion_row(con)["policy_id"] == "baseline_v1"
    assert promotion.rollback_check(con, NOW) is None                         # nothing to roll back a second time


def test_a_healthy_champion_is_not_rolled_back(con, tmp_path):
    _challenger(con, tmp_path)
    con.execute("UPDATE core_policies_s80 SET status='champion', promoted_at=? WHERE policy_id='momentum_a'", [datetime(2026, 11, 1)])
    for i in range(15):
        v = 1_000_000 * (1.002 ** i)
        con.execute("INSERT INTO paper_days VALUES (?,?,?,?,?,?)", [date(2026, 11, 1) + timedelta(days=i), v, 0.0, v, 0.0, "{}"])
    assert promotion.rollback_check(con, NOW) is None


def test_a_variant_that_trails_the_index_by_more_than_the_limit_is_held_back_by_that_alone(con, tmp_path):
    """His rule (2026-11-09): promotion also needs the history to trail the Nifty 500 by no more than 2 points a year. The progress measure (the screen against the plain baseline) is untouched."""
    service.add_variant(con, tmp_path, NOW, "lags_index", MOMENTUM, "beats the plain baseline but trails the Nifty 500 in the history")
    laggard = {**GOOD, "cagr": 0.13, "bench_cagr": 0.16, "excess_cagr": -0.03}                  # beats the baseline's 11%, trails the index by 3 points
    _run(con, "lags_index", "history", laggard, params={"n": 5})
    _run(con, "baseline_lab", "history", BASE)
    service.make_challenger(con, NOW, "lags_index", {"n": 5})
    _shadow_days(con, "lags_index", 30)
    assert service.screen(laggard, {"beats_real_frac": 0.05}, BASE)["ok"]                          # it still counts as beating the baseline (the strategist's progress measure)
    v = promotion.check(con, tmp_path, None, NOW, "lags_index", data={})
    assert not v["ready"] and v["held_back_only_by_index"] is True
    assert any("trails the Nifty 500 by 3.0%" in r and "limit is 2%" in r for r in v["reasons"])
    ok = {**laggard, "cagr": 0.14, "excess_cagr": -0.015}                                          # inside the limit: no reason from it
    assert service.index_clause(ok)["ok"] and not service.index_clause({"cagr": 0.1})["ok"]       # (a run with no index comparison cannot pass)
