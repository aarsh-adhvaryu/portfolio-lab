"""Forecasts without TimesFM (S64 Phase 3, replaces S52's tfm2_live). Layer: TOOLS (code only; no model writes a number).

    turnover   the registered baseline (HAR on ln turnover with the calendar), for the trader's tickets' size check
    results    next quarter's revenue and net margin: same quarter last year (times trailing growth for revenue)
    price      NEW: q10 / q50 / q90 of each held and listed stock's price 21, 63 and 252 sessions ahead, from a stationary
               block bootstrap (mean block 10 sessions) of its own last 750 daily log returns; the centre is the CAPM
               expected return (risk/capm.py), never momentum; method `stats_plain` as drawn, `stats_ewma` rescaled by
               EWMA volatility (lambda 0.94) over sample volatility. Which serves is decided by the registered
               calibration test (docs/protocols/s64_ranges_protocol.md; quant/ranges_eval.py): until it has run the ranges
               say "not tested yet"; if neither method covers, "not calibrated: covered x% in testing".
    scored     every stored forecast when due; price ranges by inside/outside and pinball loss; the rolling coverage of
               the last 60 scored ranges is shown with the range

AGENTS read this module's output (they add no numbers): the trader's tickets (`size_note`), the researcher and thesis
tracker (`results_lines`), the brain's `forecasts` tool, the dashboard. PLOTS: `fan(...)` gives a stock's range per horizon
for the stock page. Portfolio value ranges stay in risk/montecarlo.
"""
from __future__ import annotations

import json
import math
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pflab.quant import baselines as bl

USES = ("turnover", "revenue", "margin")
BASELINE = {"turnover": "har_cal", "revenue": "with_trailing_growth", "margin": "same_q_last_year"}
BASE_LABEL = {"har_cal": "HAR + calendar", "mean20": "20-session mean", "with_trailing_growth": "last year x trailing growth",
              "same_q_last_year": "same quarter last year"}
H5, CTX5, MIN_FINITE, Q6_MIN_RUN = 5, 512, 8, 8
BASE_SESSIONS = 1500             # about six years of sessions for the baseline fit
FUTURE = 25
FRESH_DAYS = 7                   # a turnover forecast older than this is not used by the tickets

PRICE_H = (21, 63, 252)
PRICE_USES = tuple(f"price{h}" for h in PRICE_H)
METHODS = ("stats_ewma", "stats_plain")
SAMPLE_SESSIONS, MIN_SESSIONS, MEAN_BLOCK, PATHS, LAMBDA = 750, 250, 10, 10_000, 0.94
LEVELS = (0.1, 0.5, 0.9)
COVER_LAST = 60
RESULT_FILE = ("research", "s64_ranges.json")


# --- inputs (turnover, results) --------------------------------------------------------------------------------------------------

def turnover_wide(root: Path, isins: List[str], start: date, end: date) -> Tuple[List[date], pd.DataFrame]:
    """Every bhavcopy session in [start, end] and the daily turnover (rupees) of `isins` (EQ, BE, BZ; NaN: no trade)."""
    from pflab import _duck
    from pflab.data.bhavcopy import bhav_files
    files = bhav_files(root, start, end)
    if not files:
        return [], pd.DataFrame()
    rel = f"read_parquet({files!r}, union_by_name=true)"
    sess = _duck.sql(f"SELECT DISTINCT date FROM {rel} WHERE date BETWEEN DATE '{start}' AND DATE '{end}' ORDER BY 1").df()
    dates = [pd.Timestamp(x).date() for x in sess["date"]]
    if not isins:
        return dates, pd.DataFrame(index=dates)
    lst = ",".join(f"'{i}'" for i in isins)
    tv = _duck.sql(f"SELECT date, isin, sum(turnover) t FROM {rel} WHERE date BETWEEN DATE '{start}' AND DATE '{end}' "
                    f"AND series IN ('EQ', 'BE', 'BZ') AND isin IN ({lst}) GROUP BY 1, 2").df()
    tv["date"] = [pd.Timestamp(x).date() for x in tv["date"]]
    wide = tv.pivot(index="date", columns="isin", values="t").reindex(dates)
    return dates, wide.reindex(columns=isins)


