"""S79b item 7b: the volume profile. Hand-built volume distributions and synthetic bars only."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
import pytest

from pflab import markets
from pflab.hq import tools as tl
from pflab.quant import volume_profile as vp
from tests.test_s79_explain import _ctx, _put_bars, con, root, rt  # noqa: F401  (fixtures)

IN = markets.get("IN")


# --- the arithmetic on a hand-built distribution ----------------------------------------------------------------------------------------------
V = np.array([2, 5, 10, 20, 30, 18, 9, 4, 2], float)       # total 100, POC bin 4
E = np.arange(10, dtype=float)                               # bins [0,1) ... [8,9)


def test_poc_and_value_area_on_a_hand_built_profile():
    p = vp.poc_index(V)
    assert p == 4
    lo, hi = vp.value_area_idx(V, p, 0.70)
    # 30 -> the two below hold 30 > the two above hold 27 -> 60 -> then above 27 beats below 7 -> 87 >= 70
    assert (lo, hi) == (2, 6)
    s = vp.Profile(E, V).summary()
    assert s["poc"] == 4.5 and s["val"] == 2.0 and s["vah"] == 7.0
    assert s["va_share"] == pytest.approx(0.87) and s["volume"] == 100.0


def test_poc_tie_goes_to_the_bin_nearest_the_middle_of_the_range():
    assert vp.poc_index(np.array([10, 3, 3, 3, 3, 3, 10, 10], float)) == 6      # candidates 0, 6, 7; the traded range's middle is 3.5
    assert vp.poc_index(np.zeros(5)) is None


def test_value_area_runs_out_on_one_side_and_takes_the_other():
    v = np.array([50, 20, 10, 10, 10], float)
    lo, hi = vp.value_area_idx(v, 0, 0.9)
    assert lo == 0 and hi >= 3


def test_distribute_conserves_volume_and_spreads_uniformly():
    edges = vp.linear_edges(10.0, 13.0, 1.0)
    out = vp.distribute([12.0, 12.0, 13.0], [10.0, 12.0, 12.0], [200.0, 600.0, 100.0], edges)
    # bar 1: 10-12 -> 100 in [10,11), 100 in [11,12); bar 2 has no range: all 600 at 12 (bin [12,13)); bar 3: 12-13 -> 100 in [12,13)
    assert out.tolist() == [100.0, 100.0, 700.0]
    assert out.sum() == 900.0
    half = vp.distribute([11.5], [10.5], [100.0], vp.linear_edges(10.0, 12.0, 1.0))
    assert half.tolist() == [50.0, 50.0]


def test_high_and_low_volume_nodes():
    v = np.array([2, 8, 20, 8, 1, 8, 20, 8, 2], float)          # two peaks and a thin gap between
    hv, lv = vp.nodes(v, 1.3, 0.5, 2)
    assert hv == [2, 6] and lv == [4]


def test_naked_poc_detection_and_a_later_touch_removes_it():
    pocs = [(date(2026, 10, 1), 100.0), (date(2026, 10, 2), 105.0), (date(2026, 10, 3), 103.0)]
    nk = vp.naked_pocs(pocs, [102.0, 106.0, 104.0], [98.0, 104.0, 101.0])
    assert [x["poc"] for x in nk] == [100.0, 105.0] and nk[0]["sessions_ago"] == 2
    pocs.append((date(2026, 10, 6), 104.0))
    nk2 = vp.naked_pocs(pocs, [102.0, 106.0, 104.0, 107.0], [98.0, 104.0, 101.0, 99.0])
    assert nk2 == []                                              # the last session's range 99-107 touched both


def test_poc_migration_direction_and_dead_band():
    up = vp.migration([100, 100, 101, 102, 103, 104], 8.0, 5, 0.25)
    assert up["direction"] == "up" and up["change"] == 4.0 and up["change_va_heights"] == pytest.approx(0.5)
    assert vp.migration([100, 100, 100, 100, 100, 101], 8.0, 5, 0.25)["direction"] == "flat"
    assert vp.migration([100, 101], 8.0, 5)["direction"] is None


def test_developing_poc_follows_the_day():
    edges = vp.linear_edges(99.0, 103.0, 1.0)
    hi = [100.0] * 5 + [102.0] * 10
    out = vp.developing_poc(hi, hi, [10.0] * 15, edges, points=15)
    assert out[0][1] == pytest.approx(100.5) and out[-1][1] == pytest.approx(102.5)     # busiest bin moves from the 100s to the 102s


# --- minute bars: sessions, composite, naked POCs, migration, the label --------------------------------------------------------------------------
def _session(day, levels, base=100.0):
    """375 one-minute bars of `day`; each (price, minutes) puts that many flat minutes at the price."""
    prices = np.concatenate([np.full(m, p) for p, m in levels])
    assert len(prices) == 375
    ts = pd.date_range(datetime.combine(day, time(9, 15)), periods=375, freq="min")
    return pd.DataFrame({"ts": ts, "open": prices, "high": prices, "low": prices, "close": prices, "volume": 1000.0})


def test_minute_bar_report_naked_pocs_migration_and_basis(con):
    days = [date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23)]
    for d, lv in zip(days, ([(100.0, 250), (101.0, 125)], [(101.0, 250), (102.0, 125)], [(102.0, 250), (103.0, 125)])):
        _put_bars(con, _session(d, lv), key="INE000A01011")
    rep = vp.report(con, "IN", "INE000A01011", days[-1], root=None, symbol=None, sessions=3, name="AAA")
    assert rep["basis"] == "minute bars" and rep["mode"] == "minute" and rep["sessions_with_volume"] == 3
    pocs = [x["poc"] for x in rep["poc_migration"]["session_pocs"]]
    tick = rep["bin_size"]
    assert [abs(p - e) < 2 * tick for p, e in zip(pocs, (100.0, 101.0, 102.0))] == [True, True, True]
    assert rep["poc_migration"]["direction"] == "up"
    nk = rep["naked_pocs"]
    assert len(nk) == 2 and all(x["side"] == "below" for x in nk) and {round(x["poc"]) for x in nk} == {100, 101}
    f = rep["features"]
    assert rep["close"] == 103.0 and f["position_vs_value_area"] in ("above", "inside") and f["nearest_naked_poc"]["side"] == "below"
    assert rep["session"]["developing_poc"][-1]["poc"] == pytest.approx(rep["session"]["poc"])
    assert vp.profile_line(rep).startswith("Against its volume profile (minute bars)")


def test_a_gap_between_two_clusters_is_a_low_volume_node(con):
    d = date(2026, 10, 23)
    _put_bars(con, _session(d, [(100.0, 180), (105.0, 15), (110.0, 180)]), key="INE000A01011")
    days = [d - timedelta(days=1), d - timedelta(days=2)]
    for x in days:
        _put_bars(con, _session(x, [(100.0, 180), (105.0, 15), (110.0, 180)]), key="INE000A01011")
    rep = vp.report(con, "IN", "INE000A01011", d, symbol=None, sessions=3)
    c = rep["composite"]
    assert c["hvn"] and any(abs(x - 100) < 1 for x in c["hvn"]) and any(abs(x - 110) < 1 for x in c["hvn"])


def test_reader_tolerates_neither_table_rows_nor_parquet_and_reads_the_backfill_files(con, tmp_path):
    empty = vp._bars(con, "IN", "INDEX:NIFTY 50", date(2026, 10, 1), date(2026, 10, 30), tmp_path)
    assert empty.empty
    df = _session(date(2026, 10, 22), [(100.0, 375)])
    (tmp_path / "bars_1m" / "IN").mkdir(parents=True)
    df.to_parquet(tmp_path / "bars_1m" / "IN" / "INDEX_NIFTY 50.parquet")
    got = vp._bars(con, "IN", "INDEX:NIFTY 50", date(2026, 10, 22), date(2026, 10, 22), tmp_path)
    assert len(got) == 375
    _put_bars(con, df.assign(close=101.0), key="INDEX:NIFTY 50")
    both = vp._bars(con, "IN", "INDEX:NIFTY 50", date(2026, 10, 22), date(2026, 10, 22), tmp_path)
    assert len(both) == 375 and both["close"].iloc[0] == 101.0                      # a bar in both is the table's


def test_kite_feed_trades_are_used_where_recorded_and_labelled(tmp_path):
    day = date(2026, 10, 23)
    n = 300
    ts = pd.date_range(datetime.combine(day, time(9, 16)), periods=n, freq="5s")
    px = np.where(np.arange(n) % 3 == 0, 101.0, 100.0)
    cum = np.cumsum(np.where(px == 100.0, 500.0, 100.0))
    snap = pd.DataFrame({"ts": ts, "instrument": "NSE:AAA", "last_price": px, "volume": cum})
    (tmp_path / "kite_depth").mkdir()
    snap.to_parquet(tmp_path / "kite_depth" / f"{day}.parquet")
    t = vp._depth_ticks(tmp_path, "NSE:AAA", day, 200)
    assert len(t) and t["volume"].sum() == pytest.approx(cum[-1] - cum[0])
    prof = vp.build(t["high"], t["low"], t["volume"], vp.linear_edges(99.0, 102.0, 1.0)).summary()
    assert prof["poc"] == pytest.approx(100.5)
    assert vp._depth_ticks(tmp_path, "NSE:ZZZ", day, 200).empty                         # not recorded for that instrument
    assert vp._depth_ticks(tmp_path, "NSE:AAA", day, 5000).empty                        # too few snapshots


# --- daily approximation (the replay's basis) -------------------------------------------------------------------------------------------------
def _daily_frame(n=80, seed=3, vol=True):
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    dates = IN.sessions_between(date(2026, 3, 2), date(2026, 10, 30))[:n]
    d = pd.DataFrame({"date": pd.to_datetime(dates), "open": close, "high": close * 1.004, "low": close * 0.996, "close": close,
                      "volume": rng.uniform(900, 1100, n) if vol else 1.0, "basis": vp.B_DAILY if vol else vp.B_TIME})
    return d


def test_daily_files_are_labelled_and_an_index_without_volume_is_weighted_by_time(con, tmp_path):
    d = _daily_frame()
    (tmp_path / "indices").mkdir()
    d[["date", "open", "high", "low", "close"]].to_parquet(tmp_path / "indices" / "NIFTY50_PRICE.parquet")
    last = d["date"].iloc[-1].date()
    rep = vp.report(con, "IN", "INDEX:NIFTY 50", last, root=tmp_path)
    assert rep["basis"] == vp.B_TIME and rep["mode"] == "daily rolling composite" and rep["naked_pocs"] == [] and "naked" in rep["naked_note"]
    assert rep["composite"]["val"] <= rep["composite"]["poc"] <= rep["composite"]["vah"]
    # a closes-only series is labelled as such
    d[["date", "close"]].to_parquet(tmp_path / "indices" / "NIFTY50_PRICE.parquet")
    assert vp.report(con, "IN", "INDEX:NIFTY 50", last, root=tmp_path)["basis"] == vp.B_CLOSE
    # a stock with volume in the panel is the daily approximation
    (tmp_path / "panel").mkdir()
    pan = pd.DataFrame({"date": d["date"], "isin": "INE000A01011", "open": d["open"], "high": d["high"], "low": d["low"], "close": d["close"], "volume": d["volume"],
                        "turnover": d["volume"] * d["close"], "adj_factor": 1.0, "adj_close": d["close"]})
    pan.to_parquet(tmp_path / "panel" / "prices.parquet")
    r2 = vp.report(con, "IN", "INE000A01011", last, root=tmp_path, symbol="AAA")
    assert r2["basis"] == vp.B_DAILY


def test_no_data_says_so(con, tmp_path):
    rep = vp.report(con, "IN", "INE999Z01019", date(2026, 10, 23), root=tmp_path)
    assert "note" in rep and "too little" in rep["note"]


def test_the_profile_at_t_does_not_change_when_later_rows_change():
    """Point in time: every column of the event frame at row t is the same whether or not rows after t exist (and wherever they would put the price)."""
    d = _daily_frame(120)
    full = vp.event_frame(d).reset_index(drop=True)
    for cut in (60, 85, 100):
        part = vp.event_frame(d.iloc[:cut].reset_index(drop=True)).reset_index(drop=True)
        a = full.iloc[:cut]
        pd.testing.assert_frame_equal(a, part, check_exact=False, rtol=1e-12, atol=1e-12)
    wild = d.copy()
    wild.loc[100:, ["open", "high", "low", "close"]] *= 3.0
    pd.testing.assert_frame_equal(vp.event_frame(wild).reset_index(drop=True).iloc[:100], full.iloc[:100], check_exact=False, rtol=1e-12, atol=1e-12)


def test_value_area_events_outside_and_return_to_value_by_hand():
    n = 46
    dates = pd.to_datetime(IN.sessions_between(date(2026, 3, 2), date(2026, 10, 30))[:n])
    close = np.array([100.0 + (i % 5) for i in range(40)] + [130.0, 103.0, 104.0, 102.0, 101.0, 100.0])
    d = pd.DataFrame({"date": dates, "open": close, "high": close + 0.5, "low": close - 0.5, "close": close, "volume": 1000.0, "basis": vp.B_DAILY})
    ev = vp.value_area_events("IN", daily=d)
    row = ev[ev["date"] == dates[40].date()].iloc[0]
    assert row["outside"] == 1.0 and row["dist_pct"] > 10 and row["close"] == 130.0
    assert row["pv"] < 103 < row["ph"] and row["pv"] >= 99 and row["ph"] <= 105
    assert row["back_in_1"] == 1.0 and row["back_in_5"] == 1.0                       # 103 is back inside the old value area the next day
    assert row["ret_1"] == pytest.approx(103 / 130 - 1) and row["ret_5"] == pytest.approx(100 / 130 - 1)
    assert ev["basis"].iloc[0] == vp.B_DAILY and "date" in ev.columns
    inside = ev[(ev["outside"] == 0.0)]
    assert len(inside) > 5
    late = ev.iloc[-1]
    assert np.isnan(late["back_in_1"]) and np.isnan(late["ret_5"])                   # the series ends: no outcome, not a guess
    cut = vp.value_area_events("IN", end=dates[40].date(), daily=d)
    assert cut["date"].iloc[-1] == dates[40].date()


# --- the tool ---------------------------------------------------------------------------------------------------------------------------------
def test_tool_works_with_no_arguments_and_says_what_is_missing(rt):
    assert tl.TOOLS["volume_profile"].kind == "read"
    text, err = tl.run(_ctx(rt), "volume_profile", {})
    assert not err
    out = json.loads(text)
    assert out["call_ref"] is not None and ("note" in out or "basis" in out or "error" in out)


def test_tool_reads_minute_bars_of_a_name(rt, con):
    days = [date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23)]
    for d, lv in zip(days, ([(100.0, 250), (101.0, 125)], [(101.0, 250), (102.0, 125)], [(102.0, 250), (103.0, 125)])):
        _put_bars(con, _session(d, lv), key="INE000A01011")
    out = json.loads(tl.run(_ctx(rt), "volume_profile", {"symbol": "AAA", "date": "2026-10-23", "sessions": 3})[0])
    assert out["basis"] == "minute bars" and out["features"]["migration"] == "up" and out["symbol"] == "AAA"
    fut = json.loads(tl.run(_ctx(rt), "volume_profile", {"symbol": "AAA", "date": "2027-02-01"})[0])
    assert "future" in fut["note"]


def test_switch_off_means_not_there(rt, monkeypatch):
    monkeypatch.setattr(vp, "settings", lambda table="volume_profile": {**vp.DEFAULTS, "on": False})
    out = json.loads(tl.run(_ctx(rt), "volume_profile", {})[0])
    assert out.get("off") is True
    assert vp.value_area_events("IN", daily=_daily_frame()).empty


def test_trajectory_explanation_carries_the_profile_line(rt, con):
    from pflab.hq import explain
    for d, lv in zip([date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23)],
                     ([(100.0, 250), (101.0, 125)], [(101.0, 250), (102.0, 125)], [(102.0, 250), (103.0, 125)])):
        _put_bars(con, _session(d, lv), key="INE000A01011")
    ctx, res, texts = explain.run_tools(rt, "IN", "AAA", date(2026, 10, 23), datetime(2026, 10, 23, 16, 30))
    assert "volume_profile" in res and res["volume_profile"].get("composite")
    para = explain.factual_paragraph("AAA", date(2026, 10, 23), res)
    assert "volume profile (minute bars)" in para and f"[call {res['volume_profile']['call_ref']}]" in para
    clean, rejected, used = explain.check_citations(para, texts)
    assert not [r for r in rejected if "volume profile" in r.get("sentence", "")]
