"""Volume profile (S79b item 7b): where the business was done, by code, per session and as a composite of sessions.

A bar's volume is spread uniformly over its high-low range (a bar with no range puts all its volume at its price) across price bins; summed, that is the profile.

    POC            the price bin with the most volume (a tie goes to the bin nearest the middle of the traded range)
    value area     the smallest run of bins around the POC holding 70% of the volume, grown the usual way: add the two bins above or the two below, whichever holds more.
                   VAH is the upper edge of the highest bin kept, VAL the lower edge of the lowest.
    HVN / LVN      high-volume nodes: a local peak (strictly above its neighbours within `node_width` bins) with at least `hvn_factor` x the mean bin volume;
                   low-volume nodes: a local trough inside the traded range with at most `lvn_factor` x the mean bin volume (a thin gap price moved through fast)
    developing POC the POC after each bar so far, sampled through the session (it shows where the day's business is drifting)
    POC migration  the composite POC now against `migrate_lookback` sessions ago, in value-area heights; up / down / flat with a dead band of `migrate_band`
    naked POC      a prior session's POC that no later session's high-low range has touched ("untested")

THREE BASES, always labelled in the result (`basis`):
  "kite feed trade volume"  volume increments between recorded Kite quote snapshots, put at the snapshot's last price (data/kite_depth), where recorded for the day
  "minute bars"             the 1-minute bars (table bars_1m, or data/bars_1m/<market>/<key>.parquet from the backfill)
  "daily approximation"     one bar per day (its high-low range spread uniformly, weighted by the day's traded value over the adjusted price); a day has no shape of its own,
                            so only the ROLLING composite over `window_sessions` days has a POC (no naked POCs on this basis)
  An index with no volume series is weighted by time: "time at price (index has no volume)". A series with only closes: "close only".

Point in time: the profile and every feature at date t use bars dated <= t only. `value_area_events` also prints outcome columns (what happened after) for the pre-registered
study; they are outcomes, never features.

Numbers: figures worked here are the code's; nothing is model made."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

DEFAULTS = {"on": True, "value_area_pct": 0.70, "window_sessions": 20, "bin_pct": 0.25, "session_bins": 80, "hvn_factor": 1.3, "lvn_factor": 0.5, "node_width": 2,
            "migrate_lookback": 5, "migrate_band": 0.25, "max_sessions": 20, "min_minute_sessions": 3, "min_depth_snapshots": 200}
INDEX_PREFIX = "INDEX:"
B_DEPTH, B_MINUTE, B_DAILY = "kite feed trade volume", "minute bars", "daily approximation"
B_TIME, B_CLOSE = "time at price (index has no volume)", "close only"
INDEX_FILES = {"NIFTY 50": "NIFTY50_PRICE", "NIFTY50": "NIFTY50_PRICE", "NIFTY 500": "NIFTY500_TRI", "NIFTY500": "NIFTY500_TRI", "US_SP500": "US_SP500"}


def settings(table: str = "volume_profile") -> dict:
    """The [volume_profile] (or other) table of configs/s79b.toml over the defaults; `on = false` makes the item not there."""
    try:
        from pflab import _toml, markets
        raw = _toml.load(markets.CONFIGS / "s79b.toml").get(table, {}) or {}
    except Exception:
        raw = {}
    return {**DEFAULTS, **dict(raw)} if table == "volume_profile" else dict(raw)


def is_on() -> bool:
    return bool(settings().get("on", True))


# ======================================================================================================================================
# the arithmetic: bins, profile, POC, value area, nodes
# ======================================================================================================================================

def linear_edges(lo: float, hi: float, tick: float) -> np.ndarray:
    """Bin edges from just under `lo` to at or above `hi`, `tick` wide, aligned so that edges are multiples of tick."""
    a = np.floor(lo / tick + 1e-9) * tick
    n = max(int(np.ceil((hi - a) / tick - 1e-9)), 1)
    return a + tick * np.arange(n + 1)


def geometric_edges(lo: float, hi: float, pct: float) -> np.ndarray:
    """Edges at (1 + pct/100) ** k for whole k, covering [lo, hi]. The grid is anchored at 1, not at the data, so a bin means the same price whatever else is in the
    history (a profile at date t does not change when later prices change the range of the grid)."""
    r = 1.0 + pct / 100.0
    k0 = int(np.floor(np.log(lo) / np.log(r)))
    k1 = int(np.ceil(np.log(hi) / np.log(r)))
    return r ** np.arange(k0, max(k1, k0 + 1) + 1, dtype=float)


def distribute(high, low, vol, edges: np.ndarray) -> np.ndarray:
    """Spread each bar's volume uniformly over [low, high] across the bins `edges` (n+1 edges, n bins); a bar with no range goes whole to its bin. Volume is conserved
    for bars inside the grid. Returns the summed volume per bin."""
    high, low, vol = (np.asarray(x, float).ravel() for x in (high, low, vol))
    nb = len(edges) - 1
    out = np.zeros(nb)
    ok = np.isfinite(high) & np.isfinite(low) & np.isfinite(vol) & (vol > 0)
    high, low, vol = high[ok], low[ok], vol[ok]
    flat = (high - low) <= 1e-12 * np.maximum(np.abs(high), 1.0)
    if flat.any():
        idx = np.clip(np.searchsorted(edges, low[flat], side="right") - 1, 0, nb - 1)
        np.add.at(out, idx, vol[flat])
    if (~flat).any():
        h, l, v = high[~flat], low[~flat], vol[~flat]
        for s in range(0, len(h), 400):                         # chunked: the overlap matrix is bars x bins
            hh, ll, vv = h[s:s + 400], l[s:s + 400], v[s:s + 400]
            ov = np.clip(np.minimum(hh[:, None], edges[None, 1:]) - np.maximum(ll[:, None], edges[None, :-1]), 0.0, None)
            out += (ov / (hh - ll)[:, None] * vv[:, None]).sum(0)
    return out


def distribute_rows(high, low, vol, edges: np.ndarray) -> np.ndarray:
    """Like `distribute` but one row per bar (a matrix bars x bins), for rolling sums."""
    high, low, vol = (np.asarray(x, float).ravel() for x in (high, low, vol))
    n, nb = len(high), len(edges) - 1
    M = np.zeros((n, nb))
    ok = np.isfinite(high) & np.isfinite(low) & np.isfinite(vol) & (vol > 0)
    flat = ok & ((high - low) <= 1e-12 * np.maximum(np.abs(high), 1.0))
    if flat.any():
        idx = np.clip(np.searchsorted(edges, low[flat], side="right") - 1, 0, nb - 1)
        M[np.flatnonzero(flat), idx] = vol[flat]
    ranged = ok & ~flat
    rows = np.flatnonzero(ranged)
    for s in range(0, len(rows), 300):
        r = rows[s:s + 300]
        hh, ll = high[r], low[r]
        ov = np.clip(np.minimum(hh[:, None], edges[None, 1:]) - np.maximum(ll[:, None], edges[None, :-1]), 0.0, None)
        M[r] = ov / (hh - ll)[:, None] * vol[r][:, None]
    return M


def poc_index(v: np.ndarray) -> Optional[int]:
    """The bin with the most volume; a tie goes to the bin nearest the middle of the traded range (first and last bin with volume)."""
    v = np.asarray(v, float)
    if not np.isfinite(v).any() or np.nanmax(v) <= 0:
        return None
    m = np.nanmax(v)
    cand = np.flatnonzero(v >= m * (1 - 1e-9))
    if len(cand) == 1:
        return int(cand[0])
    nz = np.flatnonzero(v > 0)
    mid = (nz[0] + nz[-1]) / 2.0
    return int(cand[np.argmin(np.abs(cand - mid))])


def value_area_idx(v: np.ndarray, poc: int, frac: float = 0.70) -> Tuple[int, int]:
    """(lowest, highest) bin index of the value area: from the POC, add the two bins above or the two below (whichever holds more volume; a tie goes up) until
    `frac` of the volume is inside. Where one side has run out the other side is taken."""
    v = np.asarray(v, float)
    n = len(v)
    target = frac * float(v.sum())
    lo = hi = int(poc)
    acc = float(v[poc])
    while acc < target - 1e-12 and (lo > 0 or hi < n - 1):
        up = v[hi + 1:hi + 3].sum() if hi < n - 1 else -1.0
        dn = v[max(lo - 2, 0):lo].sum() if lo > 0 else -1.0
        if up >= dn:
            k = min(2, n - 1 - hi)
            acc += float(v[hi + 1:hi + 1 + k].sum())
            hi += k
        else:
            k = min(2, lo)
            acc += float(v[lo - k:lo].sum())
            lo -= k
    return lo, hi


def nodes(v: np.ndarray, hvn_factor: float = 1.3, lvn_factor: float = 0.5, width: int = 2) -> Tuple[List[int], List[int]]:
    """(high-volume node bins, low-volume node bins). Mean is taken over bins inside the traded range."""
    v = np.asarray(v, float)
    nz = np.flatnonzero(v > 0)
    if len(nz) < 3:
        return [], []
    a, b = int(nz[0]), int(nz[-1])
    mean = float(v[a:b + 1].mean())
    hv, lv = [], []
    for i in range(a, b + 1):
        w0, w1 = max(a, i - width), min(b, i + width)
        nb = np.concatenate([v[w0:i], v[i + 1:w1 + 1]])
        if len(nb) == 0:
            continue
        if v[i] > nb.max() and v[i] >= hvn_factor * mean:
            hv.append(i)
        if a < i < b and v[i] < nb.min() and v[i] <= lvn_factor * mean:
            lv.append(i)
    return hv, lv


@dataclass
class Profile:
    edges: np.ndarray
    vol: np.ndarray
    frac: float = 0.70

    @property
    def centers(self) -> np.ndarray:
        return (self.edges[:-1] + self.edges[1:]) / 2.0

    @property
    def total(self) -> float:
        return float(self.vol.sum())

    def summary(self, hvn_factor: float = 1.3, lvn_factor: float = 0.5, width: int = 2) -> Optional[dict]:
        p = poc_index(self.vol)
        if p is None:
            return None
        lo, hi = value_area_idx(self.vol, p, self.frac)
        hv, lv = nodes(self.vol, hvn_factor, lvn_factor, width)
        c = self.centers
        return {"poc": float(c[p]), "val": float(self.edges[lo]), "vah": float(self.edges[hi + 1]), "volume": self.total,
                "va_share": float(self.vol[lo:hi + 1].sum() / self.total) if self.total > 0 else None,
                "hvn": [float(c[i]) for i in hv], "lvn": [float(c[i]) for i in lv],
                "low": float(self.edges[np.flatnonzero(self.vol > 0)[0]]), "high": float(self.edges[np.flatnonzero(self.vol > 0)[-1] + 1])}


def build(high, low, vol, edges: np.ndarray, frac: float = 0.70) -> Profile:
    return Profile(np.asarray(edges, float), distribute(high, low, vol, edges), frac)


def developing_poc(high, low, vol, edges: np.ndarray, points: int = 8) -> List[Tuple[int, float]]:
    """(bar number, POC price) after k bars, at about `points` evenly spaced bars and the last bar."""
    M = distribute_rows(high, low, vol, edges)
    n = len(M)
    if n == 0:
        return []
    cum = np.cumsum(M, axis=0)
    ks = sorted({int(round(x)) for x in np.linspace(0, n - 1, min(points, n))} | {n - 1})
    c = (edges[:-1] + edges[1:]) / 2.0
    out = []
    for k in ks:
        p = poc_index(cum[k])
        if p is not None:
            out.append((k + 1, float(c[p])))
    return out


def naked_pocs(session_pocs: Sequence[Tuple[object, float]], highs: Sequence[float], lows: Sequence[float]) -> List[dict]:
    """Prior session POCs that no LATER session's [low, high] has touched. `session_pocs` is oldest first as (date, poc); highs and lows are per session in the same order."""
    out = []
    for i, (d, p) in enumerate(session_pocs[:-1]):
        later_h, later_l = highs[i + 1:], lows[i + 1:]
        touched = any(l <= p <= h for h, l in zip(later_h, later_l))
        if not touched:
            out.append({"date": str(d), "poc": float(p), "sessions_ago": len(session_pocs) - 1 - i})
    return out


