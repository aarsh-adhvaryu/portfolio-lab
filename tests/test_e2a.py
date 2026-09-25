"""E2-A — the red-flag guard (§3, §4, §6, §8a).

All synthetic. Nothing here runs E2-A on real data: the charter is DRAFT and
locks at its first development run, which is Aarsh's to start.

The property these lean on hardest is §3's point-in-time key. A flag that
the engine can see one session early is lookahead, and it would flatter the
experiment in exactly the direction the charter is trying to measure.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from pflab.data import calendar as cal_mod, red_flag_events as rfe
from pflab.eval import classify, event_study as es


def _cal(days):
    return cal_mod.from_sessions(days)


SESSIONS = [date(2020, 1, d) for d in (6, 7, 8, 9, 10, 13, 14, 15)]


# -- §3's point-in-time key ---------------------------------------------
def test_after_1530_is_usable_only_from_the_next_session():
    """The market it would have moved had already closed."""
    c = _cal(SESSIONS)
    late = pd.Timestamp("2020-01-08 15:31:00")
    early = pd.Timestamp("2020-01-08 15:29:00")
    assert rfe.usable_from(late, c) == date(2020, 1, 9)
    assert rfe.usable_from(early, c) == date(2020, 1, 8)


def test_exactly_1530_is_usable_the_same_session():
    c = _cal(SESSIONS)
    assert rfe.usable_from(pd.Timestamp("2020-01-08 15:30:00"), c) == date(2020, 1, 8)


def test_a_flag_on_a_non_session_waits_for_the_next_one():
    """2020-01-11 is a Saturday: usable Monday whatever the clock says."""
    c = _cal(SESSIONS)
    assert rfe.usable_from(pd.Timestamp("2020-01-11 09:00:00"), c) == date(2020, 1, 13)
    assert rfe.usable_from(pd.Timestamp("2020-01-11 23:00:00"), c) == date(2020, 1, 13)


def test_a_flag_after_the_last_session_is_never_usable():
    """None, not the last session -- the caller must decide, not be handed
    a date the announcement preceded."""
    c = _cal(SESSIONS)
    assert rfe.usable_from(pd.Timestamp("2020-02-01 10:00:00"), c) is None


def test_missing_timestamp_yields_no_usable_date():
    assert rfe.usable_from(pd.NaT, _cal(SESSIONS)) is None


# -- §3's eligibility window --------------------------------------------
def _events(rows):
    return pd.DataFrame(rows, columns=["isin", "scrip_code", "company", "flag",
                                       "key_dt", "key_source", "usable_from",
                                       "headline", "category", "subcategory"])


def test_flagged_at_is_inclusive_of_today_and_excludes_the_future():
    ev = _events([
        ["INE1", "1", "A", "FRAUD", pd.Timestamp("2020-01-08 10:00"), "DissemDT",
         date(2020, 1, 8), "h", "c", "s"],
        ["INE2", "2", "B", "FRAUD", pd.Timestamp("2020-01-14 10:00"), "DissemDT",
         date(2020, 1, 14), "h", "c", "s"],
    ])
    assert rfe.flagged_at(ev, date(2020, 1, 8)) == {"INE1"}
    assert rfe.flagged_at(ev, date(2020, 1, 13)) == {"INE1"}
    assert rfe.flagged_at(ev, date(2020, 1, 14)) == {"INE1", "INE2"}


def test_a_flag_falls_out_of_the_window_after_twelve_months():
    ev = _events([["INE1", "1", "A", "FRAUD", pd.Timestamp("2020-01-08"),
                   "DissemDT", date(2020, 1, 8), "h", "c", "s"]])
    assert rfe.flagged_at(ev, date(2020, 12, 1)) == {"INE1"}
    assert rfe.flagged_at(ev, date(2021, 6, 1)) == set()


def test_new_flags_on_fires_only_on_the_usable_session():
    """§3's exit trigger is a NEW flag, not one already in the window -- a
    name already excluded must not be re-sold every session."""
    ev = _events([["INE1", "1", "A", "FRAUD", pd.Timestamp("2020-01-08"),
                   "DissemDT", date(2020, 1, 8), "h", "c", "s"]])
    assert rfe.new_flags_on(ev, date(2020, 1, 8)) == {"INE1"}
    assert rfe.new_flags_on(ev, date(2020, 1, 9)) == set()


# -- §3's exit hook ------------------------------------------------------
def test_red_flag_exit_sells_only_held_names_with_a_new_flag():
    from pflab.backtest import hooks as hk
    ev = _events([["INE1", "1", "A", "FRAUD", pd.Timestamp("2020-01-08"),
                   "DissemDT", date(2020, 1, 8), "h", "c", "s"],
                  ["INE9", "9", "Z", "FRAUD", pd.Timestamp("2020-01-08"),
                   "DissemDT", date(2020, 1, 8), "h", "c", "s"]])
    ex = hk.red_flag_exit(ev)
    assert ex(date(2020, 1, 8), ["INE1", "INE2"], None) == ["INE1"]   # not INE9
    assert ex(date(2020, 1, 9), ["INE1", "INE2"], None) == []
    assert ex(date(2020, 1, 8), [], None) == []


# -- §3's exclusion is applied after the ranking -------------------------
def test_exclusion_does_not_promote_a_thinner_name_into_the_universe():
    """§2's universe stays 'the 500 most traded'; §3 makes some of them
    ineligible. Excluding before the rank would change the universe too,
    and E2-A would then be two changes."""
    from pflab.backtest import engine
    names = [f"INE{i}" for i in range(6)]
    m = date(2020, 1, 31)
    pre = {"n": pd.DataFrame([[300] * 6], index=[m], columns=names),
           "close": pd.DataFrame([[100.0] * 6], index=[m], columns=names),
           "turnover": pd.DataFrame([[60, 50, 40, 30, 20, 10]], index=[m],
                                    columns=names)}
    top3 = engine.eligible_at(pre, m, 250, 3, 10.0)
    assert set(top3) == {"INE0", "INE1", "INE2"}
    # excluding the most traded leaves two, NOT three
    kept = engine.eligible_at(pre, m, 250, 3, 10.0, exclude={"INE0"})
    assert set(kept) == {"INE1", "INE2"}
    assert "INE3" not in kept


# -- §8a's arithmetic ----------------------------------------------------
def test_newey_west_t_needs_enough_observations():
    assert es.newey_west_t([0.1, -0.2, 0.3], lags=5) is None
    assert es.newey_west_t([], lags=5) is None


def test_newey_west_t_is_negative_for_a_negative_mean():
    rng = np.random.default_rng(3)
    x = rng.normal(-0.05, 0.02, 40)
    t = es.newey_west_t(x)
    assert t is not None and t < -2


def test_newey_west_t_is_near_zero_for_noise():
    rng = np.random.default_rng(5)
    t = es.newey_west_t(rng.normal(0.0, 0.05, 60))
    assert t is not None and abs(t) < 2


def test_the_pass_condition_is_the_charter_s():
    """§8a, written before the study was run: negative with t < -2 in
    2017-2019 AND negative in 2020-2021."""
    assert es.T_THRESHOLD == -2.0
    assert es.NEWEY_WEST_LAGS == 5
    assert es.GATING_HORIZON == 6
    assert es.HORIZONS == (1, 3, 6)


# -- §6 and §8a in the classifier ---------------------------------------
def _crit(cagr, dd):
    return {"rows": {"base": {"cagr": cagr, "max_drawdown": dd,
                              "turnover_annual": 1.5}},
            "benchmarks": {"NIFTY500_TRI": {"cagr": 0.10, "max_drawdown": -0.40},
                           "NIFTY500_MOMENTUM50_TRI": {"cagr": 0.12,
                                                       "max_drawdown": -0.40}}}


def _dirs(tmp_path, cand, stack):
    import json
    out = []
    for name, c in (("cd", cand), ("cv", cand), ("sd", stack), ("sv", stack)):
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "criteria.json").write_text(json.dumps(c), encoding="utf-8")
        out.append(d)
    return out


def test_adopt_needs_gate_and_the_event_study(tmp_path):
    cd, cv, sd, sv = _dirs(tmp_path, _crit(0.20, 0.30), _crit(0.10, 0.40))
    good = classify.classify_e2a(cd, cv, sd, sv, event_study={"passes": True})
    assert good["gate"]["verdict"] == "ADOPT"
    assert good["verdict"] == "ADOPT"
    # the same GATE result with a failing study is NOT an adopt
    bad = classify.classify_e2a(cd, cv, sd, sv, event_study={"passes": False})
    assert bad["gate"]["verdict"] == "ADOPT"
    assert bad["verdict"] == "INCONCLUSIVE"


def test_without_the_event_study_the_verdict_is_incomplete(tmp_path):
    cd, cv, sd, sv = _dirs(tmp_path, _crit(0.20, 0.30), _crit(0.10, 0.40))
    out = classify.classify_e2a(cd, cv, sd, sv)
    assert out["verdict"] == "INCOMPLETE"
    assert "8a" in out["verdict_reason"]


def test_c1_c4_are_not_reported_for_a_change_on_the_stack(tmp_path):
    """E2-A is not a candidate base, so E1 §13's bar does not apply."""
    cd, cv, sd, sv = _dirs(tmp_path, _crit(0.20, 0.30), _crit(0.10, 0.40))
    out = classify.classify_e2a(cd, cv, sd, sv, event_study={"passes": True})
    assert "charter_c1_c4" not in out


