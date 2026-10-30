"""Options and futures facts from the daily F&O file (S64 Phase 5 item 7; the Sensibull ideas, computed by us).

All of it is information: no signal and no advice unless a later registered test passes (CLAUDE.md 12). Per session:
    atm_iv          Black-76 implied volatility (brentq on the settlement price, the same expiry's future as the forward, the cash
                    rate from data/riskfree) at the strike nearest the forward, calls and puts averaged, for the nearest expiry
                    at least 7 days away
    iv_percentile   where today's ATM IV sits in its own last year (needs 60+ sessions of history)
    pcr             put open interest over call open interest, all expiries of the index
    fut_premium     annualised premium of the near-month index future over the index
    max_pain        the strike where option writers pay least at expiry, for the nearest expiry
    build-up class  per stock future: price up with OI up = long build-up; price down with OI up = short build-up; price up with
                    OI down = short covering; price down with OI down = long unwinding
Derived tables are rebuilt per session into data/derived/fo_index.parquet and fo_buildup.parquet.
"""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

MIN_DAYS = 7
IV_HISTORY_MIN = 60


def black76(F: float, K: float, T: float, r: float, sigma: float, call: bool) -> float:
    from scipy.stats import norm
    if T <= 0 or sigma <= 0:
        return max(F - K, 0.0) if call else max(K - F, 0.0)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    df = math.exp(-r * T)
    return df * (F * norm.cdf(d1) - K * norm.cdf(d2)) if call else df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


def implied_vol(price: float, F: float, K: float, T: float, r: float, call: bool) -> Optional[float]:
    """The volatility that gives `price` under Black-76; None when the price is below intrinsic or outside 1%-300%."""
    from scipy.optimize import brentq
    if not (price > 0 and F > 0 and K > 0 and T > 0):
        return None
    intrinsic = math.exp(-r * T) * (max(F - K, 0.0) if call else max(K - F, 0.0))
    if price <= intrinsic + 1e-9:
        return None
    lo, hi = 0.01, 3.0
    f = lambda s: black76(F, K, T, r, s, call) - price         # noqa: E731
    if f(lo) > 0 or f(hi) < 0:
        return None
    return float(brentq(f, lo, hi, xtol=1e-6))


def max_pain(opts: pd.DataFrame) -> Optional[float]:
    """The strike (among those traded) at which the total payout to option holders at expiry is smallest."""
    if opts.empty:
        return None
    calls = opts[opts["option"] == "CE"].groupby("strike")["oi"].sum()
    puts = opts[opts["option"] == "PE"].groupby("strike")["oi"].sum()
    strikes = np.array(sorted(set(calls.index) | set(puts.index)), dtype=float)
    if len(strikes) == 0:
        return None
    c = calls.reindex(strikes).fillna(0).to_numpy()
    p = puts.reindex(strikes).fillna(0).to_numpy()
    pay = [float((c * np.maximum(s - strikes, 0)).sum() + (p * np.maximum(strikes - s, 0)).sum()) for s in strikes]
    return float(strikes[int(np.argmin(pay))])


def buildup_class(price_change: float, oi_change: float) -> Optional[str]:
    if not (np.isfinite(price_change) and np.isfinite(oi_change)) or price_change == 0 or oi_change == 0:
        return None
    if oi_change > 0:
        return "long build-up" if price_change > 0 else "short build-up"
    return "short covering" if price_change > 0 else "long unwinding"


