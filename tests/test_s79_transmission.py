"""S79 item 10: transmission (US close -> Indian open gap) and lead-lag. Synthetic data only."""
from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from pflab import markets
from pflab.quant import leadlag as ll, transmission as tr

BETA = 0.4


def _write(root, sub, key, dates, close, open_=None):
    p = root / sub / f"{key}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    c = np.asarray(close, float)
    pd.DataFrame({"date": dates, "open": c if open_ is None else open_, "high": c, "low": c, "close": c}).to_parquet(p, index=False)


def make_world(root, beta=BETA, start=date(2023, 6, 1), end=date(2024, 12, 31), seed=1, noise=0.0008):
    """US S&P closes on US sessions; a Nifty whose opening gap is beta x the move of the US session that closed before its open."""
    rng = np.random.default_rng(seed)
    us, ind = markets.get("US"), markets.get("IN")
    us_days = us.sessions_between(date(2023, 5, 1), end)
    us_ret = rng.normal(0, 0.01, len(us_days))
    us_close = 4000 * np.cumprod(1 + us_ret)
    _write(root, "global", "US_SP500", us_days, us_close)
    move = dict(zip(us_days, us_ret))
    in_days = ind.sessions_between(start, end)
    closes, opens, c = [], [], 20000.0
    for m in in_days:
        u = tr.source_session("IN", m)
        gap = beta * move.get(u, 0.0) + rng.normal(0, noise)
        o = c * (1 + gap)
        c = o * (1 + rng.normal(0, 0.004))
        opens.append(o)
        closes.append(c)
    _write(root, "indices", "NIFTY50_PRICE", in_days, closes, opens)
    return in_days, us_days, us_close


def test_known_beta_recovered(tmp_path):
    in_days, us_days, us_close = make_world(tmp_path)
    asof = in_days[-1]
    out = tr.expected_open_gap(None, asof, "IN", root=tmp_path)
    assert out["n"] >= 240 and out["expected_gap_pct"] is not None
    assert out["beta"] == pytest.approx(BETA, abs=0.04)
    head = next(l for l in out["legs"] if l["headline"])
    assert head["driver"] == "US_SP500" and head["beta"] == pytest.approx(BETA, abs=0.04)
    u = date.fromisoformat(out["source_session"])
    i = us_days.index(u)
    x0 = us_close[i] / us_close[i - 1] - 1
    assert out["expected_gap_pct"] == pytest.approx(BETA * x0 * 100, abs=0.08)
    assert out["sd_pct"] > 0
    assert out["realized_gap_pct"] is not None                       # the Nifty row of asof exists, shown beside the forecast
    assert out["sd_pct"] < 0.2                                       # small noise -> narrow band


def test_point_in_time_us_close_after_indian_open_is_not_used(tmp_path):
    in_days, us_days, us_close = make_world(tmp_path)
    asof = in_days[-1]
    base = tr.expected_open_gap(None, asof, "IN", root=tmp_path)
    # a US row dated the Indian target day itself: that session closes AFTER the NSE open (02:30 IST the next day)
    path = tmp_path / "global" / "US_SP500.parquet"
    df = pd.read_parquet(path)
    extra = pd.DataFrame({"date": [asof], "open": [1e5], "high": [1e5], "low": [1e5], "close": [1e5]})
    pd.concat([df[df["date"] != asof], extra]).sort_values("date").to_parquet(path, index=False)
    after = tr.expected_open_gap(None, asof, "IN", root=tmp_path)
    assert date.fromisoformat(base["source_session"]) < asof
    assert after["source_session"] == base["source_session"]
    assert after["expected_gap_pct"] == base["expected_gap_pct"] and after["n"] == base["n"]
    # and the source close is never later than the target open on the IST clock
    sw, tw = markets.get("US").window_ist(date.fromisoformat(base["source_session"])), markets.get("IN").window_ist(asof)
    assert sw[1] <= tw[0]


def test_monday_morning_reads_friday(tmp_path):
    in_days, _us, _c = make_world(tmp_path)
    monday = next(d for d in in_days[-60:] if d.weekday() == 0 and markets.get("US").is_session(markets.get("IN").previous_session(d)))
    u = tr.source_session("IN", monday)
    assert u.weekday() == 4 and u < monday


