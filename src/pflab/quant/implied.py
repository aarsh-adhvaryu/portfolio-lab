"""What the Nifty option chain says about where the index may be at expiry (S64; the investor: "look into turning chains into
probability distributions").

Method (Breeden and Litzenberger, 1978: the risk-neutral probability that the index ends below K is e^{rT} dP/dK, the slope of
the put price across strikes):
    1. one expiry 14 to 60 days away (the nearest), its future as the forward F (else the index times e^{rT})
    2. the out-of-the-money options with open interest and trades (puts below F, calls above): their implied volatility from the
       settlement price (Black-76, quant/options.implied_vol)
    3. a smooth smile: implied volatility as a quadratic in log-moneyness ln(K/F), weighted by the square root of open interest;
       held flat beyond the traded strikes (no invented tails)
    4. put prices from the smooth smile on a fine grid of strikes, their slope, made non-decreasing and inside 0..1
The raw chain cannot be used directly: thin strikes' settlement prices are noise (a first look gave 48% below -5% and 39% below 0%).

READ WITH CARE. These are risk-neutral probabilities: buyers pay extra for protection, so they put MORE weight on falls than the
real frequency. They describe what the market charges for insurance, not what will happen. Each day's numbers are kept and scored
when the expiry comes (Brier score per level against the Nifty 50's close), so the record shows how far they run above the real
frequency. 2024-2026 is inside the spent years and too short to test anything: no signal comes from this unless a registered
study passes later (CLAUDE.md 12).
"""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

MIN_DAYS, MAX_DAYS = 14, 60
MIN_STRIKES = 8
LEVELS = (-0.20, -0.15, -0.10, -0.05, 0.05, 0.10)         # relative to the index's close on the day
FILE = "implied_probs.parquet"


