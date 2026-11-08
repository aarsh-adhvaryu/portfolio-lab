"""Market waves, rotations and crude falls (S79b item 15), flagged by code from thresholds the history sets for itself.

Everything here is a DEFINITION: fixed constants below, thresholds taken from the series' own distribution, point in time. The pre-registration is
`docs/protocols/s79_wave_sentiment_protocol.md`; an event study may count these events, it may not move these constants.

REFERENCE SAMPLE.  A threshold at session M is a percentile of the series' values at sessions BEFORE M and not after REF_END (2021-12-31): so up to 2021 it is
an expanding percentile of the history, and from 2022 on it stays frozen at the 2004-2021 sample (the spent years 2022-2025 never tune anything). It needs
MIN_REF = 500 earlier values; before that the flag is "not decided" (a count, no conclusion).

WAVE (market-wide, IN; the cross-section is the NSE daily files, price returns = close / the exchange's prior close - 1, |return| < 40%):
  breadth     advancing share = advancers / names that traded (all EQ names; the definition of `quant/breadth.py`) is in the top or bottom BREADTH_TAIL (2.5%) of
              the reference sample;
  dispersion  the spread of the 500 most-traded names' returns (1.4826 x the median absolute deviation) divided by |their median return| is at or below the
              DISP_PCT (50th) percentile of the reference sample (the names moved together: little spread around the common move);
  dominance   the share of those names whose MARKET part beats their OWN part, |beta x Nifty 500 move| > |return - beta x Nifty 500 move| (the first step of
              `quant/decompose.decompose`, betas = OLS slopes over the 250 sessions before the day), is at least the DOM_PCT (80th) percentile of the reference
              sample AND more than half.
  The three cut-offs were chosen for RARITY only (a wave should be about one session in 35, a day worth interrupting for), from how often the statistics are
  extreme, before any return was looked at; no return after a wave entered their choice.
  A wave is up when the median return is positive, down when negative. The 500 most-traded names are the 500 with the largest mean daily turnover over the 60
  sessions before the day.

ROTATION (IN, needs the foreign-flow history, which starts 2009-12 in the NSDL file, so no flag before about 2012):
  flows       the foreign net equity flow of session T (Rs crore), divided by its standard deviation over the 250 sessions before T, called z;
  switch IN   the STREAK_MIN (3) sessions before T were all net selling and z >= the ROT_Z_PCT (95th) percentile of z; the mirror (a buying streak, then z at or
              below the 5th percentile) is a switch OUT;
  divergence  India against its Asian peers, g = Nifty 500 move - the average move of Kospi, Taiex, Nikkei and Hang Seng (percent): a switch IN needs g at or above
              the GAP_PCT (80th) percentile of g, a switch OUT needs g at or below the 20th (India moves with the flow, away from Asia).
  A day's flow is reported on the NEXT business day, so the flag is dated at T and `known_on` is that next session: an event study starts its forward return there.

CRUDE FALL: a one-session Brent (IN) / WTI (US) fall at or below the CRUDE_PCT (2nd) percentile of the earlier one-day moves (reference sample as above).

`wave_events`, `rotation_events` and `crude_fall_events` return dated events using only data before each date; `wave_note` writes the post-close paragraph;
`lens_wave` is the forecaster plug-in (shadow): after a wave flag it shifts and scales the next 1/5/20 session quantiles by what earlier waves did (shrunk to
no effect while few), the fit using only waves whose forward window had ended and none after REF_END.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pflab import _duck, markets
from pflab.quant import macro_attr as MA

REF_END = date(2021, 12, 31)
MIN_REF = 500
BREADTH_TAIL = 0.025
DISP_PCT = 0.50
DOM_PCT = 0.80
UNIV_N = 500
TURNOVER_WINDOW = 60
BETA_WINDOW = 250
BETA_MIN = 60
SPLIT_GUARD = 0.40
STREAK_MIN = 3
ROT_Z_PCT = 0.95
GAP_PCT = 0.80
FLOW_Z_WINDOW = 250
CRUDE_PCT = 0.02
SHRINK_N0 = 20
STATS_COLS = ["adv_share", "n_all", "xs_disp", "med_ret", "disp_ratio", "dom_share", "n_univ"]
DEFINITION = ("wave = advancing share in the top/bottom 2.5% of earlier sessions AND the spread of the 500 most-traded names around their median return at or below its "
              "median AND the market part larger than the own part for at least the 80th percentile (and over half) of those names; thresholds from sessions "
              "before the day and not after 2021")


def settings() -> dict:
    try:
        from pflab import _toml
        p = Path(__file__).resolve().parents[3] / "configs" / "s79b.toml"
        return dict(_toml.load(p).get("waves", {}) or {})
    except Exception:
        return {}


def is_on() -> bool:
    return bool(settings().get("on", True))


# --- the cross-section ---------------------------------------------------------------------------------------------------

def _long(root: Path, d0: date, d1: date) -> pd.DataFrame:
    """date, isin, ret, turnover for series EQ: the adjusted panel up to its last date, then the NSE daily files after it."""
    root = Path(root)
    frames = []
    pmax = None
    pp = root / "panel" / "prices.parquet"
    if pp.exists():
        pmax = _duck.sql(f"SELECT max(CAST(date AS DATE)) FROM read_parquet('{pp.as_posix()}')").fetchone()[0]
        frames.append(_duck.sql(
            f"SELECT CAST(date AS DATE) AS date, isin, close / prev_close - 1.0 AS ret, turnover FROM read_parquet('{pp.as_posix()}') "
            f"WHERE series = 'EQ' AND close > 0 AND prev_close > 0 AND CAST(date AS DATE) BETWEEN DATE '{d0}' AND DATE '{d1}'").df())
    base = root / "bhavcopy"
    files = []
    for f in sorted(base.glob("*/*.parquet")) if base.exists() else []:
        try:
            d = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if d0 <= d <= d1 and (pmax is None or d > pmax):
            files.append(f)
    if files:
        lst = ",".join("'" + p.as_posix() + "'" for p in files)
        frames.append(_duck.sql(
            f"SELECT CAST(date AS DATE) AS date, isin, close / prev_close - 1.0 AS ret, turnover FROM read_parquet([{lst}], union_by_name=true) "
            "WHERE series = 'EQ' AND close > 0 AND prev_close > 0 AND isin IS NOT NULL").df())
    if not frames:
        return pd.DataFrame(columns=["date", "isin", "ret", "turnover"])
    return pd.concat(frames, ignore_index=True)


def _wide(df: pd.DataFrame):
    """(dates, R, T): returns and turnover as (sessions x names) arrays, NaN where the name has no row."""
    di, dates = pd.factorize(pd.to_datetime(df["date"]), sort=True)
    ii, _names = pd.factorize(df["isin"])
    R = np.full((len(dates), int(ii.max()) + 1 if len(ii) else 0), np.nan)
    T = np.full_like(R, np.nan)
    R[di, ii] = df["ret"].to_numpy(float)
    T[di, ii] = df["turnover"].to_numpy(float)
    return [d.date() for d in pd.DatetimeIndex(dates)], R, T


def _roll(a: np.ndarray, w: int) -> np.ndarray:
    return pd.DataFrame(a).rolling(w, min_periods=1).sum().to_numpy()


def stats_from_arrays(dates: List[date], R: np.ndarray, T: np.ndarray, m: np.ndarray, report_from: Optional[date] = None) -> pd.DataFrame:
    """Wave statistics per session from the returns matrix R (sessions x names, fractions), turnover T and the Nifty 500 move m (fraction per session, NaN allowed).
    Rows before `report_from` only warm the windows. Point in time: row i uses rows <= i (betas and turnover ranks use rows < i)."""
    R = np.where(np.abs(R) < SPLIT_GUARD, R, np.nan)
    nd, nn = R.shape
    valid = np.isfinite(R) & np.isfinite(m)[:, None]
    mv = np.where(np.isfinite(m), m, 0.0)[:, None]
    Rz = np.where(np.isfinite(R), R, 0.0)
    vm = valid.astype(float)
    n = _roll(vm, BETA_WINDOW)
    sx, sxx = _roll(vm * mv, BETA_WINDOW), _roll(vm * mv * mv, BETA_WINDOW)
    sy, sxy = _roll(Rz * vm, BETA_WINDOW), _roll(Rz * vm * mv, BETA_WINDOW)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = sxy / n - (sx / n) * (sy / n)
        var = sxx / n - (sx / n) ** 2
        beta = np.where((n >= BETA_MIN) & (var > 1e-12), cov / var, np.nan)
    beta = np.vstack([np.full((1, nn), np.nan), beta[:-1]])                      # the window ends the session BEFORE the day
    Tm = pd.DataFrame(T).rolling(TURNOVER_WINDOW, min_periods=20).mean().shift(1)
    rank = Tm.rank(axis=1, ascending=False).to_numpy()
    univ = np.isfinite(rank) & (rank <= UNIV_N)
    rows = []
    for i, d in enumerate(dates):
        if report_from is not None and d < report_from:
            continue
        r = R[i]
        ok = np.isfinite(r)
        n_all = int(ok.sum())
        if n_all == 0:
            continue
        adv = int((r[ok] > 0).sum())
        u = ok & univ[i]
        rec = {"session": d, "adv_share": adv / n_all, "n_all": n_all, "xs_disp": np.nan, "med_ret": np.nan, "disp_ratio": np.nan, "dom_share": np.nan, "n_univ": int(u.sum())}
        if u.sum() >= 50:
            ru = r[u]
            med = float(np.median(ru))
            disp = float(1.4826 * np.median(np.abs(ru - med)))
            rec.update(xs_disp=disp, med_ret=med, disp_ratio=disp / max(abs(med), 1e-4))
            b = beta[i][u]
            g = np.isfinite(b) & np.isfinite(m[i])
            if g.sum() >= 50:
                part = b[g] * m[i]
                rec["dom_share"] = float((np.abs(part) > np.abs(ru[g] - part)).mean())
        rows.append(rec)
    return pd.DataFrame(rows).set_index("session") if rows else pd.DataFrame(columns=STATS_COLS)


def cache_path(root: Path, market: str = "IN") -> Path:
    return Path(root) / "derived" / f"wave_stats_{market}.parquet"


def load_cache(root: Path, market: str = "IN") -> pd.DataFrame:
    p = cache_path(root, market)
    if not p.exists():
        return pd.DataFrame(columns=STATS_COLS)
    try:
        d = pd.read_parquet(p)
        d["session"] = pd.to_datetime(d["session"]).dt.date
        return d.set_index("session").sort_index()
    except Exception:
        return pd.DataFrame(columns=STATS_COLS)


def compute_stats(root: Path, start: date, end: date, block: int = 700) -> pd.DataFrame:
    """Wave statistics for every session with data in [start, end], in blocks (each block re-reads ~480 calendar days of warm-up)."""
    root = Path(root)
    m_ret = MA.index_moves(root, "IN") / 100.0
    parts = []
    s = start
    while s <= end:
        e = min(end, s + timedelta(days=int(block * 1.45)))
        df = _long(root, s - timedelta(days=480), e)
        if len(df):
            dates, R, T = _wide(df)
            m = m_ret.reindex(dates).to_numpy(float)
            parts.append(stats_from_arrays(dates, R, T, m, report_from=s))
            del R, T, df
        s = e + timedelta(days=1)
    return pd.concat(parts) if parts else pd.DataFrame(columns=STATS_COLS)


def ensure_stats(root: Path, upto: date, market: str = "IN", max_new_sessions: Optional[int] = None) -> pd.DataFrame:
    """The cached statistics extended through `upto` (the file is written back). `max_new_sessions` stops a tool from starting the one-off history build: when more
    sessions than that are missing the cache is returned as it is."""
    if market != "IN":
        return pd.DataFrame(columns=STATS_COLS)
    cache = load_cache(root, market)
    start = date(2004, 1, 1) if cache.empty else cache.index[-1] + timedelta(days=1)
    if start > upto:
        return cache
    if max_new_sessions is not None and (upto - start).days > max_new_sessions * 1.5:
        return cache
    new = compute_stats(root, start, upto)
    if new.empty:
        return cache
    out = pd.concat([cache, new[~new.index.isin(cache.index)]]).sort_index()
    p = cache_path(root, market)
    p.parent.mkdir(parents=True, exist_ok=True)
    o = out.reset_index().rename(columns={"index": "session"})
    o["session"] = pd.to_datetime(o["session"])
    o.to_parquet(p, index=False)
    return out


# --- thresholds and flags ------------------------------------------------------------------------------------------------

def expanding_q(x: pd.Series, q: float, min_n: int = MIN_REF) -> pd.Series:
    """The q-quantile of the finite values BEFORE each row and not after REF_END (NaN while fewer than min_n)."""
    idx = list(x.index)
    a = x.to_numpy(float)
    ref = np.array([d <= REF_END for d in idx])
    last_ref = int(ref.sum())                                   # rows are sorted by date: the reference rows come first
    out = np.full(len(a), np.nan)
    frozen = None
    for i in range(len(a)):
        stop = min(i, last_ref)
        if i > last_ref and frozen is not None:
            out[i] = frozen
            continue
        s = a[:stop]
        s = s[np.isfinite(s)]
        if len(s) >= min_n:
            out[i] = float(np.quantile(s, q))
            if i >= last_ref:
                frozen = out[i]
    return pd.Series(out, index=x.index)


def threshold_at(x: pd.Series, session: date, q: float, min_n: int = MIN_REF) -> Optional[float]:
    s = x[[d < session and d <= REF_END for d in x.index]].dropna()
    return float(np.quantile(s.to_numpy(float), q)) if len(s) >= min_n else None


def wave_flags(stats: pd.DataFrame) -> pd.DataFrame:
    """One row per session: the thresholds, the three conditions, `wave` (bool) and `direction` ('up'/'down'/None). Uses only earlier sessions' thresholds."""
    if stats.empty:
        return pd.DataFrame(columns=["wave", "direction"])
    df = stats.copy()
    hi, lo = expanding_q(df["adv_share"], 1 - BREADTH_TAIL), expanding_q(df["adv_share"], BREADTH_TAIL)
    dq = expanding_q(df["disp_ratio"], DISP_PCT)
    mq = expanding_q(df["dom_share"], DOM_PCT)
    df["thr_adv_hi"], df["thr_adv_lo"], df["thr_disp"], df["thr_dom"] = hi, lo, dq, np.maximum(mq, 0.5)
    df["ext_up"] = df["adv_share"] >= hi
    df["ext_down"] = df["adv_share"] <= lo
    df["low_disp"] = df["disp_ratio"] <= dq
    df["dominant"] = df["dom_share"] >= df["thr_dom"]
    decided = hi.notna() & dq.notna() & mq.notna() & df["dom_share"].notna() & df["disp_ratio"].notna()
    df["decided"] = decided
    ext = df["ext_up"] | df["ext_down"]
    df["wave"] = decided & ext & df["low_disp"] & df["dominant"] & ((df["ext_up"] & (df["med_ret"] > 0)) | (df["ext_down"] & (df["med_ret"] < 0)))
    df["direction"] = np.where(~df["wave"], None, np.where(df["ext_up"], "up", "down"))
    return df


