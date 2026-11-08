"""S79b item 15: macro attribution, waves, rotation, crude falls and the wave lens. Synthetic data only."""
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import duckdb
import numpy as np
import pandas as pd
import pytest

from pflab import markets
from pflab.pm import store
from pflab.quant import macro_attr as MA, transmission as tr, waves as W

TRUE = {"crude": -0.05, "currency": -0.8, "us10y": -0.01, "nasdaq": 0.15, "flows": 0.05, "asia": 0.30}
NOW = datetime(2026, 11, 8, 3, 0)


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    store.migrate(c)
    return c


def _put(root: Path, folder: str, key: str, dates, levels, col="close"):
    p = root / folder / f"{key}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": list(dates), col: np.asarray(levels, float)}).to_parquet(p, index=False)


def _levels_from_pct(moves, start=100.0):
    return start * np.cumprod(1 + np.asarray(moves) / 100.0)


def make_world(root: Path, start=date(2023, 1, 2), end=date(2024, 12, 31), seed=3, noise=0.02, drop=(), garbage_after=None, n_days=None):
    """An index whose move is exactly TRUE betas x the factors (+ small noise). Overnight factors live on US sessions; the rest on India's."""
    rng = np.random.default_rng(seed)
    ind, us = markets.get("IN"), markets.get("US")
    in_days = ind.sessions_between(start, end)
    if n_days:
        in_days = in_days[:n_days]
    us_days = us.sessions_between(date(2022, 12, 1), end)
    f = {}
    f["crude"] = dict(zip(us_days, rng.normal(0, 1.6, len(us_days))))                  # percent
    f["us10y"] = dict(zip(us_days, rng.normal(0, 6.0, len(us_days))))                  # basis points
    f["nasdaq"] = dict(zip(us_days, rng.normal(0, 1.2, len(us_days))))
    f["currency"] = dict(zip(in_days, rng.normal(0, 0.25, len(in_days))))
    f["flows"] = dict(zip(in_days, rng.normal(0, 3.0, len(in_days))))                  # Rs 1,000 crore
    peers = {k: rng.normal(0, 0.5, len(in_days)) for k in MA.ASIA_KEYS}
    common = rng.normal(0, 1.0, len(in_days))
    asia = pd.DataFrame({k: common + v for k, v in peers.items()}, index=in_days).mean(axis=1)
    y = []
    for i, m in enumerate(in_days):
        u = tr.source_session("IN", m)
        y.append(TRUE["crude"] * f["crude"].get(u, 0.0) + TRUE["us10y"] * f["us10y"].get(u, 0.0) + TRUE["nasdaq"] * f["nasdaq"].get(u, 0.0)
                 + TRUE["currency"] * f["currency"][m] + TRUE["flows"] * f["flows"][m] + TRUE["asia"] * float(asia.iloc[i]) + rng.normal(0, noise))
    # files (a move series has a first row with no move: prepend a day)
    d0, d0u = ind.previous_session(in_days[0]), us.previous_session(us_days[0])

    def lv(days, mv, first):
        return [first] + list(_levels_from_pct(mv))

    _put(root, "indices", "NIFTY500_TRI", [d0] + in_days, [100.0] + list(_levels_from_pct(y)))
    if "crude" not in drop:
        _put(root, "global", "BRENT_FUT", [d0u] + us_days, [100.0] + list(_levels_from_pct([f["crude"][d] for d in us_days])))
    if "us10y" not in drop:
        _put(root, "global", "US_10Y_YIELD", [d0u] + us_days, [4.0] + list(4.0 + np.cumsum([f["us10y"][d] / 100.0 for d in us_days])))
    if "nasdaq" not in drop:
        _put(root, "global", "US_NASDAQ", [d0u] + us_days, [100.0] + list(_levels_from_pct([f["nasdaq"][d] for d in us_days])))
    if "currency" not in drop:
        _put(root, "global", "FX_USDINR", [d0] + in_days, [80.0] + list(_levels_from_pct([f["currency"][d] for d in in_days], 80.0)))
    if "asia" not in drop:
        for k in MA.ASIA_KEYS:
            lvl = _levels_from_pct((common + peers[k]))
            _put(root, "global", k, [d0] + in_days, [100.0] + list(lvl))
        # the average of the four peers' moves is `asia`: the peers' levels are built from common+peer so their moves are exactly those percentages, compounded
    if "flows" not in drop:
        rows = [{"report_date": ind.next_session(d), "asset": "Equity", "route": "Sub-total", "net_cr": f["flows"][d] * 1000.0} for d in in_days]
        p = root / "macro" / "FPI_DAILY.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_parquet(p, index=False)
    return in_days, f