def future_sessions(cal, after: date, n: int) -> List[date]:
    out, d = [], after
    for _ in range(n):
        d = cal.next_trading_day(d)
        out.append(d)
    return out


def turnover_case(dates: List[date], rupees: np.ndarray, future: List[date]) -> Optional[dict]:
    """One stock at the last session of `dates`: the baseline for the next 5 sessions and the target date."""
    t = len(dates) - 1
    lev = np.asarray(rupees, float)
    lt = np.r_[np.log(np.where(lev > 0, lev, np.nan)), np.full(len(future), np.nan)]
    cov = bl.calendar_covariates(list(dates) + list(future))
    s = max(0, t + 1 - CTX5)
    ok = np.flatnonzero(np.isfinite(lt[s:t + 1]))
    if len(ok) < MIN_FINITE:
        return None
    idx = np.arange(t, 21, -H5)[::-1]                             # every 5th session ending at t
    idx = idx[idx >= max(22, t - BASE_SESSIONS)]
    matured = idx + H5 <= t
    base, bname = np.nan, "har_cal"
    if matured.sum() >= 30:
        base = float(bl.turnover_baselines(lt, cov, idx, matured, H5)["har_cal"][-1])
    if not np.isfinite(base):                                     # too short a history for the HAR: the simple baseline
        m20 = pd.Series(lt[:t + 1]).ffill().rolling(20, min_periods=15).mean().iloc[-1]
        base, bname = (float(m20) if np.isfinite(m20) else np.nan), "mean20"
    return {"baseline": base, "baseline_name": bname, "target": str(future[H5 - 1]), "inputs_last": str(dates[t])}


def results_history(con, root: Path, scrip: str, asof: date) -> pd.DataFrame:
    """Standalone quarters usable by `asof`: data/bse_results (history) joined with the PM store (the store wins)."""
    from pflab.fundamentals import pit
    h = pit.load_history(scrip, root)
    h = h[["quarter_end", "revenue", "net_profit"]] if len(h) else pd.DataFrame(columns=["quarter_end", "revenue", "net_profit"])
    s = con.execute("SELECT quarter_end, revenue, net_profit FROM quarterly_results WHERE scrip_code=? AND "
                    "basis='standalone' AND usable_from <= ?", [str(scrip), asof]).df()
    q = pd.concat([h, s], ignore_index=True)
    if q.empty:
        return q
    q["quarter_end"] = [pd.Timestamp(x).date() for x in q["quarter_end"]]
    return q.drop_duplicates("quarter_end", keep="last").sort_values("quarter_end").reset_index(drop=True)


def results_case(q: pd.DataFrame) -> dict:
    """Next quarter's baselines (a run under 8 consecutive quarters: no forecast)."""
    s = bl.quarter_series(q) if len(q) else pd.DataFrame()
    if s.empty:
        return {"run": 0}
    last = pd.Timestamp(s["quarter_end"].iloc[-1])
    nxt = (last + pd.offsets.QuarterEnd(1)).date()
    qe = [pd.Timestamp(x).date() for x in s["quarter_end"]] + [nxt]
    j = bl.consecutive_tail(qe, len(s) - 1)
    out = {"run": len(s) - j, "target": str(nxt), "inputs_last": str(qe[-2])}
    if out["run"] < Q6_MIN_RUN:
        return out
    for use, col in (("revenue", "ln_revenue"), ("margin", "margin")):
        x = s[col].to_numpy(float)
        b = bl.results_baselines(np.r_[x, np.nan], qe, col)[BASELINE[use]][-1]
        out[use] = {"baseline": float(b) if np.isfinite(b) else None}
    return out


def scrip_of(root: Path, isin: str, asof: date) -> Optional[str]:
    from pflab import _duck
    p = root / "bse_scrip_isin" / "map.parquet"
    if not p.exists():
        return None
    r = _duck.sql(f"SELECT scrip_code FROM '{p.as_posix()}' WHERE isin = '{isin}' AND valid_from <= DATE '{asof}' "
                   f"ORDER BY valid_from DESC LIMIT 1").fetchone()
    return str(r[0]) if r else None