def wave_flag_at(stats: pd.DataFrame, session: date) -> dict:
    """The decision for one session from the thresholds of the sessions before it. {'decided': False, ...} while the reference is too short."""
    if session not in stats.index:
        return {"decided": False, "wave": False, "note": f"no wave statistics for {session} (the NSE file of that day is not on this PC or not yet processed)"}
    row = stats.loc[session]
    thr = {"adv_hi": threshold_at(stats["adv_share"], session, 1 - BREADTH_TAIL), "adv_lo": threshold_at(stats["adv_share"], session, BREADTH_TAIL),
           "disp_ratio_max": threshold_at(stats["disp_ratio"], session, DISP_PCT), "dom_min": threshold_at(stats["dom_share"], session, DOM_PCT)}
    n_ref = int(stats["adv_share"][[d < session and d <= REF_END for d in stats.index]].notna().sum())
    out = {"session": str(session), "n_reference": n_ref, "stats": {k: (None if pd.isna(row[k]) else float(row[k])) for k in STATS_COLS}, "thresholds": thr}
    if n_ref < MIN_REF or any(v is None for v in thr.values()) or pd.isna(row["dom_share"]) or pd.isna(row["disp_ratio"]):
        return out | {"decided": False, "wave": False, "note": f"not decided: {n_ref} earlier sessions in the reference (need {MIN_REF}) or a statistic is missing"}
    thr["dom_min"] = max(thr["dom_min"], 0.5)
    up, down = row["adv_share"] >= thr["adv_hi"], row["adv_share"] <= thr["adv_lo"]
    low, dom = row["disp_ratio"] <= thr["disp_ratio_max"], row["dom_share"] >= thr["dom_min"]
    wave = bool((up and row["med_ret"] > 0 or down and row["med_ret"] < 0) and low and dom)
    return out | {"decided": True, "wave": wave, "direction": ("up" if up else "down") if wave else None, "thresholds": thr,
                  "conditions": {"breadth_extreme": bool(up or down), "low_dispersion": bool(low), "market_dominates": bool(dom)}}


