"""What the other side's session means for the open here (S79 item 10): the overnight transmission forecaster's input.

For market IN the question is: the US session that closed before today's NSE open moved by x; what does that say about the
Nifty's opening gap (open / previous close - 1)? Everything is parameterised by `market` (the market whose open is forecast)
and counted in that market's sessions:

    expected_open_gap(con, asof, market="IN") -> {"expected_gap_pct", "sd_pct", "legs": [...], "n": int, ...}

Point in time. The source session for a target morning M is `source.session_closed_by(open of M)`: the latest session whose
close (in IST: 02:30 or 01:30 the next morning for New York) is at or before the target's open. A US close dated after the
Indian open is never read. The betas of day M use only target days before M.

The rule, so no number is chosen by feel:
  HEADLINE   one factor: the source market's benchmark (US_SP500 for IN), OLS over the last WINDOW target sessions. The other
             drivers (Nasdaq, VIX, dollar, crude, Indian ADRs, India funds) are LEGS: each alone on the same window, shown for
             reading, not in the headline. CLAUDE.md #10: a covariate enters the forecast only if a registered comparison
             beats the simpler model on unseen data; `oos_compare` below is that comparison's code (model="multi" is its
             candidate). It has not been run as a claim.
  SMALL SAMPLE  fewer than MIN_N paired observations: the count and the moves, no beta, no forecast.
  STALE      training data ending more than STALE_SESSIONS target sessions before the target day: no forecast.
  SD         the prediction standard deviation of the OLS (residual spread plus the uncertainty of the line), in percent.
Sector links (documented static map below, a reason for each) and ADR -> NSE-name links are shown alongside; they are
descriptions of how the gap moved with the link, not a forecast of a name.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pflab import markets
from pflab.data import data_dir

WINDOW = 250                    # target sessions behind the beta (about one year)
MIN_N = 20                      # under this: the count, no conclusion
STALE_SESSIONS = 5
MAX_GAP_DAYS = 7                # a previous row further back than this is not "the previous session" (missing data)
LABEL = "estimate from a one-factor regression over the last year; relations drift (S79 item 10)"

# market whose open is forecast -> (series key of its open/close, source market, headline driver, label)
TARGETS = {
    "IN": {"key": "NIFTY50_PRICE", "source": "US", "headline": "US_SP500", "name": "Nifty 50"},
    "US": {"key": "US_SP500", "source": "IN", "headline": "NIFTY50_PRICE", "name": "S&P 500"},
}

ADR_KEYS = ("ADR_INFY", "ADR_WIT", "ADR_HDB", "ADR_IBN", "ADR_RDY")

# driver = (key, label, kind, why). kind: pct = percent change of the close, diff = change in points.
DRIVERS: Dict[str, List[tuple]] = {
    "IN": [
        ("US_SP500", "S&P 500", "pct", "the US broad market: foreign funds trade India as part of global risk"),
        ("US_NASDAQ", "Nasdaq", "pct", "US technology and growth: the large share of Indian IT earnings sits with US clients"),
        ("US_VIX", "US VIX", "diff", "US fear gauge: a jump means funds cut risk everywhere, emerging markets first"),
        ("DOLLAR_INDEX", "Dollar index", "pct", "a stronger dollar pulls money out of rupee assets"),
        ("WTI", "WTI crude", "pct", "India imports most of its oil: dearer crude hurts the rupee, margins and the deficit"),
        ("ADR_BASKET", "Indian ADRs (the five Indian companies listed in the US)", "pct",
         "Indian companies priced in New York while the NSE is shut: the closest read of the same shares"),
        ("US_INDIA_INDA", "iShares MSCI India (INDA)", "pct", "an India fund that trades in New York: the US view of India itself"),
    ],
    "US": [
        ("NIFTY50_PRICE", "Nifty 50", "pct", "India closes before the US opens; emerging-market risk appetite carries over weakly"),
    ],
}

# US sector ETF -> Indian sector index (data.indices SECTOR_*_PRICE), with the reason for the link. Static, documented.
SECTOR_LINKS: List[tuple] = [
    ("US_SECTOR_XLK", "SECTOR_IT_PRICE", "Indian IT services earn mostly in dollars from US clients; US technology sets their multiples"),
    ("US_SECTOR_XLF", "SECTOR_PRIVATE_BANK_PRICE", "global financials = risk appetite and foreign-fund flows into Indian private banks (HDFC Bank, ICICI Bank list in New York)"),
    ("US_SECTOR_XLF", "SECTOR_BANK_PRICE", "Bank Nifty: foreign funds hold the large private banks, so global financials set the morning's bias"),
    ("US_SECTOR_XLF", "SECTOR_FIN_SERVICES_PRICE", "the same flow channel for lenders and insurers"),
    ("US_SECTOR_XLE", "SECTOR_OIL_GAS_PRICE", "energy prices and global energy sentiment drive refiners and explorers"),
    ("US_SECTOR_XLV", "SECTOR_PHARMA_PRICE", "the US is the largest export market for Indian generics; US health-care pricing news moves them (Dr Reddy's lists in New York)"),
    ("US_SECTOR_XLB", "SECTOR_METAL_PRICE", "metal prices are set globally; US materials track the same cycle"),
    ("US_SECTOR_XLY", "SECTOR_AUTO_PRICE", "consumer discretionary = cyclical demand; Indian autos have US exposure through exports and JLR"),
    ("US_SECTOR_XLP", "SECTOR_FMCG_PRICE", "defensive rotation: staples gain when funds hide, a weak link for India's domestic consumers"),
    ("US_SECTOR_XLI", "SECTOR_INFRA_PRICE", "global capital-goods cycle; a weak prior, shown to be tested"),
]

# ADR key -> NSE symbol of the same company (one ADR is a fixed number of the NSE shares)
ADR_NSE = {"ADR_INFY": "ADR_INFY"[4:], "ADR_WIT": "WIPRO", "ADR_HDB": "HDFCBANK", "ADR_IBN": "ICICIBANK", "ADR_RDY": "DRREDDY"}


# --- data --------------------------------------------------------------------------------------------------------------

def load_frame(root: Path, key: str) -> Optional[pd.DataFrame]:
    """date (python date), open, close for a global series or an NSE index series; None when the file is not there."""
    for sub in ("global", "indices"):
        p = Path(root) / sub / f"{key}.parquet"
        if p.exists():
            try:
                df = pd.read_parquet(p)
            except Exception:
                return None
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"]).dt.date
            if "open" not in df.columns:
                df["open"] = np.nan
            df = df.dropna(subset=["close"]).drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
            return df[["date", "open", "close"]]
    return None


def _prev_ok(dates: pd.Series) -> pd.Series:
    d = pd.to_datetime(dates)
    return (d - d.shift(1)).dt.days <= MAX_GAP_DAYS


def moves(frame: Optional[pd.DataFrame], kind: str) -> pd.Series:
    """Close-to-previous-close move per row date: fraction (pct) or points (diff). NaN where the previous row is far back."""
    if frame is None or len(frame) < 2:
        return pd.Series(dtype=float)
    c = frame["close"].astype(float)
    m = (c / c.shift(1) - 1.0) if kind == "pct" else (c - c.shift(1))
    m = m.where(_prev_ok(frame["date"]))
    return pd.Series(m.to_numpy(), index=list(frame["date"]))


def gaps(frame: Optional[pd.DataFrame]) -> pd.Series:
    """Opening gap per row date: open / previous close - 1 (a fraction)."""
    if frame is None or len(frame) < 2:
        return pd.Series(dtype=float)
    g = frame["open"].astype(float) / frame["close"].astype(float).shift(1) - 1.0
    g = g.where(_prev_ok(frame["date"]) & (frame["open"] > 0))
    return pd.Series(g.to_numpy(), index=list(frame["date"]))


def driver_moves(root: Path, key: str, kind: str) -> pd.Series:
    if key == "ADR_BASKET":
        cols = [moves(load_frame(root, k), "pct") for k in ADR_KEYS]
        cols = [c for c in cols if len(c)]
        if not cols:
            return pd.Series(dtype=float)
        df = pd.concat(cols, axis=1)
        return df.mean(axis=1).where(df.notna().sum(axis=1) >= 2)
    return moves(load_frame(root, key), kind)


# --- the calendar rule -------------------------------------------------------------------------------------------------

def source_session(target_market: str, m: date) -> date:
    """The latest session of the source market whose close is at or before the open of target session `m`."""
    tgt, src = markets.get(target_market), markets.get(TARGETS[target_market]["source"])
    w = tgt.window_ist(m)
    return src.session_closed_by(w[0] if w else datetime.combine(m, tgt.open))


# --- regression --------------------------------------------------------------------------------------------------------

def ols(x: np.ndarray, y: np.ndarray) -> Optional[dict]:
    """y = a + b x. Returns beta, alpha, r2, n, s (residual sd), xbar, sxx; None when x has no spread."""
    n = len(x)
    if n < 3:
        return None
    xb, yb = float(x.mean()), float(y.mean())
    sxx = float(((x - xb) ** 2).sum())
    if sxx <= 1e-18:
        return None
    b = float(((x - xb) * (y - yb)).sum() / sxx)
    a = yb - b * xb
    res = y - (a + b * x)
    sse, sst = float((res ** 2).sum()), float(((y - yb) ** 2).sum())
    return {"beta": b, "alpha": a, "r2": (1 - sse / sst) if sst > 0 else 0.0, "n": n,
            "s": math.sqrt(sse / (n - 2)), "xbar": xb, "sxx": sxx}


def predict(fit: dict, x0: float) -> Tuple[float, float]:
    """The line at x0 and the prediction sd (residual spread plus the line's own uncertainty)."""
    mean = fit["alpha"] + fit["beta"] * x0
    sd = fit["s"] * math.sqrt(1.0 + 1.0 / fit["n"] + (x0 - fit["xbar"]) ** 2 / fit["sxx"])
    return mean, sd


def _pairs(root: Path, market: str, target_day: date, window: int, drivers: List[tuple]) -> Tuple[pd.DataFrame, Optional[str], dict]:
    """Training frame: one row per past target day (strictly before `target_day`), gap and each driver's move at that day's
    source session. Returns (frame, name of the last training day or None, {driver: moves series})."""
    tcfg = TARGETS[market]
    g = gaps(load_frame(root, tcfg["key"]))
    g = g[[d for d in g.index if d < target_day]].dropna()
    g = g.iloc[-(window + 40):]                                  # a few spare rows: a driver may be missing on some days
    mv = {k: driver_moves(root, k, kind) for k, _l, kind, _w in drivers}
    rows = []
    for d, gap in g.items():
        u = source_session(market, d)
        rows.append({"day": d, "src": u, "gap": float(gap), **{k: (float(s.get(u)) if u in s.index and pd.notna(s.get(u)) else np.nan)
                                                              for k, s in mv.items()}})
    df = pd.DataFrame(rows)
    return df, (str(g.index[-1]) if len(g) else None), mv


def _fit_leg(df: pd.DataFrame, key: str, window: int) -> Optional[dict]:
    if df.empty or key not in df:
        return None
    d = df.dropna(subset=["gap", key]).iloc[-window:]
    if len(d) < MIN_N:
        return {"n": int(len(d))}
    fit = ols(d[key].to_numpy(float), d["gap"].to_numpy(float))
    return fit if fit else {"n": int(len(d))}


def expected_open_gap(con, asof: date, market: str = "IN", root: Optional[Path] = None, model: str = "headline",
                      window: int = WINDOW) -> dict:
    """The expected opening gap of `market` on the morning of `asof` (its next session when asof is not one), in percent,
    from the source market's last close before that open. `con` is the store (unused today; kept so the forecaster calls
    every input the same way). Never raises on missing data: expected_gap_pct is None and `note` says why."""
    root = Path(root) if root else data_dir()
    out = {"market": market, "asof": str(asof), "expected_gap_pct": None, "sd_pct": None, "legs": [], "n": 0, "label": LABEL}
    if market not in TARGETS:
        out["note"] = f"market {market!r} is not supported; one of {sorted(TARGETS)}"
        return out
    tm, tcfg = markets.get(market), TARGETS[market]
    target = asof if tm.is_session(asof) else tm.next_session(asof)
    u = source_session(market, target)
    drivers = DRIVERS[market]
    out.update({"target_session": str(target), "source_market": tcfg["source"], "source_session": str(u), "headline_driver": tcfg["headline"],
                "model": model, "window_sessions": window, "target": tcfg["name"]})
    sw, tw = markets.get(tcfg["source"]).window_ist(u), tm.window_ist(target)
    if sw is not None and tw is not None and sw[1] > tw[0]:       # calendar rule: the source close is at or before the target's open
        out["note"] = f"calendar: source session {u} closes after the open of {target}"
        return out
    df, last_train, mv = _pairs(root, market, target, window, drivers)
    notes: List[str] = []
    realized = gaps(load_frame(root, tcfg["key"]))
    if target in realized.index and pd.notna(realized[target]):
        out["realized_gap_pct"] = round(float(realized[target]) * 100, 4)
    legs = []
    for key, label, kind, why in drivers:
        s = mv.get(key)
        x0 = float(s[u]) if s is not None and u in s.index and pd.notna(s[u]) else None
        leg = {"driver": key, "label": label, "move_kind": kind, "why": why, "source_move": None if x0 is None else (round(x0 * 100, 4) if kind == "pct" else round(x0, 4)),
               "source_move_unit": "percent" if kind == "pct" else "points",
               "beta_unit": "gap fraction per 1.00 fractional move" if kind == "pct" else "gap fraction per point", "headline": key == tcfg["headline"],
               "beta": None, "r2": None, "n": 0, "contribution_pct": None}
        fit = _fit_leg(df, key, window)
        if fit:
            leg["n"] = int(fit["n"])
            if "beta" in fit:
                leg.update({"beta": round(fit["beta"], 4), "r2": round(fit["r2"], 4)})
                if x0 is not None:
                    leg["contribution_pct"] = round((fit["alpha"] + fit["beta"] * x0) * 100, 4)
        if x0 is None:
            leg["missing"] = f"no {label} close for source session {u}"
        legs.append(leg)
    out["legs"] = legs
    head = next((l for l in legs if l["headline"]), None)
    out["n"] = head["n"] if head else 0
    out["last_training_day"] = last_train
    if last_train and tm.session_count(date.fromisoformat(last_train), target) - 1 > STALE_SESSIONS:
        notes.append(f"stale: the {tcfg['name']} data ends {last_train}, more than {STALE_SESSIONS} sessions before {target}")
    elif head is None or head["n"] < MIN_N:
        notes.append(f"small sample: {out['n']} paired sessions, under {MIN_N}: no conclusion")
    elif head.get("missing"):
        notes.append(head["missing"])
    else:
        x0 = head["source_move"] / 100.0
        if model == "multi":
            pred = _multi(df, drivers, {l["driver"]: l["source_move"] for l in legs}, window)
            if pred:
                out["expected_gap_pct"], out["sd_pct"], out["n"], out["multi_drivers"] = pred
            else:
                notes.append("multi model: too few complete rows or no driver moves; fall back to the headline")
        if out["expected_gap_pct"] is None:
            fit = _fit_leg(df, tcfg["headline"], window)
            mean, sd = predict(fit, x0)
            out["expected_gap_pct"], out["sd_pct"] = round(mean * 100, 4), round(sd * 100, 4)
            out["beta"], out["r2"] = round(fit["beta"], 4), round(fit["r2"], 4)
    out["sector_links"] = sector_links(root, market, target, u, window) if market == "IN" else []
    out["adr_links"] = adr_links(root, market, target, u, window) if market == "IN" else []
    if notes:
        out["note"] = "; ".join(notes)
    return out


def _multi(df: pd.DataFrame, drivers: List[tuple], today: Dict[str, Optional[float]], window: int):
    """Candidate model for the registered comparison: OLS on every driver that has a move today and enough complete rows."""
    keys = [k for k, _l, kind, _w in drivers if today.get(k) is not None]
    d = df.dropna(subset=["gap"] + keys).iloc[-window:] if keys else df.iloc[0:0]
    if not keys or len(d) < max(MIN_N, 3 * (len(keys) + 1)):
        return None
    kind = {k: kd for k, _l, kd, _w in drivers}
    X = np.column_stack([np.ones(len(d))] + [d[k].to_numpy(float) for k in keys])
    y = d["gap"].to_numpy(float)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ coef
    s2 = float(res @ res) / (len(d) - X.shape[1])
    x0 = np.array([1.0] + [today[k] / 100.0 if kind[k] == "pct" else today[k] for k in keys])
    h = float(x0 @ np.linalg.pinv(X.T @ X) @ x0)
    return round(float(x0 @ coef) * 100, 4), round(math.sqrt(s2 * (1 + h)) * 100, 4), int(len(d)), keys


def sector_links(root: Path, market: str, target: date, u: date, window: int = WINDOW) -> List[dict]:
    """For each documented US sector ETF -> Indian sector index link: how the Indian index's opening gap moved with the ETF's
    session move over the window (point in time), and what that line says for today's ETF move."""
    out = []
    for us_key, in_key, why in SECTOR_LINKS:
        etf = moves(load_frame(root, us_key), "pct")
        fr = load_frame(root, in_key)
        row = {"us_etf": us_key, "in_index": in_key, "reason": why, "us_move_pct": None, "beta": None, "r2": None, "n": 0,
               "implied_gap_pct": None, "sd_pct": None}
        if fr is None or not len(etf):
            row["note"] = "no data file"
            out.append(row)
            continue
        g = gaps(fr)
        g = g[[d for d in g.index if d < target]].dropna().iloc[-(window + 40):]
        if len(g) and markets.get(market).session_count(g.index[-1], target) - 1 > STALE_SESSIONS:
            row["note"] = f"stale: the index data ends {g.index[-1]}"
            out.append(row)
            continue
        pairs = [(float(etf[su]), float(gp)) for d, gp in g.items() for su in [source_session(market, d)] if su in etf.index and pd.notna(etf[su])]
        pairs = pairs[-window:]
        row["n"] = len(pairs)
        x0 = float(etf[u]) if u in etf.index and pd.notna(etf[u]) else None
        row["us_move_pct"] = None if x0 is None else round(x0 * 100, 4)
        if len(pairs) < MIN_N:
            row["note"] = f"small sample: {len(pairs)} sessions, under {MIN_N}"
        else:
            fit = ols(np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs]))
            if fit:
                row.update({"beta": round(fit["beta"], 4), "r2": round(fit["r2"], 4)})
                if x0 is not None:
                    mean, sd = predict(fit, x0)
                    row["implied_gap_pct"], row["sd_pct"] = round(mean * 100, 4), round(sd * 100, 4)
        out.append(row)
    return out


