"""Market breadth of one session from the exchange's daily files (S79 item 7): how many names rose and fell, how many sit above their own 20 and 50 day average,
how many closed at a 50 day high or low. By code, from the bhavcopy only (series EQ), point in time: files dated after the day are never read.

A name whose close does not follow from the day before (the file's `prev_close` differs from the last close we hold by more than 1%: a split, a bonus,
a demerger) is left out of the average and high/low counts for as long as that break sits inside the window, and the count of those is stated.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from pflab import _duck

WINDOWS = (20, 50)
BREAK_TOLERANCE = 0.01


def _files(root: Path, day: date, n: int) -> list:
    base = Path(root) / "bhavcopy"
    out = []
    for f in sorted(base.glob("*/*.parquet")) if base.exists() else []:
        try:
            d = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if d <= day:
            out.append((d, f))
    return out[-n:]


def _market_sessions(market: str, day: date, n: int) -> list:
    from pflab import markets
    m = markets.get(market)
    out, d = [], m.last_session_on_or_before(day)
    while len(out) < n:
        out.append(d)
        d = m.previous_session(d)
    return sorted(out)


def breadth(root: Path, day: date, market: str = "IN") -> dict:
    """The session's breadth. {'note': ...} when the day's file is not on this PC."""
    if market != "IN":
        return {"market": market, "day": str(day), "note": f"breadth is built from the NSE daily files; no daily-file source for {market} yet"}
    need = max(WINDOWS)
    files = _files(root, day, need + 10)
    if not files or files[-1][0] != day:
        return {"market": market, "day": str(day), "note": f"no NSE daily file for {day} on this PC (latest {files[-1][0] if files else 'none'}): breadth not given"}
    sessions = _market_sessions(market, day, need)
    paths = [f for d, f in files if d in set(sessions)]
    lst = ",".join("'" + p.as_posix() + "'" for p in paths)
    df = _duck.sql(f"SELECT CAST(date AS DATE) AS date, isin, close, high, low, prev_close FROM read_parquet([{lst}], union_by_name=true) "
                   "WHERE series = 'EQ' AND close > 0 AND isin IS NOT NULL").df()
    df["date"] = pd.to_datetime(df["date"])
    today = df[df["date"] == pd.Timestamp(day)].drop_duplicates("isin").set_index("isin")
    adv = int((today["close"] > today["prev_close"]).sum())
    dec = int((today["close"] < today["prev_close"]).sum())
    unch = int(len(today) - adv - dec)
    close = df.pivot_table(index="date", columns="isin", values="close", aggfunc="last").sort_index()
    prev = df.pivot_table(index="date", columns="isin", values="prev_close", aggfunc="last").sort_index()
    # a break: today's recorded prior close does not equal the close we hold for the previous file
    last_close = close.shift(1)
    broken = ((prev / last_close - 1.0).abs() > BREAK_TOLERANCE) & last_close.notna() & prev.notna()
    out = {"market": market, "day": str(day), "universe": "NSE series EQ names that traded", "traded": int(len(today)),
           "advancers": adv, "decliners": dec, "unchanged": unch,
           "advancing_pct": round(adv / len(today) * 100.0, 1) if len(today) else None,
           "advance_decline_ratio": round(adv / dec, 2) if dec else None,
           "net_advances": adv - dec}
    sess_idx = pd.DatetimeIndex([pd.Timestamp(s) for s in sessions])
    for w in WINDOWS:
        win = sess_idx[-w:]
        c = close.reindex(win)
        # the first session of the window has no previous file inside it, so its break flag is not tested (the window's own closes are what matter)
        ok =c.notna().all(axis=0) & ~broken.reindex(win[1:]).fillna(False).any(axis=0)
        elig = ok[ok].index.intersection(today.index)
        if len(elig) == 0:
            out[f"above_sma{w}"] = {"eligible": 0, "note": "not enough history in the files on this PC"}
            continue
        sma = c[elig].mean()
        cur = c[elig].iloc[-1]
        above = int((cur > sma).sum())
        hi = c[elig].iloc[:-1].max()
        lo = c[elig].iloc[:-1].min()
        out[f"above_sma{w}"] = {"eligible": int(len(elig)), "above": above, "pct": round(above / len(elig) * 100.0, 1)}
        if w == max(WINDOWS):
            out[f"new_high_{w}d"] = int((cur > hi).sum())
            out[f"new_low_{w}d"] = int((cur < lo).sum())
            out["excluded_for_a_price_break"] = int(len(today) - len(elig))
    out["rules"] = ("advance: close above the file's prior close; above the average: close above the simple average of the last N closes (all N sessions present, no split/bonus "
                    "break inside); new 50 day high/low: today's close is above/below every one of the 49 closes before it")
    return out
