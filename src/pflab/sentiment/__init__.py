"""S79b item 15b: sentiment and themes.

    themes.py      the themes (config), their price proxies and the proxy series
    tone.py        news tone: GDELT's own tone per theme and country, and the local model's headline tags (theme label + tone class only; code computes every figure)
    fear.py        priced fear: India VIX, US VIX, put-call ratio, option skew, the theme proxy's realised volatility
    positioning.py FII flows, FII/DII index-futures positioning, open-interest build-up of stock futures, breadth
    compute.py     the table: every component, its z-score against its own trailing history (the day itself is never in it) and the transparent combined score
    exposure.py    theme exposure of a book: sector prior, revenue mix where data exists, point-in-time rolling betas to the theme proxies
    calendar.py    scheduled shocks, a code-written scenario note before each, a surprise measure after it
    lens.py        `lens_sentiment`, a shadow forecaster plug-in (fcast/plugins.py)

Switch: `configs/s79b.toml [sentiment] on`. With it off every tool returns {"off": true} and the job and the lens do nothing.
Point in time: a value at date D uses rows dated <= D; its z-score uses the history strictly before D. Model-read news tone is forward-only (tone.py).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
S79B = REPO / "configs" / "s79b.toml"
THEMES_CONFIG = REPO / "configs" / "themes_s79b.toml"
PROTOCOL = "docs/protocols/s79_wave_sentiment_protocol.md"

DEFAULTS = {"on": True, "tagging": True, "tag_limit": 60, "tag_days": 2, "z_window": 250, "z_min": 60, "z_min_tone": 10, "beta_window": 252,
            "beta_min": 120, "t_carry": 2.0, "extreme_pct": 5.0, "lens_tilt": 0.1}


def settings() -> dict:
    try:
        from pflab import _toml
        return {**DEFAULTS, **dict(_toml.load(S79B).get("sentiment", {}) or {})}
    except Exception:
        return dict(DEFAULTS)


def is_on() -> bool:
    return bool(settings().get("on", True))


OFF = {"off": True, "message": "the sentiment item is switched off (configs/s79b.toml [sentiment] on = false)"}


def data_root(root=None) -> Path:
    if root is not None:
        return Path(root)
    from pflab.data import data_dir
    return data_dir()


def zscore_pit(s: pd.Series, window: Optional[int] = None, min_periods: Optional[int] = None) -> pd.Series:
    """z of each value against the `window` values BEFORE it (the value itself is never in its own history): point in time by construction."""
    st = settings()
    window = int(window or st["z_window"])
    min_periods = int(min_periods or st["z_min"])
    s = s.astype(float)
    h = s.shift(1)
    m = h.rolling(window, min_periods=min_periods).mean()
    sd = h.rolling(window, min_periods=min_periods).std()
    z = (s - m) / sd.where(sd > 1e-12)
    return z.where(s.notna())


def read_series(path: Path, cols=("value", "close"), date_col: str = "date") -> Optional[pd.Series]:
    """A price/level series from a parquet file as a float Series on a Timestamp index (None if the file or the column is not there)."""
    try:
        df = pd.read_parquet(path)
    except Exception:
        return None
    col = next((c for c in cols if c in df.columns), None)
    dc = date_col if date_col in df.columns else next((c for c in df.columns if "date" in c.lower()), None)
    if col is None or dc is None:
        return None
    s = pd.Series(pd.to_numeric(df[col], errors="coerce").to_numpy(float), index=pd.to_datetime(df[dc]))
    s = s[~s.index.isna()].dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s if len(s) else None


def stale_align(s: pd.Series, index: pd.DatetimeIndex, max_days: int = 4) -> pd.Series:
    """The latest observation on or before each date of `index`, kept only when it is at most `max_days` calendar days old (older: NaN, never carried further)."""
    if s is None or not len(s):
        return pd.Series(np.nan, index=index)
    left = pd.DataFrame({"d": pd.DatetimeIndex(index).astype("datetime64[ns]")}).sort_values("d")
    right = pd.DataFrame({"od": pd.DatetimeIndex(s.index).astype("datetime64[ns]"), "v": s.to_numpy(float)}).sort_values("od")
    m = pd.merge_asof(left, right, left_on="d", right_on="od")
    ok = (m["d"] - m["od"]) <= pd.Timedelta(days=max_days)
    out = pd.Series(np.where(ok, m["v"], np.nan), index=pd.DatetimeIndex(m["d"]))
    return out.reindex(pd.DatetimeIndex(index))
