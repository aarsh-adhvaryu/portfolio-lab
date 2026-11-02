"""Candles for the agents' chart tool (S78; his word 2026-11-02: "the AI must see charts, especially candlesticks, to go beyond", in the backend, for the system, not only a display).

Daily candles come from the exchange's own files already on this PC (the research panel, then the daily bhavcopy after it ends), split-adjusted; intraday (15 minute, 1 hour) and
today's bars come from Kite's `historical_data` when there is a login (read only, through `ingest/kite.py`). No candle is ever invented: a timeframe the data cannot give says so.
Columns of every frame: date (Timestamp), open, high, low, close, volume.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from pflab import _duck

TIMEFRAMES = ("daily", "weekly", "60min", "15min")
KITE_INTERVAL = {"60min": "60minute", "15min": "15minute", "daily": "day"}
KITE_DAYS = {"60min": 60, "15min": 20}                      # how far back Kite gives each interval in one call is limited; these are safe windows
COLS = ["date", "open", "high", "low", "close", "volume"]
_TOKENS: Dict[str, int] = {}


def _panel_end(root: Path) -> Optional[date]:
    p = Path(root) / "panel" / "prices.parquet"
    if not p.exists():
        return None
    v = _duck.sql(f"SELECT max(date) FROM '{p.as_posix()}'").fetchone()[0]
    return v.date() if isinstance(v, datetime) else v


def daily(root: Path, isin: str, end: date, bars: int = 120) -> pd.DataFrame:
    """Daily candles up to `end`: the panel (adjusted for splits and bonuses), then the bhavcopy files after the panel's last day (as traded)."""
    root = Path(root)
    start = end - timedelta(days=int(bars * 1.6) + 10)
    parts = []
    pe = _panel_end(root)
    p = root / "panel" / "prices.parquet"
    if p.exists():
        d = _duck.sql(f"SELECT date, open, high, low, close, adj_close, volume FROM '{p.as_posix()}' WHERE isin = '{isin}' "
                      f"AND date >= DATE '{start}' AND date <= DATE '{end}' ORDER BY date").df()
        if len(d):
            f = (d["adj_close"] / d["close"]).where(d["close"] > 0, 1.0)
            for c in ("open", "high", "low"):
                d[c] = d[c] * f
            d["close"] = d["adj_close"]
            parts.append(d[COLS])
    after = pe if pe else start
    files = sorted((root / "bhavcopy").glob("*/*.parquet")) if (root / "bhavcopy").exists() else []
    files = [f for f in files if after < _file_date(f) <= end]
    if files:
        lst = ",".join("'" + f.as_posix() + "'" for f in files)
        b = _duck.sql(f"SELECT date, open, high, low, close, volume FROM read_parquet([{lst}]) WHERE isin = '{isin}' AND close > 0 ORDER BY date").df()
        if len(b):
            parts.append(b[COLS])
    if not parts:
        return pd.DataFrame(columns=COLS)
    df = pd.concat(parts).drop_duplicates("date").sort_values("date")
    df["date"] = pd.to_datetime(df["date"])
    return df.tail(bars).reset_index(drop=True)


def _file_date(f: Path) -> date:
    try:
        return date.fromisoformat(f.stem)
    except ValueError:
        return date(1970, 1, 1)


def weekly(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    w = df.set_index("date").resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])
    return w.reset_index()[COLS]


def token_of(kite, symbol: str) -> Optional[int]:
    """Kite's instrument token of an NSE symbol (the instrument list is fetched once and kept)."""
    sym = symbol.strip().upper()
    if not _TOKENS:
        for r in kite.instruments("NSE"):
            if r.get("segment") == "NSE" and r.get("tradingsymbol") and r.get("instrument_token"):
                _TOKENS.setdefault(str(r["tradingsymbol"]).upper(), int(r["instrument_token"]))
    return _TOKENS.get(sym)


def kite_bars(kite, symbol: str, timeframe: str, end: datetime, bars: int) -> pd.DataFrame:
    """Candles from Kite (read only). Empty when the symbol has no token or Kite gives nothing."""
    tok = token_of(kite, symbol)
    if tok is None:
        return pd.DataFrame(columns=COLS)
    days = KITE_DAYS.get(timeframe, 200)
    rows = kite.historical_data(tok, end - timedelta(days=days), end, KITE_INTERVAL[timeframe])
    if not rows:
        return pd.DataFrame(columns=COLS)
    df = pd.DataFrame(rows).rename(columns={"date": "date"})
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    return df[COLS].tail(bars).reset_index(drop=True)


def get(root: Path, isin: str, symbol: str, timeframe: str, end: datetime, bars: int, kite=None) -> tuple:
    """(frame, source note). Daily and weekly from the files on this PC; intraday only from Kite."""
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"timeframe must be one of {TIMEFRAMES}")
    if timeframe in ("60min", "15min"):
        if kite is None:
            return pd.DataFrame(columns=COLS), "intraday candles need today's Kite login (none): ask for the daily chart"
        return kite_bars(kite, symbol, timeframe, end, bars), "Kite historical candles (read only)"
    n = bars * (5 if timeframe == "weekly" else 1)
    df = daily(root, isin, end.date(), max(n, 60))
    note = "the exchange's daily files on this PC (split-adjusted to the research panel's last day)"
    if timeframe == "weekly":
        return weekly(df).tail(bars).reset_index(drop=True), note
    return df.tail(bars).reset_index(drop=True), note