# --- rotation ------------------------------------------------------------------------------------------------------------

def _streaks(f: np.ndarray, sign: int) -> np.ndarray:
    """For each position, how many consecutive earlier positions (immediately before) had flow of the given sign (+1 buying / -1 selling)."""
    out = np.zeros(len(f), int)
    run = 0
    for i, v in enumerate(f):
        out[i] = run
        run = run + 1 if (np.isfinite(v) and v * sign > 0) else 0
    return out


def rotation_frame(root: Path, market: str = "IN") -> pd.DataFrame:
    """Per flow session T: flow, z, the selling/buying streak before it, g (India minus Asia) and the thresholds. Empty without the flow file."""
    f = MA.flows_by_session(root, market)
    if market != "IN" or len(f) < FLOW_Z_WINDOW:
        return pd.DataFrame()
    f = f.sort_index()
    sd = f.rolling(FLOW_Z_WINDOW, min_periods=60).std().shift(1)
    z = f / sd
    idx, asia = MA.index_moves(root, market), MA.asia_moves(root)
    g = (idx - asia.reindex(idx.index)).reindex(f.index)
    df = pd.DataFrame({"flow_k": f, "z": z, "g": g})
    df["sell_streak"], df["buy_streak"] = _streaks(f.to_numpy(float), -1), _streaks(f.to_numpy(float), +1)
    df["thr_z_hi"], df["thr_z_lo"] = expanding_q(df["z"], ROT_Z_PCT), expanding_q(df["z"], 1 - ROT_Z_PCT)
    df["thr_g_hi"], df["thr_g_lo"] = expanding_q(df["g"], GAP_PCT), expanding_q(df["g"], 1 - GAP_PCT)
    kn = MA.flow_known_dates(root, market)
    df["known_on"] = [kn.get(d) or markets.get(market).next_session(d) for d in df.index]
    inn = (df["sell_streak"] >= STREAK_MIN) & (df["z"] >= df["thr_z_hi"]) & (df["g"] >= df["thr_g_hi"])
    out = (df["buy_streak"] >= STREAK_MIN) & (df["z"] <= df["thr_z_lo"]) & (df["g"] <= df["thr_g_lo"])
    df["rotation"] = np.where(inn, "in", np.where(out, "out", None))
    return df


