"""S79b items 15, 15b, 7b: the pre-registered event-study machinery. Synthetic data only: a series with a planted effect (power), none planted (false positives under 10%),
the non-overlap rule, the halves rule, the 2022-2025 refusal, the gate arithmetic, recording once, and the two rate studies."""
from datetime import date, datetime
from types import SimpleNamespace

import duckdb
import numpy as np
import pandas as pd
import pytest

from pflab.learner import counter
from pflab.pm import store
from pflab.quant import index_event_study as S

NOW = datetime(2026, 11, 8, 4, 0)
DAYS = [d.date() for d in pd.bdate_range("2004-01-01", "2021-12-31")]


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    store.migrate(c)
    return c


def make_series(seed=1, vol=0.01, plant=None, h=5, events=(), first_half_only=False):
    """Daily closes. `plant` adds a total of plant over the h sessions that start at the NEXT session's close after each event (so F_h rises by about plant)."""
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0003, vol, len(DAYS))
    if plant:
        for i in events:
            if first_half_only and i > len(DAYS) // 2:
                continue
            r[i + 2: i + 2 + h] += plant / h
    return np.cumprod(1 + r) * 1000.0


def spaced_events(rng, n, h, lo=300, hi=None):
    hi = hi or len(DAYS) - 60
    pos = sorted(rng.choice(np.arange(lo, hi, h + 3), size=n, replace=False))
    return [int(p) for p in pos]


def study(close, ev_idx, h, t_needed=2.5, draws=1500, seed=S.SEED):
    ev = [(DAYS[i], "x") for i in ev_idx]
    return S.index_event_study(f"t_{h}", "IN", h, DAYS, close, ev, t_needed, 50, draws, seed, family="x")


# --- forward return and the rules ---------------------------------------------------------------------------------------------------------

def test_forward_return_starts_at_next_sessions_close():
    c = np.array([100.0, 110.0, 121.0, 133.1, 146.41])
    f = S.forward_returns(c, 2)
    assert f[0] == pytest.approx(133.1 / 110.0 - 1)                 # close[3] / close[1]
    assert f[1] == pytest.approx(146.41 / 121.0 - 1)
    assert np.isnan(f[2]) and np.isnan(f[4])


def test_non_overlap_drops_events_within_h_sessions():
    rows = [(i, DAYS[i], "a") for i in (10, 12, 15, 16, 21, 22, 40)]
    kept = S.non_overlapping(rows, 5)
    assert [r[0] for r in kept] == [10, 16, 22, 40]                 # 12, 15 within 5 of 10; 21 within 5 of 16
    assert all(b[0] - a[0] > 5 for a, b in zip(kept, kept[1:]))


def test_baseline_excludes_the_windows_of_all_raw_events():
    h = 5
    fwd = np.arange(100, dtype=float)
    raw = [(30, DAYS[30], "a"), (33, DAYS[33], "a")]
    m = S.baseline_mask(100, raw, fwd, h)
    assert not m[30: 33 + h + 2].any() and m[29] and m[40]


def test_period_is_enforced():
    with pytest.raises(S.PeriodRefused):
        S.check_period(None, date(2022, 1, 3))
    with pytest.raises(S.PeriodRefused):
        S.check_period(date(2003, 12, 1), None)
    assert S.check_period(None, None) == (S.PERIOD_START, S.PERIOD_END)
    longer = [d.date() for d in pd.bdate_range("2004-01-01", "2022-03-31")]
    with pytest.raises(S.PeriodRefused):                            # a series reaching 2022 is refused outright
        S.index_event_study("x", "IN", 5, longer, np.ones(len(longer)), [(date(2010, 1, 5), "x")], 2.5, 50, 100)


def test_events_after_2021_and_windows_ending_after_2021_are_cut():
    rng = np.random.default_rng(3)
    c = make_series(3)
    idx = spaced_events(rng, 30, 5)
    ev = [(DAYS[i], "x") for i in idx] + [(date(2022, 6, 1), "x"), (date(2023, 1, 2), "x"), (DAYS[-2], "x")]     # the last two sessions have no complete 5-session window
    r = S.index_event_study("t", "IN", 5, DAYS, c, ev, 2.5, 50, 500)
    assert r["n_cut_period"] == 2 and r["n_cut_window"] >= 1 and r["n_events"] == 30


def test_n_too_small_is_not_a_verdict():
    c = make_series(5)
    r = study(c, [400, 800, 1200, 1600, 2000, 2400, 2800, 3200, 3600, 4000], 5)
    assert r["status"] == "n_too_small" and r["verdict"].startswith("n too small, no conclusion") and r["passed"] is False and r["effect"] is None


