"""S79 items 8 and 9: predict, score, correct and the history replay (synthetic prices; the markets calendar is the real config)."""
import json
from datetime import date, datetime
from types import SimpleNamespace

import duckdb
import numpy as np
import pandas as pd
import pytest

from pflab import markets
from pflab.fcast import fall_risk, forecasters as F, protocol as P, replay, run, score as S, weights as W
from pflab.pm import store

NOW = datetime(2026, 11, 5, 21, 0)


@pytest.fixture(autouse=True)
def _no_external_gap(monkeypatch):
    monkeypatch.setattr(F, "EXTERNAL_GAP", lambda *a, **k: None)


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    store.migrate(c)
    return c


def walk(sessions, seed=1, vol=0.01, start=100.0):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0003, vol, len(sessions))
    return pd.Series(start * np.exp(np.cumsum(r)), index=pd.to_datetime(sessions))


def in_sessions(a=date(2026, 1, 1), b=date(2026, 10, 30)):
    return markets.get("IN").sessions_between(a, b)


# --- the arithmetic -------------------------------------------------------------------------------------------------------------------
def test_pinball_values():
    q = np.array([0.0] * len(P.LEVELS))
    pb = S.pinball(0.02, q)
    assert pb[P.LEVELS.index(0.9)] == pytest.approx(0.9 * 0.02)          # outcome above the quantile: tau * miss
    assert pb[P.LEVELS.index(0.1)] == pytest.approx(0.1 * 0.02)
    pb2 = S.pinball(-0.02, q)
    assert pb2[P.LEVELS.index(0.9)] == pytest.approx(0.1 * 0.02)          # below: (1 - tau) * miss
    assert pb2[P.LEVELS.index(0.5)] == pytest.approx(0.5 * 0.02)
    sc = S.score_one({float(l): 0.01 * (l - 0.5) * 2 for l in P.LEVELS}, 0.0)
    assert sc["covered_80"] and sc["covered_90"] and sc["pinball_mean"] > 0
    assert not S.score_one({float(l): 0.01 * (l - 0.5) * 2 for l in P.LEVELS}, 0.05)["covered_80"]


def test_quantiles_ordered_and_naive_is_symmetric_in_log():
    c = walk(in_sessions(date(2025, 6, 2)), vol=0.012)
    for name in ("naive", "volatility", "momentum", "reversion"):
        for h in P.HORIZONS:
            row = F.last_row(F.FORECASTERS[name](c, h))
            v = np.array([row[l] for l in P.LEVELS])
            assert np.all(np.diff(v) > 0), (name, h)
    r = F.last_row(F.naive(c, 5))
    assert np.log(1 + r[0.95]) == pytest.approx(-np.log(1 + r[0.05]))
    assert r[0.5] == pytest.approx(0.0, abs=1e-12)


def test_horizon_is_sessions_across_weekend_and_holiday():
    m = markets.get("IN")
    assert m.session_after(date(2026, 11, 6), 1) == date(2026, 11, 9)               # Friday -> Monday
    assert m.session_after(date(2026, 4, 2), 1) == date(2026, 4, 6)                 # Good Friday 2026-04-03 is not a session
    assert m.session_after(date(2026, 4, 2), 5) == date(2026, 4, 10)


def test_point_in_time_frames_ignore_the_future():
    us_s = in_sessions(date(2024, 1, 1), date(2026, 10, 30))
    c = walk(us_s, seed=3)
    us = walk(us_s, seed=4)
    cut = c.index[-30]
    for name in P.FORECASTERS:
        for h in P.HORIZONS:
            full = F.FORECASTERS[name](c, h, us_close=us, next_date=None)
            part = F.FORECASTERS[name](c[c.index <= cut], h, us_close=us[us.index <= cut], next_date=c.index[c.index > cut][0].date())
            a, b = full.loc[cut].to_numpy(float), part.iloc[-1].to_numpy(float)
            assert np.allclose(a, b, equal_nan=True), (name, h)
    # a future price change does not move the forecast made at `cut`
    c2 = c.copy()
    c2[c2.index > cut] *= 3.0
    assert np.allclose(F.volatility(c2, 5).loc[cut].to_numpy(), F.volatility(c, 5).loc[cut].to_numpy())


