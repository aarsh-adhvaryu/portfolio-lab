"""The chart the agents look at (S78): a candlestick picture with volume and moving averages, drawn with Pillow (already pinned), and the FACTS about the same candles worked out by
code. The model gets both: the picture to see shapes and context, the facts to quote exact numbers. What it says about a picture must be quotable from the facts.

`render` makes the PNG; `facts` returns plain numbers and short labelled observations (trend, position against the averages, gaps, candle patterns, volume against its own average).
"""
from __future__ import annotations

import io
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

BG, GRID, TEXT, MUTED = (14, 17, 23), (34, 42, 54), (232, 237, 243), (154, 167, 184)
UP, DOWN, SMA_A, SMA_B, HILO = (52, 211, 164), (255, 122, 122), (242, 184, 75), (122, 167, 255), (154, 167, 184)
W, H = 1100, 640


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                                      # an older Pillow without sized default fonts
        return ImageFont.load_default()


def sma(close: pd.Series, n: int) -> pd.Series:
    return close.rolling(n, min_periods=n).mean()


def render(df: pd.DataFrame, title: str, timeframe: str = "daily", averages=(20, 50)) -> bytes:
    """A candlestick PNG: price pane on top, volume below, the averages drawn, the range's high and low dashed. Raises on an empty frame."""
    if df is None or df.empty:
        raise ValueError("no candles to draw")
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f_small, f_mid, f_big = _font(13), _font(15), _font(20)
    left, right, top, bottom = 12, 84, 44, 40
    vol_h = 110
    pr_top, pr_bot = top, H - bottom - vol_h - 14
    vo_top, vo_bot = H - bottom - vol_h, H - bottom
    n = len(df)
    hi, lo = float(df["high"].max()), float(df["low"].min())
    pad = (hi - lo) * 0.06 or hi * 0.01
    hi, lo = hi + pad, lo - pad
    x0, x1 = left, W - right
    step = (x1 - x0) / n
    cw = max(2, int(step * 0.62))

    def y(v: float) -> float:
        return pr_top + (hi - v) / (hi - lo) * (pr_bot - pr_top)

    for k in range(5):                                      # grid and the price axis
        v = lo + (hi - lo) * k / 4
        d.line([(x0, y(v)), (x1, y(v))], fill=GRID, width=1)
        d.text((x1 + 8, y(v) - 8), f"{v:,.2f}", fill=MUTED, font=f_small)
    vmax = float(df["volume"].max()) or 1.0
    for i, r in enumerate(df.itertuples()):
        cx = x0 + step * (i + 0.5)
        up = r.close >= r.open
        col = UP if up else DOWN
        d.line([(cx, y(r.high)), (cx, y(r.low))], fill=col, width=1)
        top_b, bot_b = y(max(r.open, r.close)), y(min(r.open, r.close))
        d.rectangle([cx - cw / 2, top_b, cx + cw / 2, max(bot_b, top_b + 1)], fill=col)
        vh = (float(r.volume) / vmax) * (vo_bot - vo_top)
        d.rectangle([cx - cw / 2, vo_bot - vh, cx + cw / 2, vo_bot], fill=tuple(int(c * 0.55) for c in col))
    for nlen, col in zip(averages, (SMA_A, SMA_B)):
        s = sma(df["close"], nlen)
        pts = [(x0 + step * (i + 0.5), y(v)) for i, v in enumerate(s) if pd.notna(v)]
        if len(pts) > 1:
            d.line(pts, fill=col, width=2)
    for v, label in ((float(df["high"].max()), "high"), (float(df["low"].min()), "low")):   # the range's extremes, dashed
        for xs in range(int(x0), int(x1), 14):
            d.line([(xs, y(v)), (xs + 7, y(v))], fill=HILO, width=1)
        d.text((x0 + 4, y(v) - 15), f"{label} {v:,.2f}", fill=HILO, font=f_small)
    d.text((left, 10), title, fill=TEXT, font=f_big)
    legend = f"  {timeframe} candles · green up, red down · "
    d.text((left + d.textlength(title, font=f_big), 14), legend, fill=MUTED, font=f_small)
    lx = left + d.textlength(title, font=f_big) + d.textlength(legend, font=f_small)
    for nlen, col in zip(averages, (SMA_A, SMA_B)):
        d.line([(lx, 21), (lx + 18, 21)], fill=col, width=3)
        d.text((lx + 22, 14), f"SMA{nlen}", fill=MUTED, font=f_small)
        lx += 80
    for k in range(0, n, max(1, n // 6)):                   # a few dates on the bottom
        cx = x0 + step * (k + 0.5)
        stamp = df["date"].iloc[k]
        label = stamp.strftime("%d %b") if timeframe in ("daily", "weekly") else stamp.strftime("%d %b %H:%M")
        d.text((max(4, cx - 24), H - bottom + 8), label, fill=MUTED, font=f_small)
    d.text((x1 + 8, vo_top), "volume", fill=MUTED, font=f_small)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _patterns(df: pd.DataFrame) -> List[str]:
    out = []
    if len(df) < 3:
        return out
    a, b = df.iloc[-2], df.iloc[-1]
    body, rng = abs(b.close - b.open), (b.high - b.low) or 1e-9
    lower, upper = min(b.open, b.close) - b.low, b.high - max(b.open, b.close)
    if body / rng < 0.1:
        out.append("last candle is a doji (open and close almost equal: indecision)")
    if lower > 2 * body and upper < body and body / rng > 0.05:
        out.append("last candle has a long lower shadow (a hammer shape: sellers were pushed back)")
    if upper > 2 * body and lower < body and body / rng > 0.05:
        out.append("last candle has a long upper shadow (a shooting-star shape: buyers were pushed back)")
    if a.close < a.open and b.close > b.open and b.open <= a.close and b.close >= a.open:
        out.append("bullish engulfing: the last green body covers the previous red body")
    if a.close > a.open and b.close < b.open and b.open >= a.close and b.close <= a.open:
        out.append("bearish engulfing: the last red body covers the previous green body")
    return out


def facts(df: pd.DataFrame, timeframe: str = "daily") -> Dict[str, object]:
    """Numbers and short labelled observations about the same candles, by code. Every sentence an agent writes about the picture should be quotable from here."""
    if df is None or df.empty:
        return {}
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last
    c = df["close"]
    out: Dict[str, object] = {
        "bars": len(df), "from": str(df["date"].iloc[0])[:16], "to": str(df["date"].iloc[-1])[:16],
        "last": {"open": round(float(last.open), 2), "high": round(float(last.high), 2), "low": round(float(last.low), 2), "close": round(float(last.close), 2),
                 "volume": int(last.volume), "change_pct": round((last.close / prev.close - 1) * 100, 2) if prev.close else None},
        "range": {"high": round(float(df["high"].max()), 2), "low": round(float(df["low"].min()), 2),
                  "below_high_pct": round((1 - last.close / df["high"].max()) * 100, 2), "above_low_pct": round((last.close / df["low"].min() - 1) * 100, 2)},
    }
    obs: List[str] = []
    for n in (20, 50):
        s = sma(c, n)
        if len(c) >= n and pd.notna(s.iloc[-1]):
            v = float(s.iloc[-1])
            slope = float(s.iloc[-1] - s.iloc[-6]) if len(s.dropna()) > 6 else 0.0
            out[f"sma{n}"] = {"value": round(v, 2), "close_vs_pct": round((last.close / v - 1) * 100, 2), "slope": "rising" if slope > 0 else "falling" if slope < 0 else "flat"}
            obs.append(f"close is {'above' if last.close >= v else 'below'} the {n}-bar average ({v:,.2f}), which is {out[f'sma{n}']['slope']}")
    if len(df) >= 20:
        w = df.tail(20)
        hh = int((w["high"].diff() > 0).sum())
        hl = int((w["low"].diff() > 0).sum())
        out["trend_20"] = {"higher_highs": hh, "higher_lows": hl, "of": 19}
        obs.append(f"over the last 20 bars: {hh} higher highs and {hl} higher lows (of 19)")
        out["swing_20"] = {"high": round(float(w["high"].max()), 2), "low": round(float(w["low"].min()), 2)}
    vol = df["volume"]
    if len(vol) >= 21 and vol.iloc[-21:-1].mean() > 0:
        ratio = float(vol.iloc[-1] / vol.iloc[-21:-1].mean())
        out["volume_vs_20bar_avg"] = round(ratio, 2)
        obs.append(f"last bar's volume is {ratio:.1f}x its 20-bar average")
    gaps = []
    for i in range(max(1, len(df) - 5), len(df)):
        pc, op = df["close"].iloc[i - 1], df["open"].iloc[i]
        if pc and abs(op / pc - 1) >= 0.02:
            gaps.append(f"{str(df['date'].iloc[i])[:10]}: opened {((op / pc) - 1) * 100:+.1f}% from the previous close")
    if gaps:
        out["gaps_last_5"] = gaps
    obs += _patterns(df)
    out["observations"] = obs
    out["timeframe"] = timeframe
    return out