def migration(pocs: Sequence[float], va_height: float, lookback: int = 5, band: float = 0.25) -> dict:
    """POC now against `lookback` sessions ago, in value-area heights; direction up/down/flat with a dead band."""
    if len(pocs) <= lookback or not va_height or va_height <= 0:
        return {"direction": None, "note": "too few sessions"}
    d = float(pocs[-1]) - float(pocs[-1 - lookback])
    h = d / va_height
    return {"direction": "up" if h > band else "down" if h < -band else "flat", "change": d, "change_va_heights": h, "lookback_sessions": lookback, "dead_band": band}


# ======================================================================================================================================
# the data: minute bars, Kite feed volume, daily bars
# ======================================================================================================================================
BAR_COLS = ["ts", "open", "high", "low", "close", "volume"]


def _bars(con, market: str, key: str, start, end, root=None) -> pd.DataFrame:
    """Minute bars for `key` (an ISIN or INDEX:<name>) from `start` to `end` (dates, inclusive): the table `bars_1m` first, then, where present, the backfill's parquet
    `<root>/bars_1m/<market>/<key>.parquet` (a ':' in the key may be written '_' or '-'). A bar in both is the table's. Neither existing gives an empty frame."""
    lo = datetime.combine(pd.Timestamp(start).date(), time(0, 0)) if start is not None else datetime(1990, 1, 1)
    hi = datetime.combine(pd.Timestamp(end).date(), time(23, 59, 59)) if end is not None else datetime(2999, 1, 1)
    parts = []
    try:
        if con is not None:
            t = con.execute("SELECT ts, open, high, low, close, volume FROM bars_1m WHERE market=? AND isin=? AND ts>=? AND ts<=? ORDER BY ts", [market, key, lo, hi]).df()
            if len(t):
                parts.append(t[BAR_COLS])
    except Exception:
        pass
    try:
        base = Path(root) if root else None
        if base is None:
            from pflab.data import data_dir
            base = data_dir()
        for nm in dict.fromkeys([key, key.replace(":", "_"), key.replace(":", "-")]):
            p = base / "bars_1m" / market / f"{nm}.parquet"
            if p.exists():
                f = pd.read_parquet(p)
                f["ts"] = pd.to_datetime(f["ts"])
                f = f[(f["ts"] >= lo) & (f["ts"] <= hi)]
                if len(f):
                    parts.append(f[[c for c in BAR_COLS if c in f.columns]])
                break
    except Exception:
        pass
    if not parts:
        return pd.DataFrame(columns=BAR_COLS)
    df = pd.concat(parts, ignore_index=True).drop_duplicates("ts", keep="first").sort_values("ts").reset_index(drop=True)
    return df


