"""`lens_sentiment`: sentiment as a forecaster plug-in, in SHADOW (fcast/plugins.py; pre-registration docs/protocols/s79_wave_sentiment_protocol.md).

What it does (fixed here, not tuned): start from the `volatility` forecaster's quantiles of the h-session return and move their CENTRE by
    mu = -lens_tilt x sigma_h x tanh(score / 2)        (lens_tilt = 0.1 sigma, configs/s79b.toml [sentiment])
where `score` is the day's sentiment score (positive = risk-on, from sentiment/compute.py). The sign is contrarian (a very risk-on market is tilted down, a very risk-off one up),
chosen BEFORE any result because that is the direction the fear literature points; it is a claim, and the shadow score decides whether it is kept. sigma_h is the
volatility forecaster's own spread, so the lens differs from it only in its centre.

The score in the frame is the PRICE-BASED score (India VIX / US VIX, put-call ratio, option skew, FII flows, futures positioning, build-up, breadth) for every date, which is
what exists for history, so the history replay may run it (`replay_ok = True`). The MODEL-READ news tone is forward-only: it can enter only the LAST row, only when that row is
today or yesterday, and never for a historical date. `news_group` refuses any date older than that (returns NaN) and `tone.refuse_historical` raises: a test enforces both.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from pflab import sentiment as S
from pflab.sentiment import compute, tone, zscore_pit

NAME = "lens_sentiment"


def news_group(con, market: str, dates, today: Optional[date] = None) -> pd.Series:
    """The model-read news tone z-score for each of `dates`: NaN for every date more than one calendar day before `today` (forward-only), and NaN when too few live
    days of tags exist for a z-score. Never reads a tag that was made more than a day after its date (tone.model_tone_by_day)."""
    today = today or date.today()
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in dates])
    out = pd.Series(np.nan, index=idx)
    if con is None:
        return out
    m = tone.model_tone_by_day(con, market, None, None, today)
    if m.empty:
        return out
    daily = m.assign(w=m["tone"] * m["n"]).groupby("day").agg(w=("w", "sum"), n=("n", "sum"))
    s = (daily["w"] / daily["n"]).sort_index()
    z = zscore_pit(s, min_periods=int(S.settings()["z_min_tone"]))
    for d in idx:
        try:
            tone.refuse_historical(d.date(), today)
        except tone.ForwardOnly:
            continue
        if d in z.index and np.isfinite(z[d]):
            out[d] = float(z[d])
    return out


def score_series(con, root, market: str, index: pd.DatetimeIndex, today: Optional[date] = None, with_news: bool = True) -> pd.Series:
    """The score the lens reads on `index`: the price-based group scores (fear, positioning), plus the live news group on the last row when allowed."""
    ps = compute.price_score(root, market, index)
    score = ps["score"].copy()
    if with_news and con is not None and len(index):
        last = pd.DatetimeIndex(index)[-1]
        g = news_group(con, market, [last], today)
        if np.isfinite(g.iloc[0]):
            parts = [x for x in (ps.loc[last, "fear_score"], ps.loc[last, "pos_score"], g.iloc[0]) if np.isfinite(x)]
            if parts:
                score.loc[last] = float(np.mean(parts))
    return score


def frame(con, market: str, close: pd.Series, h: int) -> Optional[pd.DataFrame]:
    """The Lens.frame contract: quantiles of the h-session return at every date of `close` (point in time), or None when the lens cannot forecast."""
    if not S.is_on() or close is None or len(close) < 130:
        return None
    from pflab.fcast import forecasters as fc
    base = fc.volatility(close, h)
    root = S.data_root()
    try:
        score = score_series(con, root, market, close.index)
    except Exception:
        return None
    if score is None or not score.notna().any():
        return None
    tilt = float(S.settings()["lens_tilt"])
    cols = list(base.columns)
    z = fc.Z
    sig = np.log((1.0 + base[cols[-1]]) / (1.0 + base[cols[0]])) / (z[-1] - z[0])
    mu = -tilt * sig * np.tanh(score.reindex(base.index) / 2.0)
    out = (1.0 + base).mul(np.exp(mu), axis=0) - 1.0
    out[mu.isna()] = np.nan
    return out if out.notna().any().any() else None


def register_lens():
    """Called by fcast/plugins.py's loader and by the tool module: add the lens to the registry (idempotent). Nothing when the switch is off."""
    if not S.is_on():
        return None
    from pflab.fcast import plugins
    return plugins.register(plugins.Lens(name=NAME, markets=("IN", "US"), protocol=S.PROTOCOL, frame=frame, replay_ok=True,
                                         about="Sentiment (fear and positioning, price-based) tilting the centre of the volatility forecast against the crowd; model-read news tone live only."))