def test_training_uses_only_days_before_target(tmp_path):
    in_days, _us, _c = make_world(tmp_path)
    asof = in_days[-30]
    out = tr.expected_open_gap(None, asof, "IN", root=tmp_path)
    assert date.fromisoformat(out["last_training_day"]) < asof


def test_small_sample_gives_count_not_conclusion(tmp_path):
    in_days, _us, _c = make_world(tmp_path, start=date(2024, 11, 20))          # ~ 28 sessions; a target 10 sessions in has ~10 behind it
    asof = in_days[10]
    out = tr.expected_open_gap(None, asof, "IN", root=tmp_path)
    assert out["expected_gap_pct"] is None and out["sd_pct"] is None
    assert 0 < out["n"] < tr.MIN_N
    assert "small sample" in out["note"]


def test_missing_global_data_never_raises(tmp_path):
    out = tr.expected_open_gap(None, date(2024, 6, 3), "IN", root=tmp_path)
    assert out["expected_gap_pct"] is None and out["n"] == 0 and out["legs"]
    assert tr.expected_open_gap(None, date(2024, 6, 3), "XX", root=tmp_path)["expected_gap_pct"] is None
    assert ll.lead_lag(tmp_path, "US_SP500", "NIFTY50_PRICE", date(2024, 6, 3))["verdict"].startswith("no data")


def test_stale_training_data_gives_no_forecast(tmp_path):
    in_days, _us, _c = make_world(tmp_path, end=date(2024, 6, 28))
    out = tr.expected_open_gap(None, date(2024, 9, 2), "IN", root=tmp_path)           # Nifty file ends in June
    assert out["expected_gap_pct"] is None and "stale" in out["note"]


def test_us_market_is_parameterised(tmp_path):
    in_days, _us, _c = make_world(tmp_path)
    out = tr.expected_open_gap(None, date(2024, 12, 20), "US", root=tmp_path)
    assert out["market"] == "US" and out["source_market"] == "IN"
    assert date.fromisoformat(out["source_session"]) <= date(2024, 12, 20)


def test_oos_compare_runs(tmp_path):
    in_days, _us, _c = make_world(tmp_path)
    r = tr.oos_compare(tmp_path, "IN", start=in_days[-15], end=in_days[-1])
    assert r["n_days"] > 5 and r["mse_headline"] == pytest.approx(r["mse_multi"], rel=1e-2)    # (multi rounds to 4 decimals of a percent) only one driver on disk: multi == headline


# --- lead-lag ----------------------------------------------------------------------------------------------------------

def _pair(root, shift, n=600, seed=3, w=0.9, noise=0.4):
    days = markets.get("IN").sessions_between(date(2022, 1, 3), date(2026, 12, 31))[:n]
    rng = np.random.default_rng(seed)
    ra = rng.normal(0, 0.01, n)
    # b_t = w * a_{t-shift} + noise  (A leads B by `shift`)
    rb = np.zeros(n)
    rb[shift:] = w * ra[:n - shift]
    rb += rng.normal(0, 0.01 * noise, n)
    _write(root, "global", "X_A", days, 100 * np.cumprod(1 + ra))
    _write(root, "global", "X_B", days, 100 * np.cumprod(1 + rb))
    return days[-1]


def test_lag_detected_two_sessions(tmp_path):
    asof = _pair(tmp_path, 2)
    r = ll.lead_lag(tmp_path, "X_A", "X_B", asof, window=600)
    assert r["reliable"] and r["lead"]["leader"] == "X_A" and r["lead"]["follower"] == "X_B" and r["lead"]["lag_sessions"] == 2
    assert r["lead"]["corr"] > 0.5
    r2 = ll.lead_lag(tmp_path, "X_B", "X_A", asof, window=600)                          # swapped: B follows A, so the leader is still X_A
    assert r2["lead"]["leader"] == "X_A" and r2["lead"]["lag_sessions"] == 2


