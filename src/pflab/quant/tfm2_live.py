"""S52 live: the forecasts that passed their registered tests (docs/research/timesfm2_results.md), served with the
registered scoreboard and fallback (docs/research/timesfm2_protocol.md, "Use" and "Live scoreboard").

    turnover   Q5, T30C (TimesFM 3.0 + day of week, month end, expiry week): ln of the mean daily turnover over the
               next 5 sessions, for list and held stocks; the trader's tickets check an order's size against it
    revenue    Q6, F25 (TimesFM 2.5 fine-tuned on the other scrip-parity fold, as validated): next quarter's ln revenue
    margin     Q6, T25 (TimesFM 2.5 zero-shot): next quarter's net margin
Ranges are the 10% and 90% deciles; the point is what the study scored (turnover: the expected mean over the 5
sessions; results: the median). Each night (`pflab forecast run`): inputs from the bhavcopy and the PM store, point in
time (sessions up to the as-of session, results usable by then); TimesFM in .venv-train on the CPU
(`tools/tfm_live_forecast.py`; a few dozen series); the registered baseline's forecast beside every one; matured
targets scored; the scoreboard updated. Fallback, as registered: over its window, a loss ratio to the baseline above
1.05 with at least half the window matured switches that use to the baseline (the morning report says so); TimesFM
resumes at <= 1.00 over a full window. A night TimesFM could not run, the baseline serves, labelled.

Live forms (2026-10-22, recorded in the results doc): the turnover baseline (HAR + calendar) is refitted each night on
the stock's last BASE_SESSIONS sessions whose targets have matured (the study fitted once on 2008-2014); results history
joins data/bse_results with the store's standalone quarters; a company needs 8 consecutive quarters, as in the study.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pflab.quant import tfm2 as tf

USES = ("turnover", "revenue", "margin")
MODEL = {"turnover": "T30C", "revenue": "F25", "margin": "T25"}
BASELINE = {"turnover": "har_cal", "revenue": "with_trailing_growth", "margin": "same_q_last_year"}
LABEL = {"T30C": "TimesFM 3.0 + calendar", "F25": "TimesFM 2.5 fine-tuned", "T25": "TimesFM 2.5"}
BASE_LABEL = {"har_cal": "HAR + calendar", "mean20": "20-session mean", "with_trailing_growth": "last year x trailing growth",
              "same_q_last_year": "same quarter last year"}
H5, CTX5, MIN_FINITE, Q6_MIN_RUN = 5, 512, 8, 8
BASE_SESSIONS = 1500             # about six years of sessions for the nightly baseline fit
FUTURE = 25                      # calendar sessions after the as-of date (the month-end flag needs one beyond the horizon)
WINDOW_DATES = 60                # Q5: the last 60 forecast dates
SWITCH_AT, RESUME_AT = 1.05, 1.00
FRESH_DAYS = 7                   # a turnover forecast older than this is not used by the tickets


# --- inputs -----------------------------------------------------------------------------------------------------------

def bhav_files(root: Path, start: date, end: date) -> List[str]:
    return [p.as_posix() for y in range(start.year, end.year + 1) for p in sorted((root / "bhavcopy" / str(y)).glob("*.parquet"))]


def turnover_wide(root: Path, isins: List[str], start: date, end: date) -> Tuple[List[date], pd.DataFrame]:
    """Every bhavcopy session in [start, end] and the daily turnover (rupees) of `isins` (EQ, BE, BZ; NaN: no trade)."""
    from pflab import _duck
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
    """One stock at the last session of `dates`: TimesFM's context and calendar, the baseline, the target date."""
    t = len(dates) - 1
    lev = np.asarray(rupees, float)
    lt = np.r_[np.log(np.where(lev > 0, lev, np.nan)), np.full(len(future), np.nan)]
    cov = tf.calendar_covariates(list(dates) + list(future))
    s = max(0, t + 1 - CTX5)
    w = lt[s:t + 1]
    ok = np.flatnonzero(np.isfinite(w))
    if len(ok) < MIN_FINITE:
        return None
    a = ok[0]
    idx = np.arange(t, 21, -H5)[::-1]                             # every 5th session ending at t
    idx = idx[idx >= max(22, t - BASE_SESSIONS)]
    matured = idx + H5 <= t
    base, bname = np.nan, "har_cal"
    if matured.sum() >= 30:
        b = tf.turnover_baselines(lt, cov, idx, matured, H5)
        base = float(b["har_cal"][-1])
    if not np.isfinite(base):                                     # too short a history for the HAR: the simple baseline
        m20 = pd.Series(lt[:t + 1]).ffill().rolling(20, min_periods=15).mean().iloc[-1]
        base, bname = (float(m20) if np.isfinite(m20) else np.nan), "mean20"
    return {"ctx": w[a:].tolist(), "pf": cov[:, s + a:t + 1 + H5].tolist(), "baseline": base, "baseline_name": bname,
            "target": str(future[H5 - 1]), "inputs_last": str(dates[t])}


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
    """Next quarter's contexts and baselines (`run` < 8: no forecast, as in the study)."""
    s = tf.quarter_series(q) if len(q) else pd.DataFrame()
    if s.empty:
        return {"run": 0}
    last = pd.Timestamp(s["quarter_end"].iloc[-1])
    nxt = (last + pd.offsets.QuarterEnd(1)).date()
    qe = [pd.Timestamp(x).date() for x in s["quarter_end"]] + [nxt]
    j = tf.consecutive_tail(qe, len(s) - 1)
    out = {"run": len(s) - j, "target": str(nxt), "inputs_last": str(qe[-2])}
    if out["run"] < Q6_MIN_RUN:
        return out
    for use, col in (("revenue", "ln_revenue"), ("margin", "margin")):
        x = s[col].to_numpy(float)
        b = tf.results_baselines(np.r_[x, np.nan], qe, col)[BASELINE[use]][-1]
        out[use] = {"ctx": x[j:].tolist(), "baseline": float(b) if np.isfinite(b) else None}
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
    """Everything TimesFM needs tonight, plus the baselines (JSON-ready). `universe`: isin, symbol, scrip."""
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
        fold = "A" if int(scrip) % 2 == 0 else "B"
        for use in ("revenue", "margin"):
            out[use].append({"key": scrip, "isin": r.isin, "fold": fold, "target": c["target"], "asof": str(asof),
                             "inputs_last": c["inputs_last"], **c[use]})          # results usable by the run date
    return out