def _depth_ticks(root, instrument: str, day: date, min_snapshots: int = 200) -> pd.DataFrame:
    """Trade-level volume from the Kite feed recorder (data/kite_depth/<date>.parquet): the rise of the day's cumulative `volume` between snapshots, put at the snapshot's
    `last_price`. A bar-shaped frame (high = low = last price). Empty when the day was not recorded for this instrument or has fewer than `min_snapshots`."""
    try:
        from pflab.data import data_dir
        p = (Path(root) if root else data_dir()) / "kite_depth" / f"{day:%Y-%m-%d}.parquet"
        if not p.exists():
            return pd.DataFrame(columns=BAR_COLS)
        df = pd.read_parquet(p)
        df = df[df["instrument"] == instrument].sort_values("ts")
        df = df[pd.to_numeric(df["volume"], errors="coerce").notna() & pd.to_numeric(df["last_price"], errors="coerce").notna()]
        if len(df) < min_snapshots:
            return pd.DataFrame(columns=BAR_COLS)
        inc = df["volume"].astype(float).diff().clip(lower=0).fillna(0.0)
        px = df["last_price"].astype(float)
        out = pd.DataFrame({"ts": pd.to_datetime(df["ts"]), "open": px, "high": px, "low": px, "close": px, "volume": inc})
        out = out[out["volume"] > 0].reset_index(drop=True)
        return out if out["volume"].sum() > 0 else pd.DataFrame(columns=BAR_COLS)
    except Exception:
        return pd.DataFrame(columns=BAR_COLS)


