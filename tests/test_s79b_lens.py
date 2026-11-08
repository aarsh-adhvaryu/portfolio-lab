"""S79b item 18D: the plug-in lens interface. Synthetic prices only; the markets calendar is the real config."""
from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from pflab import markets
from pflab.fcast import forecasters as F, plugins, protocol as P, replay, run
from pflab.hq import tools as tl
from pflab.quant import volume_profile as vp
from tests.test_s79_explain import _ctx, rt, root  # noqa: F401  (fixtures)
from tests.test_s79_forecast import NOW, con, in_sessions, walk  # noqa: F401  (fixtures)

IDX = markets.get("IN").index


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(F, "EXTERNAL_GAP", lambda *a, **k: None)
    monkeypatch.setattr(plugins, "REGISTRY", {})
    monkeypatch.setattr(plugins, "_LOADED", {"done": True})        # no built-in lens module is loaded: only the lenses a test registers
    monkeypatch.setattr(plugins, "settings", lambda: {"on": True})
    monkeypatch.setattr(plugins, "REQUIRE_REAL_SERIES", False)       # the tests run lenses on synthetic closes


def _shift_frame(shift):
    def frame(con, market, close, h):
        lc, r, sig, ew = F._vol_parts(close)
        s = F._sigma_h(sig, ew, h, False)
        return F._frame(s * 0.0 + shift * s, s)
    return frame


def _lens(name="lens_test", shift=0.5, **kw):
    return plugins.register(plugins.Lens(name, ("IN",), "docs/protocols/s79_wave_sentiment_protocol.md", _shift_frame(shift), **kw))


def feed_for(c):
    return run.Feed("IN", index_close=c, us_close=pd.Series(dtype=float), symbols={})


# --- the interface -----------------------------------------------------------------------------------------------------------------------
def test_register_names_and_the_registry():
    l = _lens()
    assert plugins.REGISTRY["lens_test"] is l and [x.name for x in plugins.active("IN")] == ["lens_test"] and plugins.active("US") == []
    for bad in ("naive", "hedge", "hedge_base", "wave"):
        with pytest.raises(ValueError):
            plugins.register(plugins.Lens(bad, ("IN",), "x", _shift_frame(0)))
    _lens(shift=0.1)                                              # again: a replace, not a second entry
    assert len(plugins.REGISTRY) == 1


def test_switch_off_means_not_there(monkeypatch):
    _lens()
    monkeypatch.setattr(plugins, "settings", lambda: {"on": False})
    assert plugins.active("IN") == [] and not plugins.is_on()