# --- macro attribution --------------------------------------------------------------------------------------------------------------------

def test_known_betas_recovered_and_parts_add_up(tmp_path):
    in_days, f = make_world(tmp_path)
    d = MA.Design(tmp_path, "IN")
    s = in_days[-30]
    a = d.attribute(s)
    for k, b in TRUE.items():
        assert a["parts"][k]["beta"] == pytest.approx(b, rel=0.08, abs=0.003), k
    assert a["checks_out"]
    parts = sum(p["pct"] for p in a["parts"].values())
    assert parts + a["unexplained_pct"] == pytest.approx(a["total_pct"], abs=1e-5)
    assert abs(a["unexplained_pct"]) < 0.25                        # the noise is 0.02 and the betas are right: nearly all of the move is explained
    u = tr.source_session("IN", s)
    assert a["parts"]["crude"]["pct"] == pytest.approx(a["parts"]["crude"]["beta"] * f["crude"][u], abs=1e-4)
    assert a["parts"]["flows"]["factor_move"] == pytest.approx(f["flows"][s], abs=1e-3)


def test_attribution_is_point_in_time(tmp_path):
    root_a, root_b = tmp_path / "a", tmp_path / "b"
    in_days, _ = make_world(root_a)
    make_world(root_b)
    s = in_days[300]
    base = MA.Design(root_a, "IN").attribute(s)
    # rewrite every row dated after the session in root_b: the attribution of the session must not move
    for sub, key in [("indices", "NIFTY500_TRI"), ("global", "BRENT_FUT"), ("global", "US_NASDAQ"), ("global", "US_10Y_YIELD"), ("global", "FX_USDINR"), ("global", "KR_KOSPI")]:
        p = root_b / sub / f"{key}.parquet"
        df = pd.read_parquet(p)
        later = pd.to_datetime(df["date"]).dt.date > in_days[301]
        df.loc[later, "close"] = df.loc[later, "close"] * np.linspace(1.0, 3.0, int(later.sum()))
        df.to_parquet(p, index=False)
    p = root_b / "macro" / "FPI_DAILY.parquet"
    fl = pd.read_parquet(p)
    fl.loc[pd.to_datetime(fl["report_date"]).dt.date > in_days[302], "net_cr"] = 99999.0
    fl.to_parquet(p, index=False)
    again = MA.Design(root_b, "IN").attribute(s)
    for k in TRUE:
        assert again["parts"][k]["pct"] == pytest.approx(base["parts"][k]["pct"], abs=1e-9), k
        assert again["parts"][k]["beta"] == pytest.approx(base["parts"][k]["beta"], abs=1e-9), k
    assert again["total_pct"] == base["total_pct"] and again["unexplained_pct"] == pytest.approx(base["unexplained_pct"], abs=1e-9)
    # and the cut-off world (rows after the session simply absent) gives the same answer too
    assert MA.Design(root_b, "IN").attribute(in_days[100])["parts"]["asia"]["pct"] == pytest.approx(MA.Design(root_a, "IN").attribute(in_days[100])["parts"]["asia"]["pct"], abs=1e-9)