def build(con, root: Path, asof: date, universe: pd.DataFrame, cal) -> dict:
    """The baselines for tonight (JSON-ready). `universe`: isin, symbol, scrip."""
    u = universe[universe["isin"].astype(str).str.startswith("INE")]
    isins = sorted(u["isin"].astype(str))
    dates, wide = turnover_wide(root, isins, asof - timedelta(days=int((BASE_SESSIONS + 40) * 1.5)), asof)
    out: dict = {"asof": str(dates[-1]) if dates else str(asof), "turnover": [], "revenue": [], "margin": [], "skipped": {}}
    if dates:
        fut = future_sessions(cal, dates[-1], H5 + FUTURE)
        for i in isins:
            c = turnover_case(dates, wide[i].to_numpy(float), fut) if i in wide else None
            if c is None:
                out["skipped"][i] = "fewer than 8 sessions with turnover in the last 512"
                continue
            out["turnover"].append({"key": i, **c})
    for r in u.itertuples():
        scrip = r.scrip if isinstance(getattr(r, "scrip", None), str) and r.scrip else scrip_of(root, r.isin, asof)
        if not scrip:
            continue
        c = results_case(results_history(con, root, scrip, asof))
        if c["run"] < Q6_MIN_RUN:
            out["skipped"][scrip] = f"results: {c['run']} consecutive quarters on record, {Q6_MIN_RUN} needed"
            continue
        for use in ("revenue", "margin"):
            out[use].append({"key": scrip, "isin": r.isin, "target": c["target"], "asof": str(asof),
                             "inputs_last": c["inputs_last"], "baseline_name": BASELINE[use], **c[use]})
    return out


# --- price ranges ---------------------------------------------------------------------------------------------------------

def stationary_bootstrap(lr: np.ndarray, steps: int, paths: int, rng: np.random.Generator, mean_block: int = MEAN_BLOCK) -> np.ndarray:
    """(paths, steps) daily log returns drawn in blocks of random (geometric) length from `lr` (Politis and Romano 1994)."""
    n = len(lr)
    idx = np.empty((paths, steps), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, paths)
    new = rng.random((paths, steps)) < 1.0 / mean_block
    starts = rng.integers(0, n, (paths, steps))
    for t in range(1, steps):
        idx[:, t] = np.where(new[:, t], starts[:, t], (idx[:, t - 1] + 1) % n)
    return lr[idx]


def ewma_scale(lr: np.ndarray, sample: np.ndarray, lam: float = LAMBDA) -> float:
    """Today's EWMA volatility over the sample volatility (1.0 when either is not usable)."""
    ew = bl.ewma(lr, lam=lam)
    sd = float(np.std(sample, ddof=1)) if len(sample) > 2 else 0.0
    now = float(ew[-1]) if len(ew) and np.isfinite(ew[-1]) else float("nan")
    return math.sqrt(now) / sd if sd > 0 and np.isfinite(now) and now > 0 else 1.0


def price_ranges(lr: np.ndarray, price: float, drift_annual: float, horizons=PRICE_H, paths: int = PATHS,
                 rng: Optional[np.random.Generator] = None, methods=METHODS) -> Dict[str, Dict[int, Tuple[float, float, float]]]:
    """{method: {h: (q10, q50, q90) of the price h sessions ahead}} from one set of block-bootstrap draws.
    The sample's own mean is removed and the CAPM drift (annual, simple) put in its place."""
    rng = rng or np.random.default_rng(0)
    lr = np.asarray(lr, float)
    lr = lr[np.isfinite(lr)]
    sample = lr[-SAMPLE_SESSIONS:]
    draws = stationary_bootstrap(sample - sample.mean(), max(horizons), paths, rng)
    drift_d = math.log1p(drift_annual) / 252.0
    out: Dict[str, Dict[int, Tuple[float, float, float]]] = {}
    for m in methods:
        d = draws * (ewma_scale(lr, sample) if m == "stats_ewma" else 1.0) + drift_d
        cum = np.cumsum(d, axis=1)
        out[m] = {h: tuple(float(x) for x in np.quantile(price * np.exp(cum[:, h - 1]), LEVELS)) for h in horizons}
    return out