def _fill_scores(con, lens, n, with_pb, base_pb, h=1, market="IN", noise=1e-5):
    rng = np.random.default_rng(1)
    rows, i = [], 1
    ss = markets.get(market).sessions_between(date(2025, 1, 1), date(2026, 10, 30))[:n]
    for d in ss:
        for fc, pb in ((plugins.with_name(lens), with_pb), (plugins.BASE, base_pb)):
            rows.append([i, market, "live", d, d, markets.get(market).index, h, fc, 0.0, "[]", pb + rng.normal(0, noise), True, True, NOW])
            i += 1
    con.executemany("INSERT INTO forecast_scores_s79 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)


def test_admitted_needs_sixty_live_sessions_and_a_real_gain(con):
    _lens()
    _fill_scores(con, "lens_test", 59, 0.0100, 0.0110)
    assert plugins.admitted(con, "lens_test", "IN", 1) is False
    assert "59 of 60" in plugins.admission(con, "lens_test", "IN", 1)["reason"]
    con.execute("DELETE FROM forecast_scores_s79")
    _fill_scores(con, "lens_test", 70, 0.0100, 0.0110)
    a = plugins.admission(con, "lens_test", "IN", 1, log=True, now=NOW)
    assert a["admitted"] is True and a["n_live"] == 70 and a["pinball_with"] < a["pinball_without"] and a["t"] >= a["bar"]
    assert plugins.admitted(con, "lens_test", "IN", 1) is True
    assert con.execute("SELECT count(*) FROM lens_admission").fetchone()[0] == 0        # no forecast made yet: nothing to date the row by
    con.execute("DELETE FROM forecast_scores_s79")
    _fill_scores(con, "lens_test", 70, 0.0110, 0.0100)                 # worse with it
    assert plugins.admitted(con, "lens_test", "IN", 1) is False
    con.execute("DELETE FROM forecast_scores_s79")
    _fill_scores(con, "lens_test", 70, 0.0100, 0.0110)
    assert plugins.admitted(con, "lens_test", "US", 1) is False         # not its market
    assert plugins.admitted(con, "lens_unknown", "IN", 1) is False


def test_a_replay_is_never_counted_toward_admission(con):
    _lens()
    _fill_scores(con, "lens_test", 70, 0.0100, 0.0110)
    con.execute("UPDATE forecast_scores_s79 SET source='replay'")
    assert plugins.admitted(con, "lens_test", "IN", 1) is False


# --- live: in the tables, out of the hedge until admitted -------------------------------------------------------------------------------------
def _q(con, fc, h=5, source="live", last=True):
    r = con.execute("SELECT quantiles_json FROM forecasts_s79 WHERE forecaster=? AND horizon_sessions=? AND source=? AND subject=? ORDER BY as_of "
                    + ("DESC " if last else "") + "LIMIT 1", [fc, h, source, IDX]).fetchone()
    return None if r is None else {float(k): v for k, v in json.loads(r[0]).items()}


def test_a_lens_is_in_the_forecast_tables_but_not_in_the_hedge_until_admitted(con, monkeypatch):
    _lens(shift=0.8)
    ss = in_sessions(date(2025, 6, 2))
    c = walk(ss, vol=0.012)
    run.catch_up(con, "IN", ss[-1], NOW, feed_for(c), max_back=6)
    names = {r[0] for r in con.execute("SELECT DISTINCT forecaster FROM forecasts_s79 WHERE source='live'").fetchall()}
    assert {"lens_test", "hedge+lens_test", "hedge_base", "hedge"} <= names
    base, hedge, with_l, lens_q = _q(con, "hedge_base"), _q(con, "hedge"), _q(con, "hedge+lens_test"), _q(con, "lens_test")
    assert hedge == base                                                   # shadow: the combined forecast is the code forecasters' alone
    assert with_l != base and lens_q[0.5] > base[0.5]                       # the lens does something, and it is visible in its own rows
    assert sorted(lens_q) == list(P.LEVELS) and all(a <= b for a, b in zip(sorted(lens_q.values()), sorted(lens_q.values())[1:]))
    meta = json.loads(con.execute("SELECT meta_json FROM forecasts_s79 WHERE forecaster='hedge' AND source='live' ORDER BY as_of DESC LIMIT 1").fetchone()[0])
    assert meta["lenses"]["lens_test"]["admitted"] is False and meta["admitted"] == []
    # scored like any forecaster
    assert con.execute("SELECT count(*) FROM forecast_scores_s79 WHERE forecaster='lens_test' AND source='live'").fetchone()[0] > 0
    # the same lens, now admitted: the hedge is the hedge-with-the-lens
    con2 = con
    con2.execute("DELETE FROM forecast_scores_s79")
    con2.execute("DELETE FROM forecasts_s79")
    monkeypatch.setattr(plugins, "admitted", lambda *a, **k: True)
    run.catch_up(con2, "IN", ss[-1], NOW, feed_for(c), max_back=6)
    h2, w2, b2 = _q(con2, "hedge"), _q(con2, "hedge+lens_test"), _q(con2, "hedge_base")
    assert h2 == w2 and h2 != b2


def test_lens_weights_are_learned_beside_the_code_forecasters_and_leave_theirs_alone(con):
    _lens(shift=0.3)
    ss = in_sessions(date(2025, 6, 2))
    c = walk(ss, vol=0.012)
    run.catch_up(con, "IN", ss[-1], NOW, feed_for(c), max_back=30)
    src = {r[0] for r in con.execute("SELECT DISTINCT source FROM forecaster_weights").fetchall()}
    assert "live+lens_test" in src and "live" in src
    plain = {r[0] for r in con.execute("SELECT DISTINCT forecaster FROM forecaster_weights WHERE source='live'").fetchall()}
    assert "lens_test" not in plain and plain <= set(P.FORECASTERS)
    w = con.execute("SELECT forecaster, weight FROM forecaster_weights WHERE source='live+lens_test' AND horizon_sessions=1 "
                    "AND as_of=(SELECT max(as_of) FROM forecaster_weights WHERE source='live+lens_test' AND horizon_sessions=1)").fetchall()
    assert "lens_test" in {a for a, _ in w} and sum(b for _, b in w) == pytest.approx(1.0) and min(b for _, b in w) >= P.FLOOR - 1e-9
    # the plain weights are what they were without any lens
    plugins.REGISTRY.clear()
    other = pd.Series(c.values, index=c.index)
    import duckdb
    from pflab.pm import store
    c2 = duckdb.connect(":memory:")
    store.migrate(c2)
    run.catch_up(c2, "IN", ss[-1], NOW, feed_for(other), max_back=30)
    a = dict(con.execute("SELECT forecaster, weight FROM forecaster_weights WHERE source='live' AND horizon_sessions=1 AND as_of=(SELECT max(as_of) FROM forecaster_weights "
                         "WHERE source='live' AND horizon_sessions=1)").fetchall())
    b = dict(c2.execute("SELECT forecaster, weight FROM forecaster_weights WHERE source='live' AND horizon_sessions=1 AND as_of=(SELECT max(as_of) FROM forecaster_weights "
                        "WHERE source='live' AND horizon_sessions=1)").fetchall())
    assert a.keys() == b.keys() and all(a[k] == pytest.approx(b[k]) for k in a)


def test_a_broken_lens_does_not_stop_the_forecasts(con):
    def boom(*a, **k):
        raise RuntimeError("no")
    plugins.register(plugins.Lens("lens_bad", ("IN",), "x", boom))
    ss = in_sessions(date(2025, 6, 2))
    r = run.catch_up(con, "IN", ss[-1], NOW, feed_for(walk(ss)), max_back=3)
    assert r["sessions_done"] and con.execute("SELECT count(*) FROM forecasts_s79 WHERE forecaster='hedge'").fetchone()[0] > 0
    assert con.execute("SELECT count(*) FROM forecasts_s79 WHERE forecaster='lens_bad'").fetchone()[0] == 0


def test_the_hedge_is_untouched_with_no_lens(con):
    ss = in_sessions(date(2025, 6, 2))
    run.catch_up(con, "IN", ss[-1], NOW, feed_for(walk(ss)), max_back=3)
    assert con.execute("SELECT count(*) FROM forecasts_s79 WHERE forecaster IN ('hedge_base') OR forecaster LIKE 'hedge+%' OR forecaster LIKE 'lens_%'").fetchone()[0] == 0


# --- replay --------------------------------------------------------------------------------------------------------------------------------------
def _replay_series():
    ss = markets.get("IN").sessions_between(date(2018, 1, 1), date(2021, 12, 31))
    return walk(ss, seed=4, vol=0.01)


def test_replay_runs_replay_ok_lenses_skips_forward_only_ones_and_stays_in_2012_2021(con):
    _lens("lens_ok", 0.2)
    _lens("lens_fwd", 0.2, replay_ok=False)
    c = _replay_series()
    out = replay.replay(con, "IN", date(2019, 1, 1), date(2021, 12, 31), close=c, us_close=None, now=NOW)
    lb = out["horizons"]["5"]["lenses"]
    assert lb["lens_ok"]["n"] > 100 and "skipped" in lb["lens_fwd"] and "never evidence" in lb["lens_ok"]["note"]
    fcs = {r[0] for r in con.execute("SELECT DISTINCT forecaster FROM forecasts_s79 WHERE source='replay'").fetchall()}
    assert {"lens_ok", "hedge+lens_ok"} <= fcs and "lens_fwd" not in fcs
    assert con.execute("SELECT count(*) FROM forecast_scores_s79 WHERE source='replay' AND forecaster='lens_ok'").fetchone()[0] > 100
    assert con.execute("SELECT max(as_of) FROM forecasts_s79 WHERE source='replay'").fetchone()[0] <= date(2021, 12, 31)
    assert con.execute("SELECT count(*) FROM forecast_scores_s79 WHERE source='live'").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM forecaster_weights WHERE source='replay+lens_ok'").fetchone()[0] > 0
    assert not plugins.admitted(con, "lens_ok", "IN", 5)
    # a second run replaces, not doubles
    replay.replay(con, "IN", date(2019, 1, 1), date(2021, 12, 31), close=c, us_close=None, now=NOW)
    n1 = con.execute("SELECT count(*) FROM forecasts_s79 WHERE source='replay' AND forecaster='lens_ok'").fetchone()[0]
    assert n1 == con.execute("SELECT count(*) FROM forecast_scores_s79 WHERE source='replay' AND forecaster='lens_ok'").fetchone()[0]


def test_replay_refuses_the_spent_years_with_lenses_too(con):
    _lens()
    c = _replay_series()
    for bad in ({"start": date(2022, 1, 3), "end": date(2022, 6, 30)}, {"start": date(2020, 1, 1), "end": date(2023, 1, 1)}):
        with pytest.raises(ValueError):
            replay.replay(con, "IN", close=c, us_close=None, write=False, **bad)


# --- the tools ------------------------------------------------------------------------------------------------------------------------------------
def test_lenses_tool_works_with_no_arguments_and_shows_the_state(rt, con):
    _lens()
    assert tl.TOOLS["lenses"].kind == "read"
    out = json.loads(tl.run(_ctx(rt), "lenses", {})[0])
    assert out["call_ref"] is not None and out["on"] is True and out["lenses"][0]["lens"] == "lens_test"
    h = out["lenses"][0]["horizons"]["5"]
    assert h["state"] == "shadow" and h["n_live"] == 0 and "0 of 60" in h["reason"] and h["weight"] is None and out["lenses"][0]["protocol"].endswith("protocol.md")


def test_lenses_tool_reports_scores_weights_and_the_off_switch(rt, con, monkeypatch):
    _lens(shift=0.3)
    ss = in_sessions(date(2025, 6, 2))
    run.catch_up(con, "IN", ss[-1], NOW, feed_for(walk(ss, vol=0.012)), max_back=30)
    h = json.loads(tl.run(_ctx(rt), "lenses", {"market": "IN"})[0])["lenses"][0]["horizons"]["1"]
    assert h["n_live"] > 5 and h["pinball_vs_naive_live"] > 0 and h["weight"] and h["state"] == "shadow"
    monkeypatch.setattr(plugins, "settings", lambda: {"on": False})
    assert json.loads(tl.run(_ctx(rt), "lenses", {})[0]).get("off") is True


# --- lens_value_area ----------------------------------------------------------------------------------------------------------------------------
def _daily_for(c):
    return pd.DataFrame({"date": c.index, "open": c.values, "high": c.values * 1.004, "low": c.values * 0.996, "close": c.values, "volume": 1.0, "basis": vp.B_TIME})


def test_lens_value_area_is_registered_in_shadow(monkeypatch):
    vp.register_lens()
    l = plugins.REGISTRY["lens_value_area"]
    assert l.replay_ok and "IN" in l.markets and l.protocol == "docs/protocols/s79_wave_sentiment_protocol.md" and plugins.active("IN")


def test_lens_value_area_frame_is_ordered_point_in_time_and_none_without_data(monkeypatch):
    ss = markets.get("IN").sessions_between(date(2023, 1, 2), date(2026, 10, 30))
    c = walk(ss, seed=9, vol=0.01)
    c.name = None
    monkeypatch.setattr(vp, "_daily", lambda *a, **k: _daily_for(c))
    vp._CACHE.clear()
    vp._EV.clear()
    fr = vp.lens_frame(None, "IN", c, 5)
    ok = fr.dropna()
    assert len(ok) > 400 and (np.diff(ok.to_numpy(float), axis=1) > 0).all()
    # point in time: rows before a cut are the same whether or not the later closes exist
    n = 700
    cut = c.iloc[:n]
    monkeypatch.setattr(vp, "_daily", lambda *a, **k: _daily_for(c).iloc[:n])
    vp._CACHE.clear()
    vp._EV.clear()
    fr2 = vp.lens_frame(None, "IN", cut, 5)
    pd.testing.assert_frame_equal(fr.iloc[:n], fr2, check_exact=False, rtol=1e-9, atol=1e-12)
    # no daily bars, or a different series: no forecast, never a guess
    monkeypatch.setattr(vp, "_daily", lambda *a, **k: pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "basis"]))
    vp._CACHE.clear()
    assert vp.lens_frame(None, "IN", c, 5) is None
    monkeypatch.setattr(vp, "_daily", lambda *a, **k: _daily_for(c * 3.0))
    vp._CACHE.clear()
    vp._EV.clear()
    assert vp.lens_frame(None, "IN", c, 5) is None