# --- power and false positives -----------------------------------------------------------------------------------------------------------

def test_planted_effect_is_found_and_passes_the_gate():
    h = 5
    rng = np.random.default_rng(11)
    idx = spaced_events(rng, 60, h)
    c = make_series(11, plant=0.02, h=h, events=idx)
    r = study(c, idx, h, t_needed=2.5, draws=2000)
    assert r["status"] == "ok" and r["n_events"] == 60
    assert 0.012 < r["effect"] < 0.028 and r["ci_low"] > 0 and r["same_sign"] is True
    assert r["p"] < S.p_cut(2.5) and r["gate"]["passed"] and r["verdict"].startswith("followed through: 60 events, effect +")
    assert r["direction"] == "up"


def test_planted_negative_effect_is_found_in_its_own_direction():
    h = 5
    rng = np.random.default_rng(12)
    idx = spaced_events(rng, 60, h)
    c = make_series(12, plant=-0.02, h=h, events=idx)
    r = study(c, idx, h, draws=2000)
    assert r["effect"] < -0.012 and r["direction"] == "down" and r["gate"]["passed"]


def test_no_planted_effect_false_positive_rate_under_10_percent():
    h = 5
    hits = 0
    runs = 40
    for s in range(runs):
        rng = np.random.default_rng(100 + s)
        idx = spaced_events(rng, 40, h)
        c = make_series(100 + s)
        r = study(c, idx, h, draws=600)
        if r["p"] is not None and r["p"] <= S.p_cut(2.0):         # the lowest bar the counter can ever set: t = 2.0
            hits += 1
    assert hits / runs < 0.10


def test_small_planted_effect_fails_the_size_condition():
    h = 5
    rng = np.random.default_rng(13)
    idx = spaced_events(rng, 150, h)
    c = make_series(13, plant=0.005, h=h, events=idx, vol=0.004)       # real but 0.5% gross: under 0.5% after the 0.2% cost
    r = study(c, idx, h, draws=1500)
    assert r["p"] < S.p_cut(2.5) and r["gate"]["effect_ok"] is False and r["passed"] is False and r["verdict"] == "no reliable follow-through"


def test_halves_rule_effect_in_one_half_only_fails():
    h = 5
    rng = np.random.default_rng(14)
    idx = spaced_events(rng, 80, h)
    c = make_series(14, plant=0.03, h=h, events=idx, first_half_only=True)
    r = study(c, idx, h, draws=1500)
    assert r["effect"] > 0 and r["halves"]["first"]["effect"] > 0.02 and abs(r["halves"]["second"]["effect"]) < 0.015
    # an effect in the first half only may or may not flip the second half's sign; force the check on the sign logic itself:
    r2 = dict(r, same_sign=False)
    assert S.gate(r2, 2.5)["passed"] is False


def test_seed_is_fixed_and_the_result_repeats():
    h = 5
    rng = np.random.default_rng(15)
    idx = spaced_events(rng, 40, h)
    c = make_series(15)
    a, b = study(c, idx, h, draws=500), study(c, idx, h, draws=500)
    assert a["p"] == b["p"] and a["ci_low"] == b["ci_low"] and S.SEED == 20261108 and S.DRAWS == 10_000


# --- gate arithmetic ----------------------------------------------------------------------------------------------------------------------

def test_gate_arithmetic():
    base = {"n_events": 25, "p": 0.01, "same_sign": True, "effect_gate_applies": True, "effect_gate_value": 0.008}
    assert S.gate(base, 2.0)["passed"] is True                              # p cut at t=2 is 0.0228, |0.8%| - 0.2% = 0.6% >= 0.5%
    assert S.gate({**base, "effect_gate_value": 0.007}, 2.0)["passed"] is True      # 0.7% - 0.2% = 0.5% exactly
    assert S.gate({**base, "effect_gate_value": 0.0069}, 2.0)["effect_ok"] is False
    assert S.gate({**base, "effect_gate_value": -0.009}, 2.0)["passed"] is True      # the size is of |effect|
    assert S.gate({**base, "n_events": 19}, 2.0)["n_ok"] is False
    assert S.gate({**base, "p": 0.03}, 2.0)["p_ok"] is False and S.gate({**base, "p": 0.03}, 1.8)["p_ok"] is True
    assert S.gate({**base, "same_sign": False}, 2.0)["passed"] is False
    assert S.gate({**base, "effect_gate_applies": False}, 2.0)["effect_ok"] is None and S.gate({**base, "effect_gate_applies": False}, 2.0)["passed"] is True
    assert S.p_cut(counter.t_needed(100)) == pytest.approx(0.0005, rel=0.05)
    assert S.p_cut(counter.t_needed(1)) == pytest.approx(0.0228, rel=0.01)            # the floor t = 2.0 (N = 1 or 2)
    assert S.p_cut(counter.t_needed(10)) == pytest.approx(0.005, rel=0.01)


