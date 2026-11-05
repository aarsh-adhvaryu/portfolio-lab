"""Split one day's move of a stock into market, sector and its own part (S79 item 7), by code.

    move = beta_m x market + beta_s x (sector - beta_sm x market) + own

The betas are ordinary least squares slopes of DAILY returns over the 250 sessions BEFORE the day (never the day itself), worked by the same routine the shock
limits use (`risk/shock_betas.rolling_betas`): the stock on the market (Nifty 500 TRI), then the stock's leftover on the sector's leftover (the sector's TRI index after
removing its own market beta), so the sector part is only what the sector did beyond the market. The sector is the one the sector map gave on or before the day
(`quant/comove.sector_index_for`); a name in an industry without its own index has no sector part (its sector is inside "own", and that is said).
Days with a return beyond 40% are left out of the fit: the exchange's limits are far tighter, so they are a split or bonus in the files.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from pflab import _duck

WINDOW = 250
MIN_OBS = 60
SPLIT_GUARD = 0.40
MARKET_KEY = {"IN": "NIFTY500_TRI"}


def bhav_row(root: Path, isin: str, day: date) -> Optional[dict]:
    """The exchange's own row of the day: close and prior close (the prior close is already adjusted for a split or bonus)."""
    p = Path(root) / "bhavcopy" / f"{day.year}" / f"{day}.parquet"
    if not p.exists():
        return None
    d = _duck.sql(f"SELECT symbol, close, prev_close, open, high, low, volume FROM '{p.as_posix()}' WHERE isin = '{isin}' AND series = 'EQ' AND close > 0 LIMIT 1").df()
    return None if d.empty else d.iloc[0].to_dict()


def prior_close(root: Path, isin: str, day: date) -> Optional[float]:
    """The close the day is measured against: the exchange's prior close of the day's file, else the previous session's close in the candles."""
    r = bhav_row(root, isin, day)
    if r and r.get("prev_close") and r["prev_close"] > 0:
        return float(r["prev_close"])
    from pflab.quant import candles
    df = candles.daily(root, isin, day, bars=5)
    df = df[df["date"] < pd.Timestamp(day)]
    return float(df["close"].iloc[-1]) if len(df) else None


def _index_returns(root: Path, key: str) -> pd.Series:
    from pflab.data import indices
    d = indices.load(key, root)
    s = d.assign(date=pd.to_datetime(d["date"])).drop_duplicates("date").set_index("date")["close"].sort_index().astype(float)
    return s.pct_change().dropna()


def _slope(y: pd.Series, x: pd.Series) -> Optional[float]:
    from pflab.risk.shock_betas import rolling_betas
    j = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    if len(j) < MIN_OBS:
        return None
    b = rolling_betas(j[["y"]], j["x"], window=len(j), min_obs=MIN_OBS)["y"].iloc[-1]
    return None if pd.isna(b) else float(b)


def decompose(root: Path, isin: str, day: date, market: str = "IN") -> dict:
    """{'total_pct', 'market_pct', 'sector_pct', 'own_pct', betas, ...} or {'note': why not}. Percent figures are rounded to two places."""
    if market not in MARKET_KEY:
        return {"market": market, "day": str(day), "note": f"daily market and sector series are only wired for IN so far; none for {market}"}
    from pflab.quant import candles, comove
    row = bhav_row(root, isin, day)
    df = candles.daily(root, isin, day, bars=WINDOW + 40)
    if row is None and (df.empty or df["date"].iloc[-1] != pd.Timestamp(day)):
        return {"market": market, "day": str(day), "note": f"no price for that name on {day} in the files on this PC"}
    if df.empty or len(df) < 2:
        return {"market": market, "day": str(day), "note": "no price history for that name"}
    stock = df.set_index("date")["close"].astype(float)
    r_s = stock.pct_change().dropna()
    if row is not None and row.get("prev_close"):
        total = float(row["close"]) / float(row["prev_close"]) - 1.0                # the exchange's own adjusted prior close
    elif stock.index[-1] == pd.Timestamp(day):
        total = float(r_s.iloc[-1])
    else:
        return {"market": market, "day": str(day), "note": "no price for that name on the day"}
    r_m = _index_returns(root, MARKET_KEY[market])
    d0 = pd.Timestamp(day)
    if d0 not in r_m.index:
        return {"market": market, "day": str(day), "note": f"no {MARKET_KEY[market]} value for {day}"}
    industry, skey = comove.sector_index_for(root, isin, day)
    out = {"market": market, "day": str(day), "isin": isin, "total_pct": round(total * 100.0, 2), "market_index": MARKET_KEY[market],
           "market_index_pct": round(float(r_m.loc[d0]) * 100.0, 2), "industry": industry}
    hist = r_s[(r_s.index < d0) & (r_s.abs() < SPLIT_GUARD)].tail(WINDOW)
    mh = r_m.reindex(hist.index)
    b_m = _slope(hist, mh)
    if b_m is None:
        out.update(note=f"fewer than {MIN_OBS} sessions of history before {day}: no beta, so no split of the move", beta_market=None)
        return out
    market_part = b_m * float(r_m.loc[d0])
    out.update(beta_market=round(b_m, 2), beta_window=f"{len(hist.dropna())} sessions before {day}", market_pct=round(market_part * 100.0, 2))
    sector_part = 0.0
    out["sector_index"] = skey
    if skey:
        try:
            r_sec = _index_returns(root, skey)
        except Exception:
            r_sec = None
        if r_sec is not None and d0 in r_sec.index:
            b_sm = _slope(r_sec.reindex(hist.index), mh)
            if b_sm is not None:
                sec_res_hist = r_sec.reindex(hist.index) - b_sm * mh
                stock_res_hist = hist - b_m * mh
                b_s = _slope(stock_res_hist, sec_res_hist)
                if b_s is not None:
                    sec_res = float(r_sec.loc[d0]) - b_sm * float(r_m.loc[d0])
                    sector_part = b_s * sec_res
                    out.update(sector_index_pct=round(float(r_sec.loc[d0]) * 100.0, 2), beta_sector=round(b_s, 2), sector_beyond_market_pct=round(sec_res * 100.0, 2))
        if "beta_sector" not in out:
            out["sector_note"] = "the sector index or its beta was not available for the day: the sector is inside the own part"
    else:
        out["sector_note"] = "this industry has no index of its own in the files: the sector is inside the own part"
    out["sector_pct"] = round(sector_part * 100.0, 2)
    out["own_pct"] = round((total - market_part - sector_part) * 100.0, 2)
    out["method"] = ("daily-return OLS slopes over the sessions before the day (risk/shock_betas.rolling_betas); own = total - market part - sector part; "
                     "the day itself is never in the fit")
    return out