def test_small_sample_gives_count_not_conclusion(tmp_path):
    in_days, _ = make_world(tmp_path, n_days=40)
    d = MA.Design(tmp_path, "IN")
    a = d.attribute(in_days[15])                                      # 14 sessions before it: under MIN_N
    assert all(p["pct"] is None for p in a["parts"].values())
    assert all(("under 20" in p["note"]) for p in a["parts"].values() if p["factor_move"] is not None)
    assert a["unexplained_pct"] == a["total_pct"]                      # nothing is explained, nothing invented
    b = d.attribute(in_days[35])
    assert b["parts"]["asia"]["pct"] is not None and b["parts"]["asia"]["n"] >= 20


def test_missing_series_is_unavailable_not_invented(tmp_path):
    in_days, _ = make_world(tmp_path, drop=("nasdaq", "flows", "crude"))
    a = MA.Design(tmp_path, "IN").attribute(in_days[-10])
    for k in ("nasdaq", "flows", "crude"):
        assert a["parts"][k]["pct"] is None and "unavailable" in a["parts"][k]["note"]
    assert a["parts"]["asia"]["pct"] is not None
    assert a["checks_out"]
    # no data at all for the market: the design is empty, not an error
    empty = MA.Design(tmp_path / "nothing", "IN")
    assert empty.dates == [] and "note" in empty.attribute(date(2024, 1, 2))


def test_flows_part_appears_only_when_the_report_is_in(tmp_path, con):
    in_days, _ = make_world(tmp_path)
    ind = markets.get("IN")
    p = tmp_path / "macro" / "FPI_DAILY.parquet"
    fl = pd.read_parquet(p)
    last = in_days[-1]
    full = fl.copy()
    fl = fl[pd.to_datetime(fl["report_date"]).dt.date <= last]            # the report of the last session (dated the next business day) is not in
    fl.to_parquet(p, index=False)
    r1 = MA.catch_up(con, tmp_path, "IN", last, now=NOW, backfill=5)
    assert r1["sessions_written"] == 5
    row = con.execute("SELECT pct, note FROM macro_attribution WHERE market='IN' AND session=? AND part='flows'", [last]).fetchone()
    assert row[0] is None and "unavailable" in row[1]
    full.to_parquet(p, index=False)                                       # the report arrives
    r2 = MA.catch_up(con, tmp_path, "IN", last, now=NOW, backfill=5)
    assert r2["sessions_written"] == 1
    row = con.execute("SELECT pct, as_of FROM macro_attribution WHERE market='IN' AND session=? AND part='flows'", [last]).fetchone()
    assert row[0] is not None and row[1] == ind.next_session(last)
    n = con.execute("SELECT count(*) FROM macro_attribution WHERE market='IN' AND session=?", [last]).fetchone()[0]
    assert n == 2 + len(MA.FACTORS["IN"])                                  # total + unexplained + one per factor
    again = MA.read(con, "IN", last)
    assert sum(p["pct"] for p in again["parts"].values() if p["pct"] is not None) + again["unexplained_pct"] == pytest.approx(again["total_pct"], abs=1e-5)
    # nothing left to do on a third run
    assert MA.catch_up(con, tmp_path, "IN", last, now=NOW, backfill=5)["sessions_written"] == 0


# --- waves ----------------------------------------------------------------------------------------------------------------------------------

def make_cross_section(seed=5, n_days=820, n_names=600):
    """Background days: market ~ N(0, 0.8%), each name = beta x market + own N(0, 2%). Event days are set by the caller."""
    rng = np.random.default_rng(seed)
    dates = [d.date() for d in pd.bdate_range("2016-01-04", periods=n_days)]
    m = rng.normal(0, 0.008, n_days)
    beta = rng.normal(1.0, 0.2, n_names)
    own = rng.normal(0, 0.02, (n_days, n_names))
    turnover = np.tile(rng.uniform(1e6, 1e9, n_names), (n_days, 1))
    return dates, m, beta, own, turnover


def _stats(dates, m, beta, own, turnover):
    R = m[:, None] * beta[None, :] + own
    return W.stats_from_arrays(dates, R, turnover, m)