# --- crude ---------------------------------------------------------------------------------------------------------------

def crude_moves(root: Path, market: str = "IN") -> pd.Series:
    return MA.moves_of(MA.level_series(root, market, "crude"), "pct")


# --- event lists for the event study -------------------------------------------------------------------------------------

def _within(d: date, start: Optional[date], end: Optional[date]) -> bool:
    return (start is None or d >= start) and (end is None or d <= end)


def wave_events(market: str = "IN", start: Optional[date] = None, end: Optional[date] = None, root: Optional[Path] = None, stats: Optional[pd.DataFrame] = None) -> List[dict]:
    """Sessions flagged as a market-wide wave, each decided from rows dated on or before it. [{'date', 'kind': 'wave', 'direction', adv_share, ...}]."""
    if market != "IN":
        return []
    if stats is None:
        from pflab.data import data_dir
        stats = load_cache(root or data_dir(), market)
    fl = wave_flags(stats)
    out = []
    for d, r in fl[fl["wave"]].iterrows() if len(fl) else []:
        if _within(d, start, end):
            out.append({"date": d, "kind": "wave", "direction": r["direction"], "adv_share": float(r["adv_share"]), "disp_ratio": float(r["disp_ratio"]),
                        "dom_share": float(r["dom_share"]), "med_ret_pct": round(float(r["med_ret"]) * 100, 3)})
    return out


