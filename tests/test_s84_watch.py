"""S84 T1 NOTICE (`think/watch.py`): each signal fires at its threshold and not below; join vs new; the daily cap; a missed run; scope; idempotence; point in time; the catch-up. Synthetic data only
(rule 7: no real names, holdings or amounts)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from pflab import markets, think
from pflab.think import cases, watch
from tests.test_s80_core import AAA, BBB, GLD, DAYS, NOW, con  # noqa: F401  (the fixture)

DAY = DAYS[-1]                                        # 2026-10-30, a Friday: the last stored close
CCC = "INE000C01013"


@pytest.fixture(autouse=True)
def _no_real_data(monkeypatch):
    monkeypatch.setattr(watch, "_index", lambda market, root=None: None)


def _reshape(con, isin, rets, day=DAY):
    """Rewrite the last len(rets) closes of `isin` (ending at `day`) from the close before them: close_k = close_(k-1) x (1 + ret_k)."""
    rows = con.execute("SELECT date FROM prices WHERE isin=? AND date<=? ORDER BY date DESC LIMIT ?", [isin, day, len(rets) + 1]).fetchall()
    ds = sorted(r[0] for r in rows)
    px = float(con.execute("SELECT close FROM prices WHERE isin=? AND date=?", [isin, ds[0]]).fetchone()[0])
    for d, r in zip(ds[1:], rets):
        px *= 1.0 + r
        con.execute("UPDATE prices SET close=? WHERE isin=? AND date=?", [px, isin, d])


def _sigs(con, isin=None):
    return [(s["isin"], s["signal"]) for s in cases.signals(con) if isin is None or s["isin"] == isin]


def _names(con, isin):
    return {s["signal"] for s in cases.signals(con) if s["isin"] == isin}


def _index_series(rets_last=None, n=len(DAYS)):
    """A synthetic index on the same dates: small alternating noise, the last returns replaced by `rets_last`."""
    r = np.array([0.001 if k % 2 else -0.001 for k in range(n)], dtype=float)
    if rets_last:
        r[-len(rets_last):] = rets_last
    lvl = 1000.0 * np.cumprod(1.0 + r)
    return pd.Series(lvl, index=pd.to_datetime(DAYS))


def _event(con, isin, kind, sev, ts, source="bse_announcement", ref="r1", headline="synthetic headline"):
    con.execute("INSERT INTO kg2_event (event_id, isin, source, ref, ts, event_date, kind, severity, headline, link_rule, link_proof, dedupe_key, ts_rule) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [f"{source}:{ref}:{isin}", isin, source, ref, ts, ts.date(), kind, sev, headline, "t", "t", f"{source}:{ref}", "release_time"])


def test_a_quiet_book_gives_no_signal_and_no_case(con, tmp_path):
    r = watch.run(con, NOW, mode="close", root=tmp_path)
    assert r["signals"] == [] and r["cases_opened"] == [] and r["errors"] == []


def test_a_one_day_move_fires_beyond_2_5_usual_moves_and_not_below(con, tmp_path):
    _reshape(con, BBB, [-0.015])                                    # BBB's usual daily move is about 0.8%: 1.5% is under 2.5 of them
    watch.run(con, NOW, mode="close", root=tmp_path)
    assert "move_1d" not in _names(con, BBB)
    _reshape(con, BBB, [-0.04])
    r = watch.run(con, NOW + timedelta(minutes=1), mode="close", root=tmp_path)
    s = [x for x in cases.signals(con) if x["isin"] == BBB and x["signal"] == "move_1d"][0]
    assert s["value"] == pytest.approx(-0.04, abs=1e-6) and s["surprise"] > 1.0 and s["exposure_inr"] > 0 and s["score"] == pytest.approx(s["surprise"] * s["exposure_inr"])
    assert len(r["cases_opened"]) == 1 and "usual daily move" in cases.get_case(con, r["cases_opened"][0])["title"]


def test_a_fall_of_20_percent_in_10_sessions_fires_and_15_does_not(con, tmp_path):
    _reshape(con, BBB, [-0.017] * 10)                               # about -16%, each day under the one-day line
    watch.run(con, NOW, mode="close", root=tmp_path)
    assert "fall_10d" not in _names(con, BBB)
    _reshape(con, BBB, [-0.0225] * 10)                              # about -20.4%
    watch.run(con, NOW + timedelta(minutes=1), mode="close", root=tmp_path)
    assert "fall_10d" in _names(con, BBB)


def test_fifteen_points_worse_than_the_market_in_5_sessions_fires_and_ten_does_not(con, tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "_index", lambda market, root=None: _index_series())
    _reshape(con, BBB, [-0.022] * 5)                                # about -10.6% against a flat market
    watch.run(con, NOW, mode="close", root=tmp_path)
    assert "rel_fall_5d" not in _names(con, BBB)
    _reshape(con, BBB, [-0.033] * 5)                                # about -15.5%
    watch.run(con, NOW + timedelta(minutes=1), mode="close", root=tmp_path)
    assert "rel_fall_5d" in _names(con, BBB)


def test_the_market_down_10_percent_in_20_sessions_fires_and_9_does_not(con, tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "_index", lambda market, root=None: _index_series([-0.0047] * 20))          # about -9.0%
    watch.run(con, NOW, mode="close", root=tmp_path)
    assert ("MARKET:IN", "market_down_20d") not in _sigs(con)
    monkeypatch.setattr(watch, "_index", lambda market, root=None: _index_series([-0.0054] * 20))          # about -10.3%
    r = watch.run(con, NOW + timedelta(minutes=1), mode="close", root=tmp_path)
    assert ("MARKET:IN", "market_down_20d") in _sigs(con)
    assert any(cases.get_case(con, c)["isin"] == "MARKET:IN" and cases.get_case(con, c)["kind"] == "market" for c in r["cases_opened"])


def test_a_burst_of_news_fires_against_the_names_own_norm(con, tmp_path):
    for i in range(2):
        _event(con, AAA, "news", "low", datetime.combine(DAY, datetime.min.time()) + timedelta(hours=9 + i), source="news_x", ref=f"n{i}")
    watch.run(con, NOW, mode="close", root=tmp_path)
    assert "news_burst" not in _names(con, AAA)                                    # two items are under the minimum of three
    for i in range(2, 5):
        _event(con, AAA, "news", "low", datetime.combine(DAY, datetime.min.time()) + timedelta(hours=9 + i), source="news_x", ref=f"n{i}")
    watch.run(con, NOW + timedelta(minutes=1), mode="close", root=tmp_path)
    assert "news_burst" in _names(con, AAA)


def test_a_thesis_break_event_fires_a_routine_one_does_not_and_a_later_one_is_never_read(con, tmp_path):
    t = datetime.combine(DAY, datetime.min.time()) + timedelta(hours=11)
    _event(con, BBB, "results", "low", t, ref="routine")
    _event(con, BBB, "fraud_investigation", "high", NOW + timedelta(hours=2), ref="later")                # released after `now`: point in time
    watch.run(con, NOW, mode="close", root=tmp_path)
    assert "thesis_event" not in _names(con, BBB)
    _event(con, BBB, "fraud_investigation", "high", t, ref="real")
    r = watch.run(con, NOW + timedelta(minutes=1), mode="close", root=tmp_path)
    s = [x for x in cases.signals(con) if x["signal"] == "thesis_event"]
    assert len(s) == 1 and json.loads(s[0]["detail_json"])["ref"] == "bse_announcement:real" and len(r["cases_opened"]) == 1
    watch.run(con, NOW + timedelta(minutes=2), mode="close", root=tmp_path)                                # the same event is one signal, not two
    assert len([x for x in cases.signals(con) if x["signal"] == "thesis_event"]) == 1


def test_a_storyline_moving_15_points_in_a_day_fires_and_14_does_not(con, tmp_path):
    con.execute("INSERT INTO storylines_s80 (storyline_id, market, claim, kind, direction, subject, opened_on, status, status_on, prior, probability) VALUES (1,'IN','Synthetic claim about a cause and what it should do to prices',"
                "'market',-1,'NIFTY500_TRI',?, 'open', ?, 0.5, 0.6)", [DAY - timedelta(days=30), DAY - timedelta(days=30)])
    con.execute("INSERT INTO storyline_exposure_s80 VALUES (1, ?, 0.8, 't', ?)", [BBB, DAY])
    con.execute("INSERT INTO storyline_prob_s80 VALUES (1, ?, 0.50, 0, '{}')", [DAY - timedelta(days=1)])
    con.execute("INSERT INTO storyline_prob_s80 VALUES (1, ?, 0.64, 0, '{}')", [DAY])
    watch.run(con, NOW, mode="close", root=tmp_path)
    assert ("STORY:1", "storyline_jump") not in _sigs(con)
    con.execute("UPDATE storyline_prob_s80 SET probability=0.66 WHERE storyline_id=1 AND prob_date=?", [DAY])
    watch.run(con, NOW + timedelta(minutes=1), mode="close", root=tmp_path)
    s = [x for x in cases.signals(con) if x["isin"] == "STORY:1"]
    assert s and s[0]["value"] == pytest.approx(16.0) and s[0]["exposure_inr"] > 0


def test_a_move_outside_the_stored_forecast_range_fires(con, tmp_path):
    prev = DAYS[-2]
    base = float(con.execute("SELECT close FROM prices WHERE isin=? AND date=?", [BBB, prev]).fetchone()[0])
    q = {"0.05": -0.02, "0.1": -0.015, "0.25": -0.007, "0.5": 0.0, "0.75": 0.007, "0.9": 0.015, "0.95": 0.02}
    con.execute("INSERT INTO forecasts_s79 VALUES (1,'IN','live',?,?,?,1,'hedge',?,?,?,'{}',now())", [prev, BBB, "BBB", json.dumps(q), base, DAY])
    _reshape(con, BBB, [0.015])                                                                            # inside the 5-95% range
    watch.run(con, NOW, mode="close", root=tmp_path)
    assert "outside_forecast" not in _names(con, BBB)
    _reshape(con, BBB, [0.03])
    watch.run(con, NOW + timedelta(minutes=1), mode="close", root=tmp_path)
    s = [x for x in cases.signals(con) if x["signal"] == "outside_forecast"][0]
    assert s["isin"] == BBB and s["surprise"] > 1.0


def test_a_split_is_not_a_fall(con, tmp_path):
    f = tmp_path / "corporate_actions"
    f.mkdir()
    ex = DAYS[-4]
    pd.DataFrame({"isin": [BBB], "ex_date": [ex], "factor": [0.5]}).to_parquet(f / "factors.parquet")
    con.execute("UPDATE prices SET close = close / 2 WHERE isin=? AND date >= ?", [BBB, ex])                 # the close halves on the ex-date: a 1-for-2 split
    watch.run(con, NOW, mode="close", root=tmp_path)
    assert not ({"move_1d", "move_5d", "fall_10d"} & _names(con, BBB))


def _passed_on(con, why="synthetic reason for passing", on=None):
    on = on or DAYS[-60]
    con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, 'CCC', 'CCC Ltd', 'synthetic', now())", [CCC])
    for k, d in enumerate(DAYS):
        con.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [CCC, d, 100.0])
    con.execute("INSERT INTO skips_s83 (skip_id, market, isin, symbol, why, skipped_on, session_ref) VALUES (1,'IN',?,'CCC',?,?,'s')", [CCC, why, on])
    return on


def test_a_missed_run_opens_only_when_20_points_ahead_of_the_index(con, tmp_path, monkeypatch):
    on = _passed_on(con)
    monkeypatch.setattr(watch, "_index", lambda market, root=None: _index_series())                       # the index is about flat since
    con.execute("UPDATE prices SET close=118 WHERE isin=? AND date > ?", [CCC, on])                       # +18 points
    watch.run(con, NOW, mode="close", root=tmp_path)
    assert "missed_run" not in _names(con, CCC)
    con.execute("UPDATE prices SET close=122 WHERE isin=? AND date > ?", [CCC, on])                       # +22 points
    r = watch.run(con, NOW + timedelta(minutes=1), mode="close", root=tmp_path)
    s = [x for x in cases.signals(con) if x["signal"] == "missed_run"][0]
    d = json.loads(s["detail_json"])
    assert s["value"] >= 20.0 and d["passed_on"] == str(on) and d["why_passed"] == "synthetic reason for passing" and "price changed" in d["question"]
    c = cases.get_case(con, r["cases_opened"][0])
    assert c["kind"] == "missed_run" and c["isin"] == CCC and "passed on" in c["title"] and d["exposure_basis"].startswith("stand-in")
    watch.run(con, NOW + timedelta(minutes=2), mode="close", root=tmp_path)                               # a case that has fired does not fire again at once (cooldown)
    assert len([x for x in cases.signals(con) if x["signal"] == "missed_run"]) == 1


def test_a_screened_name_is_a_missed_run_too_and_a_held_one_is_not(con, tmp_path, monkeypatch):
    on = _passed_on(con, on=DAYS[-30])
    con.execute("DELETE FROM skips_s83")
    con.execute("INSERT INTO screen_log_s83 VALUES (1, ?, ?, 'IN', 'screen_stocks', '{}', 1, ?)", [datetime.combine(on, datetime.min.time()), on, json.dumps(["CCC", "BBB"])])
    monkeypatch.setattr(watch, "_index", lambda market, root=None: _index_series())
    con.execute("UPDATE prices SET close=130 WHERE isin=? AND date > ?", [CCC, on])
    watch.run(con, NOW, mode="close", root=tmp_path)
    assert "missed_run" in _names(con, CCC) and "missed_run" not in _names(con, BBB)                      # BBB is held: it was not passed on


def test_scope_has_the_holdings_the_picks_the_skips_and_the_screened_with_a_labelled_stand_in(con, tmp_path):
    _passed_on(con)
    con.execute("INSERT INTO picks_s83 (pick_id, market, isin, symbol, source, thesis, break_condition, state, proposed_on) VALUES (1,'IN','INE000D01014','DDD','system','t','b','proposed',?)", [DAYS[-5]])
    sc = {e["symbol"]: e for e in watch.scope(con, DAY, root=tmp_path)}
    assert sc["BBB"]["held"] and sc["BBB"]["exposure_inr"] > 0 and 0 < sc["BBB"]["exposure_pct"] < 1 and sc["BBB"]["why"] == "held"
    assert not sc["CCC"]["held"] and sc["CCC"]["base_day"] == DAYS[-60] and "skipped" in sc["CCC"]["why"] and sc["CCC"]["exposure_basis"].startswith("stand-in")
    assert "pick" in sc["DDD"]["why"] and sc["DDD"]["exposure_inr"] > 0
    assert all(set(e) >= {"name", "isin", "symbol", "market", "exposure_inr", "exposure_pct", "why"} for e in sc.values())
    assert [e["symbol"] for e in watch.scope(con, DAY, root=tmp_path, held_only=True)] and all(e["held"] for e in watch.scope(con, DAY, root=tmp_path, held_only=True))


def test_a_new_signal_on_a_name_with_an_open_case_joins_it(con, tmp_path):
    _reshape(con, BBB, [-0.04])
    r1 = watch.run(con, NOW, mode="close", root=tmp_path)
    assert len(r1["cases_opened"]) == 1
    cid = r1["cases_opened"][0]
    _event(con, BBB, "guidance_cut", "medium", NOW - timedelta(hours=1), source="news_x", ref="g1")
    r2 = watch.run(con, NOW + timedelta(minutes=5), mode="close", root=tmp_path)
    assert r2["cases_opened"] == [] and r2["joined"] == [cid]
    assert {s["case_id"] for s in cases.signals(con) if s["isin"] == BBB} == {cid}
    assert len(cases.open_cases(con)) == 1


def test_at_most_three_new_cases_a_day_and_the_fourth_is_noticed_not_examined(con, tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "_index", lambda market, root=None: _index_series([-0.0054] * 20))
    t = datetime.combine(DAY, datetime.min.time()) + timedelta(hours=11)
    _reshape(con, BBB, [-0.05])
    _reshape(con, GLD, [-0.02])
    _event(con, AAA, "fraud_investigation", "high", t, ref="x")
    r = watch.run(con, NOW, mode="close", root=tmp_path)
    assert len(r["cases_opened"]) == 3 and r["noticed"] >= 1 and len(r["cases_noticed"]) == r["noticed"]
    opened = [cases.get_case(con, c) for c in r["cases_opened"]]
    noticed = [cases.get_case(con, c) for c in r["cases_noticed"]]
    assert all(c["state"] == "open" for c in opened) and all(c["state"] == "noticed" for c in noticed)
    assert min(c["score"] for c in opened) >= max(c["score"] for c in noticed)                                # the largest scores were thought through
    assert cases.cases_opened_on(con, DAY) == 3 and not [c for c in cases.open_cases(con) if c["state"] == "noticed"]
    assert {s["status"] for s in cases.signals(con, case_id=noticed[0]["case_id"])} == {"not_examined"}
    assert cases.thinking_block(con, DAY)["noticed_not_examined_today"] == len(noticed)


def test_the_cap_is_a_setting(con, tmp_path, monkeypatch):
    monkeypatch.setattr(think, "settings", lambda: {**think.DEFAULTS, "max_cases_per_day": 1})
    _reshape(con, BBB, [-0.05])
    _reshape(con, GLD, [-0.02])
    r = watch.run(con, NOW, mode="close", root=tmp_path)
    assert len(r["cases_opened"]) == 1 and r["noticed"] == 1 and cases.get_case(con, r["cases_opened"][0])["isin"] == BBB


def test_running_twice_stores_each_signal_once(con, tmp_path):
    _reshape(con, BBB, [-0.04])
    a = watch.run(con, NOW, mode="close", root=tmp_path)
    n = len(cases.signals(con))
    b = watch.run(con, NOW + timedelta(minutes=30), mode="close", root=tmp_path)
    assert n > 0 and len(cases.signals(con)) == n and b["signals"] == [] and b["cases_opened"] == [] and len(a["signals"]) == n


def test_nothing_dated_after_the_day_is_read(con, tmp_path):
    for k, d in enumerate([date(2026, 11, 2), date(2026, 11, 3)]):
        con.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [BBB, d, 10.0])          # a crash AFTER the day being watched
    con.execute("INSERT INTO screen_log_s83 VALUES (1, ?, ?, 'IN', 'screen_stocks', '{}', 1, ?)", [datetime(2026, 11, 3), date(2026, 11, 3), json.dumps(["BBB"])])
    r = watch.run(con, NOW, mode="close", root=tmp_path)
    assert r["signals"] == [] and cases.signals(con) == []


def test_a_name_with_no_price_in_5_days_is_not_watched_on_a_stale_close(con, tmp_path):
    con.execute("DELETE FROM prices WHERE isin=? AND date > ?", [BBB, DAYS[-12]])
    assert watch.run(con, NOW, mode="close", root=tmp_path)["signals"] == []


def test_session_mode_reads_live_quotes_of_held_names_and_never_the_heavy_sources(con, tmp_path):
    assert "no live quotes" in watch.run(con, NOW, mode="session", root=tmp_path)["note"]
    px = float(con.execute("SELECT close FROM prices WHERE isin=? AND date=?", [BBB, DAY]).fetchone()[0])
    for i in range(4):
        _event(con, BBB, "news", "low", datetime.combine(DAY, datetime.min.time()) + timedelta(hours=9 + i), source="news_x", ref=f"n{i}")
    r = watch.run(con, NOW, mode="session", quotes={BBB: px * 0.95}, root=tmp_path)
    assert "move_1d" in _names(con, BBB) and "news_burst" not in _names(con, BBB) and len(r["cases_opened"]) == 1
    assert json.loads([s for s in cases.signals(con) if s["signal"] == "move_1d"][0]["detail_json"])["price"] == pytest.approx(px * 0.95)


def test_the_catch_up_runs_each_missed_close_once_and_a_first_run_only_the_latest(con, tmp_path):
    r = watch.run(con, NOW, mode="catchup", root=tmp_path)
    closes = [x[0] for x in con.execute("SELECT day FROM think_watch_runs_s84 WHERE mode='close' ORDER BY day").fetchall()]
    assert closes == [DAY] and r["errors"] == []                                                              # nothing logged before: only the latest session
    later = datetime(2026, 11, 5, 16, 30)
    watch.run(con, later, mode="catchup", root=tmp_path)
    want = markets.get("IN").sessions_between(DAY + timedelta(days=1), markets.get("IN").session_closed_by(later))
    closes = [x[0] for x in con.execute("SELECT day FROM think_watch_runs_s84 WHERE mode='close' ORDER BY day").fetchall()]
    assert closes == [DAY] + want and len(want) >= 3
    n = con.execute("SELECT count(*) FROM think_watch_runs_s84").fetchone()[0]
    watch.run(con, later, mode="catchup", root=tmp_path)                                                       # a gap is run once
    assert con.execute("SELECT count(*) FROM think_watch_runs_s84").fetchone()[0] == n


def _us_bars(root, sym, rets, base=100.0):
    n = 300
    r = np.array([0.004 if k % 2 else -0.004 for k in range(n)])
    r[-len(rets):] = rets
    px = base * np.cumprod(1 + r)
    days = [d.date() for d in pd.bdate_range(end=date(2026, 10, 29), periods=n)]
    p = root / "us" / "raw"
    p.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": days, "open": px, "high": px, "low": px, "close": px, "adj_close": px, "volume": 1e6, "dividend": 0.0}).to_parquet(p / f"{sym}.parquet")


def test_the_us_morning_watches_a_named_us_pick_and_the_overnight_shock_in_the_indices(con, tmp_path):
    _us_bars(tmp_path, "XYZ", [-0.12])
    con.execute("INSERT INTO picks_s83 (pick_id, market, isin, symbol, source, thesis, break_condition, state, proposed_on) VALUES (1,'US','ZZ0000000001','XYZ','system','t','b','proposed',?)", [DAYS[-5]])
    g = tmp_path / "global"
    g.mkdir()
    n = 300
    r = np.array([0.003 if k % 2 else -0.003 for k in range(n)])
    r[-1] = -0.05
    pd.DataFrame({"date": [d.date() for d in pd.bdate_range(end=date(2026, 10, 29), periods=n)], "close": 5000.0 * np.cumprod(1 + r)}).to_parquet(g / "US_SP500.parquet")
    r = watch.run(con, datetime(2026, 10, 30, 9, 0), mode="us_morning", root=tmp_path)
    assert ("ZZ0000000001", "move_1d") in _sigs(con) and ("MACRO:SP500", "overnight_shock") in _sigs(con) and r["errors"] == []
    assert con.execute("SELECT count(*) FROM think_watch_runs_s84 WHERE mode='us_morning'").fetchone()[0] == 1
    assert all(c["market"] == "US" for c in cases.open_cases(con))


def test_an_after_hours_quote_counts_as_one_more_bar(con, tmp_path):
    _us_bars(tmp_path, "XYZ", [0.001])
    con.execute("INSERT INTO picks_s83 (pick_id, market, isin, symbol, source, thesis, break_condition, state, proposed_on) VALUES (1,'US','ZZ0000000001','XYZ','system','t','b','proposed',?)", [DAYS[-5]])
    last = float(pd.read_parquet(tmp_path / "us" / "raw" / "XYZ.parquet")["close"].iloc[-1])
    watch.run(con, datetime(2026, 10, 30, 9, 0), mode="us_morning", root=tmp_path)
    assert _sigs(con) == []
    watch.run(con, datetime(2026, 10, 30, 9, 5), mode="us_morning", quotes={"XYZ": last * 0.9}, root=tmp_path)
    s = [x for x in cases.signals(con) if x["signal"] == "move_1d"][0]
    assert json.loads(s["detail_json"])["after_hours_quote"] == pytest.approx(last * 0.9)


def test_the_watch_is_off_when_the_loop_is_off_and_the_wide_watch_stays_off(con, tmp_path, monkeypatch):
    assert think.settings()["wide_watch"] is False and watch.settings()["wide_watch"] is False
    _reshape(con, BBB, [-0.05])
    monkeypatch.setattr(think, "on", lambda: False)
    assert watch.run(con, NOW, mode="close", root=tmp_path)["off"] is True and cases.signals(con) == []
    with pytest.raises(ValueError):
        watch.run(con, NOW, mode="weekly", root=tmp_path)