def pinball(y: float, q: Tuple[float, float, float]) -> float:
    """Mean pinball loss of the three quantiles at levels 0.1, 0.5, 0.9."""
    return float(np.mean([max(t * (y - v), (t - 1.0) * (y - v)) for t, v in zip(LEVELS, q)]))


def target_date(asof: date, h: int) -> date:
    return asof + timedelta(days=int(math.ceil(h * 365 / 252)))


def drift_for(root: Path, isin: str, asof: date, table=None, erp: Optional[float] = None) -> Tuple[float, str]:
    """(annual CAPM expected return, how it was made). A name without a 36-month fit counts as beta 1."""
    from pflab.data import riskfree
    from pflab.risk import capm
    table = riskfree.monthly_table(root) if table is None else table
    erp = capm.erp(root, table) if erp is None else erp
    f = capm.for_isin(root, isin, asof, table)
    beta = f["beta"] if f.get("beta") is not None else 1.0
    how = f"CAPM beta {beta:.2f}" if f.get("beta") is not None else "no 36-month fit: beta 1"
    return capm.expected_return(beta, f["rf_now"], erp), how


def serving_method(root: Optional[Path] = None) -> Tuple[str, str]:
    """(method that serves, label to show with its ranges) from the calibration test's result file."""
    from pflab.data import data_dir
    p = Path(root or data_dir()).joinpath(*RESULT_FILE)
    if not p.exists():
        return "stats_plain", "not tested yet: the calibration test (docs/protocols/s64_ranges_protocol.md) has not run"
    try:
        r = json.loads(p.read_text(encoding="utf-8"))
        return r["serve"], r["label"]
    except Exception:
        return "stats_plain", "not tested yet: the calibration result is unreadable"


# --- store and score -----------------------------------------------------------------------------------------------------------

COLS = ("forecast_id, use, subject, as_of, target, inputs_last, model, q10, q50, q90, point, baseline, baseline_name, "
        "actual, loss_model, loss_baseline, scored_at, created_at")


def _num(x) -> Optional[float]:
    return float(x) if x is not None and np.isfinite(x) else None


def _insert(con, now: datetime, **r) -> None:
    from pflab.pm.store import next_id
    fid = next_id(con, "forecasts", "forecast_id")
    con.execute(f"INSERT INTO forecasts ({COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [fid, r["use"], r["subject"], r["asof"], r["target"], r["inputs_last"], r.get("model"), r.get("q10"),
                 r.get("q50"), r.get("q90"), r.get("point"), r.get("baseline"), r.get("baseline_name"), None, None, None,
                 None, now])


def store_baselines(con, inputs: dict, now: datetime) -> int:
    """Turnover: one row per stock and night. Results: one row per company and quarter, made before the result."""
    n = 0
    for use in USES:
        for c in inputs.get(use, []):
            b = _num(c.get("baseline"))
            if use == "turnover":
                if con.execute("SELECT 1 FROM forecasts WHERE use=? AND subject=? AND as_of=?", [use, c["key"], inputs["asof"]]).fetchone():
                    continue
                asof = inputs["asof"]
            else:
                if con.execute("SELECT 1 FROM forecasts WHERE use=? AND subject=? AND target=?", [use, c["key"], c["target"]]).fetchone():
                    continue
                asof = c.get("asof", inputs["asof"])
            _insert(con, now, use=use, subject=c["key"], asof=asof, target=c["target"], inputs_last=c["inputs_last"],
                    model="baseline", point=b, baseline=b, baseline_name=c.get("baseline_name", BASELINE[use]))
            n += 1
    return n


