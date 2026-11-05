"""One day's path from the minute bars, by code (S79 item 7). Every figure an agent writes about "how the day went" comes from here.

Rules (stated in the output, so a reader can quote them):
  gap            open of the first bar against the prior close (the exchange's own `prev_close`, so a split or bonus is not a gap)
  opening drive  the first 30 minutes: first open to the close of the bar before 09:45 (market open + 30 min)
  trend day      |close - open| / (high - low) >= 0.6 AND the close is in the outer quarter of the day's range on the side of the move; else range day
  close location (close - low) / (high - low): 0 at the low, 1 at the high
  burst          a minute whose return is more than K times the standard deviation of the previous 30 minute returns of the SAME day (needs 20 of them),
                 so nothing later in the day, and nothing from another day, leaks in; neighbouring bursts (<= 2 minutes apart) are one event
A minute that is missing is a gap in the record: it is counted and listed, never filled, and no return is taken across it.
Point in time: bars dated after the day, or after `asof` (the clock) inside the day, are never read.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

K_DEFAULT = 4.0
SD_WINDOW = 30
SD_MIN = 20
TREND_ER = 0.6
TREND_EDGE = 0.25
DRIVE_MINUTES = 30
MERGE_MINUTES = 2
COLS = ["ts", "open", "high", "low", "close", "volume"]


def load_bars(con, market: str, isin: str, day: date, asof: Optional[datetime] = None) -> pd.DataFrame:
    """The day's minute bars of one name, oldest first. Nothing dated after `day` (nor after `asof`, when given) is returned."""
    lo = datetime.combine(day, time(0, 0))
    hi = datetime.combine(day, time(23, 59, 59))
    if asof is not None and asof < hi:
        hi = asof
    df = con.execute("SELECT ts, open, high, low, close, volume FROM bars_1m WHERE market=? AND isin=? AND ts>=? AND ts<=? ORDER BY ts",
                     [market, isin, lo, hi]).df()
    return df[COLS] if len(df) else pd.DataFrame(columns=COLS)


def expected_minutes(open_t: time, close_t: time) -> int:
    """Whole minutes from the open up to (not including) the close: a 09:15-15:30 session has 375."""
    return (close_t.hour * 60 + close_t.minute) - (open_t.hour * 60 + open_t.minute)


def _hm(ts) -> str:
    return pd.Timestamp(ts).strftime("%H:%M")


def gaps(bars: pd.DataFrame, open_t: time, close_t: time, last_allowed: Optional[datetime] = None) -> dict:
    """Missing minutes of the session window (stated, never filled): how many, and the first few runs of them."""
    if bars.empty:
        return {"missing": expected_minutes(open_t, close_t), "runs": []}
    day = pd.Timestamp(bars["ts"].iloc[0]).date()
    start = datetime.combine(day, open_t)
    end = datetime.combine(day, close_t)
    if last_allowed is not None and last_allowed < end:
        end = last_allowed + timedelta(minutes=1)
    full = pd.date_range(start, end - timedelta(minutes=1), freq="min")
    have = set(pd.to_datetime(bars["ts"]).dt.floor("min"))
    miss = [t for t in full if t not in have]
    runs: List[str] = []
    i = 0
    while i < len(miss):
        j = i
        while j + 1 < len(miss) and miss[j + 1] - miss[j] == pd.Timedelta(minutes=1):
            j += 1
        runs.append(_hm(miss[i]) if i == j else f"{_hm(miss[i])}-{_hm(miss[j])}")
        i = j + 1
    return {"missing": len(miss), "runs": runs[:8], "more_runs": max(0, len(runs) - 8)}


def bursts(bars: pd.DataFrame, k: float = K_DEFAULT) -> List[dict]:
    """Minutes whose return is beyond k standard deviations of the previous SD_WINDOW returns of the day. Adjacent ones merge into one event."""
    if len(bars) < SD_MIN + 2:
        return []
    ts = pd.to_datetime(bars["ts"]).reset_index(drop=True)
    close = bars["close"].astype(float).reset_index(drop=True)
    adj = (ts.diff() == pd.Timedelta(minutes=1)).to_numpy()                       # a return only between two neighbouring minutes
    ret = (close / close.shift(1) - 1.0).to_numpy()
    ret = np.where(adj, ret, np.nan)
    hits = []
    for i in range(1, len(ret)):
        if np.isnan(ret[i]):
            continue
        prev = ret[max(0, i - SD_WINDOW):i]
        prev = prev[~np.isnan(prev)]
        if len(prev) < SD_MIN:
            continue
        sd = float(np.std(prev, ddof=1))
        if sd <= 0:                                                               # a dead-flat stretch: any move at all is a burst, but the multiple is undefined
            if ret[i] != 0.0:
                hits.append((i, float(ret[i]), None))
            continue
        z = float(ret[i]) / sd
        if abs(z) > k:
            hits.append((i, float(ret[i]), z))
    events: List[dict] = []
    for i, r, z in hits:
        t = ts.iloc[i]
        if events and (t - events[-1]["_last"]) <= pd.Timedelta(minutes=MERGE_MINUTES) and np.sign(r) == np.sign(events[-1]["_r0"]):
            e = events[-1]
            e["_last"] = t
            e["minutes"] += 1
            e["return_pct"] = round(e["return_pct"] + r * 100.0, 2)                # sum of minute returns: the event's size to a good approximation
            e["end"] = _hm(t)
            if abs(r) > abs(e["_r0"]):
                e["_r0"], e["z"] = r, (None if z is None else round(z, 1))
            continue
        events.append({"start": _hm(t), "end": _hm(t), "ts": t.to_pydatetime(), "minutes": 1, "return_pct": round(r * 100.0, 2),
                       "z": None if z is None else round(z, 1), "_last": t, "_r0": r,
                       "volume": float(bars["volume"].iloc[i]) if bars["volume"].iloc[i] == bars["volume"].iloc[i] else None})
    for e in events:
        e.pop("_last"), e.pop("_r0")
    return events


