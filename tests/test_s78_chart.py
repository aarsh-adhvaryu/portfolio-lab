"""S78: the agents SEE charts. Candles from the exchange files (adjusted), a candlestick picture drawn by Pillow, facts by code, a tool whose picture rides back to the model inside
the tool result, and an end-to-end check that the request the model receives holds an image block (the backend, not a display). Synthetic data only."""
from __future__ import annotations

import base64
import io
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from pflab.agents import analyst as an
from pflab.hq import egress, llm, tools as tl
from pflab.hq.desk import Desk
from pflab.pm import store
from pflab.quant import candles, chart
from tests.test_s68_assistant import CFG, Model, _ask, _say, _use  # noqa: F401

AAA = "INE000A01011"


def _bars(n=120, start=100.0, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2026-03-02", periods=n)
    close = start * np.cumprod(1 + rng.normal(0.001, 0.012, n))
    open_ = np.r_[start, close[:-1]] * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    return pd.DataFrame({"date": idx, "open": open_, "high": high, "low": low, "close": close, "volume": rng.integers(80_000, 400_000, n)})


@pytest.fixture
def root(tmp_path):
    """A data folder with a panel (to 2026-07-31, split-adjusted) and bhavcopy files after it."""
    df = _bars(160)
    panel = df[df["date"] <= "2026-07-31"].copy()
    panel["isin"], panel["symbol"], panel["adj_close"] = AAA, "AAA", panel["close"] * 0.5            # a 1:2 split: every raw price is twice the adjusted one
    (tmp_path / "panel").mkdir()
    panel.assign(date=panel["date"].dt.date).to_parquet(tmp_path / "panel" / "prices.parquet")
    after = df[df["date"] > "2026-07-31"]
    (tmp_path / "bhavcopy" / "2026").mkdir(parents=True)
    for _, r in after.iterrows():
        pd.DataFrame([{"date": r["date"].date(), "symbol": "AAA", "series": "EQ", "isin": AAA, "open": r["open"] * 0.5, "high": r["high"] * 0.5, "low": r["low"] * 0.5,
                       "close": r["close"] * 0.5, "prev_close": 0.0, "volume": r["volume"], "turnover": 0.0, "trades": 1}]).to_parquet(tmp_path / "bhavcopy" / "2026" / f"{r['date'].date()}.parquet")
    return tmp_path


def test_daily_candles_join_the_panel_and_the_files_after_it_and_are_split_adjusted(root):
    df = candles.daily(root, AAA, date(2026, 10, 15), bars=100)
    assert len(df) == 100 and list(df.columns) == candles.COLS and df["date"].is_monotonic_increasing and df["date"].is_unique
    raw = _bars(160)
    first = df.iloc[0]
    want = raw[raw["date"] == first["date"]].iloc[0]
    assert first["close"] == pytest.approx(want["close"] * 0.5, rel=1e-6)                         # the panel's adjusted close
    assert first["high"] == pytest.approx(want["high"] * 0.5, rel=1e-6)                           # its highs scaled the same way
    assert df["date"].max() <= pd.Timestamp("2026-10-15")


def test_a_symbol_with_no_candles_gives_an_empty_frame_and_intraday_needs_kite(root):
    assert candles.daily(root, "INE999Z99999", date(2026, 10, 15)).empty
    df, note = candles.get(root, AAA, "AAA", "15min", datetime(2026, 10, 15, 12), 50, kite=None)
    assert df.empty and "Kite" in note
    with pytest.raises(ValueError):
        candles.get(root, AAA, "AAA", "yearly", datetime(2026, 10, 15), 50)


def test_weekly_candles_are_built_from_the_daily_ones(root):
    d = candles.daily(root, AAA, date(2026, 10, 15), bars=100)
    w = candles.weekly(d)
    assert 15 <= len(w) <= 25 and w["high"].iloc[0] >= w["low"].iloc[0]
    first_week = d[d["date"] <= w["date"].iloc[0]]
    assert w["volume"].iloc[0] == first_week["volume"].sum() and w["open"].iloc[0] == first_week["open"].iloc[0]


def test_the_picture_is_a_real_candlestick_chart_not_a_blank(root):
    df = candles.daily(root, AAA, date(2026, 10, 15), bars=90)
    png = chart.render(df, "AAA")
    im = Image.open(io.BytesIO(png))
    assert im.format == "PNG" and im.size == (chart.W, chart.H)
    px = np.asarray(im.convert("RGB")).reshape(-1, 3)
    green = ((px[:, 1] > 180) & (px[:, 0] < 90)).sum()
    red = ((px[:, 0] > 200) & (px[:, 1] < 140)).sum()
    assert green > 500 and red > 500 and (px != np.array(chart.BG)).any(axis=1).mean() > 0.04          # both candle colours, and ink on the page
    with pytest.raises(ValueError):
        chart.render(df.iloc[0:0], "AAA")


def test_the_facts_are_numbers_by_code_and_name_the_patterns(root):
    df = candles.daily(root, AAA, date(2026, 10, 15), bars=90)
    f = chart.facts(df)
    assert f["bars"] == 90 and f["last"]["close"] == pytest.approx(df["close"].iloc[-1], abs=0.01)
    assert f["range"]["high"] == pytest.approx(df["high"].max(), abs=0.01) and "sma20" in f and "sma50" in f and f["volume_vs_20bar_avg"] > 0
    assert any("average" in o for o in f["observations"]) and f["trend_20"]["of"] == 19
    eng = df.copy().tail(5).reset_index(drop=True)
    eng.loc[3, ["open", "close"]] = [110.0, 100.0]                                                      # a red candle ...
    eng.loc[4, ["open", "close"]] = [99.0, 112.0]                                                       # ... swallowed by a green one
    eng.loc[3, ["high", "low"]], eng.loc[4, ["high", "low"]] = [111.0, 99.5], [113.0, 98.0]
    assert any("bullish engulfing" in o for o in chart.facts(eng)["observations"])
    gap = eng.copy()
    gap.loc[4, "open"] = float(gap.loc[3, "close"]) * 1.05
    assert chart.facts(gap).get("gaps_last_5")


# --- the tool, and the backend path to the model ---------------------------------------------------------------------------------------------

@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, 'AAA', 'AAA Ltd', 'synthetic', now())", [AAA])
    return c