def test_lens_value_area_off_switch(monkeypatch):
    ss = markets.get("IN").sessions_between(date(2023, 1, 2), date(2026, 10, 30))
    c = walk(ss, seed=9)
    monkeypatch.setattr(vp, "_daily", lambda *a, **k: _daily_for(c))
    vp._CACHE.clear()
    monkeypatch.setattr(vp, "lens_settings", lambda: {"on": False, "shrink_n": 60.0, "max_shift_sigma": 0.15, "history_sessions": 3000})
    assert vp.lens_frame(None, "IN", c, 5) is None


def test_the_shift_is_capped_and_shrunk(monkeypatch):
    ss = markets.get("IN").sessions_between(date(2022, 1, 3), date(2026, 10, 30))
    c = walk(ss, seed=2, vol=0.01)
    monkeypatch.setattr(vp, "_daily", lambda *a, **k: _daily_for(c))
    vp._CACHE.clear()
    vp._EV.clear()
    fr = vp.lens_frame(None, "IN", c, 5).dropna()
    lc, r, sig, ew = F._vol_parts(c)
    base = F._frame(sig * 0.0, F._sigma_h(sig, ew, 5, False)).reindex(fr.index)
    mid = np.log1p(fr[0.5]) - np.log1p(base[0.5])
    s5 = F._sigma_h(sig, ew, 5, False).reindex(fr.index)
    assert (mid.abs() <= 0.15 * s5 + 1e-12).all()


