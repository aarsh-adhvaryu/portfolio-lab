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


# -- §8a truncation (added 2026-09-25) ----------------------------------
def _open_panel(days, names, price=100.0):
    return pd.DataFrame(price, index=list(days), columns=list(names))


def test_a_horizon_running_past_the_period_end_is_refused_not_silently_shortened():
    """§8a: no forward return may read a price after the period end.

    A six-month horizon opened in late 2019 would otherwise reach into 2020
    -- data development has not been shown -- and the last months of
    validation would read into the sealed period.
    """
    days = pd.bdate_range("2019-01-01", "2020-12-31").date
    c = _cal(days)
    ow = _open_panel(days, ["INE1"])
    # 1 month from 2019-10-31 lands inside 2019; 6 months does not
    r1 = es._forward_return(ow, "INE1", date(2019, 10, 31), 1, c,
                            period_end=date(2019, 12, 31))
    assert r1 is not None
    with pytest.raises(es.HorizonPastPeriodEnd):
        es._forward_return(ow, "INE1", date(2019, 10, 31), 6, c,
                           period_end=date(2019, 12, 31))


def test_no_forward_return_reads_a_price_after_the_period_end():
    """The invariant, swept across every month-end of both periods and every
    chartered horizon: whatever comes back, it never touched 2021-12-31+."""
    days = pd.bdate_range("2016-06-01", "2023-12-31").date
    c = _cal(days)
    ow = _open_panel(days, ["INE1"])
    for pend in (date(2019, 12, 31), date(2021, 12, 31)):
        for m in pd.date_range("2017-01-31", pend, freq="ME").date:
            if m not in c:
                m = c[c.asof(m)]
            for h in es.HORIZONS:
                try:
                    v = es._forward_return(ow, "INE1", m, h, c, period_end=pend)
                except es.HorizonPastPeriodEnd:
                    continue                      # excluded, and counted by run()
                if v is None:
                    continue
                start = c.next_session(m)
                target = start + pd.Timedelta(days=int(round(h * 30.44)))
                target = target.date() if hasattr(target, "date") else target
                end = c[c.asof(target)]
                assert end <= pend, f"{h}m from {m} read {end}, past {pend}"


def test_excluded_events_are_counted_not_dropped_quietly():
    """A horizon that silently drops its most recent cohorts is a different
    study from the one chartered."""
    days = pd.bdate_range("2019-01-01", "2019-12-31").date
    c = _cal(days)
    names = [f"INE{i}" for i in range(60)]
    ow = _open_panel(days, names)
    ev = _events([[n, n, n, "FRAUD", pd.Timestamp("2019-11-01 10:00"), "DissemDT",
                   date(2019, 11, 1), "h", "c", "s"] for n in names[:5]])
    me = [d for d in (date(2019, 10, 31), date(2019, 11, 29)) if d in c]
    tw = pd.DataFrame(1.0, index=list(days), columns=names)
    mw = pd.DataFrame(0.1, index=list(days), columns=names)
    out = es.run(ev, me, lambda m: names, ow, tw, mw, c,
                 period_end=date(2019, 12, 31))
    assert "excluded_horizon_past_period_end" in out
    assert out["period_end"] == "2019-12-31"
    assert out["excluded_horizon_past_period_end"][6] > 0


def test_a_study_that_cannot_yet_be_judged_says_so(tmp_path):
    """§8a's condition spans both periods. Running development alone once
    reported `passes: false`, which read as "the study failed" when it meant
    "the period label did not match". Incomplete is None, never False."""
    dev_only = {"e2a_development": {"mean_excess_6m": -0.077,
                                    "t_newey_west": -3.14}}
    v = es.verdict(dev_only)
    assert v["passes"] is None
    assert "validation" in v["passes_reason"]
    assert v["first_period_passes"] is True      # development's half IS met
    assert v["second_period_passes"] is None


def test_the_pass_condition_needs_both_halves():
    strong = {"mean_excess_6m": -0.077, "t_newey_west": -3.14}
    weak_t = {"mean_excess_6m": -0.077, "t_newey_west": -1.2}
    positive = {"mean_excess_6m": 0.02, "t_newey_west": 0.5}
    assert es.verdict({"2017-2019": strong, "2020-2021": strong})["passes"] is True
    # negative but not significant in the first period is not a pass
    assert es.verdict({"2017-2019": weak_t, "2020-2021": strong})["passes"] is False
    # significant in the first period but positive in the second is not either
    assert es.verdict({"2017-2019": strong, "2020-2021": positive})["passes"] is False


def test_period_labels_are_matched_by_alias_not_by_luck():
    """The charter names the periods by year; the configs name them
    e2a_development / e2a_validation. Both must resolve."""
    strong = {"mean_excess_6m": -0.05, "t_newey_west": -3.0}
    for dk in es.DEV_KEYS:
        for vk in es.VAL_KEYS:
            assert es.verdict({dk: strong, vk: strong})["passes"] is True


# -- the precision audit must not leak what it is asking about ----------
def test_masking_removes_the_company_and_every_date():
    from tools.flag_audit_sample import mask_text, _mask_company
    h = ("Reliance Industries Ltd has informed BSE that CRISIL downgraded its "
         "rating on 15-Mar-2019, effective March 20, 2019, for FY19")
    m = mask_text(h, "Reliance Industries Ltd")
    assert "Reliance" not in m and "Industries" not in m
    assert "2019" not in m and "Mar" not in m.replace("[DATE]", "")
    assert "downgraded" in m          # the substance survives
    # the pseudonym is stable and never the name
    a = _mask_company("Reliance Industries Ltd")
    assert a == _mask_company("reliance industries ltd  ")
    assert "Reliance" not in a and a.startswith("COMPANY-")


def test_the_audit_file_carries_no_returns_and_an_empty_label_column(tmp_path):
    import pandas as pd
    from tools.flag_audit_sample import write
    df = pd.DataFrame([{"row": 1, "flag": "FRAUD",
                        "headline": "[CO] informed BSE of alleged fraud",
                        "category": "Company Update", "subcategory": "General",
                        "_company_masked": "COMPANY-ABC123"}])
    df.attrs["population"] = {"FRAUD": 38}
    p = write(df, tmp_path / "flag_audit.md")
    text = p.read_text(encoding="utf-8")
    # no return DATA (the prose does say the word, deliberately), no regex,
    # no pseudonym leaking into the table, and a blank label cell
    import re as _re
    banned_data = ("mean_excess", "t_newey", "cagr", "max_drawdown",
                   "COMPANY-ABC123")
    for b in banned_data:
        assert b.lower() not in text.lower(), b
    # no signed percentages or decimal figures that could be a return
    table = " ".join(l for l in text.splitlines() if l.startswith("| 1 |"))
    assert not _re.search(r"[-+]?\d+\.\d+\s*%?", table), table
    assert "| 1 | FRAUD |" in text
    assert text.rstrip().endswith("|  |")      # the label cell is empty
    assert "TRUE" in text and "FALSE" in text and "UNSURE" in text