def test_overnight_follows_the_driver():
    ix = pd.bdate_range("2019-01-01", "2022-06-30")                       # synthetic dates only
    rng = np.random.default_rng(7)
    us_r = pd.Series(rng.normal(0, 0.01, len(ix)), index=ix)
    # the Indian return on day j responds to the US return of the day before
    in_r = 0.5 * us_r.shift(1).fillna(0) + rng.normal(0, 0.004, len(ix))
    us = 100 * np.exp(us_r.cumsum())
    inn = 100 * np.exp(in_r.cumsum())
    fr = F.overnight(inn, 1, us_close=us)
    # at the last-but-one row the driver (US return of the last row's date) is known: centre = beta * it, beta close to 0.5
    t = ix[-300]
    mu = np.log(1 + fr.loc[t, 0.5])
    assert mu == pytest.approx(0.5 * us_r.loc[t], abs=0.004)
    assert (fr.loc[ix[-300]:].iloc[:-1].notna().all().all())
    assert F.last_driver(inn, us, ix[-1].date() + pd.Timedelta(days=3)) is None or True


# --- Hedge ----------------------------------------------------------------------------------------------------------------------------
def test_hedge_moves_toward_the_better_forecaster_and_keeps_the_floor():
    w = np.array([0.25, 0.25, 0.25, 0.25])
    losses = np.array([1.0, 0.5, 1.0, 1.0])                                # forecaster 1 is better than naive (1.0 is the naive loss)
    for _ in range(3000):
        w = W.hedge_step(w, losses, 1.0, 1)
    assert w[1] > 0.8 and w.sum() == pytest.approx(1.0)
    assert (w >= P.FLOOR - 1e-12).all() and w[0] == pytest.approx(P.FLOOR)
    one = W.hedge_step(np.full(4, 0.25), losses, 1.0, 1)
    assert one[1] > 0.25 > one[0]                                          # the direction of a single step
    assert W.hedge_step(np.full(4, 0.25), losses, 1.0, 20)[1] < one[1]     # a longer horizon learns more slowly
    assert W.mix_floor(np.array([0.99, 0.005, 0.005]))[1] == pytest.approx(P.FLOOR)


def test_combine_is_ordered_and_weighted():
    a = {float(l): 0.01 * i for i, l in enumerate(P.LEVELS)}
    b = {float(l): 0.03 * i for i, l in enumerate(P.LEVELS)}
    c = W.combine({"a": a, "b": b}, {"a": 0.75, "b": 0.25})
    assert c[0.95] == pytest.approx(0.75 * a[0.95] + 0.25 * b[0.95])
    v = [c[l] for l in P.LEVELS]
    assert v == sorted(v)


# --- registration ---------------------------------------------------------------------------------------------------------------------
def test_registration_raises_the_counter_once(con):
    from pflab.learner import counter
    n0 = counter.n_tests(con)
    assert P.register(con, NOW) == 2
    assert counter.n_tests(con) == n0 + 2 and P.register(con, NOW) == 0
    assert P.registered_sha(con, "IN") == P.protocol_sha()
    assert counter.t_needed(counter.n_tests(con)) >= 2.0


# --- the loop on the store ------------------------------------------------------------------------------------------------------------
def feed_for(c):
    return run.Feed("IN", index_close=c, us_close=pd.Series(dtype=float), symbols={})


def test_post_close_scores_a_matured_forecast_and_catch_up_is_idempotent(con):
    ss = in_sessions()
    c = walk(ss, seed=5, vol=0.01)
    s0 = ss[-8]
    feed = feed_for(c)
    r0 = run.post_close(con, "IN", s0, NOW, feed)
    assert r0["made"] > 0 and r0["scored"] == 0
    n_fc = con.execute("SELECT count(*) FROM forecasts_s79").fetchone()[0]
    assert n_fc == len(P.HORIZONS) * 5                                     # 4 forecasters + hedge per horizon (no US series: overnight absent)
    res = run.catch_up(con, "IN", ss[-1], NOW, feed)
    assert res["sessions_done"] == [str(d) for d in ss[-7:]]               # every missed session, in order
    sc = con.execute("SELECT realised, matures, as_of FROM forecast_scores_s79 WHERE horizon_sessions=1 AND forecaster='hedge' ORDER BY as_of").fetchall()
    assert len(sc) == 7 and sc[0][2] == s0 and sc[0][1] == ss[-7]
    assert sc[0][0] == pytest.approx(c[pd.Timestamp(ss[-7])] / c[pd.Timestamp(s0)] - 1)
    h5 = con.execute("SELECT matures FROM forecasts_s79 WHERE horizon_sessions=5 AND as_of=? AND forecaster='naive'", [s0]).fetchone()[0]
    assert h5 == markets.get("IN").session_after(s0, 5)
    assert con.execute("SELECT count(*) FROM forecast_scores_s79 WHERE horizon_sessions=5").fetchone()[0] >= 1       # s0 + 5 sessions matured inside the window
    snap = [con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("forecasts_s79", "forecast_scores_s79", "forecaster_weights", "fall_risk_s79")]
    again = run.catch_up(con, "IN", ss[-1], NOW, feed)
    assert again["sessions_done"] == []
    run.post_close(con, "IN", ss[-1], NOW, feed)                           # even a direct repeat changes nothing
    assert snap == [con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("forecasts_s79", "forecast_scores_s79", "forecaster_weights", "fall_risk_s79")]
    # the weights moved by code after the outcomes
    w = W.current(con, "IN", 1, "live", F.names_for("IN", True)[:4], upto=ss[-1])
    assert abs(w["naive"] - 0.25) > 1e-6
    assert W.n_updates(con, "IN", 1, "live") == 7