def rotation_events(market: str = "IN", start: Optional[date] = None, end: Optional[date] = None, root: Optional[Path] = None, frame: Optional[pd.DataFrame] = None) -> List[dict]:
    """Foreign-flow switches with India diverging from Asia. `date` is when the flag is KNOWABLE (the next session, when NSDL reports the flow), `session` the flow's
    own session. History starts where the flow file starts (2009-12; the 500-value reference makes the first flag about 2012)."""
    if market != "IN":
        return []
    if frame is None:
        from pflab.data import data_dir
        frame = rotation_frame(root or data_dir(), market)
    out = []
    for d, r in (frame[frame["rotation"].notna()].iterrows() if len(frame) else []):
        if _within(r["known_on"], start, end):
            out.append({"date": r["known_on"], "session": d, "kind": "rotation", "direction": r["rotation"], "flow_k": float(r["flow_k"]), "z": float(r["z"]),
                        "gap_pct": float(r["g"])})
    return sorted(out, key=lambda e: e["date"])


def crude_fall_events(market: str = "IN", start: Optional[date] = None, end: Optional[date] = None, root: Optional[Path] = None, moves: Optional[pd.Series] = None) -> List[dict]:
    """One-session crude falls in the worst CRUDE_PCT of earlier one-day moves. `date` is the last market session on or before the crude date (a crude settlement
    after the close of that session is not in its close); `crude_date` is the crude row's own date."""
    if moves is None:
        from pflab.data import data_dir
        moves = crude_moves(root or data_dir(), market)
    m = moves.dropna()
    if len(m) < MIN_REF:
        return []
    thr = expanding_q(m, CRUDE_PCT)
    mk = markets.get(market)
    out = []
    for d, v in m.items():
        t = thr.get(d)
        if t is not None and np.isfinite(t) and v <= t and _within(d, start, end):
            try:
                ses = mk.last_session_on_or_before(d)
            except Exception:
                ses = d
            out.append({"date": ses, "crude_date": d, "kind": "crude_fall", "move_pct": round(float(v), 3), "threshold_pct": round(float(t), 3)})
    return out