def adr_links(root: Path, market: str, target: date, u: date, window: int = WINDOW) -> List[dict]:
    """For each Indian ADR: the NSE share's opening gap against the ADR's session move (same company, so the strongest link)."""
    out = []
    for adr, sym in ADR_NSE.items():
        mv = moves(load_frame(root, adr), "pct")
        row = {"adr": adr, "nse_symbol": sym, "us_move_pct": None, "beta": None, "r2": None, "n": 0, "implied_gap_pct": None, "sd_pct": None}
        g = nse_gaps(root, sym, target)
        if not len(mv) or not len(g):
            row["note"] = "no data"
            out.append(row)
            continue
        g = g.iloc[-(window + 40):]
        pairs = [(float(mv[su]), float(gp)) for d, gp in g.items() for su in [source_session(market, d)] if su in mv.index and pd.notna(mv[su])][-window:]
        row["n"] = len(pairs)
        x0 = float(mv[u]) if u in mv.index and pd.notna(mv[u]) else None
        row["us_move_pct"] = None if x0 is None else round(x0 * 100, 4)
        if len(pairs) < MIN_N:
            row["note"] = f"small sample: {len(pairs)} sessions, under {MIN_N}"
        else:
            fit = ols(np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs]))
            if fit:
                row.update({"beta": round(fit["beta"], 4), "r2": round(fit["r2"], 4)})
                if x0 is not None:
                    mean, sd = predict(fit, x0)
                    row["implied_gap_pct"], row["sd_pct"] = round(mean * 100, 4), round(sd * 100, 4)
        out.append(row)
    return out