def store_prices(con, root: Path, asof: date, universe: pd.DataFrame, now: datetime, paths: int = PATHS) -> dict:
    """Both methods' ranges for every held and listed stock at 21, 63 and 252 sessions (one row each)."""
    from pflab.app import research
    from pflab.data import riskfree
    from pflab.risk import capm
    table = erp = None
    n, skipped = 0, {}
    for r in universe.itertuples():
        isin = str(r.isin)
        if not isin.startswith("INE"):
            continue
        c = research.closes(con, root, isin, asof, years=4).dropna()
        if len(c) < MIN_SESSIONS + 1:
            skipped[isin] = f"{len(c)} sessions of prices, {MIN_SESSIONS} needed"
            continue
        if table is None:                                       # the cash rate and the market premium, once
            table = riskfree.monthly_table(root)
            erp = capm.erp(root, table)
        lr = np.diff(np.log(c.to_numpy(float)))
        drift, _how = drift_for(root, isin, asof, table, erp)
        rng = np.random.default_rng([asof.toordinal(), zlib.crc32(isin.encode())])
        res = price_ranges(lr, float(c.iloc[-1]), drift, paths=paths, rng=rng)
        last = pd.Timestamp(c.index[-1]).date()
        for m, by_h in res.items():
            for h, q in by_h.items():
                use = f"price{h}"
                if con.execute("SELECT 1 FROM forecasts WHERE use=? AND subject=? AND as_of=? AND model=?",
                               [use, isin, asof, m]).fetchone():
                    continue
                _insert(con, now, use=use, subject=isin, asof=asof, target=target_date(asof, h), inputs_last=last, model=m,
                        q10=q[0], q50=q[1], q90=q[2], point=q[1], baseline=float(c.iloc[-1]), baseline_name="last_close")
                n += 1
    return {"stored": n, "skipped": skipped}


def turnover_actual(dates: List[date], wide: pd.DataFrame, isin: str, asof: date, target: date) -> Optional[float]:
    """ln of the mean daily turnover over the sessions after `asof` up to `target`, once `target` has traded."""
    if not dates or dates[-1] < target or isin not in wide:
        return None
    s = wide[isin]
    v = s[[d for d in dates if asof < d <= target]].to_numpy(float)
    v = v[np.isfinite(v) & (v > 0)]
    return math.log(v.mean()) if len(v) else None


def results_actual(con, root: Path, scrip: str, quarter: date, use: str, asof: date) -> Optional[float]:
    q = results_history(con, root, scrip, asof)
    s = bl.quarter_series(q) if len(q) else pd.DataFrame()
    if s.empty:
        return None
    hit = s[[pd.Timestamp(x).date() == quarter for x in s["quarter_end"]]]
    if hit.empty:
        return None
    v = float(hit.iloc[0]["ln_revenue" if use == "revenue" else "margin"])
    return v if np.isfinite(v) else None


def score(con, actual: Callable[[str, str, date, date], Optional[float]], now: datetime) -> int:
    """Score every open forecast whose target has matured: squared error (turnover), absolute error (results), inside /
    pinball (price: realised price against its q10, q50, q90, loss relative to the price at the time)."""
    n = 0
    for fid, use, subj, asof, target, q10, q50, q90, point, base in con.execute(
            "SELECT forecast_id, use, subject, as_of, target, q10, q50, q90, point, baseline FROM forecasts "
            "WHERE scored_at IS NULL").fetchall():
        y = actual(use, subj, asof, date.fromisoformat(str(target)))
        if y is None:
            continue
        if use.startswith("price"):
            lm = pinball(y, (q10, q50, q90)) / base if base else None
            lb = None
        else:
            f = (lambda e: e * e) if use == "turnover" else abs
            lm = f(y - point) if point is not None else None
            lb = f(y - base) if base is not None else None
        con.execute("UPDATE forecasts SET actual=?, loss_model=?, loss_baseline=?, scored_at=? WHERE forecast_id=?",
                    [y, lm, lb, now, fid])
        n += 1
    return n