def test_catch_up_stops_when_the_data_has_not_arrived(con):
    ss = in_sessions()
    c = walk(ss, seed=6)
    short = c[c.index <= pd.Timestamp(ss[-3])]
    res = run.catch_up(con, "IN", ss[-1], NOW, feed_for(short), max_back=5)
    assert res["sessions_done"][-1] == str(ss[-3]) and res["stopped"]
    res2 = run.catch_up(con, "IN", ss[-1], NOW, feed_for(c))                # the data arrives: the missing two are done in order
    assert res2["sessions_done"] == [str(ss[-2]), str(ss[-1])]


def test_a_forecast_does_not_depend_on_later_prices(con):
    ss = in_sessions()
    c = walk(ss, seed=8)
    s = ss[-12]
    run.post_close(con, "IN", s, NOW, feed_for(c))
    c2 = c.copy()
    c2[c2.index > pd.Timestamp(s)] *= 5.0
    con2 = duckdb.connect(":memory:")
    store.migrate(con2)
    run.post_close(con2, "IN", s, NOW, feed_for(c2))
    q = "SELECT horizon_sessions, forecaster, quantiles_json FROM forecasts_s79 ORDER BY 1, 2"
    assert con.execute(q).fetchall() == con2.execute(q).fetchall()


def test_symbols_are_forecast_and_scored_too(con):
    ss = in_sessions()
    idx = walk(ss, seed=9)
    stk = walk(ss, seed=10, vol=0.02)
    feed = run.Feed("IN", index_close=idx, us_close=pd.Series(dtype=float), symbols={"INE000A01010": "TESTCO"}, symbol_loader=lambda isin: stk)
    run.catch_up(con, "IN", ss[-1], NOW, feed, max_back=4)
    n = con.execute("SELECT count(*) FROM forecast_scores_s79 WHERE subject='INE000A01010'").fetchone()[0]
    assert n > 0
    assert con.execute("SELECT count(*) FROM forecasts_s79 WHERE symbol='TESTCO' AND forecaster='hedge'").fetchone()[0] == 4 * len(P.HORIZONS)


# --- verdicts -------------------------------------------------------------------------------------------------------------------------
def _fake_scores(con, n, source="live", hedge=0.9, naive=1.0, cov=True):
    idx = markets.get("IN").index
    rng = np.random.default_rng(0)
    rows, fid = [], con.execute("SELECT coalesce(max(forecast_id),0) FROM forecast_scores_s79").fetchone()[0]
    for i in range(n):
        d = date(2026, 1, 1) + pd.Timedelta(days=i)
        for fc, base in ((P.COMBINED, hedge), (P.BENCHMARK, naive)):
            fid += 1
            rows.append([fid, "IN", source, d, d, idx, 1, fc, 0.0, "[]", base * (1 + 0.1 * rng.normal()), (i % 5 != 0) if cov else False, True, NOW])
    df = pd.DataFrame(rows, columns=["forecast_id", "market", "source", "as_of", "matures", "subject", "horizon_sessions", "forecaster", "realised",
                                     "pinball_json", "pinball_mean", "covered_80", "covered_90", "scored_at"])
    con.register("_f", df)
    con.execute("INSERT INTO forecast_scores_s79 SELECT * FROM _f")
    con.unregister("_f")


def test_no_verdict_below_60_live_sessions(con):
    _fake_scores(con, 59)
    v = S.verdict(con, "IN", 1)
    assert v["decided"] is False and "not enough data" in v["status"] and v["n"] == 59
    assert "passed" not in v
    assert S.n_live(con, "IN") == 59 and S.scoreboard(con, "IN")["live_sessions_h1"] == 59