# --- flags in the store and the event stream ----------------------------------------------------------------------------

def record_flag(con, market: str, session: date, kind: str, direction: str, stats: dict, thresholds: dict, text: str, now: Optional[datetime] = None,
                call_id: Optional[int] = None, known_on: Optional[date] = None) -> dict:
    """Store a high-salience flag (once per market, session, kind). The storylines' adapter reads it as evidence (`story/adapters.py`). Idempotent."""
    now = now or datetime.now()
    claim_id = None                                                              # (S80 phase 4: the situation claim is gone; the column stays, empty)
    con.execute("DELETE FROM wave_flag WHERE market=? AND session=? AND kind=?", [market, session, kind])
    con.execute("INSERT INTO wave_flag (market, session, kind, direction, salience, known_on, stats_json, thresholds_json, definition, call_id, claim_id, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [market, session, kind, direction, "high", known_on or session, json.dumps(stats, default=str), json.dumps(thresholds, default=str), DEFINITION[:500],
                 call_id, claim_id, now])
    return {"market": market, "session": str(session), "kind": kind, "direction": direction, "salience": "high", "claim_id": claim_id}


def recent_flags(con, market: str = "IN", n: int = 10) -> List[dict]:
    """Newest first: what the World screen shows."""
    try:
        rs = con.execute("SELECT session, kind, direction, salience, known_on, stats_json, call_id FROM wave_flag WHERE market=? ORDER BY session DESC, kind LIMIT ?", [market, n]).fetchall()
    except Exception:
        return []
    return [{"session": str(a), "kind": b, "direction": c, "salience": d, "known_on": str(e), "stats": json.loads(f or "{}"), "call_id": g} for a, b, c, d, e, f, g in rs]