def coverage(con, method: str, h: int, last: int = COVER_LAST) -> Optional[dict]:
    """Rolling coverage of the 80% range over the last `last` scored price ranges of a method and horizon."""
    rows = con.execute("SELECT q10, q90, actual FROM forecasts WHERE use=? AND model=? AND scored_at IS NOT NULL "
                       "ORDER BY scored_at DESC, forecast_id DESC LIMIT ?", [f"price{h}", method, last]).fetchall()
    if not rows:
        return None
    inside = sum(1 for a, b, y in rows if a <= y <= b)
    return {"n": len(rows), "covered": inside / len(rows), "method": method, "horizon": h}


def run(con, root: Path, asof: date, universe: pd.DataFrame, cal, now: Optional[datetime] = None, paths: int = PATHS) -> dict:
    """The nightly step: baselines and price ranges built and stored, everything due scored."""
    from pflab.app import research
    now = now or datetime.now()
    inputs = build(con, root, asof, universe, cal)
    stored = store_baselines(con, inputs, now)
    pr = store_prices(con, root, asof, universe, now, paths)
    isins = sorted({s for (s,) in con.execute("SELECT DISTINCT subject FROM forecasts WHERE use='turnover' AND scored_at IS NULL").fetchall()})
    first = con.execute("SELECT min(as_of) FROM forecasts WHERE use='turnover' AND scored_at IS NULL").fetchone()[0]
    dates, wide = turnover_wide(root, isins, pd.Timestamp(first).date(), asof) if isins and first else ([], pd.DataFrame())
    cache: Dict[str, pd.Series] = {}

    def closes(isin):
        if isin not in cache:
            cache[isin] = research.closes(con, root, isin, asof, years=4).dropna()
        return cache[isin]

    def actual(use, subj, a, target):
        if use == "turnover":
            return turnover_actual(dates, wide, subj, pd.Timestamp(a).date(), target)
        if use.startswith("price"):
            c = closes(subj)
            if c.empty or c.index[-1] < pd.Timestamp(target):
                return None
            at = c[c.index <= pd.Timestamp(a)]
            on = c[c.index <= pd.Timestamp(target)]
            ref = con.execute("SELECT baseline FROM forecasts WHERE use=? AND subject=? AND as_of=? LIMIT 1", [use, subj, a]).fetchone()
            return float(ref[0] * on.iloc[-1] / at.iloc[-1]) if ref and len(at) and len(on) else None
        return results_actual(con, root, subj, target, use, asof)
    scored = score(con, actual, now)
    return {"asof": inputs["asof"], "turnover": len(inputs["turnover"]), "revenue": len(inputs["revenue"]),
            "margin": len(inputs["margin"]), "stored": stored + pr["stored"], "scored": scored,
            "skipped": len(inputs["skipped"]) + len(pr["skipped"]), "serving": serving_method(root)[0]}


# --- what the agents read ---------------------------------------------------------------------------------------------------

def turnover_estimate(con, isin: str, asof: Optional[date] = None) -> Optional[Tuple[float, str]]:
    """(rupees a day expected over the next 5 sessions, label) from the latest fresh baseline forecast, or None."""
    asof = asof or date.today()
    r = con.execute("SELECT as_of, baseline, baseline_name FROM forecasts WHERE use='turnover' AND subject=? "
                    "AND as_of <= ? AND as_of > ? ORDER BY as_of DESC LIMIT 1",
                    [isin, asof, asof - timedelta(days=FRESH_DAYS)]).fetchone()
    if not r or r[1] is None:
        return None
    return math.exp(r[1]), f"{BASE_LABEL.get(r[2], r[2])}, made {r[0]:%d-%b}"


def turnover_fn(con, asof: Optional[date] = None) -> Callable[[str], Optional[Tuple[float, str]]]:
    return lambda isin: turnover_estimate(con, isin, asof)


def size_note(order_rupees: float, est: Optional[Tuple[float, str]]) -> Optional[str]:
    if not est or est[0] <= 0:
        return None
    share = order_rupees / est[0]
    return (f"Size check (ESTIMATE, {est[1]}): Rs {order_rupees:,.0f} is {share:.1%} of the expected daily turnover over "
            f"the next 5 sessions (Rs {est[0]:,.0f} a day)" + ("; a large order for this stock" if share > 0.10 else ""))