def trajectory(bars: pd.DataFrame, prev_close: Optional[float], open_t: time = time(9, 15), close_t: time = time(15, 30), k: float = K_DEFAULT,
               asof: Optional[datetime] = None) -> dict:
    """The day's path from its bars. {} keys: n_bars, gaps, prior_close, open, high, low, close, gap_pct, day_pct, opening_drive, day_type, ... (all by code)."""
    b = bars.sort_values("ts").reset_index(drop=True) if len(bars) else bars
    if b.empty:
        return {"n_bars": 0, "expected_bars": expected_minutes(open_t, close_t), "note": "no minute bars recorded for this day"}
    o, c = float(b["open"].iloc[0]), float(b["close"].iloc[-1])
    hi, lo = float(b["high"].max()), float(b["low"].min())
    rng = hi - lo
    t_hi = b.loc[b["high"].idxmax(), "ts"]
    t_lo = b.loc[b["low"].idxmin(), "ts"]
    out: dict = {"n_bars": int(len(b)), "expected_bars": expected_minutes(open_t, close_t), "first_bar": _hm(b["ts"].iloc[0]), "last_bar": _hm(b["ts"].iloc[-1]),
                 "gaps": gaps(b, open_t, close_t, asof if asof is not None and asof.date() == pd.Timestamp(b["ts"].iloc[0]).date() else None),
                 "open": round(o, 2), "high": round(hi, 2), "low": round(lo, 2), "close": round(c, 2),
                 "time_of_high": _hm(t_hi), "time_of_low": _hm(t_lo)}
    if prev_close and prev_close > 0:
        out["prior_close"] = round(float(prev_close), 2)
        out["gap_pct"] = round((o / prev_close - 1.0) * 100.0, 2)
        out["day_pct"] = round((c / prev_close - 1.0) * 100.0, 2)
    else:
        out["prior_close"] = None
        out["gap_pct"] = None
        out["note_prior_close"] = "no prior close on record: the gap and the day's move against it are not given"
    out["intraday_pct"] = round((c / o - 1.0) * 100.0, 2) if o else None
    # opening drive: the first 30 minutes of the session window
    first_day = pd.Timestamp(b["ts"].iloc[0]).date()
    cut = datetime.combine(first_day, open_t) + timedelta(minutes=DRIVE_MINUTES)
    w = b[pd.to_datetime(b["ts"]) < cut]
    if len(w):
        wo, wc = float(w["open"].iloc[0]), float(w["close"].iloc[-1])
        tot_v = float(b["volume"].sum())
        out["opening_drive"] = {"minutes_of_data": int(len(w)), "pct": round((wc / wo - 1.0) * 100.0, 2), "high": round(float(w["high"].max()), 2),
                                "low": round(float(w["low"].min()), 2),
                                "volume_share_pct": round(float(w["volume"].sum()) / tot_v * 100.0, 1) if tot_v > 0 else None,
                                "direction": "up" if wc > wo else "down" if wc < wo else "flat"}
    else:
        out["opening_drive"] = None
    if rng > 0:
        loc = (c - lo) / rng
        er = abs(c - o) / rng
        out["close_location"] = round(loc, 2)
        out["range_efficiency"] = round(er, 2)
        up = c >= o
        edge = loc >= 1 - TREND_EDGE if up else loc <= TREND_EDGE
        out["day_type"] = "trend day" if (er >= TREND_ER and edge) else "range day"
    else:
        out["close_location"], out["range_efficiency"], out["day_type"] = None, None, "no range"
    out["day_type_rule"] = (f"trend day when |close-open|/(high-low) >= {TREND_ER} and the close sits in the outer {int(TREND_EDGE * 100)}% of the range on the side of the move; "
                            "otherwise range day")
    out["burst_rule"] = f"a minute return beyond {k:g} standard deviations of the previous {SD_WINDOW} minute returns of the day (at least {SD_MIN}); neighbours within {MERGE_MINUTES} minutes are one event"
    bs = bursts(b, k)
    out["n_bursts"] = len(bs)
    out["bursts"] = [{kk: (vv.strftime("%H:%M") if kk == "ts" else vv) for kk, vv in e.items()} for e in sorted(bs, key=lambda e: -abs(e["return_pct"]))[:10]]
    return out


def burst_events(bars: pd.DataFrame, k: float = K_DEFAULT) -> List[dict]:
    """The merged bursts with their full timestamps (for aligning against filings and news)."""
    return bursts(bars.sort_values("ts").reset_index(drop=True) if len(bars) else bars, k)