@pytest.fixture
def rt(con, root, tmp_path, monkeypatch):
    monkeypatch.setattr(an, "config", lambda: CFG)
    from pflab.hq import service
    monkeypatch.setattr(service, "gate", lambda r: egress.Gate())
    (tmp_path / "pm" / "app").mkdir(parents=True)
    return Desk(con, tmp_path / "pm", root, tmp_path / "repo", None, {"brain": "normal", "preset": "full", "telegram_send": False}, clock=lambda: datetime(2026, 10, 15, 15, 0))


def test_the_tool_returns_facts_and_leaves_the_picture_for_the_model(rt, con):
    ctx = tl.Ctx(rt, None, "m", False, {}, egress.Gate(), datetime(2026, 10, 15, 15, 0), role="research")
    text, err = tl.run(ctx, "chart_view", {"symbol": "AAA", "timeframe": "daily", "bars": 80})
    assert not err
    out = json.loads(text)
    assert out["seen"] is True and out["facts"]["bars"] == 80 and "attached" in out["picture"]
    assert len(ctx.images) == 1 and ctx.images[0]["source"]["media_type"] == "image/png"
    Image.open(io.BytesIO(base64.b64decode(ctx.images[0]["source"]["data"]))).verify()                  # the bytes are a real PNG


def test_an_unknown_symbol_or_intraday_without_kite_is_an_honest_problem_not_a_picture(rt, con):
    ctx = tl.Ctx(rt, None, "m", False, {}, egress.Gate(), datetime(2026, 10, 15, 15, 0), role="research")
    text, err = tl.run(ctx, "chart_view", {"symbol": "AAA", "timeframe": "15min"})
    assert json.loads(text)["seen"] is False and "Kite" in json.loads(text)["problem"] and ctx.images == []
    text2, err2 = tl.run(ctx, "chart_view", {"symbol": "NOSUCH"})
    assert err2 and "no instrument" in text2


def test_the_request_the_model_receives_holds_the_picture_and_its_facts_and_the_log_does_not_keep_the_bytes(rt, con):
    m = Model(_use(("chart_view", {"symbol": "AAA", "timeframe": "daily", "bars": 60})), _say("It trades above its 50-bar average on rising volume: see the facts."))
    out = _ask(rt, con, "Look at the chart of AAA", m)
    assert out["status"] == "done"
    second = m.seen[1]["messages"][-1]["content"]                                                       # the tool_result block sent back on turn 2
    block = second[0]
    assert block["type"] == "tool_result" and isinstance(block["content"], list)
    kinds = [b["type"] for b in block["content"]]
    assert kinds == ["text", "image"] and block["content"][1]["source"]["media_type"] == "image/png"
    assert "facts" in block["content"][0]["text"] and len(block["content"][1]["source"]["data"]) > 5_000
    logged = con.execute("SELECT request_json FROM api_calls ORDER BY call_id").fetchall()
    assert all("omitted_chars" in r[0] or '"image"' not in r[0] for r in logged) and max(len(r[0]) for r in logged) < 400_000    # the bytes are not in the log
    assert not any(len(r[0]) > 300_000 for r in logged)


def test_the_privacy_scan_skips_image_bytes_but_still_scans_the_text_around_them():
    gate = egress.Gate(ids={"ABCDE1234F" * 2}, names={"zzname"})
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "ABCDE1234F" * 2 + "xx"}}      # base64 that happens to contain an id
    ok = {"messages": [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": [{"type": "text", "text": "facts"}, img]}]}]}
    llm.body_check(ok, gate)
    bad = {"messages": [{"role": "user", "content": [{"type": "text", "text": "my name is zzname"}, img]}]}
    with pytest.raises(egress.EgressBlocked):
        llm.body_check(bad, gate)