def _index_name(key: str) -> Optional[str]:
    k = key[len(INDEX_PREFIX):] if key.startswith(INDEX_PREFIX) else key
    return k.strip().upper()


def _daily(con, market: str, key: str, start=None, end=None, root=None) -> pd.DataFrame:
    """Daily bars [date, open, high, low, close, volume, basis]: an index file (indices/<KEY>.parquet or global/<KEY>.parquet), else an ISIN from the research panel
    (IN, adjusted: high and low x adj_factor, weight = traded value / adjusted close) or the US file. `volume` is NaN where the series has none (then the basis says how
    it is weighted). Empty when nothing is found."""
    from pflab.data import data_dir
    root = Path(root) if root else data_dir()
    nm = _index_name(key) if (key.startswith(INDEX_PREFIX) or key.upper() in INDEX_FILES or (root / "indices" / f"{key}.parquet").exists()
                              or (root / "global" / f"{key}.parquet").exists()) else None
    df = None
    try:
        if nm is not None:
            fname = INDEX_FILES.get(nm, nm.replace(" ", "_"))
            for sub in ("indices", "global"):
                for cand in (fname, key):
                    p = root / sub / f"{cand}.parquet"
                    if p.exists():
                        df = pd.read_parquet(p)
                        break
                if df is not None:
                    break
        else:
            from pflab import _duck
            f = root / ("us" if key.startswith(("US:", "ZZ")) else "panel") / "prices.parquet"
            if f.exists():
                d = _duck.sql(f"SELECT date, open, high, low, close, volume, turnover, adj_factor, adj_close FROM '{f.as_posix()}' WHERE isin = '{key}' ORDER BY date").df()
                if len(d):
                    af = d["adj_factor"].astype(float).where(lambda s: s > 0, 1.0)
                    w = d["turnover"].astype(float) / d["adj_close"].astype(float).where(lambda s: s > 0)
                    w = w.where(np.isfinite(w), d["volume"].astype(float))
                    df = pd.DataFrame({"date": d["date"], "open": d["open"] * af, "high": d["high"] * af, "low": d["low"] * af, "close": d["adj_close"], "volume": w})
    except Exception:
        df = None
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "basis"])
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    for c in ("open", "high", "low", "volume"):
        if c not in df.columns:
            df[c] = np.nan
    if df["high"].isna().all() or df["low"].isna().all():
        df["high"], df["low"] = df["close"], df["close"]
        basis = B_CLOSE
    else:
        basis = None
    has_vol = df["volume"].notna().any() and float(df["volume"].fillna(0).sum()) > 0
    if basis is None:
        basis = B_DAILY if has_vol else B_TIME
    if not has_vol:
        df["volume"] = 1.0                                       # time at price: every day weighs the same
    df["basis"] = basis
    df = df[["date", "open", "high", "low", "close", "volume", "basis"]].dropna(subset=["close"]).drop_duplicates("date", keep="last").sort_values("date")
    if start is not None:
        df = df[df["date"] >= pd.Timestamp(start)]
    if end is not None:
        df = df[df["date"] <= pd.Timestamp(end)]
    return df.reset_index(drop=True)


# ======================================================================================================================================
# the daily rolling composite: every date's profile of the last W days (for the lens and the event study)
# ======================================================================================================================================