def test_wave_flagged_on_extreme_breadth_low_dispersion_and_not_on_a_dispersed_day(tmp_path):
    dates, m, beta, own, to = make_cross_section()
    up, dispersed, down, sector_day = 760, 780, 800, 740
    m[up] = 0.04;  own[up] = np.random.default_rng(1).normal(0, 0.004, own.shape[1])               # everything rises together
    m[down] = -0.045;  own[down] = np.random.default_rng(2).normal(0, 0.004, own.shape[1])
    m[dispersed] = 0.025;  own[dispersed] = np.random.default_rng(3).normal(0, 0.07, own.shape[1])  # a big index day with names all over the place
    m[sector_day] = 0.003;  own[sector_day] = 0.012 + np.random.default_rng(4).normal(0, 0.003, own.shape[1])   # every name up, but not through the market
    st = _stats(dates, m, beta, own, to)
    fl = W.wave_flags(st)
    assert bool(fl.loc[dates[up], "wave"]) and fl.loc[dates[up], "direction"] == "up"
    assert bool(fl.loc[dates[down], "wave"]) and fl.loc[dates[down], "direction"] == "down"
    assert not bool(fl.loc[dates[dispersed], "wave"])
    assert not bool(fl.loc[dates[sector_day], "wave"])
    assert st.loc[dates[sector_day], "adv_share"] > 0.95 and st.loc[dates[sector_day], "dom_share"] < 0.5   # extreme breadth, but the market did not do it
    # the single-session decision (the live path) agrees with the vectorised one
    one = W.wave_flag_at(st, dates[up])
    assert one["decided"] and one["wave"] and one["direction"] == "up" and one["n_reference"] >= W.MIN_REF
    assert not W.wave_flag_at(st, dates[dispersed])["wave"]
    ev = W.wave_events("IN", stats=st)
    assert {e["date"] for e in ev} >= {dates[up], dates[down]} and dates[dispersed] not in {e["date"] for e in ev}
    assert len(ev) <= 0.06 * len(dates)                                  # rare by construction, not every busy day
    # a short history is "not decided", with its count
    early = W.wave_flag_at(st, dates[100])
    assert early["decided"] is False and "not decided" in early["note"]


def test_wave_statistics_are_point_in_time():
    dates, m, beta, own, to = make_cross_section(n_days=700)
    full = _stats(dates, m, beta, own, to)
    cut = 650
    part = _stats(dates[:cut], m[:cut], beta, own[:cut], to[:cut])
    pd.testing.assert_frame_equal(full.iloc[:cut], part, check_exact=False, atol=1e-9)
    fl_full, fl_part = W.wave_flags(full), W.wave_flags(part)
    assert (fl_full["wave"].iloc[:cut].to_numpy() == fl_part["wave"].to_numpy()).all()
    assert np.allclose(fl_full["thr_adv_hi"].iloc[:cut].to_numpy(float), fl_part["thr_adv_hi"].to_numpy(float), equal_nan=True)


def test_reference_sample_never_includes_the_spent_years():
    idx = [d.date() for d in pd.bdate_range("2018-06-01", periods=1800)]       # runs well past 2021
    x = pd.Series(np.random.default_rng(0).normal(0, 1, 1800), index=idx)
    x.iloc[-300:] = 50.0                                                       # a huge level in 2025-26 must not move any threshold
    q = W.expanding_q(x, 0.95)
    after = [i for i, d in enumerate(idx) if d > W.REF_END]
    assert len(after) > 100 and q.iloc[after].nunique() == 1                   # frozen at the 2020-2021 sample
    assert q.iloc[-1] < 5
    assert W.threshold_at(x, idx[-1], 0.95) == pytest.approx(q.iloc[-1])


# --- rotation and crude -------------------------------------------------------------------------------------------------------------------