# --- TimesFM (in .venv-train) -----------------------------------------------------------------------------------------

def timesfm_subprocess(repo: Path, folder: Path, timeout_s: int = 1800) -> Callable[[dict], dict]:
    """Runs tools/tfm_live_forecast.py in .venv-train on the CPU, offline (the weights are in the Hugging Face cache)."""
    def run(inputs: dict) -> dict:
        py = repo / ".venv-train" / "Scripts" / "python.exe"
        if not py.exists():
            raise FileNotFoundError(f"{py} (S47/S52 training environment) is missing")
        folder.mkdir(parents=True, exist_ok=True)
        fin, fout = folder / f"inputs_{inputs['asof']}.json", folder / f"deciles_{inputs['asof']}.json"
        fin.write_text(json.dumps(inputs), encoding="utf-8")
        env = {**os.environ, "HF_HUB_OFFLINE": "1", "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run([str(py), str(repo / "tools" / "tfm_live_forecast.py"), str(fin), str(fout)], env=env,
                           capture_output=True, text=True, timeout=timeout_s, cwd=str(repo))
        if r.returncode != 0:
            raise RuntimeError(f"tfm_live_forecast exited {r.returncode}: {(r.stderr or r.stdout)[-400:]}")
        return json.loads(fout.read_text(encoding="utf-8"))
    return run