def test_no_lead_on_noise(tmp_path):
    days = markets.get("IN").sessions_between(date(2022, 1, 3), date(2026, 12, 31))[:600]
    rng = np.random.default_rng(11)
    _write(tmp_path, "global", "X_A", days, 100 * np.cumprod(1 + rng.normal(0, 0.01, 600)))
    _write(tmp_path, "global", "X_B", days, 100 * np.cumprod(1 + rng.normal(0, 0.01, 600)))
    r = ll.lead_lag(tmp_path, "X_A", "X_B", days[-1], window=600)
    assert not r["reliable"] and r["lead"] is None and r["verdict"].startswith("no reliable lead")
    assert len(r["lags"]) == 11


def test_lead_lag_small_sample(tmp_path):
    days = markets.get("IN").sessions_between(date(2024, 1, 1), date(2024, 12, 31))[:15]
    rng = np.random.default_rng(2)
    _write(tmp_path, "global", "X_A", days, 100 * np.cumprod(1 + rng.normal(0, 0.01, 15)))
    _write(tmp_path, "global", "X_B", days, 100 * np.cumprod(1 + rng.normal(0, 0.01, 15)))
    r = ll.lead_lag(tmp_path, "X_A", "X_B", days[-1])
    assert 0 < r["n"] < ll.MIN_N and r["lead"] is None and "small sample" in r["verdict"]


def test_minute_level_absent_is_said(tmp_path):
    import duckdb
    con = duckdb.connect()
    r = ll.minute_lead_lag(con, "A", "B")
    assert not r["reliable"] and "bars_1m" in r["verdict"]


def test_minute_level_when_rows_exist():
    import duckdb
    con = duckdb.connect()
    rng = np.random.default_rng(5)
    n = 400
    ra = rng.normal(0, 0.001, n)
    rb = np.zeros(n)
    rb[3:] = 0.9 * ra[:-3]
    rb += rng.normal(0, 0.0003, n)
    ts = pd.date_range("2026-10-23 09:15", periods=n, freq="min")
    rows = [("A", t, float(c)) for t, c in zip(ts, 100 * np.cumprod(1 + ra))] + [("B", t, float(c)) for t, c in zip(ts, 100 * np.cumprod(1 + rb))]
    con.execute("CREATE TABLE bars_1m (symbol VARCHAR, ts TIMESTAMP, close DOUBLE)")
    con.executemany("INSERT INTO bars_1m VALUES (?,?,?)", rows)
    r = ll.minute_lead_lag(con, "A", "B", date(2026, 10, 23))
    assert r["reliable"] and r["lead"]["leader"] == "A" and r["lead"]["lag_minutes"] == 3


# --- the tools ---------------------------------------------------------------------------------------------------------

def _ctx(root):
    return SimpleNamespace(rt=SimpleNamespace(data_root=root), con=None, asof=date(2024, 12, 30))


def test_tools_registered_and_work_with_empty_args(tmp_path):
    from pflab.hq import tools as T
    from pflab.hq.tools_s79 import names, t_transmission as tt
    assert {"transmission", "lead_lag"} <= set(names())
    by = {t.name: t for t in tt.TOOLS}
    for t in by.values():
        assert t.kind == "read" and T.validate(t, {}) is None
    out = by["transmission"].fn(_ctx(tmp_path), {})                       # no data at all: a harmless dict
    assert out["expected_gap_pct"] is None
    out = by["lead_lag"].fn(_ctx(tmp_path), {})
    assert out["reliable"] is False and "verdict" in out
    assert by["lead_lag"].fn(_ctx(tmp_path), {"sector": "IT"})["lead"] is None


def test_tool_on_synthetic_world(tmp_path):
    from pflab.hq.tools_s79 import t_transmission as tt
    in_days, _u, _c = make_world(tmp_path)
    ctx = _ctx(tmp_path)
    out = {t.name: t for t in tt.TOOLS}["transmission"].fn(ctx, {"market": "IN", "date": str(in_days[-1])})
    assert out["expected_gap_pct"] is not None and out["legs"] and out["n"] >= 240
    out = {t.name: t for t in tt.TOOLS}["lead_lag"].fn(ctx, {"date": str(in_days[-1]), "symbol_a": "US_SP500", "symbol_b": "NIFTY50_PRICE"})
    assert out["reliable"] and out["lead"]["leader"] == "US_SP500" and out["lead"]["lag_sessions"] == 1