def _fmt(use: str, v: float) -> str:
    return f"Rs {math.exp(v):,.0f} mn" if use == "revenue" else f"{v:.1%}"


def results_lines(con, scrip: str, symbol: Optional[str] = None, target: Optional[date] = None) -> List[str]:
    """Before a result: what the baseline expects for its quarter (labelled). After it: the result against that. The newest
    quarter, or `target`."""
    out = []
    name = symbol or scrip
    for use in ("revenue", "margin"):
        r = con.execute("SELECT target, baseline, actual, scored_at FROM forecasts WHERE use=? AND subject=? AND "
                        "(CAST(? AS DATE) IS NULL OR target = ?) ORDER BY target DESC LIMIT 1",
                        [use, str(scrip), target, target]).fetchone()
        if not r or r[1] is None:
            continue
        tgt, base, act, scored = r
        what = "revenue" if use == "revenue" else "net margin"
        if scored is None:
            out.append(f"{name} {what}, quarter ending {tgt}: about {_fmt(use, base)} (ESTIMATE, {BASE_LABEL[BASELINE[use]]})")
        elif act is not None:
            out.append(f"{name} {what}, quarter ending {tgt}: {_fmt(use, act)} against about {_fmt(use, base)} "
                       f"({BASE_LABEL[BASELINE[use]]})")
    return out


def price_lines(con, isin: str, symbol: Optional[str] = None, root: Optional[Path] = None) -> List[str]:
    """The serving method's newest price ranges for a stock, each with the label and its rolling coverage."""
    method, label = serving_method(root)
    out = []
    for h in PRICE_H:
        r = con.execute("SELECT as_of, target, q10, q50, q90 FROM forecasts WHERE use=? AND subject=? AND model=? "
                        "ORDER BY as_of DESC LIMIT 1", [f"price{h}", isin, method]).fetchone()
        if not r:
            continue
        cv = coverage(con, method, h)
        cov = f"; covered {cv['covered']:.0%} of the last {cv['n']} scored" if cv else "; none scored yet"
        out.append(f"{symbol or isin} price in {h} sessions (to {r[1]:%d-%b-%Y}, made {r[0]:%d-%b}): {r[2]:,.0f} to {r[4]:,.0f}, "
                   f"middle {r[3]:,.0f} (80% range, ESTIMATE, {method}: {label}{cov})")
    return out


def fan(con, isin: str, root: Optional[Path] = None) -> dict:
    """PLOT input for the stock page: the serving method's q10 / q50 / q90 per horizon, newest run."""
    method, label = serving_method(root)
    rows = []
    for h in PRICE_H:
        r = con.execute("SELECT as_of, q10, q50, q90, baseline FROM forecasts WHERE use=? AND subject=? AND model=? "
                        "ORDER BY as_of DESC LIMIT 1", [f"price{h}", isin, method]).fetchone()
        if r:
            rows.append({"sessions": h, "asof": str(r[0]), "q10": r[1], "q50": r[2], "q90": r[3], "price": r[4]})
    return {"method": method, "label": label, "ranges": rows}


def show(con, root: Optional[Path] = None) -> str:
    L = []
    for use in USES + PRICE_USES:
        n = con.execute("SELECT count(*), max(as_of), count(scored_at) FROM forecasts WHERE use=?", [use]).fetchone()
        L.append(f"{use}: {n[0]} forecast(s), latest {n[1]}, {n[2]} scored")
    for h in PRICE_H:
        for m in METHODS:
            cv = coverage(con, m, h)
            if cv:
                L.append(f"  coverage {m} {h} sessions: {cv['covered']:.0%} of the last {cv['n']} scored (the target is 80%)")
    L.append("serving: " + " - ".join(serving_method(root)))
    for (s,) in con.execute("SELECT DISTINCT subject FROM forecasts WHERE use IN ('revenue', 'margin')").fetchall():
        L += ["  " + x for x in results_lines(con, s)]
    return "\n".join(L)