# --- store, score, scoreboard -----------------------------------------------------------------------------------------

def _num(x) -> Optional[float]:
    return float(x) if x is not None and np.isfinite(x) else None


def rows_from(inputs: dict, deciles: Optional[dict]) -> List[dict]:
    """One row per forecast: TimesFM's deciles (None when it did not run) beside the baseline."""
    out = []
    models = (deciles or {}).get("models", {})
    for use in USES:
        for c in inputs.get(use, []):
            q = (deciles or {}).get(use, {}).get(c["key"])
            row = {"use": use, "subject": c["key"], "asof": c.get("asof", inputs["asof"]), "target": c["target"],
                   "inputs_last": c["inputs_last"], "model": None, "q10": None, "q50": None, "q90": None, "point": None,
                   "baseline": _num(c.get("baseline")), "baseline_name": c.get("baseline_name", BASELINE[use])}
            if q is not None:
                a = np.asarray(q, float)
                if use == "turnover":                              # (5, 9) daily ln turnover deciles
                    if np.isfinite(a).all():
                        lv = np.exp(a)
                        row.update(q10=math.log(lv[:, 0].mean()), q50=math.log(lv[:, 4].mean()), q90=math.log(lv[:, 8].mean()),
                                   point=float(tf.turnover_from_deciles(a[None])[0]))
                elif np.isfinite(a).all():                         # (9,) next quarter's deciles
                    row.update(q10=float(a[0]), q50=float(a[4]), q90=float(a[8]), point=float(a[4]))
                if row["point"] is not None:
                    row["model"] = models.get(use, MODEL[use])
            out.append(row)
    return out


def store_rows(con, rows: List[dict], now: datetime) -> int:
    """Turnover: one row per stock and night. Results: one row per company and quarter, made before the result; a row
    the baseline alone filled (TimesFM did not run) is replaced by a later TimesFM one while the quarter is open."""
    from pflab.pm.store import next_id
    n = 0
    for r in rows:
        if r["use"] != "turnover":
            old = con.execute("SELECT forecast_id, model, scored_at FROM tfm_forecasts WHERE use=? AND subject=? AND target=?",
                              [r["use"], r["subject"], r["target"]]).fetchone()
            if old and (old[1] is not None or old[2] is not None or r["model"] is None):
                continue
            if old:
                con.execute("DELETE FROM tfm_forecasts WHERE forecast_id=?", [old[0]])
        elif con.execute("SELECT 1 FROM tfm_forecasts WHERE use=? AND subject=? AND as_of=?",
                         [r["use"], r["subject"], r["asof"]]).fetchone():
            continue
        fid = next_id(con, "tfm_forecasts", "forecast_id")
        con.execute("INSERT INTO tfm_forecasts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [fid, r["use"], r["subject"], r["asof"], r["target"], r["inputs_last"], r["model"], r["q10"], r["q50"],
                     r["q90"], r["point"], r["baseline"], r["baseline_name"], None, None, None, None, now])
        n += 1
    return n


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
    s = tf.quarter_series(q) if len(q) else pd.DataFrame()
    if s.empty:
        return None
    hit = s[[pd.Timestamp(x).date() == quarter for x in s["quarter_end"]]]
    if hit.empty:
        return None
    v = float(hit.iloc[0]["ln_revenue" if use == "revenue" else "margin"])
    return v if np.isfinite(v) else None


def score(con, actual: Callable[[str, str, date, date], Optional[float]], now: datetime) -> int:
    """Score every open forecast whose target has matured: squared error (turnover), absolute error (results)."""
    n = 0
    for fid, use, subj, asof, target, point, base in con.execute(
            "SELECT forecast_id, use, subject, as_of, target, point, baseline FROM tfm_forecasts WHERE scored_at IS NULL").fetchall():
        y = actual(use, subj, asof, date.fromisoformat(str(target)))
        if y is None:
            continue
        f = (lambda e: e * e) if use == "turnover" else abs
        lm = f(y - point) if point is not None else None
        lb = f(y - base) if base is not None else None
        con.execute("UPDATE tfm_forecasts SET actual=?, loss_model=?, loss_baseline=?, scored_at=? WHERE forecast_id=?",
                    [y, lm, lb, now, fid])
        n += 1
    return n


