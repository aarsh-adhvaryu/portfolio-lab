"""Who moved first (S79 item 10): lead-lag between two return series, within a sector and across sectors and markets.

    lead_lag(root, a, b, asof, window=500)  -> {"lead": {...} | None, "verdict", "lags": [...], "n", ...}
    lead_lag_sector(root, sector, asof)     -> the sector's documented links, each tested, and the best lead among them
    minute_lead_lag(con, a, b, day)         -> the same test on 1-minute returns when `bars_1m` has rows (it need not)

Series: a global key (US_SP500, ADR_INFY, ...), an NSE index key (NIFTY50_PRICE, SECTOR_IT_PRICE) or its short sector name
(IT), or an NSE symbol (INFY; resolved to its ISIN as of the date, adjusted closes).

Method. Daily simple returns of each series on its own previous close, then the dates both traded (the common calendar), the last
`window` of them with date <= asof (point in time). Lag k (in common sessions, -5..+5): corr(a_t, b_{t+k}); k > 0 means A leads B
by k sessions. Both series are pre-whitened with the AR(3) filter fitted on A (so a series' own memory does not pass for a link).
A lead is called RELIABLE only when all four hold at a non-zero lag:
  1. Bartlett: |r_k| exceeds z / sqrt(n - |k|), z the two-sided normal quantile at 5% / 10 lags (Bonferroni over the 10 non-zero lags);
  2. shuffle: B circularly shifted by a random offset (499 draws, seed 0, offsets beyond the lag range) rarely shows a larger
     max |r_k| over the non-zero lags (p <= 0.05);
  3. effect size |r_k| >= 0.10 (a huge sample makes tiny correlations "significant");
  4. the same sign in both halves of the window.
Otherwise the answer is "no reliable lead". Under MIN_N common sessions: the count, no conclusion.
Cross-market note: the New York session of date d closes after the NSE session of date d, so "US leads India" shows at lag +1 on
the common calendar by construction (that is the overnight transmission, not a discovery).
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from statistics import NormalDist
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pflab.quant import transmission as tr

MAX_LAG = 5
MIN_N = 20
MIN_ABS_R = 0.10
SHUFFLES = 499
AR_ORDER = 3
RULE = ("reliable lead = non-zero lag with Bartlett |r| > z/sqrt(n) (z at 5%/10 lags), shuffle p <= 0.05, |r| >= 0.10 and the same "
        "sign in both halves; after AR(3) pre-whitening; otherwise no reliable lead")

# the ADRs that belong to an Indian sector index
SECTOR_ADRS = {"IT": ("ADR_INFY", "ADR_WIT"), "PRIVATE_BANK": ("ADR_HDB", "ADR_IBN"), "BANK": ("ADR_HDB", "ADR_IBN"),
               "FIN_SERVICES": ("ADR_HDB", "ADR_IBN"), "PHARMA": ("ADR_RDY",)}


def load_close(root: Path, ref: str, asof: date) -> Optional[pd.Series]:
    """Close series (index python date, dates <= asof) for a reference; None when it cannot be found."""
    from pflab.data import indices
    ref = str(ref).strip()
    keys = [ref, ref.upper()]
    sector = ref.upper().replace(" ", "_")
    if sector in indices.SECTORS:
        keys.append(f"SECTOR_{sector}_PRICE")
    for k in keys:
        fr = tr.load_frame(root, k)
        if fr is not None:
            fr = fr[fr["date"] <= asof]
            return pd.Series(fr["close"].to_numpy(float), index=list(fr["date"])) if len(fr) else None
    fr = tr.nse_frame(root, ref.upper(), asof, years=8)
    if fr is not None and len(fr):
        return pd.Series(fr["close"].to_numpy(float), index=list(fr["date"]))
    return None


def _returns(close: pd.Series) -> pd.Series:
    r = close / close.shift(1) - 1.0
    gap_ok = (pd.to_datetime(pd.Series(close.index)).diff().dt.days <= tr.MAX_GAP_DAYS).to_numpy()
    return r.where(gap_ok).dropna()


def _prewhiten(a: np.ndarray, b: np.ndarray, p: int = AR_ORDER):
    n = len(a)
    if n <= 3 * p:
        return a, b
    X = np.column_stack([a[p - j - 1:n - j - 1] for j in range(p)])
    phi, *_ = np.linalg.lstsq(X, a[p:] - a[p:].mean(), rcond=None)
    f = lambda v: v[p:] - sum(phi[j] * v[p - j - 1:n - j - 1] for j in range(p))
    return f(a), f(b)


def _xcorr(a: np.ndarray, b: np.ndarray, lags) -> Dict[int, float]:
    out = {}
    n = len(a)
    for k in lags:
        x, y = (a[:n - k], b[k:]) if k >= 0 else (a[-k:], b[:n + k])
        if len(x) < 3 or x.std() == 0 or y.std() == 0:
            out[k] = float("nan")
        else:
            out[k] = float(np.corrcoef(x, y)[0, 1])
    return out


def test_pair(a: np.ndarray, b: np.ndarray, max_lag: int = MAX_LAG, seed: int = 0) -> dict:
    """The cross-correlation table and the verdict for two aligned return arrays (a leads b at positive lag)."""
    a, b = _prewhiten(np.asarray(a, float), np.asarray(b, float))
    n = len(a)
    lags = list(range(-max_lag, max_lag + 1))
    r = _xcorr(a, b, lags)
    z = NormalDist().inv_cdf(1 - 0.05 / (2 * 2 * max_lag))
    table = [{"lag": k, "corr": None if np.isnan(r[k]) else round(r[k], 4), "n": n - abs(k),
              "bartlett_bound": round(z / np.sqrt(max(n - abs(k), 1)), 4)} for k in lags]
    nz = [k for k in lags if k != 0 and not np.isnan(r[k])]
    cand = [k for k in nz if abs(r[k]) > z / np.sqrt(n - abs(k)) and abs(r[k]) >= MIN_ABS_R]
    out = {"n": n, "lags": table, "lag0_corr": None if np.isnan(r[0]) else round(r[0], 4), "lead": None, "p_shuffle": None}
    if not cand:
        return out
    k = max(cand, key=lambda j: abs(r[j]))
    rng = np.random.default_rng(seed)
    obs = max(abs(r[j]) for j in nz)
    hi = n - max_lag - 1
    stats = []
    for _ in range(SHUFFLES):
        s = int(rng.integers(max_lag + 1, hi)) if hi > max_lag + 1 else max_lag + 1
        rs = _xcorr(a, np.roll(b, s), nz)
        stats.append(max(abs(v) for v in rs.values() if not np.isnan(v)))
    p = (1 + sum(1 for v in stats if v >= obs)) / (1 + SHUFFLES)
    out["p_shuffle"] = round(p, 4)
    h = n // 2
    r1, r2 = _xcorr(a[:h], b[:h], [k])[k], _xcorr(a[h:], b[h:], [k])[k]
    same = bool(np.sign(r1) == np.sign(r[k]) and np.sign(r2) == np.sign(r[k]))
    if p <= 0.05 and same:
        out["lead"] = {"lag": k, "corr": round(r[k], 4), "n": n - abs(k), "half_corrs": [round(r1, 4), round(r2, 4)]}
    else:
        out["not_reliable_because"] = ("shuffle p " + str(round(p, 3)) if p > 0.05 else "the sign flips between the two halves")
    return out


def lead_lag(root: Path, a: str, b: str, asof: date, window: int = 500, max_lag: int = MAX_LAG) -> dict:
    """Does A lead B (or B lead A)? See the module doc for the rule. Never raises on missing data."""
    out = {"a": a, "b": b, "asof": str(asof), "window_sessions": window, "rule": RULE, "reliable": False, "lead": None, "n": 0}
    ca, cb = load_close(Path(root), a, asof), load_close(Path(root), b, asof)
    miss = [n for n, c in ((a, ca), (b, cb)) if c is None or len(c) < 3]
    if miss:
        out["verdict"] = f"no data for {', '.join(miss)}"
        return out
    ra, rb = _returns(ca), _returns(cb)
    common = sorted(set(ra.index) & set(rb.index))[-window:]
    out["n"] = len(common)
    out["from"], out["to"] = (str(common[0]), str(common[-1])) if common else (None, None)
    if len(common) < MIN_N:
        out["verdict"] = f"small sample: {len(common)} common sessions, under {MIN_N}: no conclusion"
        return out
    res = test_pair(ra[common].to_numpy(), rb[common].to_numpy(), max_lag)
    out.update({"lags": res["lags"], "lag0_corr": res["lag0_corr"], "p_shuffle": res["p_shuffle"], "n": res["n"]})
    if res["lead"]:
        k = res["lead"]["lag"]
        leader, follower = (a, b) if k > 0 else (b, a)
        out["lead"] = {"leader": leader, "follower": follower, "lag_sessions": abs(k), "corr": res["lead"]["corr"], "n": res["lead"]["n"],
                       "half_corrs": res["lead"]["half_corrs"]}
        out["reliable"] = True
        out["verdict"] = f"{leader} leads {follower} by {abs(k)} session(s), r={res['lead']['corr']:+.2f} (n={res['lead']['n']})"
    else:
        out["verdict"] = "no reliable lead" + (f" ({res['not_reliable_because']})" if res.get("not_reliable_because") else "")
    if _cross_market(a, b):
        out["note"] = "US-India: a US session closes after the NSE session of the same date, so US-leads-India shows at lag +1 by construction"
    return out


def _cross_market(a: str, b: str) -> bool:
    us = lambda s: s.upper().startswith(("US_", "ADR_")) or s.upper() in ("DOLLAR_INDEX", "WTI", "GOLD")
    ind = lambda s: not us(s)
    return (us(a) and ind(b)) or (us(b) and ind(a))


def lead_lag_sector(root: Path, sector: str, asof: date, window: int = 500) -> dict:
    """The sector's documented links, each tested: its US ETF(s) -> the Indian sector index, the index -> the Nifty 50, its ADR(s) -> the
    index. The best reliable lead (largest |r|) is the answer, else 'no reliable lead'."""
    sec = sector.upper().replace(" ", "_")
    idx = f"SECTOR_{sec}_PRICE"
    pairs = [(us, i) for us, i, _w in tr.SECTOR_LINKS if i == idx]
    pairs += [(idx, "NIFTY50_PRICE")] + [(adr, idx) for adr in SECTOR_ADRS.get(sec, ())]
    res = [lead_lag(root, x, y, asof, window) for x, y in pairs]
    rel = [r for r in res if r.get("reliable")]
    best = max(rel, key=lambda r: abs(r["lead"]["corr"])) if rel else None
    return {"sector": sec, "asof": str(asof), "pairs": [{k: r.get(k) for k in ("a", "b", "n", "lag0_corr", "reliable", "lead", "verdict")} for r in res],
            "lead": best["lead"] if best else None, "verdict": best["verdict"] if best else "no reliable lead", "rule": RULE,
            "n_tested": len(res)}


def minute_lead_lag(con, a: str, b: str, day: Optional[date] = None, max_lag: int = MAX_LAG) -> dict:
    """The same test on 1-minute returns from the store's `bars_1m` (symbol, a timestamp column, close) for one day; says so when
    the table or its rows are not there. Lags are minutes."""
    out = {"a": a, "b": b, "unit": "minutes", "reliable": False, "lead": None, "n": 0}
    try:
        cols = {r[0].lower() for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name='bars_1m'").fetchall()}
    except Exception as e:
        out["verdict"] = f"bars_1m unreadable: {repr(e)[:80]}"
        return out
    ts = next((c for c in ("ts", "minute", "datetime", "bar_time", "time") if c in cols), None)
    if not cols or ts is None or not {"symbol", "close"} <= cols:
        out["verdict"] = "no bars_1m table (or without symbol, close and a time column): minute-level lead-lag not available"
        return out
    where, args = ("", [])
    if day is not None:
        where, args = f" AND CAST({ts} AS DATE) = ?", [day]
    ser = {}
    for sym in (a, b):
        df = con.execute(f"SELECT {ts} AS t, close FROM bars_1m WHERE symbol = ?{where} ORDER BY {ts}", [sym] + args).df()
        if len(df) < 3:
            out["verdict"] = f"no minute bars for {sym}" + (f" on {day}" if day else "")
            return out
        s = pd.Series(df["close"].to_numpy(float), index=pd.to_datetime(df["t"]))
        ser[sym] = (s / s.shift(1) - 1.0).dropna()
    common = ser[a].index.intersection(ser[b].index)
    out["n"] = len(common)
    if len(common) < max(MIN_N, 10 * max_lag):
        out["verdict"] = f"small sample: {len(common)} common minutes: no conclusion"
        return out
    res = test_pair(ser[a][common].to_numpy(), ser[b][common].to_numpy(), max_lag)
    out.update({"lags": res["lags"], "lag0_corr": res["lag0_corr"], "p_shuffle": res["p_shuffle"]})
    if res["lead"]:
        k = res["lead"]["lag"]
        leader, follower = (a, b) if k > 0 else (b, a)
        out.update({"lead": {"leader": leader, "follower": follower, "lag_minutes": abs(k), "corr": res["lead"]["corr"]}, "reliable": True,
                    "verdict": f"{leader} leads {follower} by {abs(k)} minute(s), r={res['lead']['corr']:+.2f}"})
    else:
        out["verdict"] = "no reliable lead"
    return out