def rolling_profile(daily: pd.DataFrame, window: int = 20, bin_pct: float = 0.25, frac: float = 0.70) -> pd.DataFrame:
    """For each date t, the profile of the days t-window+1 .. t (daily bars spread over their range, one geometric grid for the whole history). Columns:
    poc, val, vah, volume (the window's); NaN until `window` days exist. Index = the daily frame's dates. Uses only days <= t."""
    n = len(daily)
    cols = ["poc", "val", "vah", "volume"]
    if n < window or n == 0:
        return pd.DataFrame(np.nan, index=pd.DatetimeIndex(daily["date"]) if n else pd.DatetimeIndex([]), columns=cols)
    hi = daily["high"].to_numpy(float)
    lo = daily["low"].to_numpy(float)
    vol = daily["volume"].to_numpy(float)
    edges = geometric_edges(float(np.nanmin(lo)) * 0.999, float(np.nanmax(hi)) * 1.001, bin_pct)
    M = distribute_rows(hi, lo, vol, edges)
    C = np.vstack([np.zeros((1, M.shape[1])), np.cumsum(M, axis=0)])
    c = (edges[:-1] + edges[1:]) / 2.0
    out = np.full((n, 4), np.nan)
    for t in range(window - 1, n):
        v = C[t + 1] - C[t + 1 - window]
        p = poc_index(v)
        if p is None:
            continue
        a, b = value_area_idx(v, p, frac)
        out[t] = (c[p], edges[a], edges[b + 1], v.sum())
    return pd.DataFrame(out, index=pd.DatetimeIndex(daily["date"]), columns=cols)


def event_frame(daily: pd.DataFrame, window: int = 20, bin_pct: float = 0.25, frac: float = 0.70, lookback: int = 5, band: float = 0.25) -> pd.DataFrame:
    """Per date t, features known at t's close (rows <= t only):
        poc, val, vah          the rolling profile through t
        outside                +1 close above / -1 below / 0 inside the value area of the PRIOR day's profile (through t-1: where value was before today's trade)
        dist_pct               how far outside that value area, % of the close (0 when inside)
        poc_change_va          POC(t) - POC(t - lookback) in value-area heights of t - lookback
        mig                    +1 / -1 / 0 beyond a dead band of `band` value-area heights
    """
    rp = rolling_profile(daily, window, bin_pct, frac)
    df = rp.copy()
    df["close"] = daily["close"].to_numpy(float)
    pv, ph = df["val"].shift(1), df["vah"].shift(1)
    c = df["close"]
    df["outside"] = np.where(pv.isna(), np.nan, np.where(c > ph, 1.0, np.where(c < pv, -1.0, 0.0)))
    df["dist_pct"] = np.where(df["outside"] == 1.0, (c - ph) / c * 100.0, np.where(df["outside"] == -1.0, (pv - c) / c * 100.0, np.where(pv.isna(), np.nan, 0.0)))
    height = (df["vah"] - df["val"]).shift(lookback)
    df["poc_change_va"] = (df["poc"] - df["poc"].shift(lookback)) / height.where(height > 0)
    df["mig"] = np.where(df["poc_change_va"].isna(), np.nan, np.where(df["poc_change_va"] > band, 1.0, np.where(df["poc_change_va"] < -band, -1.0, 0.0)))
    df["pv"], df["ph"] = pv, ph
    return df


