"""S85 L1 (wide): the wide watch (`think/wide.py`), exposure through funds (`think/exposure.py`), "what did I miss" (`think/missed.py`, job `think_missed`) and bounded threshold tuning
(`think/tuning.py`, Amendment A2 of the thinking-loop protocol). Synthetic data only (rule 7: no real names, holdings or amounts)."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pflab import think
from pflab.paper import book
from pflab.think import cases, exposure, missed, tuning, watch, wide
from tests.test_s80_core import AAA, BBB, GLD, DAYS, NOW, con  # noqa: F401  (the fixture)

DAY = DAYS[-1]
PROTOCOL = Path(__file__).resolve().parents[1] / "docs" / "protocols" / "s84_thinking_live_protocol.md"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    exposure.clear_cache()
    monkeypatch.setattr(watch, "_index", lambda market, root=None: None)
    yield
    exposure.clear_cache()


def cfg(monkeypatch, **kw):
    orig = think.settings
    monkeypatch.setattr(think, "settings", lambda raw=False: {**orig(raw), **kw})


def walk(last=(), n=None, vol=0.01, start=100.0, days=None):
    """Closes on the fixture's days: alternating +-vol (usual daily move = vol), the last returns replaced by `last`."""
    days = days or DAYS
    n = n or len(days)
    r = np.array([vol if k % 2 else -vol for k in range(n)], dtype=float)
    if len(last):
        r[-len(last):] = last
    return pd.Series(start * np.cumprod(1.0 + r), index=pd.to_datetime(days[-n:]))


def isin_of(k: int) -> str:
    return f"INE9{k:02d}A01010"


def world(monkeypatch, names: dict):
    """names: symbol -> (weight, last returns). The members of the (synthetic) Nifty 500 and their closes; nothing else is read."""
    rows, series = [], {}
    for k, (sym, (w, last)) in enumerate(names.items()):
        rows.append({"isin": isin_of(k), "symbol": sym, "weight": w, "basis": "synthetic proxy"})
        series[isin_of(k)] = walk(last)
    frame = pd.DataFrame(rows)
    monkeypatch.setattr(exposure, "index_weights", lambda index, day, root=None, con=None: frame if index == "NIFTY500" else frame.iloc[0:0])
    monkeypatch.setattr(wide, "_series", lambda con, root, market, uni, day: {i: s for i, s in series.items() if i in set(uni["isin"])})
    return {sym: isin_of(k) for k, sym in enumerate(names)}


def wsigs(con, isin=None):
    return [s for s in cases.signals(con) if '"wide": true' in (s["detail_json"] or "") and (isin is None or s["isin"] == isin)]


# --- 1. the wide watch ---------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_a_member_that_jumps_gets_a_stored_wide_signal_and_a_calm_one_does_not_and_a_second_pass_adds_nothing(con, monkeypatch, tmp_path):
    ids = world(monkeypatch, {"JUMP": (0.02, [0.04]), "CALM": (0.02, [0.004])})
    r = wide.run_pass(con, NOW, DAY, NOW, "IN", root=tmp_path)
    assert r["wide"]["scanned"] == 2 and "error" not in r["wide"]
    names = {s["signal"] for s in wsigs(con, ids["JUMP"])}
    assert "move_1d" in names and wsigs(con, ids["CALM"]) == []
    s = [x for x in wsigs(con, ids["JUMP"]) if x["signal"] == "move_1d"][0]
    d = json.loads(s["detail_json"])
    assert d["wide"] is True and "Nifty 500 member" in d["why_in_scope"] and s["surprise"] > 1.0 and s["score"] == pytest.approx(s["surprise"] * s["exposure_inr"])
    n = len(cases.signals(con))
    row = con.execute("SELECT scanned, signals, stored FROM think_wide_runs_s85 WHERE run_key=?", [f"IN:{DAY}"]).fetchone()
    assert row[0] == 2 and row[2] == n
    r2 = wide.run_pass(con, NOW + timedelta(minutes=1), DAY, NOW, "IN", root=tmp_path)             # idempotent per name, signal and day
    assert len(cases.signals(con)) == n and r2["signals"] == [] and r2["cases_opened"] == []