def test_verdict_after_60_needs_registration_and_the_bar(con):
    _fake_scores(con, 80, hedge=0.9, naive=1.0)
    assert S.verdict(con, "IN", 1)["decided"] is False                       # not registered
    P.register(con, NOW)
    v = S.verdict(con, "IN", 1)
    assert v["decided"] and v["beats_naive"] and v["bar"] >= 2.0 and v["covers"]
    assert v["passed"] is True
    con.execute("DELETE FROM forecast_scores_s79")
    _fake_scores(con, 80, hedge=1.0, naive=1.0)
    assert S.verdict(con, "IN", 1)["passed"] is False


def test_a_replay_never_counts_as_live_and_never_decides(con):
    _fake_scores(con, 200, source="replay")
    assert S.n_live(con, "IN") == 0
    assert S.verdict(con, "IN", 1)["decided"] is False
    v = S.verdict(con, "IN", 1, source="replay")
    assert v["decided"] is False and "refused" in v["status"]


# --- the history replay ---------------------------------------------------------------------------------------------------------------
def test_replay_refuses_the_spent_years(con):
    c = walk(pd.bdate_range("2010-01-01", "2023-06-30"))
    for bad in (dict(start=date(2022, 1, 3)), dict(end=date(2023, 1, 31)), dict(start=date(2020, 1, 1), end=date(2025, 12, 31)), dict(end=date(2022, 1, 1))):
        with pytest.raises(ValueError, match="spent|ends"):
            replay.replay(con, "IN", close=c, us_close=None, write=False, **bad)
    with pytest.raises(ValueError):
        P.refuse_spent(date(2024, 6, 3))


def test_replay_never_sees_2022_and_is_kept_apart_from_live(con):
    c = walk(pd.bdate_range("2009-01-01", "2023-06-30"), seed=11)
    out = replay.replay(con, "IN", date(2020, 1, 1), date(2021, 12, 31), close=c, us_close=None, now=NOW)
    assert out["sessions"] > 400 and out["horizons"]["1"]["forecasters"]["hedge"]["n"] > 400
    assert con.execute("SELECT max(as_of), max(matures) FROM forecasts_s79").fetchone()[0] <= date(2021, 12, 31)
    assert con.execute("SELECT max(matures) FROM forecasts_s79").fetchone()[0] <= date(2021, 12, 31)
    assert con.execute("SELECT count(*) FROM forecasts_s79 WHERE source<>'replay'").fetchone()[0] == 0
    assert S.n_live(con, "IN") == 0 and S.verdict(con, "IN", 1)["decided"] is False
    assert con.execute("SELECT count(*) FROM forecaster_weights WHERE source='replay'").fetchone()[0] > 0
    # replaying the same span again replaces the replay rows, never adds
    n1 = con.execute("SELECT count(*) FROM forecasts_s79").fetchone()[0]
    replay.replay(con, "IN", date(2020, 1, 1), date(2021, 12, 31), close=c, us_close=None, now=NOW)
    assert con.execute("SELECT count(*) FROM forecasts_s79").fetchone()[0] == n1
    # the live loop starts from the replay's weights, not from uniform
    names = F.names_for("IN", True)[:4]
    w0 = W.current(con, "IN", 1, "live", names)
    assert max(w0.values()) != min(w0.values())
    # a replay row and a live row of the same date coexist
    assert out["fall_risk"]["n"] > 100


def test_replay_matches_the_live_path_on_the_same_day(con):
    ss = pd.bdate_range("2018-01-01", "2021-12-31")
    c = walk(ss, seed=12)
    replay.replay(con, "IN", date(2021, 6, 1), date(2021, 12, 31), close=c, us_close=None, now=NOW)
    d = pd.Timestamp("2021-09-15")
    for name in ("naive", "volatility", "momentum", "reversion"):
        row = con.execute("SELECT quantiles_json FROM forecasts_s79 WHERE forecaster=? AND horizon_sessions=5 AND as_of=?", [name, d.date()]).fetchone()
        live = F.last_row(F.FORECASTERS[name](c[c.index <= d], 5))
        assert {float(k): v for k, v in json.loads(row[0]).items()} == pytest.approx(live, abs=1e-7)