def resolve_isin(root: Path, symbol: str, asof: date) -> Optional[str]:
    """ISIN of an NSE symbol as of a date (the symbol is read from the panel's row on or before `asof`, never joined without a date)."""
    p = Path(root) / "panel" / "prices.parquet"
    if not p.exists():
        return None
    from pflab import _duck
    r = _duck.sql(f"SELECT isin FROM '{p.as_posix()}' WHERE symbol = '{symbol.replace(chr(39), '')}' AND date <= DATE '{asof}' "
                  f"ORDER BY date DESC LIMIT 1").fetchall()
    return r[0][0] if r else None


def nse_frame(root: Path, symbol: str, asof: date, years: int = 3) -> Optional[pd.DataFrame]:
    """Adjusted open and close of an NSE share (by ISIN as of `asof`), rows dated <= asof."""
    isin = resolve_isin(root, symbol, asof)
    if not isin:
        return None
    from pflab import _duck
    p = (Path(root) / "panel" / "prices.parquet").as_posix()
    df = _duck.sql(f"SELECT date, adj_open AS open, adj_close AS close FROM '{p}' WHERE isin = '{isin}' AND date <= DATE '{asof}' "
                   f"AND date >= DATE '{asof - timedelta(days=365 * years)}' ORDER BY date").df()
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def nse_gaps(root: Path, symbol: str, target: date) -> pd.Series:
    fr = nse_frame(root, symbol, target - timedelta(days=1))
    return gaps(fr).dropna() if fr is not None else pd.Series(dtype=float)