def index_day(day: pd.DataFrame, d: date, symbol: str, rate: float) -> dict:
    """The index facts of one session for `symbol` (NIFTY): see the module docstring."""
    x = day[(day["symbol"] == symbol) & (day["kind"] == "index")]
    out: dict = {"date": d, "symbol": symbol}
    fut = x[x["instrument"] == "FUT"].copy()
    opt = x[x["instrument"] == "OPT"].copy()
    fut["days"] = [(e - d).days for e in fut["expiry"]]
    near = fut[fut["days"] >= MIN_DAYS].sort_values("days")          # a contract a day from expiry has a noisy premium
    if near.empty:
        near = fut[fut["days"] >= 1].sort_values("days")
    if len(near):
        f0 = near.iloc[0]
        und = float(f0["underlying"]) if pd.notna(f0["underlying"]) else None
        out["future_expiry"], out["future_close"] = f0["expiry"], float(f0["close"])
        if und and f0["days"] > 0:
            out["fut_premium_ann"] = (float(f0["close"]) / und - 1.0) * 365.0 / float(f0["days"])
    if len(opt):
        c, p = opt[opt["option"] == "CE"]["oi"].sum(), opt[opt["option"] == "PE"]["oi"].sum()
        out["call_oi"], out["put_oi"] = float(c), float(p)
        out["pcr"] = float(p / c) if c else None
        out["oi_change_options"] = float(opt["oi_change"].sum())
    if len(fut):
        out["oi_change_futures"] = float(fut["oi_change"].sum())
    # ATM IV on the nearest expiry at least MIN_DAYS away
    exps = sorted({e for e in opt["expiry"] if (e - d).days >= MIN_DAYS})
    if exps:
        e = exps[0]
        T = (e - d).days / 365.0
        o = opt[opt["expiry"] == e]
        fe = fut[fut["expiry"] == e]
        F = float(fe["settle"].iloc[0]) if len(fe) and pd.notna(fe["settle"].iloc[0]) else None
        if F is None and len(o) and pd.notna(o["underlying"].iloc[0]):
            F = float(o["underlying"].iloc[0]) * math.exp(rate * T)
        if F:
            k = o.loc[(o["strike"] - F).abs().idxmin(), "strike"]
            ivs = []
            for _i, r in o[o["strike"] == k].iterrows():
                v = implied_vol(float(r["settle"]), F, float(k), T, rate, r["option"] == "CE")
                if v:
                    ivs.append(v)
            if ivs:
                out["atm_iv"], out["atm_strike"], out["iv_expiry"] = float(np.mean(ivs)), float(k), e
            out["max_pain"] = max_pain(o)
            out["max_pain_expiry"] = e
    return out


def buildup_day(day: pd.DataFrame, d: date) -> pd.DataFrame:
    """Per stock: the near-month future's price change, and the open interest and its change summed over all expiries (a roll
    from one month to the next moves OI between contracts, not out of the stock), with the build-up class."""
    f = day[(day["kind"] == "stock") & (day["instrument"] == "FUT")].copy()
    f["days"] = [(e - d).days for e in f["expiry"]]
    f = f[f["days"] >= 1]
    tot = f.groupby("symbol")[["oi", "oi_change"]].sum()
    f = f.sort_values("days").drop_duplicates("symbol").drop(columns=["oi", "oi_change"]).join(tot, on="symbol")
    f["price_change"] = f["close"] / f["prev_close"] - 1.0
    prev_oi = f["oi"] - f["oi_change"]
    f["oi_change_pct"] = np.where(prev_oi > 0, f["oi_change"] / prev_oi, np.nan)
    f["class"] = [buildup_class(a, b) for a, b in zip(f["price_change"], f["oi_change"])]
    return f[["date", "symbol", "expiry", "close", "price_change", "oi", "oi_change", "oi_change_pct", "class"]].reset_index(drop=True)


def derive(root: Path, d: date, rate: Optional[float] = None) -> Optional[dict]:
    """Add the session's rows to data/derived/fo_index.parquet and fo_buildup.parquet (replacing the date); the index row."""
    from pflab.data import fo_daily, riskfree
    day = fo_daily.load_day(d, root)
    if day is None or day.empty:
        return None
    if rate is None:
        rate = riskfree.at(riskfree.monthly_table(root), d)[0]
    row = index_day(day, d, "NIFTY", rate)
    row["rate"] = rate
    out = Path(root) / "derived"
    out.mkdir(parents=True, exist_ok=True)
    for name, new in (("fo_index.parquet", pd.DataFrame([row])), ("fo_buildup.parquet", buildup_day(day, d))):
        p = out / name
        old = pd.read_parquet(p) if p.exists() else pd.DataFrame()
        if len(old):
            old = old[pd.to_datetime(old["date"]).dt.date != d]
        pd.concat([old, new], ignore_index=True).to_parquet(p, index=False)
    return row