# --- the agenda kind ----------------------------------------------------------------------------------------------------------------------------
def test_propose_lens_drafts_a_protocol_stub_only(con, tmp_path, monkeypatch):
    from pflab.agenda import kinds, propose_lens as pl
    assert "propose_lens" in kinds.names()
    monkeypatch.setattr(pl, "stub_dir", lambda: tmp_path / "lens_candidates")
    cands = pl._produce(con, "IN", NOW)
    assert len(cands) == 1 and cands[0]["subject"].startswith("lens:lens_")
    rt = SimpleNamespace(cursor=lambda: con)
    res = pl._work(rt, {"market": "IN", "payload": cands[0]["payload"]}, NOW)
    assert res["useful"] is False and "stub filed" in res["outcome"]
    files = list((tmp_path / "lens_candidates").glob("*.md"))
    assert len(files) == 1
    txt = files[0].read_text(encoding="utf-8")
    assert "STUB" in txt and "NOT registered, no code, not live" in txt and "def " not in txt and "import " not in txt
    assert con.execute("SELECT status FROM lens_candidates").fetchone()[0] == "stub"
    again = pl._work(rt, {"market": "IN", "payload": cands[0]["payload"]}, NOW)
    assert "skip" in again
    nxt = pl._produce(con, "IN", NOW)
    assert all(c["payload"]["name"] != cands[0]["payload"]["name"] for c in nxt)
    monkeypatch.setattr(plugins, "settings", lambda: {"on": False})
    assert pl._produce(con, "IN", NOW) == []


def test_the_migrations_exist(con):
    for t in ("lens_admission", "lens_candidates"):
        con.execute(f"SELECT * FROM {t} LIMIT 1")


def test_lenses_do_not_run_on_a_series_that_is_not_the_markets_own(con, monkeypatch):
    monkeypatch.setattr(plugins, "REQUIRE_REAL_SERIES", True)
    plugins._REAL.clear()
    _lens()
    ss = in_sessions(date(2025, 6, 2))
    c = walk(ss, vol=0.012)                                           # synthetic: not the Nifty file's series
    assert plugins.is_market_series("IN", c) is False
    run.catch_up(con, "IN", ss[-1], NOW, feed_for(c), max_back=3)
    assert con.execute("SELECT count(*) FROM forecasts_s79 WHERE forecaster='lens_test' OR forecaster='hedge_base'").fetchone()[0] == 0
    real = pd.Series([100.0, 101.0, 102.0], index=pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"]))
    import pflab.fcast.run as R
    monkeypatch.setattr(R, "load_series", lambda market, root=None: real)
    plugins._REAL.clear()
    assert plugins.is_market_series("IN", real * 1.001) is True