# --- the comparison the headline waits for -----------------------------------------------------------------------------

def oos_compare(root: Path, market: str = "IN", start: Optional[date] = None, end: Optional[date] = None, window: int = WINDOW,
                step: int = 1) -> dict:
    """Walk-forward: for each target day in [start, end], fit on the `window` days before it and predict its gap with the
    headline (one factor) and the multi model; the mean squared error of each and the share of days the multi model won.
    Code for the registered comparison; running it on real data is a counted test (CLAUDE.md #10), so nothing here runs it."""
    tcfg = TARGETS[market]
    drivers = DRIVERS[market]
    end = end or date.today()
    g = gaps(load_frame(root, tcfg["key"]))
    days = [d for d in g.index if pd.notna(g[d]) and (start is None or d >= start) and d <= end][::step]
    se_h, se_m = [], []
    for d in days:
        df, _last, mv = _pairs(root, market, d, window, drivers)
        u = source_session(market, d)
        today = {k: (float(s[u]) * (100.0 if kind == "pct" else 1.0) if u in s.index and pd.notna(s[u]) else None)
                 for k, _l, kind, _w in drivers for s in [mv[k]]}
        fit = _fit_leg(df, tcfg["headline"], window)
        mu = _multi(df, drivers, today, window)
        if not fit or "beta" not in fit or today.get(tcfg["headline"]) is None or mu is None:
            continue
        ph, _ = predict(fit, today[tcfg["headline"]] / 100.0)
        se_h.append((ph - float(g[d])) ** 2)
        se_m.append((mu[0] / 100.0 - float(g[d])) ** 2)
    n = len(se_h)
    return {"market": market, "n_days": n, "mse_headline": float(np.mean(se_h)) if n else None, "mse_multi": float(np.mean(se_m)) if n else None,
            "multi_won_share": float(np.mean([m < h for h, m in zip(se_h, se_m)])) if n else None}