def make_rotation_world(root: Path, diverge=True, seed=11):
    rng = np.random.default_rng(seed)
    ind = markets.get("IN")
    days = ind.sessions_between(date(2018, 1, 1), date(2021, 6, 30))
    n = len(days)
    flows = rng.normal(0, 1.5, n)                                    # Rs 1,000 crore
    T = 820
    flows[T - 4:T] = [-1.6, -2.0, -1.2, -1.8]                        # a selling streak
    flows[T] = 9.0                                                   # then unusually large buying
    asia = rng.normal(0, 0.8, n)
    idx = asia + rng.normal(0, 0.1, n)
    idx[T] = asia[T] + (1.8 if diverge else 0.0)
    d0 = ind.previous_session(days[0])
    _put(root, "indices", "NIFTY500_TRI", [d0] + days, [100.0] + list(_levels_from_pct(idx)))
    for k in MA.ASIA_KEYS:
        _put(root, "global", k, [d0] + days, [100.0] + list(_levels_from_pct(asia)))
    rows = [{"report_date": ind.next_session(d), "asset": "Equity", "route": "Sub-total", "net_cr": float(v) * 1000.0} for d, v in zip(days, flows)]
    (root / "macro").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(root / "macro" / "FPI_DAILY.parquet", index=False)
    return days, T


def test_rotation_on_flow_switch_with_asia_divergence(tmp_path):
    days, T = make_rotation_world(tmp_path / "yes", diverge=True)
    ev = W.rotation_events("IN", root=tmp_path / "yes")
    hit = [e for e in ev if e["session"] == days[T]]
    assert hit and hit[0]["direction"] == "in"
    assert hit[0]["date"] == markets.get("IN").next_session(days[T])         # knowable when NSDL reports it, a session later
    # the same flow switch without the divergence from Asia is not a rotation
    days2, T2 = make_rotation_world(tmp_path / "no", diverge=False)
    assert not [e for e in W.rotation_events("IN", root=tmp_path / "no") if e["session"] == days2[T2]]
    # without the flow file there are simply no events
    assert W.rotation_events("IN", root=tmp_path / "empty") == []


def test_crude_fall_events_by_percentile_and_point_in_time():
    idx = [d.date() for d in pd.bdate_range("2012-01-02", periods=1000)]
    mv = pd.Series(np.random.default_rng(2).normal(0, 1.5, 1000), index=idx)
    mv.iloc[800] = -12.0
    ev = W.crude_fall_events("IN", moves=mv)
    assert any(e["crude_date"] == idx[800] for e in ev)
    assert all(e["move_pct"] <= e["threshold_pct"] for e in ev)
    assert not any(e["crude_date"] < idx[500] for e in ev)                    # no verdict before 500 earlier moves
    mv2 = mv.copy()
    mv2.iloc[900:] = -30.0                                                    # later crashes do not create or remove an earlier event
    ev2 = W.crude_fall_events("IN", moves=mv2, end=idx[899])
    assert [e["crude_date"] for e in ev2] == [e["crude_date"] for e in ev if e["crude_date"] <= idx[899]]
    assert W.crude_fall_events("IN", moves=mv.iloc[:100]) == []


# --- the lens -------------------------------------------------------------------------------------------------------------------------------

