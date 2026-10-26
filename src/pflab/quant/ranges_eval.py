"""The registered calibration test of the price ranges (S64 Phase 3c; docs/research/s64_ranges_protocol.md). Layer: tool.

Monthly origins on point-in-time Nifty 500 members; for each origin a seeded sample of 100 names with 750 sessions and a
60-month CAPM fit; both methods (`stats_plain`, `stats_ewma`) from the same block-bootstrap draws, at 21 and 63 sessions;
development 2010-2017, validation 2018-2021. Everything at an origin uses data up to it: returns, the CAPM beta (60
months), the market premium (expanding mean of the Nifty 500 TRI excess return) and the cash rate (futures carry).

The rule in code (`decide`): a method passes coverage if its 80% interval covers 75-85% in both periods at both horizons;
`stats_ewma` replaces `stats_plain` only if its pinball loss is lower by a one-sided Diebold-Mariano test (HAC on the
monthly mean differences) with t >= counter.t_needed(N) in development and >= 1.65 in validation, and it passes coverage.
Writes PFLAB_DATA_DIR/research/s64_ranges.json, which `forecast.serving_method` reads.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

import numpy as np
import pandas as pd

from pflab.quant import forecast as fc

PERIODS = {"development": ("2010-01-01", "2017-12-31"), "validation": ("2018-01-01", "2021-12-31")}
HORIZONS = (21, 63)
SAMPLE, PATHS, SEED = 100, 3000, 64
COVER_BAND = (0.75, 0.85)
T_VAL = 1.65
BETA_WINDOW, BETA_MIN = 60, 36


def dm_one_sided(loss_a: np.ndarray, loss_b: np.ndarray, lags: int) -> dict:
    """Diebold-Mariano, H1: a has the lower mean loss. d = loss_b - loss_a; Newey-West standard error."""
    import statsmodels.api as sm
    from scipy.stats import norm
    d = np.asarray(loss_b, float) - np.asarray(loss_a, float)
    d = d[np.isfinite(d)]
    if len(d) < 6 or float(d.std()) == 0.0:
        return {"mean_diff": float(d.mean()) if len(d) else float("nan"), "t": float("nan"), "p": float("nan"), "n": int(len(d))}
    fit = sm.OLS(d, np.ones(len(d))).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    t = float(fit.tvalues[0])
    return {"mean_diff": float(d.mean()), "t": t, "p": float(1 - norm.cdf(t)), "n": int(len(d))}


def decide(res: dict, t_dev_needed: float) -> dict:
    """The protocol's rule on a result dict {period: {h: {method: {covered, pinball, n}, dm: {t, ...}}}}."""
    cov_ok = {}
    for m in fc.METHODS:
        got = [res[p][h][m]["covered"] for p in PERIODS for h in HORIZONS if res.get(p, {}).get(h, {}).get(m, {}).get("n")]
        cov_ok[m] = len(got) == len(PERIODS) * len(HORIZONS) and all(COVER_BAND[0] <= c <= COVER_BAND[1] for c in got)
    replace = cov_ok["stats_ewma"] and all(
        (res["development"][h]["dm"]["t"] >= t_dev_needed and res["validation"][h]["dm"]["t"] >= T_VAL) for h in HORIZONS
        if math.isfinite(res["development"][h]["dm"]["t"]) and math.isfinite(res["validation"][h]["dm"]["t"])) and all(
        math.isfinite(res[p][h]["dm"]["t"]) for p in PERIODS for h in HORIZONS)
    if replace:
        serve = "stats_ewma"
    elif cov_ok["stats_plain"]:
        serve = "stats_plain"
    elif cov_ok["stats_ewma"]:
        serve = "stats_ewma"
    else:
        serve = "stats_plain"
    worst = {m: min((res[p][h][m]["covered"] for p in PERIODS for h in HORIZONS if res.get(p, {}).get(h, {}).get(m, {}).get("n")),
                    default=float("nan")) for m in fc.METHODS}
    if cov_ok[serve]:
        label = f"calibrated: the 80% range covered {COVER_BAND[0]:.0%}-{COVER_BAND[1]:.0%} in testing (2010-2021)"
    else:
        label = f"not calibrated: covered {worst[serve]:.0%} in testing (the target is 80%)"
    return {"serve": serve, "label": label, "coverage_pass": cov_ok, "ewma_replaces_plain": bool(replace)}