def window(con, use: str) -> Tuple[pd.DataFrame, int]:
    """The rows in this use's scoreboard window and its full size N, over matured forecasts only (the protocol: "over
    the last N matured forecasts"). Q5: the last 60 forecast dates with matured targets, N = 60. Q6: the last two
    quarters with results in, N = the companies forecast for them (some may not have reported yet)."""
    df = con.execute("SELECT as_of, target, subject, loss_model, loss_baseline, scored_at FROM tfm_forecasts "
                     "WHERE use=? AND model IS NOT NULL", [use]).df()
    if df.empty:
        return df, (WINDOW_DATES if use == "turnover" else 0)
    done = df.dropna(subset=["scored_at"])
    if use == "turnover":
        keep = sorted(done["as_of"].unique())[-WINDOW_DATES:]
        return df[df["as_of"].isin(keep)], WINDOW_DATES
    keep = sorted(done["target"].unique())[-2:]
    w = df[df["target"].isin(keep)]
    return w, len(w)


def serving(con, use: str) -> str:
    r = con.execute("SELECT serving FROM tfm_scoreboard WHERE use=? ORDER BY as_of DESC, updated_at DESC LIMIT 1", [use]).fetchone()
    return r[0] if r else "timesfm"


REFRESH_DAYS = 365          # fine-tuned weights older than this: a refresh on newer data is due
ON_BASELINE_DAYS = 30       # a use served by its baseline this long: TimesFM lost its live test


def refresh_due(con, root: Path, asof: date) -> List[Tuple[str, str]]:
    """S63 (the investor: wire the refresh): (key, why and what to run) for each reason TimesFM needs attention.
        missing     the fine-tuned revenue weights are not on this PC (a fresh install): the registered S52 run
                    rebuilds them (`tools/s52_unattended.ps1`, GPU, 5-7 h); until then the baseline serves revenue
        stale       the weights are older than REFRESH_DAYS: fine-tuning on newer quarters is a model change, so a new
                    pre-registered study (CLAUDE.md 12), prepared with Claude Code
        lost        a use has been served by its baseline for ON_BASELINE_DAYS: the same, with the scoreboard as evidence"""
    out = []
    folder = Path(root) / "research" / "timesfm2"               # tools/timesfm2_forecast.py folder()
    ws = [folder / "ft" / f"q6_ln_revenue_{f}" / "model.safetensors" for f in ("A", "B")]
    if not all(w.exists() for w in ws):
        out.append(("missing", "The fine-tuned TimesFM revenue weights are not on this PC, so revenue ranges come from "
                               "the baseline. Rebuild them as registered: powershell -ExecutionPolicy Bypass -File "
                               "tools\\s52_unattended.ps1 (GPU, 5-7 h, resumes if stopped; cap the clocks first)."))
    else:
        age = (datetime.now() - datetime.fromtimestamp(min(w.stat().st_mtime for w in ws))).days
        if age > REFRESH_DAYS:
            out.append(("stale", f"The fine-tuned TimesFM revenue weights are {age} days old. Fine-tuning on the newer "
                                 "quarters is a model change: ask Claude Code to prepare a registered refresh study."))
    for use in USES:
        rows = con.execute("SELECT as_of, serving FROM tfm_scoreboard WHERE use=? AND as_of >= ? ORDER BY as_of",
                           [use, asof - timedelta(days=ON_BASELINE_DAYS)]).fetchall()
        if rows and all(s == "baseline" for _, s in rows) and (asof - rows[0][0]).days >= ON_BASELINE_DAYS - 3:
            out.append((f"lost:{use}", f"TimesFM has lost its live scoreboard for {use} for {ON_BASELINE_DAYS} days (the "
                                       "baseline serves). A refresh is a new registered study: ask Claude Code."))
    return out