def test_lens_registers_in_shadow_and_shifts_only_after_waves():
    from pflab.fcast import forecasters as F, plugins, protocol as P
    W.register_lens()
    assert "lens_wave" in plugins.REGISTRY and plugins.REGISTRY["lens_wave"].markets == ("IN",) and plugins.REGISTRY["lens_wave"].replay_ok
    assert plugins.REGISTRY["lens_wave"].protocol.endswith("s79_wave_sentiment_protocol.md")
    con = duckdb.connect(":memory:")
    store.migrate(con)
    assert plugins.admitted(con, "lens_wave", "IN", 5) is False                # no live sessions: shadow
    rng = np.random.default_rng(9)
    dates = pd.bdate_range("2015-01-01", periods=1100)
    r = rng.normal(0.0, 0.01, len(dates))
    wave_pos = list(range(200, 900, 60))
    for p in wave_pos:
        r[p + 1:p + 6] += 0.012                                                 # a wave is followed by five good days
    close = pd.Series(100 * np.exp(np.cumsum(r)), index=dates)
    states = pd.Series(0, index=[d.date() for d in dates])
    for p in wave_pos:
        states.iloc[p] = 1
    fr = W.lens_frame(None, "IN", close, 5, states=states)
    base = F.volatility(close, 5)
    assert list(fr.columns) == list(P.LEVELS) and fr.index.equals(close.index)
    ok = fr.dropna()
    assert (np.diff(ok.to_numpy(), axis=1) > 0).all()
    quiet = [i for i in range(300, 1000) if i not in wave_pos]
    assert np.allclose(fr.iloc[quiet].to_numpy(), base.iloc[quiet].to_numpy())  # no wave: the volatility quantiles, unchanged
    first, last = wave_pos[0], wave_pos[-1]
    assert np.allclose(fr.iloc[first].to_numpy(), base.iloc[first].to_numpy())   # the first wave: nothing yet learnt (no earlier wave), no shift
    assert fr.iloc[last][0.5] > base.iloc[last][0.5] + 0.002                    # after several waves that were followed by gains the median is shifted up
    # point in time: changing closes after a wave's date does not change that date's quantiles
    close2 = close.copy()
    close2.iloc[wave_pos[4] + 1:] *= np.linspace(1.0, 2.0, len(close2) - wave_pos[4] - 1)
    fr2 = W.lens_frame(None, "IN", close2, 5, states=states)
    assert np.allclose(fr2.iloc[wave_pos[4]].to_numpy(), fr.iloc[wave_pos[4]].to_numpy())
    # other markets and an empty state series: it cannot forecast
    assert W.lens_frame(None, "US", close, 5, states=states) is None
    assert W.lens_frame(None, "IN", close, 5, states=pd.Series(dtype=float)) is None


# --- tools, store, note, jobs -------------------------------------------------------------------------------------------------------------

def _ctx(root, con, call_ref=7):
    return SimpleNamespace(rt=SimpleNamespace(data_root=root), con=con, asof=date(2024, 12, 31), call_ref=call_ref)


def test_tools_work_with_empty_args_and_on_missing_data(tmp_path, con):
    import pflab.hq.tools  # noqa: F401  (loads the tool table first, as the app does)
    from pflab.hq import tools_s79
    import pflab.hq.tools  # noqa: F401
    from pflab.hq.tools_s79 import t_waves as TW
    assert {"macro_attribution", "wave_detector"} <= set(tools_s79.names())
    make_world(tmp_path)
    TW._DESIGNS.clear()
    out = TW.macro_attribution(_ctx(tmp_path, con), {})
    assert out["call_ref"] == 7 and out["total_pct"] is not None and out["session"] == "2024-12-31"
    assert out["dominant"] and len(out["recent"]) == 5 and set(out["parts"]) == set(MA.FACTORS["IN"])
    assert sum(p["pct"] for p in out["parts"].values() if p["pct"] is not None) + out["unexplained_pct"] == pytest.approx(out["total_pct"], abs=1e-5)
    us = TW.macro_attribution(_ctx(tmp_path, con), {"market": "US"})
    assert "note" in us and "error" not in us                                  # no S&P 500 history here: a harmless note
    w = TW.wave_detector(_ctx(tmp_path, con), {})
    assert w["wave"] is False and w["call_ref"] == 7 and "error" not in w
    nothing = TW.macro_attribution(_ctx(tmp_path / "void", con), {})
    assert "error" not in nothing and "note" in nothing
    TW._DESIGNS.clear()