def store_stats(con, market: str, stats: pd.DataFrame, now: Optional[datetime] = None) -> int:
    now = now or datetime.now()
    n = 0
    for d, r in stats.iterrows():
        con.execute("DELETE FROM wave_stats WHERE market=? AND session=?", [market, d])
        con.execute("INSERT INTO wave_stats (market, session, adv_share, n_all, xs_disp, med_ret, disp_ratio, dom_share, n_univ, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [market, d, _f(r["adv_share"]), _i(r["n_all"]), _f(r["xs_disp"]), _f(r["med_ret"]), _f(r["disp_ratio"]), _f(r["dom_share"]), _i(r["n_univ"]), now])
        n += 1
    return n


def _f(x):
    return None if pd.isna(x) else float(x)


def _i(x):
    return None if pd.isna(x) else int(x)


def scan_session(con, root: Path, market: str, session: date, now: Optional[datetime] = None, stats: Optional[pd.DataFrame] = None, call_id: Optional[int] = None) -> dict:
    """Decide the wave and the rotation for one session, store the stats and any flag, and return what was found. Idempotent."""
    out = {"market": market, "session": str(session), "wave": None, "rotation": None}
    if market != "IN":
        return out | {"note": f"no daily cross-section for {market}: no wave test"}
    st = stats if stats is not None else load_cache(root, market)
    if session in st.index:
        store_stats(con, market, st.loc[[session]], now)
    w = wave_flag_at(st, session)
    out["wave"] = w
    if w.get("wave"):
        text = wave_sentence(w, session)
        out["wave_flag"] = record_flag(con, market, session, "wave", w["direction"], w["stats"], w["thresholds"], text, now, call_id)
    try:
        rf = rotation_frame(root, market)
        if len(rf) and session in rf.index:
            r = rf.loc[session]
            out["rotation"] = {"decided": bool(pd.notna(r["thr_z_hi"]) and pd.notna(r["thr_g_hi"])), "flag": None if r["rotation"] is None or pd.isna(r["rotation"]) else r["rotation"],
                               "flow_k": _f(r["flow_k"]), "z": _f(r["z"]), "gap_pct": _f(r["g"]), "sell_streak": int(r["sell_streak"]), "buy_streak": int(r["buy_streak"]),
                               "known_on": str(r["known_on"])}
            if out["rotation"]["flag"]:
                thr = {k: _f(r[k]) for k in ("thr_z_hi", "thr_z_lo", "thr_g_hi", "thr_g_lo")}
                out["rotation_flag"] = record_flag(con, market, session, "rotation", out["rotation"]["flag"], out["rotation"], thr, rotation_sentence(out["rotation"], session), now,
                                                   call_id, known_on=r["known_on"])
        elif len(rf) == 0:
            out["rotation"] = {"decided": False, "note": "no foreign-flow history on this PC"}
    except Exception as e:
        out["rotation"] = {"decided": False, "note": f"rotation not worked: {type(e).__name__}"}
    return out


# --- words ---------------------------------------------------------------------------------------------------------------

def wave_sentence(w: dict, session: date) -> str:
    s, t = w["stats"], w["thresholds"]
    word = "up" if w.get("direction") == "up" else "down"
    return (f"Market-wide wave {word} on {session}: {s['adv_share'] * 100:.0f}% of names advanced; the names moved together (spread around the common move "
            f"{s['disp_ratio']:.1f}; on half of earlier days it was above {t['disp_ratio_max']:.1f}); the market part beat the own part for "
            f"{s['dom_share'] * 100:.0f}% of the 500 most-traded names (the bar is {t['dom_min'] * 100:.0f}%).")


def rotation_sentence(r: dict, session: date) -> str:
    word = "into" if r["flag"] == "in" else "out of"
    return (f"Foreign money switched {word} Indian shares on {session}: net {r['flow_k'] * 1000:+,.0f} crore (z {r['z']:+.1f}) after a streak, while India moved "
            f"{r['gap_pct']:+.2f} points against the Asian peers' average. Known from {r['known_on']}.")


def wave_note(con, market: str, session: date, calls: Optional[Dict[str, int]] = None) -> str:
    """The post-close paragraph for one session, written by code from the stored rows; every figure carries the id of the tool call it came from (`calls` maps
    'macro_attribution' / 'wave_detector' to call ids; without an id the table row is named instead). Empty string when there is nothing to say."""
    calls = calls or {}

    def cite(tool: str) -> str:
        return f" [call {calls[tool]}]" if calls.get(tool) else f" [{tool} {market} {session}]"
    parts = []
    try:
        fl = {r[0]: r for r in con.execute("SELECT kind, direction, stats_json, thresholds_json, known_on FROM wave_flag WHERE market=? AND session=?", [market, session]).fetchall()}
    except Exception:
        fl = {}
    wv = fl.get("wave")
    if wv:
        w = {"stats": json.loads(wv[2]), "thresholds": json.loads(wv[3]), "direction": wv[1]}
        parts.append(wave_sentence(w, session) + cite("wave_detector"))
        parts.append("So the book moved with the market, not with its own picks: on a day like this most names, held or not, went the same way for the same reason, "
                     "and a holding's move says little about the holding.")
    rt = fl.get("rotation")
    if rt:
        r = json.loads(rt[2])
        r["flag"] = rt[1]
        parts.append(rotation_sentence(r, session) + cite("wave_detector"))
    a = MA.read(con, market, session)
    if a and a.get("total_pct") is not None and (wv or rt):
        bits = [f"{k} {p['pct']:+.2f}" for k, p in a["parts"].items() if p.get("pct") is not None]
        miss = [k for k, p in a["parts"].items() if p.get("pct") is None]
        txt = f"Of the index's {a['total_pct']:+.2f}% move: " + ", ".join(bits) + (f", unexplained {a['unexplained_pct']:+.2f}" if a.get("unexplained_pct") is not None else "") + " (points of percent)"
        if miss:
            txt += "; no part for " + ", ".join(miss)
        parts.append(txt + "." + cite("macro_attribution"))
    return " ".join(parts)


# --- the forecaster plug-in ----------------------------------------------------------------------------------------------

def wave_states(root: Optional[Path] = None, upto: Optional[date] = None, market: str = "IN") -> pd.Series:
    """+1 (up wave), -1 (down wave) or 0 per session from the cached statistics (extended through `upto` when the cache is short and the gap is small)."""
    from pflab.data import data_dir
    root = Path(root or data_dir())
    st = load_cache(root, market)
    if upto is not None and (st.empty or st.index[-1] < upto):
        st = ensure_stats(root, upto, market, max_new_sessions=40)
    fl = wave_flags(st)
    if fl.empty:
        return pd.Series(dtype=float)
    return pd.Series(np.where(fl["wave"], np.where(fl["direction"] == "up", 1, -1), 0), index=fl.index)


def lens_frame(con, market: str, close: pd.Series, horizon: int, states: Optional[pd.Series] = None) -> Optional[pd.DataFrame]:
    """Quantiles of the h-session return given the wave state at each date: the volatility forecaster's quantiles, shifted by m x sigma_h and scaled by k, where m
    and k are the (shrunk toward 0 and 1 with n/(n+20)) mean and root-mean-square of the earlier waves' forward log returns in sigma_h units. Only waves whose
    forward window has ended by the date, and none dated after REF_END, enter. Dates without a wave get the volatility quantiles unchanged. None when there are
    no wave statistics at all."""
    from pflab.fcast import forecasters as F, protocol as P
    if market != "IN":
        return None
    if states is None:
        states = wave_states(upto=close.index[-1].date() if hasattr(close.index[-1], "date") else close.index[-1])
    if states is None or len(states) == 0:
        return None
    base = F.volatility(close, int(horizon))
    levels = list(base.columns)
    L = np.log1p(base.to_numpy(float))
    i95, i05 = levels.index(0.95), levels.index(0.05)
    sig = (L[:, i95] - L[:, i05]) / (2 * 1.6448536269514722)
    c = close.astype(float).to_numpy()
    lc = np.log(c)
    fwd = np.full(len(c), np.nan)
    fwd[:-horizon] = lc[horizon:] - lc[:-horizon]
    dts = [d.date() if hasattr(d, "date") else d for d in close.index]
    st = states.reindex(dts).fillna(0).to_numpy(int)
    mu = np.zeros(len(c))
    ks = np.ones(len(c))
    for s in (1, -1):
        pos = np.array([p for p in np.where(st == s)[0] if dts[p] <= REF_END and np.isfinite(fwd[p]) and np.isfinite(sig[p]) and sig[p] > 0], int)
        if len(pos) == 0:
            continue
        y = fwd[pos] / sig[pos]
        cn, cs, cq = np.arange(1, len(pos) + 1), np.cumsum(y), np.cumsum(y * y)
        k = np.searchsorted(pos + horizon, np.arange(len(c)), side="right")               # events whose forward window ended at or before each row
        for i in np.where(st == s)[0]:
            kk = int(k[i])
            if kk == 0:
                continue
            n, mean, rms = int(cn[kk - 1]), cs[kk - 1] / cn[kk - 1], np.sqrt(cq[kk - 1] / cn[kk - 1])
            w = n / (n + SHRINK_N0)
            mu[i] = w * mean
            ks[i] = float(np.clip(1.0 + w * (rms - 1.0), 0.5, 2.0))
    newL = (mu * sig)[:, None] + ks[:, None] * L
    return pd.DataFrame(np.expm1(newL), index=base.index, columns=base.columns)


def register_lens() -> None:
    try:
        from pflab.fcast import plugins
    except ImportError:
        return
    plugins.register(plugins.Lens(
        name="lens_wave", markets=("IN",), protocol="docs/protocols/s79_wave_sentiment_protocol.md", frame=lens_frame, replay_ok=True,
        about="After a market-wide wave (price-based: breadth, dispersion, market share of the move) the volatility quantiles are shifted and scaled by what earlier waves did; "
              "the foreign-flow rotation state is not in this lens (its history is shorter and its flag is known a day late)."))