def test_a_name_whose_last_bar_is_not_the_day_gives_no_signal_and_nothing_after_the_day_is_read(con, monkeypatch, tmp_path):
    ids = world(monkeypatch, {"JUMP": (0.02, [0.04])})
    old = walk([0.04], days=DAYS[:-1])                                       # its last bar is the day before: stale
    monkeypatch.setattr(wide, "_series", lambda con_, root, market, uni, day: {ids["JUMP"]: old})
    r = wide.run_pass(con, NOW, DAY, NOW, "IN", root=tmp_path)
    assert r["wide"]["scanned"] == 0 and r["wide"]["stale_bars"] == 1 and wsigs(con) == []


def test_the_wide_watch_opens_at_most_one_case_a_day_the_strongest_and_keeps_the_rest_as_signals(con, monkeypatch, tmp_path):
    ids = world(monkeypatch, {"BIG": (0.05, [0.04]), "MID": (0.02, [0.04]), "SMALL": (0.005, [0.04])})
    r = wide.run_pass(con, NOW, DAY, NOW, "IN", root=tmp_path)
    assert len(r["cases_opened"]) == 1
    c = cases.get_case(con, r["cases_opened"][0])
    assert c["symbol"] == "BIG" and c["opened_by"] == "wide" and c["state"] == "open" and "wide watch" in c["title"]
    for sym in ("MID", "SMALL"):
        sg = wsigs(con, ids[sym])
        assert sg and all(s["status"] == "not_examined" and s["case_id"] is None for s in sg)
    cfg(monkeypatch, wide_cases_per_day=2)
    exposure.clear_cache()
    assert wide._wide_cases_today(con, DAY) == 1


def test_the_daily_cap_stays_the_cap_a_wide_name_replaces_only_a_weaker_unthought_case(con, monkeypatch, tmp_path):
    ids = world(monkeypatch, {"BIG": (0.05, [0.04])})
    weak = [cases.open_case(con, NOW, market="IN", kind="move", isin=f"INE777X0{k}010", symbol=f"W{k}", title="t", score=float(k + 1)) for k in range(3)]       # the day is full
    assert cases.cases_opened_on(con, DAY) == 3
    cases.add_step(con, weak[0], NOW, "read")                                # the weakest one has been thought through: it stays
    cases.add_step(con, weak[1], NOW, "read")
    r = wide.run_pass(con, NOW, DAY, NOW, "IN", root=tmp_path)
    assert len(r["cases_opened"]) == 1 and r["wide"]["demoted_cases"] == [weak[2]]            # the only unthought one (score 3) is weaker than the wide name's score
    assert cases.get_case(con, weak[2])["state"] == "noticed" and cases.cases_opened_on(con, DAY) == 3
    # a day that is full of cases nobody has thought through and that are all stronger: nothing is opened
    con.execute("DELETE FROM think_signals_s84")
    con.execute("DELETE FROM think_cases_s84 WHERE opened_by='wide'")
    con.execute("UPDATE think_cases_s84 SET score=1e12, state='open' WHERE case_id=?", [weak[2]])
    r2 = wide.run_pass(con, NOW + timedelta(minutes=1), DAY, NOW, "IN", root=tmp_path)
    assert r2["cases_opened"] == [] and wsigs(con, ids["BIG"])