def test_bar_is_read_from_the_counter_at_run_time(con):
    t0, n0 = S.bar_now(con)
    for i in range(60):
        counter.record(con, NOW, "study", "x", {}, note=f"filler:{i}")
    t1, n1 = S.bar_now(con)
    assert n1 == n0 + 60 and t1 > t0 and t1 == counter.t_needed(n1)


# --- recording ---------------------------------------------------------------------------------------------------------------------------

def test_record_fills_the_registration_row_once_and_never_adds_to_the_counter(con):
    from pflab.learner import s79
    s79.register_all(con, NOW)
    n_before = counter.n_tests(con)
    assert n_before >= 11
    h = 5
    rng = np.random.default_rng(21)
    idx = spaced_events(rng, 40, h)
    c = make_series(21)
    t_need, n = S.bar_now(con)
    r = S.index_event_study("wave_5", "IN", h, DAYS, c, [(DAYS[i], "x") for i in idx], t_need, n, 500, family="wave")
    row = S.record(con, r, "p" * 64, NOW)
    assert row["learn_tests_filled"] == 1 and counter.n_tests(con) == n_before
    pas, t_dev, n_dev, thr = con.execute("SELECT passed, t_dev, n_dev, threshold_dev FROM learn_tests WHERE note='s79:wave_sentiment:wave_5'").fetchone()
    assert pas is not None and n_dev == r["n_events"] and thr == pytest.approx(t_need)
    with pytest.raises(RuntimeError):                                  # run once
        S.record(con, r, "p" * 64, NOW)
    got = S.results(con)
    assert len(got) == 1 and got[0]["test"] == "wave_5" and got[0]["details"]["n_events_raw"] == 40 and got[0]["protocol_sha"] == "p" * 64
    assert S.already_recorded(con, "wave_5", "IN") and not S.already_recorded(con, "wave_20", "IN")


def test_protocol_refused_when_not_the_committed_file(tmp_path):
    with pytest.raises(S.ProtocolMismatch):
        S.protocol_sha(tmp_path, "docs/protocols/none.md")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "p.md").write_text("x", encoding="utf-8")
    with pytest.raises(S.ProtocolMismatch):                             # not a git repository / not committed
        S.protocol_sha(tmp_path, "docs/p.md")
    assert len(S.protocol_sha(tmp_path, "docs/p.md", require_committed=False)) == 64
    assert len(S.code_sha()) == 64


# --- the tool ----------------------------------------------------------------------------------------------------------------------------

def test_tool_works_with_empty_args_and_lists_what_was_not_run(con):
    import pflab.hq.tools  # noqa: F401
    from pflab.hq import tools_s79
    from pflab.hq.tools_s79 import t_studies as TS
    assert "wave_studies" in tools_s79.names()
    ctx = SimpleNamespace(con=con, call_ref=9, rt=None)
    out = TS.wave_studies(ctx, {})
    assert out["call_ref"] == 9 and "error" not in out and out["n_tests_total"] == 11
    h = 5
    rng = np.random.default_rng(31)
    idx = spaced_events(rng, 40, h)
    r = S.index_event_study("wave_5", "IN", h, DAYS, make_series(31), [(DAYS[i], "x") for i in idx], 2.5, 50, 400, family="wave")
    S.record(con, r, "p" * 64, NOW)
    out = TS.wave_studies(ctx, {})
    assert out["n_run"] == 1 and out["results"][0]["test"] == "wave_5" and "wave_5" not in out["not_run"] and "wave_20" in out["not_run"]
    only = TS.wave_studies(ctx, {"test": "wave_20"})
    assert only["n_run"] == 0


def test_tool_switch_off(con, monkeypatch):
    from pflab.hq.tools_s79 import t_studies as TS
    monkeypatch.setattr(TS, "_is_on", lambda: False)
    assert TS.wave_studies(SimpleNamespace(con=con, call_ref=1, rt=None), {})["off"] is True