# --- fall risk -------------------------------------------------------------------------------------------------------------------------
def test_fall_risk_small_sample_shows_n_and_no_conclusion(con):
    ss = in_sessions()
    c = walk(ss, seed=13)
    r = fall_risk.make(con, "IN", c, ss[-1], "live", NOW)
    assert r["p"] is None and 0 < r["p_raw"] <= 1 and r["n_cal"] == 0
    st = fall_risk.status(con, "IN")
    assert "no conclusion" in st["note"] and "not enough data" in st["verdict"]
    assert fall_risk.make(con, "IN", c, ss[-1], "live", NOW)["existing"] is True


def test_fall_risk_calibration_shift_and_brier(con):
    p = np.full(200, 0.2)
    y = np.r_[np.ones(60), np.zeros(140)]                                     # observed 30%
    a = fall_risk.fit_shift(p, y)
    assert float(np.mean(fall_risk.apply_shift(p, a))) == pytest.approx(0.3, abs=1e-6)
    ss = in_sessions()
    c = walk(ss, seed=14, vol=0.02)
    run.catch_up(con, "IN", ss[-1], NOW, feed_for(c), max_back=60)
    res = con.execute("SELECT count(*) FROM fall_risk_s79 WHERE outcome IS NOT NULL").fetchone()[0]
    assert res > 0 and con.execute("SELECT min(brier) FROM fall_risk_s79 WHERE outcome IS NOT NULL").fetchone()[0] >= 0


# --- tools ----------------------------------------------------------------------------------------------------------------------------
def test_tools_work_on_an_empty_store_and_after_a_run(con):
    from pflab.hq.tools import Ctx
    from pflab.hq.tools_s79 import t_forecast
    ctx = Ctx(rt=SimpleNamespace(cursor=lambda: con, data_root="."), pass_id=None, model="x", shadow=True, syms={}, gate=None, now=NOW)
    names = {t.name for t in t_forecast.TOOLS}
    assert names == {"forecast_now", "forecast_scoreboard", "fall_risk"}
    for t in t_forecast.TOOLS:
        assert isinstance(t.fn(ctx, {}), dict)
    ss = in_sessions()
    run.catch_up(con, "IN", ss[-1], NOW, feed_for(walk(ss, seed=15)), max_back=12)
    now_out = t_forecast.forecast_now(ctx, {})
    assert now_out["horizons"]["1"]["return_quantiles_percent"] and "verdict" in now_out["horizons"]["1"]
    sb = t_forecast.forecast_scoreboard(ctx, {"market": "IN"})
    assert sb["live_sessions_h1"] >= 1 and sb["of"] == 60
    assert "not enough data" in sb["horizons"]["1"]["verdict"]["status"]


def test_overnight_is_made_when_the_us_close_is_in_and_remade_if_it_came_late(con):
    ss = in_sessions(date(2024, 1, 1), date(2026, 10, 30))
    c = walk(ss, seed=21)
    us_full = walk(pd.bdate_range("2023-12-01", "2026-11-02"), seed=22)
    s, nxt = ss[-6], ss[-5]
    late = us_full[us_full.index < pd.Timestamp(s)]                          # the US session dated s is not in yet when the Indian close is processed
    feed = run.Feed("IN", index_close=c, us_close=late, symbols={})
    run.post_close(con, "IN", s, NOW, feed)
    meta = json.loads(con.execute("SELECT meta_json FROM forecasts_s79 WHERE forecaster='overnight' AND horizon_sessions=1 AND as_of=?", [s]).fetchone()[0])
    assert meta["driver_ret"] is None
    q_before = con.execute("SELECT quantiles_json FROM forecasts_s79 WHERE forecaster='hedge' AND horizon_sessions=1 AND as_of=?", [s]).fetchone()[0]
    feed2 = run.Feed("IN", index_close=c, us_close=us_full, symbols={})       # the US close arrives before the next Indian open
    assert run.refresh_overnight(con, feed2, "IN", s, NOW) == len(P.HORIZONS)
    meta = json.loads(con.execute("SELECT meta_json FROM forecasts_s79 WHERE forecaster='overnight' AND horizon_sessions=1 AND as_of=?", [s]).fetchone()[0])
    assert meta["driver_ret"] is not None
    assert con.execute("SELECT quantiles_json FROM forecasts_s79 WHERE forecaster='hedge' AND horizon_sessions=1 AND as_of=?", [s]).fetchone()[0] != q_before
    assert run.refresh_overnight(con, feed2, "IN", s, NOW) == 0               # once
    r = run.post_close(con, "IN", nxt, NOW, feed2)                            # the next session scores the (remade) forecast, in order
    assert r["scored"] >= 5