def test_a_held_name_outranks_a_wide_one(con, monkeypatch, tmp_path):
    world(monkeypatch, {"WIDEJ": (0.08, [-0.04])})                          # an 8% index weight, same one-day move as the held name below
    rows = con.execute("SELECT date FROM prices WHERE isin=? ORDER BY date DESC LIMIT 2", [BBB]).fetchall()
    px0 = float(con.execute("SELECT close FROM prices WHERE isin=? AND date=?", [BBB, min(r[0] for r in rows)]).fetchone()[0])
    con.execute("UPDATE prices SET close=? WHERE isin=? AND date=?", [px0 * 0.96, BBB, DAY])
    cfg(monkeypatch, wide_watch=True)
    watch.run(con, NOW, mode="close", root=tmp_path)
    held = [s for s in cases.signals(con) if s["isin"] == BBB and s["signal"] == "move_1d"]
    wd = [s for s in wsigs(con) if s["signal"] == "move_1d"]
    assert held and wd
    assert held[0]["exposure_inr"] > wd[0]["exposure_inr"] > 0 and held[0]["score"] / held[0]["surprise"] > wd[0]["score"] / wd[0]["surprise"]


def test_the_watch_runs_the_wide_pass_only_when_the_switch_is_on_and_a_failing_wide_pass_never_stops_it(con, monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(wide, "run_pass", lambda *a, **k: called.append(a[4]) or {"signals": [], "cases_opened": [], "joined": [], "noticed": 0, "cases_noticed": [], "wide": {"market": "IN"}})
    cfg(monkeypatch, wide_watch=False)
    r = watch.run(con, NOW, mode="close", root=tmp_path)
    assert called == [] and "wide" not in r
    cfg(monkeypatch, wide_watch=True)
    r = watch.run(con, NOW + timedelta(minutes=1), mode="close", root=tmp_path)
    assert called == ["IN"] and r["wide"] == {"IN": {"market": "IN"}} and r["errors"] == []
    monkeypatch.setattr(wide, "run_pass", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = watch.run(con, NOW + timedelta(minutes=2), mode="close", root=tmp_path)
    assert r["errors"] == [] and "boom" in r["wide"]["IN"]["error"]


def test_a_run_of_20_points_against_the_index_in_20_sessions_is_a_wide_signal_and_opens_a_missed_run_kind_case(con, monkeypatch, tmp_path):
    names = {"RUNNER": (0.03, [0.011] * 20)}                               # about +24% in 20 sessions on a flat index
    world(monkeypatch, names)
    flat = walk(vol=0.0005)
    monkeypatch.setattr(watch, "_index", lambda market, root=None: flat)
    r = wide.run_pass(con, NOW, DAY, NOW, "IN", root=tmp_path)
    s = [x for x in wsigs(con) if x["signal"] == "wide_run_20d"]
    assert s and s[0]["value"] > 20.0
    assert [cases.get_case(con, c)["kind"] for c in r["cases_opened"]] == ["missed_run"]


# --- 2. exposure through funds ------------------------------------------------------------------------------------------------------------------------------------------------------

def _values(con):
    h = book.holdings(con, DAY)
    return {r["isin"]: float(r["value"]) for r in h["rows"]}, float(h["value"])


def _file(con, rows):
    for isin, pct in rows:
        con.execute("INSERT INTO fund_holdings VALUES (?,?,?,?,?,?,?,?,?,?)", [GLD, DAY - timedelta(days=20), isin, "n", "i", pct, None, "equity", "sha", NOW])


def test_fund_exposure_is_the_shares_plus_the_funds_weight_times_the_funds_value_by_hand(con):
    _file(con, [(AAA, 8.0), (BBB, 2.0)])
    exposure.clear_cache()
    v, whole = _values(con)
    x = exposure.fund_exposure(con, DAY, AAA)
    assert x["direct_inr"] == pytest.approx(v[AAA]) and x["via_funds_inr"] == pytest.approx(0.08 * v[GLD])
    assert x["funds"][0]["weight"] == pytest.approx(0.08) and x["funds"][0]["inr"] == pytest.approx(0.08 * v[GLD])
    assert x["total_inr"] == pytest.approx(v[AAA] + 0.08 * v[GLD]) and x["total_pct_book"] == pytest.approx((v[AAA] + 0.08 * v[GLD]) / watch._whole_inr(con, DAY))
    assert x["uncovered"] == [] and "portfolio file" in x["basis"] and x["coverage"] == "1 of 1 held funds have holdings data"
    y = exposure.fund_exposure(con, DAY, "INE000Z01019")                      # a company no held fund holds
    assert y["via_funds_inr"] == 0.0 and y["funds"] == [] and "none" in y["basis"] or "no held fund" in y["basis"]


def test_a_fund_with_no_holdings_data_counts_as_zero_and_is_listed_as_uncovered(con):
    exposure.clear_cache()
    x = exposure.fund_exposure(con, DAY, AAA)
    assert x["via_funds_inr"] == 0.0 and [u["symbol"] for u in x["uncovered"]] == ["GLDBEES"] and "gold" in x["uncovered"][0]["why"]
    assert x["coverage"] == "0 of 1 held funds have holdings data"


def test_an_index_fund_uses_the_indexs_weights_a_labelled_proxy(con, monkeypatch):
    frame = pd.DataFrame([{"isin": AAA, "symbol": "AAA", "weight": 0.05, "basis": "proxy: synthetic"}, {"isin": BBB, "symbol": "BBB", "weight": 0.01, "basis": "proxy: synthetic"}])
    monkeypatch.setattr(exposure, "index_weights", lambda index, day, root=None, con=None: frame)
    cfg(monkeypatch, fund_index={"GLDBEES": "NIFTY500"})
    exposure.clear_cache()
    v, _whole = _values(con)
    x = exposure.fund_exposure(con, DAY, AAA)
    assert x["via_funds_inr"] == pytest.approx(0.05 * v[GLD]) and "proxy" in x["basis"] and x["uncovered"] == []
    assert exposure.via_funds(con, DAY) == pytest.approx({AAA: 0.05 * v[GLD], BBB: 0.01 * v[GLD]})


def test_the_scope_and_the_signal_score_use_the_total_exposure_and_a_name_in_a_held_fund_counts_at_its_rupees(con):
    _file(con, [(AAA, 8.0), ("INE000Z01019", 3.0)])
    exposure.clear_cache()
    v, whole = _values(con)
    rows = watch.scope(con, DAY, market="IN", held_only=True)
    a = [r for r in rows if r["isin"] == AAA][0]
    assert a["exposure_inr"] == pytest.approx(v[AAA] + 0.08 * v[GLD]) and a["via_funds_inr"] == pytest.approx(0.08 * v[GLD]) and a["exposure_pct"] == pytest.approx(a["exposure_inr"] / whole)
    b = [r for r in rows if r["isin"] == BBB][0]
    assert b["exposure_inr"] == pytest.approx(v[BBB]) and b["via_funds_inr"] == 0.0
    outside = [{"isin": "INE000Z01019", "held": False, "exposure_inr": 5.0, "exposure_pct": 0.0, "exposure_basis": "stand-in"}]
    exposure.apply_to_scope(con, DAY, outside, whole, {})
    assert outside[0]["exposure_inr"] == pytest.approx(0.03 * v[GLD]) and "through funds" in outside[0]["exposure_basis"] and outside[0]["via_funds_inr"] == pytest.approx(0.03 * v[GLD])


def test_the_case_text_names_the_part_through_funds_and_the_funds_with_no_data(con, monkeypatch):
    _file(con, [(AAA, 8.0)])
    exposure.clear_cache()
    v, _ = _values(con)
    t = exposure.case_text(con, DAY, {"isin": AAA})
    assert "exposure_via_funds_inr" in t and f"{0.08 * v[GLD]:,.0f}" in t and "GLDBEES (8.0%)" in t
    assert "none of it" in exposure.case_text(con, DAY, {"isin": BBB})
    assert exposure.case_text(con, DAY, {"isin": "MARKET:IN"}) == ""
    monkeypatch.setattr(exposure, "_held_funds", lambda con_, day, root=None: [])
    assert exposure.case_text(con, DAY, {"isin": AAA}) == ""                  # the book holds no fund: the sentence is left out


def test_the_first_message_of_a_case_carries_the_through_funds_sentence(con):
    from pflab.think import session
    _file(con, [(AAA, 8.0)])
    exposure.clear_cache()
    case = cases.get_case(con, cases.open_case(con, NOW, market="IN", kind="move", isin=AAA, symbol="AAA", title="AAA fell", exposure_inr=1.0, exposure_pct=0.01, score=1.0))
    txt = session._first_message(con, NOW, case, [{"symbol": "AAA"}], {"text": "nothing stored", "items": []}, DAY)
    assert "exposure_via_funds_inr" in txt and txt.startswith("CASE #")


# --- 3. what did I miss ----------------------------------------------------------------------------------------------------------------------------------------------------------------

def _mover_world(monkeypatch, con):
    last = {"NOTICED": [0.03] * 5, "CAPPED": [0.03] * 5, "OUTSIDE": [0.03] * 5, "BELOW": [0.0078] * 5, "QUIET": [0.0015] * 5, "PASTLINE": [0.03] * 5}
    ids = {sym: isin_of(k) for k, sym in enumerate(last)}
    data = {ids[s]: {"symbol": s, "series": walk(l)} for s, l in last.items()}
    monkeypatch.setattr(missed, "universe_series", lambda con_, root, market, day, cfg_: data)
    monkeypatch.setattr(missed, "_scope_isins", lambda con_, day, market, root: {i for s, i in ids.items() if s != "OUTSIDE"})
    cases.open_case(con, NOW - timedelta(days=1), market="IN", kind="move", isin=ids["NOTICED"], symbol="NOTICED", title="t", score=1.0)
    cases.record_signal(con, NOW - timedelta(days=1), market="IN", isin=ids["CAPPED"], symbol="CAPPED", signal="move_1d", value=0.03, threshold=0.025, surprise=1.2, exposure_inr=1.0, score=1.2)
    return ids


def _by(con, sym, h=5):
    rows = con.execute("SELECT kind, detail FROM think_misses_s84 WHERE symbol=? ORDER BY miss_id", [sym]).fetchall()
    return [(k, json.loads(d)) for k, d in rows if json.loads(d)["horizon"] == h]


def test_the_misses_are_classified_by_reason_and_the_threshold_that_would_have_caught_them_is_named(con, monkeypatch):
    ids = _mover_world(monkeypatch, con)
    out = missed.one(con, NOW, "IN", DAY, None)
    assert out["movers"] == 12                                               # six names, two horizons
    assert _by(con, "NOTICED") == []                                         # a case was opened in its window: noticed, not a miss
    assert [k for k, _ in _by(con, "CAPPED")] == ["cap"]
    assert [k for k, _ in _by(con, "OUTSIDE")] == ["outside_scope"]
    assert [k for k, _ in _by(con, "PASTLINE")] == ["cap"]                   # past its line yet nothing stored: the day's limit
    (kind, d), = _by(con, "BELOW")
    assert kind == "below_threshold" and d["would_catch"]["param"] == "move_sigmas" and 1.5 < d["would_catch"]["value"] < think.settings()["move_sigmas"] and d["reason_text"] == "the threshold was too high"
    (kind, d), = _by(con, "QUIET")
    assert kind == "no_event" and d["would_catch"] is None
    n = con.execute("SELECT count(*) FROM think_misses_s84").fetchone()[0]
    assert missed.one(con, NOW + timedelta(minutes=1), "IN", DAY, None)["missed"] == 0 and con.execute("SELECT count(*) FROM think_misses_s84").fetchone()[0] == n       # idempotent
    sm = missed.summary(con, DAY)
    assert sm["by_reason"]["cap"] >= 2 and sm["by_reason"]["outside_scope"] >= 1 and "the cap cost us" in sm["text"] and "the threshold was too high" in sm["text"] and sm["total"] == n


def test_an_event_in_the_graph_makes_a_small_move_below_threshold_rather_than_no_event(con, monkeypatch):
    ids = _mover_world(monkeypatch, con)
    con.execute("INSERT INTO kg2_event (event_id, isin, source, ref, ts, event_date, kind, severity, headline, link_rule, link_proof, dedupe_key, ts_rule) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ["e1", ids["QUIET"], "news_x", "r1", datetime.combine(DAY, datetime.min.time()), DAY, "news", "low", "h", "t", "t", "k", "release_time"])
    missed.one(con, NOW, "IN", DAY, None)
    (kind, d), = _by(con, "QUIET")
    assert kind == "below_threshold" and d["graph_events"] == 1 and d["would_catch"] is None


def test_the_missed_job_looks_at_each_session_once_and_says_what_it_found(con, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(missed, "one", lambda con_, now, market, day, root=None: calls.append((market, day)) or {"market": market, "day": str(day), "movers": 40, "missed": 3, "by_reason": {"cap": 3}, "rows": []})
    r = missed.run(con, NOW, tmp_path)
    assert list(r) == ["IN"] and r["IN"]["missed"] == 3 and len(calls) == 1
    assert con.execute("SELECT count(*) FROM paper_acts WHERE loop='think_missed'").fetchone()[0] == 1
    assert missed.run(con, NOW + timedelta(hours=1), tmp_path) == {} and len(calls) == 1


def test_the_job_is_registered_follows_the_thinking_loop_and_is_switched_by_the_config(con, monkeypatch):
    from types import SimpleNamespace
    from pflab.service import ondemand, tasks  # noqa: F401
    from pflab.service import tasks_s79_think85 as tj
    from pflab.service.jobs import REGISTRY
    assert "think_missed" in REGISTRY and ondemand.AFTER["think_missed"] == ("think_loop",) and "think_missed" in ondemand.MAX_AGE_H
    assert tj._enabled(SimpleNamespace(con=con))[0] is True and think.settings()["wide_watch"] is True and think.settings()["tune_thresholds"] is False
    cfg(monkeypatch, missed_job=False)
    assert tj._enabled(SimpleNamespace(con=con))[0] is False
    monkeypatch.setattr(missed, "run", lambda con_, now, root=None: {})
    out = tj._run(SimpleNamespace(con=con, now=NOW, data_root=None))
    assert out == {"skipped": "nothing new to look at"} or "tuning_note" in out


# --- 4. bounded threshold tuning --------------------------------------------------------------------------------------------------------------------------------------------------------

def _miss(con, day, param, value, kind="below_threshold"):
    from pflab.pm.store import next_id
    mid = next_id(con, "think_misses_s84", "miss_id")
    con.execute("INSERT INTO think_misses_s84 VALUES (?,?,?,?,?,?,?,?,?)", [mid, day, kind, "IN", f"INE{mid:09d}", f"M{mid}", 10.0, 0.0,
                json.dumps({"horizon": 5, "direction": "rise", "would_catch": {"param": param, "value": value} if param else None})])


def _quiet_case(con, day, signal):
    cid = cases.open_case(con, datetime.combine(day, datetime.min.time()), market="IN", kind="move", isin=f"INE8{cid_counter()}A01010", symbol="Q", title="t", score=1.0)
    cases.record_signal(con, datetime.combine(day, datetime.min.time()), market="IN", isin="x", symbol="Q", signal=signal, value=1, threshold=1, surprise=1, exposure_inr=1, score=1)
    con.execute("UPDATE think_signals_s84 SET case_id=? WHERE case_id IS NULL AND symbol='Q'", [cid])
    cases.close_case(con, cid, day, "quiet for 60 sessions")
    return cid


_n = [0]


def cid_counter() -> str:
    _n[0] += 1
    return f"{_n[0]:04d}"


def test_tuning_does_nothing_under_the_counts_and_when_switched_off(con, monkeypatch):
    assert "switched off" in tuning.run_weekly(con, NOW)["why"]                # OFF by default
    cfg(monkeypatch, tune_thresholds=True)
    r = tuning.run_weekly(con, NOW)
    assert r["changed"] is False and "under the counts" in r["why"] and r["counts"]["scored"] == 0 and r["counts"]["gate_open"] is False
    cfg(monkeypatch, tune_thresholds=False)
    assert "switched off" in tuning.run_weekly(con, NOW)["why"]


def test_tuning_lowers_one_threshold_by_at_most_ten_percent_records_it_and_the_settings_read_it(con, monkeypatch):
    for v in (2.0, 2.1, 2.2, 2.3, 2.4, 2.45):                                  # six misses a lower move_sigmas would have caught: under 60, so the gate is the scored count
        _miss(con, DAY - timedelta(days=3), "move_sigmas", v)
    for k in range(40):                                                         # 40 scored decisions open the gate
        con.execute("INSERT INTO think_scores_s84 VALUES (?,?,?,?,?,?,?,?)", [k + 1, k + 1, 20, "rule", "hold", 0.0, 0.0, DAY])
    cfg(monkeypatch, tune_thresholds=True)
    cfg_v = think.settings(raw=True)["move_sigmas"]
    assert cfg_v == 2.5
    p = tuning.propose(con, DAY)
    assert p["param"] == "move_sigmas" and p["direction"] == "lower" and p["new_value"] == pytest.approx(2.25) and p["old_value"] == 2.5       # 10% step, not below the 25th percentile (2.2)
    r = tuning.run_weekly(con, NOW)
    assert r["changed"] is True and r["new_value"] == pytest.approx(2.25)
    assert think.settings()["move_sigmas"] == pytest.approx(2.25) and think.settings(raw=True)["move_sigmas"] == 2.5          # the config's value is never edited
    row = con.execute("SELECT param, old_value, new_value, config_value, state FROM think_tuning_s84").fetchone()
    assert row == ("move_sigmas", 2.5, 2.25, 2.5, "applied")
    again = tuning.run_weekly(con, NOW + timedelta(days=3))                    # one threshold a week
    assert again["changed"] is False and "one threshold a week" in again["why"]
    rv = tuning.revert(con, day=DAY)
    assert rv == {"reverted": True, "tuning_id": r["tuning_id"], "param": "move_sigmas", "back_to": 2.5} and think.settings()["move_sigmas"] == 2.5
    assert con.execute("SELECT state FROM think_tuning_s84").fetchone()[0] == "reverted"
    assert tuning.revert(con)["reverted"] is False


def test_tuning_stays_inside_half_to_double_the_config_value_and_a_step_never_exceeds_ten_percent(con, monkeypatch):
    for k in range(40):
        con.execute("INSERT INTO think_scores_s84 VALUES (?,?,?,?,?,?,?,?)", [k + 1, k + 1, 20, "rule", "hold", 0.0, 0.0, DAY])
    for _ in range(6):
        _miss(con, DAY - timedelta(days=2), "move_sigmas", 0.1)               # they would be caught only by a line far under the band
    cur = 2.5
    for week in range(12):                                                    # week after week the line comes down but never under 1.25 (0.5 x 2.5), each step at most 10%
        p = tuning.propose(con, DAY)
        if p is None:
            break
        assert p["new_value"] >= cur * 0.9 - 1e-9 and p["new_value"] >= 1.25 - 1e-9
        con.execute("DELETE FROM think_tuning_s84")                           # (the weekly rhythm is its own test)
        tuning.apply(con, DAY, p)
        cur = p["new_value"]
    assert cur == pytest.approx(1.25) and tuning.propose(con, DAY) is None                   # at the edge of its band: not moved
    with pytest.raises(ValueError):
        tuning.apply(con, DAY, {"param": "move_sigmas", "old_value": 1.25, "new_value": 1.0, "config_value": 2.5, "direction": "lower", "reason": "x"})
    with pytest.raises(ValueError):
        tuning.apply(con, DAY, {"param": "max_cases_per_day", "old_value": 3, "new_value": 2.7, "config_value": 3, "direction": "lower", "reason": "x"})


def test_false_alarms_raise_a_threshold_and_a_binding_cap_stops_a_lower_line(con, monkeypatch):
    for k in range(40):
        con.execute("INSERT INTO think_scores_s84 VALUES (?,?,?,?,?,?,?,?)", [k + 1, k + 1, 20, "rule", "hold", 0.0, 0.0, DAY])
    for _ in range(6):
        _quiet_case(con, DAY - timedelta(days=1), "fall_10d")
    p = tuning.propose(con, DAY)
    assert p["param"] == "fall_pct_10d" and p["direction"] == "raise" and p["new_value"] == pytest.approx(0.22) and p["old_value"] == pytest.approx(0.20)
    # misses ahead of alarms, but the cap already binds (3 cases a day against a cap of 3): no lower line
    con.execute("DELETE FROM think_cases_s84")
    con.execute("DELETE FROM think_signals_s84")
    for v in (2.0, 2.1, 2.2, 2.3, 2.4, 2.45):
        _miss(con, DAY - timedelta(days=3), "move_sigmas", v)
    for k in range(3):
        cases.open_case(con, NOW - timedelta(hours=k), market="IN", kind="move", isin=f"INE5{k:08d}", symbol="X", title="t", score=1.0)
    con.execute("INSERT INTO think_watch_runs_s84 VALUES ('close:IN:%s', 'close', 'IN', ?, ?, 1, 3, 0)" % DAY, [DAY, NOW])
    assert tuning.propose(con, DAY) is None


def test_the_counts_gate_either_count_opens_it_and_the_job_needs_the_amendment_registered(con, monkeypatch):
    assert tuning.counts(con)["gate_open"] is False
    for _ in range(60):
        _miss(con, DAY - timedelta(days=1), None, None, kind="outside_scope")
    c = tuning.counts(con)
    assert c["misses"] == 60 and c["scored"] == 0 and c["gate_open"] is True
    cfg(monkeypatch, tune_thresholds=True)
    from pflab.learner import s84
    monkeypatch.setattr(s84, "PROTOCOL", Path("nonexistent.md"))
    assert "Amendment A2 is not registered" in tuning.run_weekly(con, NOW)["why"]


def test_the_settings_read_the_override_file_and_ignore_a_value_outside_the_band(con):
    think.write_overrides({"move_sigmas": 2.0, "fall_pct_10d": 0.05})        # 0.05 is under half of 0.20: refused
    s = think.settings()
    assert s["move_sigmas"] == 2.0 and s["fall_pct_10d"] == 0.20 and think.settings(raw=True)["move_sigmas"] == 2.5
    think.write_overrides({})
    assert think.settings()["move_sigmas"] == 2.5


def test_the_status_says_in_plain_words_where_the_tuning_stands(con):
    s = tuning.status(con)
    assert s["on"] is False and s["overrides"] == {} and "No threshold has been changed" in s["text"] and "needs 40 or 60" in s["text"]


# --- the registered protocol amendment ----------------------------------------------------------------------------------------------------------------------------------------

def test_the_protocols_amendment_a2_is_the_codes_rule_dated_and_registered_once(con):
    text = PROTOCOL.read_text(encoding="utf-8")
    assert "Amendment A2, 2026-11-13" in text
    block = json.loads(re.search(r"```json amendment_a2\n(.*?)\n```", text, re.S).group(1))
    assert block == json.loads(json.dumps(tuning.RULE))                       # the whole block, key for key
    assert block["step_max"] == 0.10 and block["band"] == [0.5, 2.0] and block["per_week"] == 1 and block["min_scored"] == 40 and block["min_misses"] == 60
    from pflab.learner import s84
    assert s84.register_thinking_live(con, NOW) == ["s84:thinking_live"]
    assert s84.register_thinking_amendment_a2(con, NOW) == ["s84:thinking_live_a2"] and s84.register_thinking_amendment_a2(con, NOW) == []
    assert s84.protocol_ok(con)["unchanged"] is True
    n = con.execute("SELECT count(*) FROM learn_tests WHERE note LIKE 's84:thinking_live%'").fetchone()[0]
    assert n == 2