def update_scoreboard(con, asof: date, now: datetime) -> List[str]:
    """The registered switch, per use; returns a sentence for each change (the morning report and the outbox)."""
    msgs = []
    for use in USES:
        w, full = window(con, use)
        sc = w.dropna(subset=["loss_model", "loss_baseline"]) if len(w) else w
        if use == "turnover":
            matured = int(sc["as_of"].nunique()) if len(sc) else 0
        else:
            matured = int(len(sc))
        ratio = float(sc["loss_model"].mean() / sc["loss_baseline"].mean()) if len(sc) and sc["loss_baseline"].mean() > 0 else None
        prev = serving(con, use)
        now_s = prev
        if prev == "timesfm" and ratio is not None and full and matured >= math.ceil(full / 2) and ratio > SWITCH_AT:
            now_s = "baseline"
        elif prev == "baseline" and ratio is not None and full and matured >= full and ratio <= RESUME_AT:
            now_s = "timesfm"
        from pflab.pm.store import transaction
        with transaction(con):
            con.execute("DELETE FROM tfm_scoreboard WHERE use=? AND as_of=?", [use, asof])
            con.execute("INSERT INTO tfm_scoreboard VALUES (?,?,?,?,?,?,?,?)",
                        [use, asof, matured, full, ratio, now_s, now_s != prev, now])
        if now_s != prev:
            msgs.append(f"S52 {use} forecasts: {'switched to the baseline' if now_s == 'baseline' else 'TimesFM resumes'} "
                        f"(loss ratio {ratio:.2f} to {BASE_LABEL[BASELINE[use]]} over {matured} matured of {full})")
    return msgs


def run(con, root: Path, asof: date, universe: pd.DataFrame, cal, forecaster: Optional[Callable[[dict], dict]],
        now: Optional[datetime] = None) -> dict:
    """The nightly step: build, forecast (TimesFM may fail: the baseline serves), store, score, scoreboard."""
    now = now or datetime.now()
    inputs = build(con, root, asof, universe, cal)
    deciles, err = None, None
    if forecaster is not None and any(inputs[u] for u in USES):
        try:
            deciles = forecaster(inputs)
        except Exception as e:                                     # recorded and reported, never hidden
            err = f"{type(e).__name__}: {str(e)[:300]}"
    stored = store_rows(con, rows_from(inputs, deciles), now)
    asof_s = date.fromisoformat(inputs["asof"])
    isins = sorted({s for (s,) in con.execute("SELECT DISTINCT subject FROM tfm_forecasts WHERE use='turnover' AND scored_at IS NULL").fetchall()})
    first = con.execute("SELECT min(as_of) FROM tfm_forecasts WHERE use='turnover' AND scored_at IS NULL").fetchone()[0]
    dates, wide = turnover_wide(root, isins, pd.Timestamp(first).date(), asof) if isins and first else ([], pd.DataFrame())

    def actual(use, subj, a, target):
        if use == "turnover":
            return turnover_actual(dates, wide, subj, pd.Timestamp(a).date(), target)
        return results_actual(con, root, subj, target, use, asof)
    scored = score(con, actual, now)
    msgs = update_scoreboard(con, asof_s, now)
    return {"asof": inputs["asof"], "turnover": len(inputs["turnover"]), "revenue": len(inputs["revenue"]),
            "margin": len(inputs["margin"]), "stored": stored, "scored": scored, "timesfm": deciles is not None,
            "error": err, "skipped": len(inputs["skipped"]), "changes": msgs}


# --- what the agents read ---------------------------------------------------------------------------------------------