def test_switch_off_returns_off(tmp_path, con, monkeypatch):
    import pflab.hq.tools  # noqa: F401
    from pflab.hq.tools_s79 import t_waves as TW
    monkeypatch.setattr(W, "settings", lambda: {"on": False})
    assert TW.macro_attribution(_ctx(tmp_path, con), {})["off"] is True
    assert TW.wave_detector(_ctx(tmp_path, con), {})["off"] is True


def test_flag_stored_once_and_the_note_cites_the_calls(tmp_path, con):
    in_days, _ = make_world(tmp_path)
    s = in_days[-5]
    MA.write(con, MA.Design(tmp_path, "IN").attribute(s), NOW)
    stats = {"adv_share": 0.97, "n_all": 2700, "xs_disp": 0.004, "med_ret": 0.03, "disp_ratio": 0.13, "dom_share": 0.95, "n_univ": 495}
    thr = {"adv_hi": 0.8, "adv_lo": 0.2, "disp_ratio_max": 2.5, "dom_min": 0.6}
    w = {"stats": stats, "thresholds": thr, "direction": "up"}
    W.record_flag(con, "IN", s, "wave", "up", stats, thr, W.wave_sentence(w, s), NOW, call_id=41)
    W.record_flag(con, "IN", s, "wave", "up", stats, thr, W.wave_sentence(w, s), NOW, call_id=41)
    assert con.execute("SELECT count(*) FROM wave_flag WHERE market='IN' AND session=?", [s]).fetchone()[0] == 1
    assert W.recent_flags(con, "IN")[0]["salience"] == "high"
    txt = W.wave_note(con, "IN", s, calls={"wave_detector": 41, "macro_attribution": 42})
    assert "[call 41]" in txt and "[call 42]" in txt and "not with its own picks" in txt and "97%" in txt
    assert W.wave_note(con, "IN", in_days[-4], calls={}) == ""                  # nothing flagged that day: nothing to say


def test_jobs_registered_and_catch_up_all_missed_sessions(tmp_path, con):
    import pflab.service.tasks_s79_waves  # noqa: F401
    from pflab.service import jobs
    assert {"macro_attribution", "wave_scan"} <= set(jobs.REGISTRY)
    in_days, _ = make_world(tmp_path)
    MA.write(con, MA.Design(tmp_path, "IN").attribute(in_days[-40]), NOW)
    r = MA.catch_up(con, tmp_path, "IN", in_days[-1], now=NOW, backfill=10)
    have = {x[0] for x in con.execute("SELECT DISTINCT session FROM macro_attribution WHERE market='IN'").fetchall()}
    assert set(in_days[-39:]) <= have                                          # every session missed since the last write
    assert r["latest"] == str(in_days[-1])


def test_nse_provisional_flow_fills_the_session_nsdl_has_not_reported(tmp_path, con):
    in_days, f = make_world(tmp_path)
    ind = markets.get("IN")
    last = in_days[-1]
    p = tmp_path / "macro" / "FPI_DAILY.parquet"
    fl = pd.read_parquet(p)
    fl[pd.to_datetime(fl["report_date"]).dt.date <= last].to_parquet(p, index=False)         # NSDL has not reported `last` yet
    (tmp_path / "flows").mkdir()
    pd.DataFrame({"date": [last], "fii_net_cr": [f["flows"][last] * 1000.0]}).to_parquet(tmp_path / "flows" / "FII_DII_CASH.parquet", index=False)
    assert MA.flows_by_session(tmp_path)[last] == pytest.approx(f["flows"][last], abs=1e-6)
    assert MA.flow_known_dates(tmp_path)[last] == last                                        # NSE's figure is out the same evening
    assert MA.flow_known_dates(tmp_path)[in_days[-2]] == last                                 # NSDL's the next business day
    a = MA.Design(tmp_path, "IN").attribute(last)
    assert a["parts"]["flows"]["pct"] is not None and a["parts"]["flows"]["known_on"] == str(last)
    MA.write(con, a, NOW)
    assert con.execute("SELECT as_of FROM macro_attribution WHERE market='IN' AND session=? AND part='flows'", [last]).fetchone()[0] == last