def smile(m: np.ndarray, iv: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Quadratic fit of implied volatility on log-moneyness (coefficients, highest power first)."""
    return np.polyfit(m, iv, 2, w=w)


def cdf_from_smile(coef: np.ndarray, F: float, T: float, r: float, m_lo: float, m_hi: float, grid: np.ndarray) -> np.ndarray:
    """P(index at expiry < K) for K in `grid`, from put prices priced with the smooth smile (flat outside the traded range)."""
    from pflab.quant import options
    m = np.clip(np.log(grid / F), m_lo, m_hi)
    vol = np.maximum(np.polyval(coef, m), 0.01)
    put = np.array([options.black76(F, k, T, r, v, False) for k, v in zip(grid, vol)])
    c = math.exp(r * T) * np.gradient(put, grid)
    return np.clip(np.maximum.accumulate(np.nan_to_num(c, nan=0.0)), 0.0, 1.0)


def day(chain: pd.DataFrame, d: date, rate: float, symbol: str = "NIFTY") -> Optional[dict]:
    """The probabilities for one session; None when no expiry has enough traded strikes."""
    from pflab.quant import options
    x = chain[(chain["symbol"] == symbol) & (chain["kind"] == "index")]
    opt = x[x["instrument"] == "OPT"]
    fut = x[x["instrument"] == "FUT"]
    exps = sorted(e for e in opt["expiry"].unique() if MIN_DAYS <= (e - d).days <= MAX_DAYS)
    for e in exps:
        T = (e - d).days / 365.0
        o = opt[(opt["expiry"] == e) & (opt["oi"] > 0) & (opt["contracts"] > 0)]
        if o.empty or pd.isna(o["underlying"].iloc[0]):
            continue
        spot = float(o["underlying"].iloc[0])
        fe = fut[fut["expiry"] == e]
        F = float(fe["settle"].iloc[0]) if len(fe) and pd.notna(fe["settle"].iloc[0]) else spot * math.exp(rate * T)
        otm = o[((o["option"] == "PE") & (o["strike"] < F)) | ((o["option"] == "CE") & (o["strike"] >= F))]
        rows = []
        for r in otm.itertuples():
            v = options.implied_vol(float(r.settle), F, float(r.strike), T, rate, r.option == "CE")
            if v is not None:
                rows.append((math.log(r.strike / F), v, math.sqrt(max(r.oi, 1.0))))
        if len(rows) < MIN_STRIKES:
            continue
        m, iv, w = map(np.array, zip(*rows))
        coef = smile(m, iv, w)
        rmse = float(np.sqrt(np.average((np.polyval(coef, m) - iv) ** 2, weights=w)))
        grid = np.linspace(F * 0.5, F * 1.5, 801)
        cdf = cdf_from_smile(coef, F, T, rate, float(m.min()), float(m.max()), grid)
        out = {"date": d, "expiry": e, "days": (e - d).days, "spot": spot, "forward": F, "rate": rate, "strikes": len(rows),
               "fit_rmse": rmse, "atm_iv": float(np.polyval(coef, 0.0)),
               "skew_90_110": float(np.polyval(coef, np.clip(math.log(0.9 * spot / F), m.min(), m.max()))
                                    - np.polyval(coef, np.clip(math.log(1.1 * spot / F), m.min(), m.max()))),
               "m_lo": float(m.min()), "m_hi": float(m.max())}
        for lv in LEVELS:
            p_below = float(np.interp(spot * (1 + lv), grid, cdf))
            out[f"p_{'below' if lv < 0 else 'above'}_{abs(int(round(lv * 100)))}"] = p_below if lv < 0 else 1.0 - p_below
        return out
    return None


def derive_missing(root: Path) -> int:
    """Every F&O session without a row gets one (rate: the cash rate known that day)."""
    from pflab.data import fo_daily, riskfree
    root = Path(root)
    p = root / "derived" / FILE
    old = pd.read_parquet(p) if p.exists() else pd.DataFrame()
    have = set(pd.to_datetime(old["date"]).dt.date) if len(old) else set()
    table = riskfree.monthly_table(root)
    new = []
    for d in fo_daily.sessions(root):
        if d in have:
            continue
        chain = fo_daily.load_day(d, root)
        if chain is None:
            continue
        try:
            r = day(chain, d, riskfree.at(table, d)[0])
        except Exception:
            r = None
        if r:
            new.append(r)
    if new:
        p.parent.mkdir(parents=True, exist_ok=True)
        pd.concat([old, pd.DataFrame(new)], ignore_index=True).sort_values("date").to_parquet(p, index=False)
    return len(new)


def outcomes(root: Path) -> pd.DataFrame:
    """Each kept row whose expiry has a Nifty 50 close: whether each level was crossed at expiry (1 / 0)."""
    from pflab.data import indices
    root = Path(root)
    p = root / "derived" / FILE
    if not p.exists():
        return pd.DataFrame()
    t = pd.read_parquet(p)
    px = indices.load("NIFTY50_PRICE", root)
    close = pd.Series(px["close"].to_numpy(float), index=pd.to_datetime(px["date"])).sort_index()
    t["expiry_ts"] = pd.to_datetime(t["expiry"])
    t = t[t["expiry_ts"] <= close.index.max()].copy()
    if t.empty:
        return t
    t["end"] = close.reindex(t["expiry_ts"], method="ffill").to_numpy()
    for lv in LEVELS:
        name = f"{'below' if lv < 0 else 'above'}_{abs(int(round(lv * 100)))}"
        hit = (t["end"] < t["spot"] * (1 + lv)) if lv < 0 else (t["end"] > t["spot"] * (1 + lv))
        t[f"hit_{name}"] = hit.astype(float)
    return t


def scorecard(root: Path) -> dict:
    """Per level: the average probability the options gave, how often it happened, the Brier score, n (rows) and the number of
    distinct expiries (rows on the same expiry are not independent)."""
    t = outcomes(root)
    if t.empty:
        return {"scored": 0}
    out = {"scored": int(len(t)), "expiries": int(t["expiry"].nunique()), "from": str(pd.Timestamp(t["date"].min()).date()),
           "to": str(pd.Timestamp(t["date"].max()).date()), "levels": {}}
    for lv in LEVELS:
        name = f"{'below' if lv < 0 else 'above'}_{abs(int(round(lv * 100)))}"
        p, h = t[f"p_{name}"], t[f"hit_{name}"]
        out["levels"][name] = {"options_said": round(float(p.mean()), 4), "happened": round(float(h.mean()), 4),
                               "brier": round(float(((p - h) ** 2).mean()), 5)}
    out["note"] = ("risk-neutral probabilities are expected to run above the real frequency for falls; rows on one expiry share "
                   "an outcome, so the expiries, not the rows, are the independent count; 2024-2026 is spent: a description")
    return out


def latest(root: Path, asof: date) -> Optional[dict]:
    p = Path(root) / "derived" / FILE
    if not p.exists():
        return None
    t = pd.read_parquet(p)
    t = t[pd.to_datetime(t["date"]) <= pd.Timestamp(asof)]
    if t.empty:
        return None
    r = t.sort_values("date").iloc[-1].to_dict()
    return {k: (str(v)[:10] if k in ("date", "expiry") else (round(float(v), 4) if isinstance(v, float) else v)) for k, v in r.items()}


def line(root: Path, asof: date) -> Optional[str]:
    r = latest(root, asof)
    if not r:
        return None
    return (f"Options on {r['date']} price a {r['p_below_10']:.0%} chance the Nifty ends more than 10% lower by {r['expiry']} "
            f"({r['days']} days) and {r['p_below_5']:.0%} for 5% lower; {r['p_above_5']:.0%} for 5% higher. Risk-neutral: insurance "
            "costs extra, so these run above the real odds of a fall.")