def derive_missing(root: Path) -> int:
    from pflab.data import fo_daily
    p = Path(root) / "derived" / "fo_index.parquet"
    have = set(pd.to_datetime(pd.read_parquet(p)["date"]).dt.date) if p.exists() else set()
    n = 0
    for d in fo_daily.sessions(root):
        if d not in have and derive(root, d) is not None:
            n += 1
    return n


CURRENT_DAYS = 7          # (audit 2026-10-30) a session older than this is history, not today's market: "no current data"


def is_current(session, asof: date, expiry=None) -> bool:
    """A reading may be used as today's only when its session is recent and its contract has not expired."""
    s = pd.Timestamp(session).date()
    if (asof - s).days > CURRENT_DAYS:
        return False
    return expiry is None or pd.isna(expiry) or pd.Timestamp(expiry).date() > asof


def last_session(root: Path, asof: date) -> Optional[str]:
    p = Path(root) / "derived" / "fo_index.parquet"
    if not p.exists():
        return None
    t = pd.to_datetime(pd.read_parquet(p, columns=["date"])["date"])
    t = t[t <= pd.Timestamp(asof)]
    return None if t.empty else str(t.max().date())


def iv_percentile(hist: pd.Series, today: float) -> Optional[float]:
    h = hist.dropna()
    return None if len(h) < IV_HISTORY_MIN else float((h <= today).mean() * 100)


def summary(root: Path, asof: date, current: bool = True) -> Optional[dict]:
    """The latest session on or before `asof`: index facts, the IV percentile in its own last year, and participant OI. `current`: None when
    that session is older than CURRENT_DAYS (an old chain is not today's)."""
    p = Path(root) / "derived" / "fo_index.parquet"
    if not p.exists():
        return None
    t = pd.read_parquet(p)
    t["date"] = pd.to_datetime(t["date"])
    t = t[t["date"] <= pd.Timestamp(asof)].sort_values("date")
    if t.empty:
        return None
    r = t.iloc[-1].to_dict()
    if current and not is_current(r["date"], asof):
        return None
    out = {k: (None if pd.isna(v) else v) for k, v in r.items()}
    out["date"] = str(pd.Timestamp(out["date"]).date())
    if out.get("atm_iv") is not None:
        hist = t[t["date"] > t["date"].iloc[-1] - pd.Timedelta(days=365)]["atm_iv"]
        out["iv_percentile_1y"] = iv_percentile(hist, out["atm_iv"])
        out["iv_sessions_in_history"] = int(hist.notna().sum())
    return out


def line(root: Path, asof: date) -> Optional[str]:
    """One line for the summaries, e.g. "Nifty IV 14 (30th percentile), PCR 1.1, futures premium 6.2% a year"."""
    s = summary(root, asof)
    if not s:
        last = last_session(root, asof)
        return f"Options: no current data (the last session read is {last})" if last else None
    parts = []
    if s.get("atm_iv") is not None:
        pc = s.get("iv_percentile_1y")
        parts.append(f"Nifty IV {s['atm_iv'] * 100:.0f}" + (f" ({pc:.0f}th percentile of its year)" if pc is not None else " (percentile after 60 sessions)"))
    if s.get("pcr") is not None:
        parts.append(f"PCR {s['pcr']:.2f}")
    if s.get("fut_premium_ann") is not None:
        parts.append(f"futures premium {s['fut_premium_ann'] * 100:.1f}% a year")
    return (", ".join(parts) + f" ({s['date']}; information, not a signal)") if parts else None


def buildup_for(root: Path, asof: date, symbols) -> Dict[str, dict]:
    p = Path(root) / "derived" / "fo_buildup.parquet"
    if not p.exists():
        return {}
    t = pd.read_parquet(p)
    t["date"] = pd.to_datetime(t["date"])
    t = t[t["date"] <= pd.Timestamp(asof)]
    if t.empty:
        return {}
    if not is_current(t["date"].max(), asof):
        return {}                                              # an old build-up is not today's
    t = t[t["date"] == t["date"].max()]
    t = t[t["symbol"].isin(list(symbols))]
    return {r["symbol"]: {"class": r["class"], "price_change_pct": round(float(r["price_change"]) * 100, 2),
                          "oi_change_pct": None if pd.isna(r["oi_change_pct"]) else round(float(r["oi_change_pct"]) * 100, 1),
                          "on": str(r["date"].date())} for _i, r in t.iterrows()}