def turnover_estimate(con, isin: str, asof: Optional[date] = None) -> Optional[Tuple[float, str]]:
    """(rupees a day expected over the next 5 sessions, label) from the latest fresh forecast, or None."""
    asof = asof or date.today()
    r = con.execute("SELECT as_of, point, baseline, baseline_name FROM tfm_forecasts WHERE use='turnover' AND subject=? "
                    "AND as_of <= ? AND as_of > ? ORDER BY as_of DESC LIMIT 1",
                    [isin, asof, asof - timedelta(days=FRESH_DAYS)]).fetchone()
    if not r:
        return None
    srv = serving(con, "turnover")
    if srv == "timesfm" and r[1] is not None:
        return math.exp(r[1]), f"{LABEL['T30C']}, made {r[0]:%d-%b}"
    if r[2] is None:
        return None
    why = "TimesFM off by its scoreboard" if srv == "baseline" else "TimesFM did not run"
    return math.exp(r[2]), f"{BASE_LABEL[r[3]]}, {why}, made {r[0]:%d-%b}"


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
    """Before a result: the range for its quarter (labelled). After it: the result against the range. The newest
    quarter, or `target`."""
    out = []
    name = symbol or scrip
    for use in ("revenue", "margin"):
        srv = serving(con, use)
        r = con.execute("SELECT target, q10, q90, point, baseline, actual, scored_at, model FROM tfm_forecasts WHERE use=? "
                        "AND subject=? AND (CAST(? AS DATE) IS NULL OR target = ?) ORDER BY target DESC LIMIT 1",
                        [use, str(scrip), target, target]).fetchone()
        if not r:
            continue
        tgt, q10, q90, pt, base, act, scored, model = r
        what = "revenue" if use == "revenue" else "net margin"
        use_tfm = srv == "timesfm" and model is not None
        if scored is None:
            if use_tfm:
                out.append(f"{name} {what}, quarter ending {tgt}: range {_fmt(use, q10)} to {_fmt(use, q90)} (10-90%, "
                           f"ESTIMATE, {LABEL.get(model.split()[0], model)})")
            elif base is not None:
                out.append(f"{name} {what}, quarter ending {tgt}: about {_fmt(use, base)} (ESTIMATE, "
                           f"{BASE_LABEL[BASELINE[use]]}; {'TimesFM off by its scoreboard' if srv == 'baseline' else 'TimesFM did not run'})")
        elif act is not None:
            if use_tfm:
                side = "above" if act > q90 else "below" if act < q10 else "inside"
                out.append(f"{name} {what}, quarter ending {tgt}: {_fmt(use, act)}, {side} the range "
                           f"{_fmt(use, q10)} to {_fmt(use, q90)}")
            elif base is not None:
                out.append(f"{name} {what}, quarter ending {tgt}: {_fmt(use, act)} against about {_fmt(use, base)} "
                           f"({BASE_LABEL[BASELINE[use]]})")
    return out


def show(con) -> str:
    L = []
    for use in USES:
        r = con.execute("SELECT as_of, matured, window_n, ratio, serving FROM tfm_scoreboard WHERE use=? ORDER BY as_of DESC, updated_at DESC "
                        "LIMIT 1", [use]).fetchone()
        n = con.execute("SELECT count(*), max(as_of) FROM tfm_forecasts WHERE use=?", [use]).fetchone()
        model = LABEL[MODEL[use]] if serving(con, use) == "timesfm" else BASE_LABEL[BASELINE[use]]
        tail = (f"; scoreboard {r[0]}: ratio {r[3]:.2f} over {r[1]} matured of {r[2]}" if r and r[3] is not None
                else "; nothing matured yet")
        L.append(f"{use}: serving {model}; {n[0]} forecast(s), latest {n[1]}{tail}")
    rows = con.execute("SELECT DISTINCT subject FROM tfm_forecasts WHERE use IN ('revenue', 'margin')").fetchall()
    for (s,) in rows:
        L += ["  " + x for x in results_lines(con, s)]
    return "\n".join(L)