def run_test(root: Path, con=None, now: Optional[datetime] = None, progress: Callable[[str], None] = lambda s: None,
             sample: int = SAMPLE, paths: int = PATHS, periods: Optional[dict] = None, write: bool = True) -> dict:
    from pflab.data import riskfree
    from pflab.learner import counter, templates as tp
    from pflab.risk import capm, shock_betas
    periods = periods or PERIODS
    now = now or datetime.now()
    rng = np.random.default_rng(SEED)
    mem = tp.members(root)
    w = tp.wide_panel(root, sorted(set(mem["isin"])), "2007-01-01", "2022-06-30")
    sessions, tr = w["tr"].index, w["tr"]
    table = riskfree.monthly_table(root)
    mret = capm.market_returns(root, sessions[-1].date())
    mrf = capm.monthly_rf(table, mret.index)
    mex = mret - mrf
    mon = tr.ffill().resample("ME").last()
    sret = mon / mon.shift(1) - 1.0
    ex = sret.sub(mrf.reindex(sret.index), axis=0)
    betas = shock_betas.rolling_betas(ex.reindex(mex.index), mex, BETA_WINDOW, BETA_MIN)
    every = tp.month_ends(sessions, str(sessions[0].date()), str(sessions[-1].date()))
    lr_all = np.log(tr.where(tr > 0)).diff()
    # obs[(period, h, method)] -> lists of (inside, pinball); month_loss[(period, h, method)] -> {month: [losses]}
    inside: Dict[tuple, list] = {}
    loss: Dict[tuple, Dict[pd.Timestamp, list]] = {}
    for name, (a, b) in periods.items():
        a_, b_ = pd.Timestamp(a), pd.Timestamp(b)
        for k, i in enumerate(every):
            t = sessions[i]
            if not a_ <= t <= b_ or i < fc.SAMPLE_SESSIONS or i + max(HORIZONS) >= len(sessions):
                continue
            live = sorted(set(mem[(mem["from_date"] <= t) & (mem["to_date"] > t)]["isin"]) & set(tr.columns))
            mkey = t + pd.offsets.MonthEnd(0)
            if mkey not in betas.index:
                continue
            have = tr.iloc[i - fc.SAMPLE_SESSIONS + 1:i + 1][live].notna().sum()
            ok = [c for c in live if have[c] >= fc.SAMPLE_SESSIONS - 20 and pd.notna(betas.at[mkey, c])
                  and pd.notna(tr.iloc[i][c]) and all(pd.notna(tr.iloc[i + h][c]) for h in HORIZONS)]
            if len(ok) < 20:
                continue
            pick = list(rng.choice(ok, size=min(sample, len(ok)), replace=False))
            rf_now = riskfree.at(table, t.date())[0]
            erp = float(mex[mex.index <= mkey].mean() * 12.0)           # expanding, point in time
            for c in pick:
                lr = lr_all[c].iloc[i - fc.SAMPLE_SESSIONS + 1:i + 1].to_numpy(float)
                lr = lr[np.isfinite(lr)]
                if len(lr) < fc.MIN_SESSIONS:
                    continue
                drift = capm.expected_return(float(betas.at[mkey, c]), rf_now, erp)
                res = fc.price_ranges(lr, 1.0, drift, HORIZONS, paths, rng)
                for m, by_h in res.items():
                    for h, q in by_h.items():
                        y = float(tr.iloc[i + h][c] / tr.iloc[i][c])
                        inside.setdefault((name, h, m), []).append(q[0] <= y <= q[2])
                        loss.setdefault((name, h, m), {}).setdefault(mkey, []).append(fc.pinball(y, q))
            progress(f"{name} {t.date()} done ({len(pick)} names)")
    out: dict = {}
    for name in periods:
        out[name] = {}
        for h in HORIZONS:
            cell: dict = {}
            for m in fc.METHODS:
                ins = inside.get((name, h, m), [])
                cell[m] = {"covered": float(np.mean(ins)) if ins else float("nan"), "n": len(ins),
                           "pinball": float(np.mean([x for v in loss.get((name, h, m), {}).values() for x in v])) if ins else float("nan")}
            months = sorted(set(loss.get((name, h, "stats_ewma"), {})) & set(loss.get((name, h, "stats_plain"), {})))
            la = np.array([np.mean(loss[(name, h, "stats_ewma")][mk]) for mk in months])
            lb = np.array([np.mean(loss[(name, h, "stats_plain")][mk]) for mk in months])
            cell["dm"] = dm_one_sided(la, lb, h // 21 + 1)
            out[name][h] = cell
    n_tests = counter.n_tests(con) + 1 if con is not None else 1
    bar = counter.t_needed(n_tests)
    dec = decide(out, bar)
    result = {"made": now.isoformat(timespec="seconds"), "tests_in_family": n_tests, "dev_bar": round(bar, 3),
              "results": {p: {str(h): v for h, v in d.items()} for p, d in out.items()}, **dec}
    if write:
        p = root.joinpath(*fc.RESULT_FILE)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    if con is not None and write:
        d0 = out["development"][HORIZONS[0]]["dm"] if "development" in out else {}
        v0 = out["validation"][HORIZONS[0]]["dm"] if "validation" in out else {}
        counter.record(con, now, "study", "ranges_ewma_vs_plain", {"horizons": list(HORIZONS)}, n_dev=d0.get("n"),
                       t_dev=d0.get("t"), t_val=v0.get("t"), threshold_dev=bar, passed=dec["ewma_replaces_plain"],
                       note="S64 ranges: EWMA-scaled bootstrap vs plain (pinball, DM)")
    lines = [f"Price ranges calibration test ({now:%Y-%m-%d}); N tests in the family {n_tests}, development bar t >= {bar:.2f}"]
    for pname, d in out.items():
        for h, cell in d.items():
            lines.append(f"  {pname} {h} sessions: " + "; ".join(
                f"{m} covered {cell[m]['covered']:.1%} (n {cell[m]['n']}, pinball {cell[m]['pinball']:.4f})" for m in fc.METHODS)
                + f"; DM ewma vs plain t {cell['dm']['t']:+.2f}")
    lines.append(f"coverage pass: {dec['coverage_pass']}; EWMA replaces plain: {dec['ewma_replaces_plain']}")
    lines.append(f"SERVES: {dec['serve']} - {dec['label']}")
    result["text"] = "\n".join(lines)
    return result