def test_the_window_and_its_limitation_travel_with_the_verdict(tmp_path):
    """§6's low-power declaration must reach whoever reads the number."""
    cd, cv, sd, sv = _dirs(tmp_path, _crit(0.20, 0.30), _crit(0.10, 0.40))
    out = classify.classify_e2a(cd, cv, sd, sv, event_study={"passes": True})
    w = out["window"]
    assert w["development"] == "2017-01-01..2019-12-31"
    assert w["validation"] == "2020-01-01..2021-12-31"
    assert "not shown" in w["declared_limitation"]
    assert "IBC" in w["why"]


def test_usable_from_is_never_earlier_than_the_announcement():
    """The invariant the whole experiment rests on, over every session and
    every minute of the day: a flag can never be acted on before it exists,
    and one stamped after 15:30 can never be acted on the same day.

    Checked on the real 2019+ table when it was built: 8,783 late flags,
    zero usable on or before their own date, zero early flags usable before
    theirs.
    """
    import datetime as dt
    days = [date(2020, 3, d) for d in (2, 3, 4, 5, 6, 9, 10, 11, 12, 13)]
    c = _cal(days)
    for d in [date(2020, 3, x) for x in range(1, 16)]:
        for hh, mm in ((0, 0), (9, 15), (15, 29), (15, 30), (15, 31), (23, 59)):
            ts = pd.Timestamp(dt.datetime.combine(d, dt.time(hh, mm)))
            u = rfe.usable_from(ts, c)
            if u is None:
                continue
            assert u >= d, f"{ts} -> {u} is before the announcement"
            if dt.time(hh, mm) > dt.time(15, 30):
                assert u > d, f"{ts} after 15:30 must not be usable on {d}"
            assert u in c, f"{u} is not a trading session"