def value_area_events(market: str = "IN", start=None, end=None, key: Optional[str] = None, con=None, root=None, window: Optional[int] = None,
                      daily: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """The dated events the pre-registered value-area study needs (docs/protocols/s79_wave_sentiment_protocol.md), one row per session in [start, end], point in time:

        date, close, poc, val, vah, outside (+1/-1/0), dist_pct, poc_change_va, mig (+1/-1/0), pv, ph (the PRIOR day's value area, frozen)
        basis, n_days_window
      outcomes (NOT features; they look forward from the date):
        back_in_1, back_in_5   True when a close within the next 1 / 5 sessions is back inside [pv, ph] (NaN if the series ends first); only meaningful where outside != 0
        ret_5                  close(t+5)/close(t) - 1 (from the event close)
        ret_5_next             close(t+6)/close(t+1) - 1 (the 5-session return that starts at the NEXT session's close)
        ret_1                  close(t+1)/close(t) - 1

    `key` defaults to the market's index. History is whatever the series holds before `end`; nothing after `end` is read. Minute-bar history is not used here (it is only weeks
    long): the basis column says 'daily approximation' (or 'time at price' / 'close only'). The caller states n and the date range."""
    cfg = settings()
    if not cfg.get("on", True):
        return pd.DataFrame()
    from pflab import markets
    key = key or INDEX_PREFIX + markets.get(market).index
    window = int(window or cfg["window_sessions"])
    if daily is None:
        daily = _daily(con, market, key, None, end, root)
    elif end is not None:
        daily = daily[daily["date"] <= pd.Timestamp(end)].reset_index(drop=True)
    if len(daily) < window + 10:
        return pd.DataFrame()
    ev = event_frame(daily, window, float(cfg["bin_pct"]), float(cfg["value_area_pct"]), int(cfg["migrate_lookback"]), float(cfg["migrate_band"]))
    c = ev["close"].to_numpy(float)
    n = len(c)
    inside = ((c >= ev["pv"].to_numpy(float)) & (c <= ev["ph"].to_numpy(float)))
    for k, name in ((1, "back_in_1"), (5, "back_in_5")):
        res = np.full(n, np.nan)
        for t in range(n):
            if t + k >= n:
                break
            res[t] = float(inside[t + 1:t + k + 1].any()) if np.isfinite(ev["pv"].iloc[t]) else np.nan
        ev[name] = res
    ev["ret_1"] = pd.Series(c, index=ev.index).shift(-1) / c - 1.0
    ev["ret_5"] = pd.Series(c, index=ev.index).shift(-5) / c - 1.0
    ev["ret_5_next"] = pd.Series(c, index=ev.index).shift(-6) / pd.Series(c, index=ev.index).shift(-1) - 1.0
    ev["basis"] = daily["basis"].iloc[0]
    ev["n_days_window"] = window
    ev.insert(0, "date", [d.date() for d in ev.index])
    ev = ev.reset_index(drop=True)
    if start is not None:
        ev = ev[ev["date"] >= pd.Timestamp(start).date()]
    if end is not None:
        ev = ev[ev["date"] <= pd.Timestamp(end).date()]
    return ev.dropna(subset=["poc"]).reset_index(drop=True)


# ======================================================================================================================================
# the report: per session and composite (the tool's result)
# ======================================================================================================================================

def _day_bars(con, market: str, key: str, day: date, root, symbol: Optional[str], cfg: dict) -> Tuple[pd.DataFrame, Optional[str]]:
    """The best volume record of one session: Kite feed trades, else minute bars. (frame, basis) or (empty, None)."""
    if symbol and not key.startswith(INDEX_PREFIX):
        t = _depth_ticks(root, f"NSE:{symbol}", day, int(cfg["min_depth_snapshots"]))
        if len(t):
            return t, B_DEPTH
    b = _bars(con, market, key, day, day, root)
    b = b[b["volume"].fillna(0) > 0] if len(b) else b
    if len(b):
        return b, B_MINUTE
    return b, None


def report(con, market: str, key: str, as_of: date, root=None, symbol: Optional[str] = None, sessions: Optional[int] = None, name: Optional[str] = None) -> dict:
    """The profile of `key` at the close of `as_of`: the last session and a composite of up to `sessions` sessions. Minute/feed profiles where at least `min_minute_sessions`
    sessions have them, else the daily rolling profile. Every figure carries the basis."""
    from pflab import markets
    cfg = settings()
    m = markets.get(market)
    n_s = int(sessions or cfg["max_sessions"])
    end = m.last_session_on_or_before(as_of)
    days = m.sessions_between(m.session_after(end, -(n_s - 1)), end)
    out: dict = {"market": market, "key": key, "symbol": name or symbol or key, "as_of": str(as_of)}
    got = []
    for d in days:
        b, basis = _day_bars(con, market, key, d, root, symbol, cfg)
        if basis:
            got.append((d, b, basis))
    if len(got) >= int(cfg["min_minute_sessions"]):
        return _minute_report(out, got, as_of, cfg, len(days))
    return _daily_report(out, con, market, key, as_of, root, cfg, len(got), len(days))


def _minute_report(out: dict, got: list, as_of: date, cfg: dict, n_days: int) -> dict:
    lo = min(float(b["low"].min()) for _, b, _ in got)
    hi = max(float(b["high"].max()) for _, b, _ in got)
    tick = max((hi - lo) / int(cfg["session_bins"]), 1e-9)
    tick = float(f"{tick:.3g}")
    edges = linear_edges(lo, hi, tick)
    frac, hv, lv, w = float(cfg["value_area_pct"]), float(cfg["hvn_factor"]), float(cfg["lvn_factor"]), int(cfg["node_width"])
    sess, pocs, highs, lows = [], [], [], []
    comp = np.zeros(len(edges) - 1)
    for d, b, basis in got:
        p = build(b["high"], b["low"], b["volume"], edges, frac)
        comp += p.vol
        s = p.summary(hv, lv, w)
        if s is None:
            continue
        sess.append((d, b, basis, s))
        pocs.append((d, s["poc"]))
        highs.append(float(b["high"].max()))
        lows.append(float(b["low"].min()))
    if not sess:
        return {**out, "note": "no volume in the minute bars", "basis": B_MINUTE}
    last_d, last_b, last_basis, last_s = sess[-1]
    bases = sorted({s[2] for s in sess})
    comp_s = Profile(edges, comp, frac).summary(hv, lv, w)
    height = comp_s["vah"] - comp_s["val"]
    mig = migration([p for _, p in pocs], height, min(int(cfg["migrate_lookback"]), max(len(pocs) - 1, 1)), float(cfg["migrate_band"]))
    close = float(last_b.sort_values("ts")["close"].iloc[-1])
    nk = naked_pocs(pocs, highs, lows)
    for x in nk:
        x["distance_pct"] = round((x["poc"] / close - 1.0) * 100.0, 3)
        x["side"] = "above" if x["poc"] > close else "below"
    dev = developing_poc(last_b["high"], last_b["low"], last_b["volume"], edges)
    nodes_lv = comp_s["lvn"]
    lv_up = [p for p in nodes_lv if p > close]
    lv_dn = [p for p in nodes_lv if p < close]
    pos = "above" if close > comp_s["vah"] else "below" if close < comp_s["val"] else "inside"
    nk_up = [x for x in nk if x["poc"] > close]
    nk_dn = [x for x in nk if x["poc"] < close]
    near = min(nk, key=lambda x: abs(x["distance_pct"])) if nk else None
    res = {**out, "basis": " + ".join(bases), "mode": "minute", "last_session": str(last_d), "sessions_with_volume": len(sess), "sessions_asked": n_days,
           "bin_size": tick, "close": close,
           "session": {k: _r(v) for k, v in last_s.items()} | {"developing_poc": [{"after_bar": k, "poc": _r(p)} for k, p in dev]},
           "composite": {k: _r(v) for k, v in comp_s.items()} | {"sessions": len(sess), "from": str(sess[0][0]), "to": str(last_d)},
           "poc_migration": {**{k: _r(v) for k, v in mig.items()}, "session_pocs": [{"date": str(d), "poc": _r(p)} for d, p in pocs[-8:]]},
           "naked_pocs": [{**x, "poc": _r(x["poc"])} for x in sorted(nk, key=lambda x: abs(x["distance_pct"]))[:5]],
           "features": {"close_vs_poc_pct": _r((close / comp_s["poc"] - 1.0) * 100.0), "position_vs_value_area": pos,
                        "distance_from_value_area_pct": _r(0.0 if pos == "inside" else ((close / comp_s["vah"] - 1.0) if pos == "above" else (close / comp_s["val"] - 1.0)) * 100.0),
                        "migration": mig.get("direction"),
                        "nearest_naked_poc": near and {"poc": _r(near["poc"]), "distance_pct": near["distance_pct"], "side": near["side"], "date": near["date"]},
                        "naked_pocs_above": len(nk_up), "naked_pocs_below": len(nk_dn),
                        "low_volume_gap_above": _r(min(lv_up)) if lv_up else None, "low_volume_gap_below": _r(max(lv_dn)) if lv_dn else None}}
    return res


def _daily_report(out: dict, con, market: str, key: str, as_of: date, root, cfg: dict, n_minute: int, n_days: int) -> dict:
    d = _daily(con, market, key, None, as_of, root)
    window = int(cfg["window_sessions"])
    if len(d) < window + 10:
        return {**out, "basis": B_DAILY, "note": f"no minute bars ({n_minute} of {n_days} sessions) and too little daily history for a profile ({len(d)} days)"}
    ev = event_frame(d, window, float(cfg["bin_pct"]), float(cfg["value_area_pct"]), int(cfg["migrate_lookback"]), float(cfg["migrate_band"]))
    r = ev.iloc[-1]
    if not np.isfinite(r["poc"]):
        return {**out, "basis": d["basis"].iloc[0], "note": "profile not available"}
    # the composite's low-volume nodes on the same window
    w = d.iloc[-window:]
    edges = geometric_edges(float(w["low"].min()) * 0.999, float(w["high"].max()) * 1.001, float(cfg["bin_pct"]))
    p = build(w["high"], w["low"], w["volume"], edges, float(cfg["value_area_pct"]))
    s = p.summary(float(cfg["hvn_factor"]), float(cfg["lvn_factor"]), int(cfg["node_width"]))
    close = float(r["close"])
    pos = "above" if close > r["vah"] else "below" if close < r["val"] else "inside"
    lvn = s["lvn"] if s else []
    lv_up = [x for x in lvn if x > close]
    lv_dn = [x for x in lvn if x < close]
    mig = {"direction": None if not np.isfinite(r["mig"]) else ("up" if r["mig"] > 0 else "down" if r["mig"] < 0 else "flat"),
           "change_va_heights": _r(r["poc_change_va"]), "lookback_sessions": int(cfg["migrate_lookback"]), "dead_band": float(cfg["migrate_band"])}
    return {**out, "basis": d["basis"].iloc[0], "mode": "daily rolling composite", "last_session": str(d["date"].iloc[-1].date()), "window_sessions": window,
            "minute_sessions_found": n_minute, "close": _r(close),
            "composite": {"poc": _r(r["poc"]), "val": _r(r["val"]), "vah": _r(r["vah"]), "hvn": [_r(x) for x in (s or {}).get("hvn", [])], "lvn": [_r(x) for x in lvn],
                          "sessions": window, "from": str(w["date"].iloc[0].date()), "to": str(w["date"].iloc[-1].date())},
            "poc_migration": mig, "naked_pocs": [],
            "naked_note": "a daily bar has no shape of its own: naked POCs need minute bars",
            "features": {"close_vs_poc_pct": _r((close / r["poc"] - 1.0) * 100.0), "position_vs_value_area": pos,
                         "distance_from_value_area_pct": _r(0.0 if pos == "inside" else ((close / r["vah"] - 1.0) if pos == "above" else (close / r["val"] - 1.0)) * 100.0),
                         "close_outside_prior_value_area": None if not np.isfinite(r["outside"]) else int(r["outside"]),
                         "migration": mig["direction"], "nearest_naked_poc": None, "low_volume_gap_above": _r(min(lv_up)) if lv_up else None,
                         "low_volume_gap_below": _r(max(lv_dn)) if lv_dn else None}}


def _r(v):
    if isinstance(v, (float, np.floating)):
        return None if not np.isfinite(v) else round(float(v), 4)
    if isinstance(v, list):
        return [_r(x) for x in v]
    return v


def profile_line(rep: dict) -> str:
    """One plain sentence for a trajectory explanation. Empty when there is no profile. Figures are the code's, quoted as printed in the result."""
    f = (rep or {}).get("features") or {}
    comp = (rep or {}).get("composite") or {}
    if not f or comp.get("poc") is None:
        return ""
    return (f"Against its volume profile ({rep.get('basis')}), the close sat {f.get('position_vs_value_area')} the value area {comp['val']} to {comp['vah']} "
            f"with the busiest price (POC) at {comp['poc']}" + (f"; the POC migration over recent sessions is {f['migration']}" if f.get("migration") else "") + ".")


# ======================================================================================================================================
# the lens: lens_value_area (item 18D), registered in shadow
# ======================================================================================================================================
LENS_NAME = "lens_value_area"
PROTOCOL = "docs/protocols/s79_wave_sentiment_protocol.md"
_CACHE: Dict[tuple, pd.DataFrame] = {}
_EV: Dict[tuple, pd.DataFrame] = {}


def lens_settings() -> dict:
    return {"on": True, "shrink_n": 60.0, "max_shift_sigma": 0.15, "history_sessions": 3000, **settings("lens")}


def _subject_key(market: str, close: pd.Series) -> str:
    from pflab import markets
    nm = close.name if isinstance(close.name, str) and close.name else None
    idx = markets.get(market).index
    if nm is None or nm == idx:
        return INDEX_PREFIX + idx
    return nm


def lens_frame(con, market: str, close: pd.Series, h: int):
    """Quantiles of the h-session return: the volatility forecaster's spread with its centre shifted by what the value-area states have meant before. Point in time:
    the state at t comes from `event_frame` (rows <= t); each state's mean shift is the mean of the standardised h-session returns that had ALREADY MATURED by t
    (origins k <= t-h), shrunk to zero by n/(n+n0). The centre shift is the sum over the active states, capped at `max_shift_sigma` standard deviations. None when the daily
    bars of the subject are not available."""
    from pflab.fcast import forecasters as F
    cfg, sc = settings(), lens_settings()
    if not (cfg.get("on", True) and sc.get("on", True)) or len(close) < 150:
        return None
    key = _subject_key(market, close)
    ck = (market, key, close.index[0], close.index[-1], len(close), int(h))
    if ck in _CACHE:
        return _CACHE[ck].copy()
    daily = _daily(None, market, key, None, close.index[-1], None)
    cap = int(sc["history_sessions"])
    daily = daily.iloc[-cap:].reset_index(drop=True)          # recent history only: the rolling profile is the slow part, older rows are NaN (no forecast) in the frame
    if len(daily) < int(cfg["window_sessions"]) + 30:
        return None
    close_c = close.iloc[-cap:]
    # the daily file must be the same series as the close it is asked to help forecast (same dates, same level), else the lens does not forecast
    dc = pd.Series(daily["close"].to_numpy(float), index=pd.DatetimeIndex(daily["date"]))
    dc = dc[~dc.index.duplicated(keep="last")]
    common = close_c.index.intersection(dc.index)
    if len(common) < 0.9 * len(close_c) or float(np.nanmedian(np.abs(dc.loc[common].to_numpy() / close_c.loc[common].to_numpy() - 1.0))) > 0.02:
        return None
    ek = (market, key, daily["date"].iloc[0], daily["date"].iloc[-1], len(daily))
    if ek not in _EV:
        e0 = event_frame(daily, int(cfg["window_sessions"]), float(cfg["bin_pct"]), float(cfg["value_area_pct"]), int(cfg["migrate_lookback"]), float(cfg["migrate_band"]))
        e0.index = pd.DatetimeIndex(daily["date"])
        _EV[ek] = e0[~e0.index.duplicated(keep="last")]
        if len(_EV) > 6:
            _EV.pop(next(iter(_EV)))
    ev = _EV[ek].reindex(close.index)
    lc, r, sig, ew = F._vol_parts(close)
    s = F._sigma_h(sig, ew, h, False)
    zf = (lc.shift(-h) - lc) / s                                  # the standardised h-session outcome of origin k (known only from k+h on)
    shift = pd.Series(0.0, index=close.index)
    n0 = float(sc["shrink_n"])
    for ind in ((ev["outside"] == 1.0), (ev["outside"] == -1.0), (ev["mig"] == 1.0), (ev["mig"] == -1.0)):
        i = ind.fillna(False).astype(float)
        num = (i * zf.fillna(0.0)).where(zf.notna(), 0.0).cumsum().shift(h).fillna(0.0)       # outcomes matured by t: origins k <= t-h
        cnt = (i * zf.notna()).cumsum().shift(h).fillna(0.0)
        mean = num / (cnt + n0)
        shift = shift + (i * mean)
    cap = float(sc["max_shift_sigma"])
    mu = shift.clip(-cap, cap) * s
    out = F._frame(mu.where(s.notna() & ev["pv"].notna()), s)
    _CACHE[ck] = out
    if len(_CACHE) > 24:
        _CACHE.pop(next(iter(_CACHE)))
    return out.copy()


def register_lens() -> None:
    """Register lens_value_area (shadow). Called by the tool module's import and by `fcast.plugins`."""
    from pflab.fcast import plugins
    plugins.register(plugins.Lens(LENS_NAME, ("IN", "US"), PROTOCOL, lens_frame, True,
                                  "close outside the prior value area and POC migration shift the centre of the next-1/5/20-session return quantiles (daily approximation)"))
