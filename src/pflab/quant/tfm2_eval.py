"""S52 evaluation: the registered rules of docs/research/timesfm2_protocol.md applied to the files on disk.

    inputs/      written by `prepare` (tools/timesfm2_study.py)
    forecasts/   written by tools/timesfm2_forecast.py (deciles)
Every function returns plain dicts (JSON-ready). Nothing here chooses anything on validation or holdout data: choices
(configuration, baseline, version) are made on development, then the rule is applied once.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pflab.quant import tfm2 as tf
from pflab.quant import vol_study as vs

Q1_CANDS = ("T25", "T30", "T30X", "F25", "C")
Q1_ALPHA = 0.05 / 5
Q3_ALPHA, Q3B_ALPHA, Q4_ALPHA = 0.05 / 2, 0.05, 0.05
Q5_CANDS, Q5_ALPHA = ("T25", "T30", "T30C"), 0.05 / 3
Q6_CANDS, Q6_ALPHA = ("T25", "T30", "F25"), 0.05 / 3
Q6_PERIODS = {"dev": ("2013-01-01", "2017-12-31"), "val": ("2018-01-01", "2019-12-31"),
              "holdout": ("2026-01-01", "2099-12-31")}
Q5_DEV_FROM = "2008-01-01"
MIN_HOLDOUT = 20                       # holdout conditions apply only with at least this many matured forecast dates


def _load(p: Path) -> dict:
    d = np.load(p, allow_pickle=False)
    return {k: d[k] for k in d.files}


def _periods(dates) -> np.ndarray:
    return np.array([tf.period_of(x) or "" for x in dates])


def _mean(x) -> float:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return float(x.mean()) if len(x) else float("nan")


# --- Q1 / Q2 ----------------------------------------------------------------------------------------------------------------

class Market:
    """One market's inputs plus full-length targets and baselines, indexed by its forecast dates."""

    def __init__(self, path: Path):
        d = _load(path)
        self.name = path.stem.replace("q1_", "")
        self.fold = str(d["fold"])
        self.dates_all, self.r, self.v = d["dates"], d["r"], d["v"]
        self.lnvix = d["lnvix"]
        self.idx = d["idx"]
        self.dates = self.dates_all[self.idx]
        self.per = _periods(self.dates)
        dev_full = np.array([tf.period_of(x) == "dev" for x in self.dates_all])
        self.dev_full = dev_full
        rv = vs.target_rv(np.nan_to_num(self.r))
        self.rv = rv[self.idx]
        self.fall = vs.target_fall(np.nan_to_num(self.r))[self.idx]
        self.base = {k: f[self.idx] for k, f in tf.baselines_q1(self.r, self.v, dev_full).items()}
        self.rv_full = rv

    def mask(self, period: str) -> np.ndarray:
        return (self.per == period) & np.isfinite(self.rv)

    def at(self, f: np.ndarray, dates: np.ndarray) -> np.ndarray:
        """A forecast array given on `dates` -> aligned with this market's forecast dates (NaN where missing)."""
        s = pd.Series(np.asarray(f, float), index=list(dates))
        return s.reindex(list(self.dates)).to_numpy()


def load_markets(root: Path, names) -> Dict[str, Market]:
    return {m: Market(root / "inputs" / f"q1_{m}.npz") for m in names if (root / "inputs" / f"q1_{m}.npz").exists()}


def q1_raw(root: Path, cand: str, mk: Market) -> Dict[str, np.ndarray]:
    """config -> unscaled RV forecast and the variance path's deciles, aligned to the market's dates."""
    out = {}
    base = root / "forecasts" / "q1" / cand
    if not base.exists():
        return out
    for cfg in sorted(p.name for p in base.iterdir() if p.is_dir()):
        f = base / cfg / f"{mk.name}.npz"
        if f.exists():
            d = _load(f)
            q = d["q"]
            full = np.full((len(mk.dates), q.shape[1], 9), np.nan)
            pos = pd.Series(np.arange(len(mk.dates)), index=list(mk.dates)).reindex(list(d["dates"])).to_numpy()
            ok = np.isfinite(pos)
            full[pos[ok].astype(int)] = q[ok]
            out[cfg] = full
    return out


def _pooled_qlike(mks: Dict[str, Market], fc: Dict[str, np.ndarray], period: str) -> float:
    vals = []
    for m, mk in mks.items():
        if m in fc:
            ok = mk.mask(period) & np.isfinite(fc[m])
            vals.append(vs.qlike(mk.rv[ok], fc[m][ok]))
    return _mean(np.concatenate(vals)) if vals else float("nan")


def q1_candidate(root: Path, cand: str, mks: Dict[str, Market]) -> Optional[dict]:
    """Choose the configuration on development (scale fitted on development, pooled), return the forecasts."""
    raws = {m: q1_raw(root, cand, mk) for m, mk in mks.items()}
    cfgs = sorted({c for r in raws.values() for c in r})
    if not cfgs:
        return None
    best, by_cfg = None, {}
    for cfg in cfgs:
        unscaled = {m: tf.rv_from_deciles(r[cfg]) if cfg in r else None for m, r in raws.items()}
        unscaled = {m: f for m, f in unscaled.items() if f is not None}
        num = np.concatenate([mks[m].rv[mks[m].mask("dev")] for m in unscaled])
        den = np.concatenate([f[mks[m].mask("dev")] for m, f in unscaled.items()])
        ok = np.isfinite(num) & np.isfinite(den) & (den > 0)
        scale = float(np.mean(num[ok] / den[ok])) if ok.any() else 1.0
        fc = {m: f * scale for m, f in unscaled.items()}
        dq = _pooled_qlike(mks, fc, "dev")
        by_cfg[cfg] = dq
        if best is None or dq < best["dev_qlike"]:
            best = {"config": cfg, "scale": scale, "dev_qlike": dq, "fc": fc,
                    "paths": {m: tf.var_path_from_deciles(raws[m][cfg], scale) for m in fc}}
    best["dev_qlike_by_config"] = by_cfg
    return best


def q1_combination(mks: Dict[str, Market], f25: dict) -> dict:
    """Candidate C per market: HAR on ln v + ln F25 (+ ln VIX for US_SP500), fitted on that market's development."""
    fc, paths = {}, {}
    for m, mk in mks.items():
        if m not in f25["fc"]:
            continue
        full = np.full(len(mk.dates_all), np.nan)
        full[mk.idx] = f25["fc"][m]
        vix = mk.lnvix if m == "US_SP500" and np.isfinite(mk.lnvix[mk.dev_full]).mean() > 0.9 else None
        c = tf.combination(mk.v, full, mk.rv_full, mk.dev_full & np.isfinite(full), vix)
        fc[m] = c[mk.idx]
        ratio = fc[m] / f25["fc"][m]
        paths[m] = f25["paths"][m] * ratio[:, None]          # the F25 path, rescaled to C's level
    return {"config": f25["config"], "scale": 1.0, "fc": fc, "paths": paths,
            "dev_qlike": _pooled_qlike(mks, fc, "dev")}


def q1_evaluate(root: Path) -> dict:
    mks = load_markets(root, tf.MARKETS)
    out: dict = {"markets": sorted(mks)}
    bq = {b: _pooled_qlike(mks, {m: mk.base[b] for m, mk in mks.items()}, "dev") for b in ("ewma094", "har_r2", "har_logv")}
    base = min(bq, key=bq.get)
    out["baseline_dev_qlike"], out["baseline"] = bq, base
    bfc = {m: mk.base[base] for m, mk in mks.items()}
    cands = {}
    for c in ("T25", "T30", "T30X", "F25"):
        r = q1_candidate(root, c, mks)
        if r:
            cands[c] = r
    if "F25" in cands:
        cands["C"] = q1_combination(mks, cands["F25"])
    res = {}
    for c, r in cands.items():
        scored = sorted(r["fc"])
        rows = [(mks[m].dates[mks[m].mask("val")], vs.qlike(mks[m].rv[mks[m].mask("val")], r["fc"][m][mks[m].mask("val")]),
                 vs.qlike(mks[m].rv[mks[m].mask("val")], bfc[m][mks[m].mask("val")])) for m in scored]
        dm = tf.pooled_dm(rows)
        better = {m: bool(_mean(a) < _mean(b)) for m, (_d, a, b) in zip(scored, rows)}
        val_q, base_val = _pooled_qlike(mks, r["fc"], "val"), _pooled_qlike(mks, {m: bfc[m] for m in scored}, "val")
        hold_n = sum(int(mks[m].mask("holdout").sum()) for m in scored)
        hold = (_pooled_qlike(mks, r["fc"], "holdout") / _pooled_qlike(mks, {m: bfc[m] for m in scored}, "holdout")
                if hold_n else float("nan"))
        if c in ("F25", "C"):
            breadth = all(sum(better[m] for m in fold if m in better) >= 4 for fold in (tf.FOLD_A, tf.FOLD_B))
        else:
            breadth = sum(better.values()) >= 7
        hold_ok = (hold <= 1.0) if hold_n >= MIN_HOLDOUT else True
        passes = bool(val_q < base_val and dm["p"] < Q1_ALPHA and breadth and hold_ok)
        res[c] = {"config": r["config"], "scale": r["scale"], "dev_qlike": r["dev_qlike"],
                  "dev_qlike_by_config": r.get("dev_qlike_by_config", {}), "val_qlike": val_q,
                  "baseline_val_qlike": base_val, "dm_val": dm, "markets_better": better, "holdout_ratio": hold,
                  "holdout_rows": hold_n, "passes": passes}
    out["candidates"] = res
    passing = [c for c in res if res[c]["passes"]]
    out["adopt"] = min(passing, key=lambda c: res[c]["val_qlike"]) if passing else None
    out["_fc"] = cands                                         # for Q2 (dropped before writing JSON)
    out["_mks"] = mks
    return out


def q2_evaluate(q1: dict) -> dict:
    mks, cands = q1["_mks"], q1["_fc"]
    rival = {m: mk.base["ewma094"] for m, mk in mks.items()}
    out: dict = {"rival": "ewma094 (live volatility chance, each market's own map)"}
    for c, r in cands.items():
        scored = sorted(r["paths"])
        sc = {m: tf.fall_chance(r["paths"][m]) for m in scored}
        m_val = {m: mks[m].mask("val") & np.isfinite(sc[m]) & np.isfinite(rival[m]) for m in scored}
        boot = tf.pooled_auc_diff_bootstrap([sc[m][m_val[m]] for m in scored], [rival[m][m_val[m]] for m in scored],
                                            [mks[m].fall[m_val[m]] for m in scored])
        better = {m: bool(vs.auc(sc[m][m_val[m]], mks[m].fall[m_val[m]]) > vs.auc(rival[m][m_val[m]], mks[m].fall[m_val[m]]))
                  for m in scored}
        if c in ("F25", "C"):
            breadth = all(sum(better[m] for m in fold if m in better) >= 4 for fold in (tf.FOLD_A, tf.FOLD_B))
        else:
            breadth = sum(better.values()) >= 7
        mh = {m: mks[m].mask("holdout") & np.isfinite(sc[m]) for m in scored}
        hn = sum(int(v.sum()) for v in mh.values())
        a_h = tf.pooled_auc([sc[m][mh[m]] for m in scored], [mks[m].fall[mh[m]] for m in scored]) if hn else float("nan")
        r_h = tf.pooled_auc([rival[m][mh[m]] for m in scored], [mks[m].fall[mh[m]] for m in scored]) if hn else float("nan")
        hold_ok = (a_h >= r_h) if hn >= MIN_HOLDOUT else True
        brier = _mean(np.concatenate([(sc[m][m_val[m]] - mks[m].fall[m_val[m]]) ** 2 for m in scored]))
        out[c] = {"auc_val_diff": boot, "markets_better": better, "holdout_auc": a_h, "holdout_rival_auc": r_h,
                  "brier_val": brier, "passes": bool(boot["diff"] > 0 and boot["p"] < Q1_ALPHA and breadth and hold_ok)}
    passing = [c for c in cands if out[c]["passes"]]
    out["adopt"] = max(passing, key=lambda c: out[c]["auc_val_diff"]["diff"]) if passing else None
    return out


def q1_dev_choice(root: Path) -> dict:
    """Before fine-tuning (amendment 2): the input T25 prefers on development."""
    mks = load_markets(root, tf.MARKETS)
    r = q1_candidate(root, "T25", mks)
    if r is None:
        raise FileNotFoundError("no T25 forecasts for Q1 yet")
    return {"F25_input": r["config"].split("_")[0], "T25_dev_config": r["config"], "T25_dev_qlike": r["dev_qlike"]}


# --- Q3 / Q4 ----------------------------------------------------------------------------------------------------------------

def q34_evaluate(root: Path) -> dict:
    data = {}
    for p in sorted((root / "inputs").glob("q3_*.npz")):
        d = _load(p)
        data[p.stem.replace("q3_", "")] = d
    out: dict = {"q3": {}, "q4": {}}
    by_h: Dict[int, dict] = {}
    for hi, h in enumerate(tf.RANGE_H):
        rows = {}
        for m, d in data.items():
            lnc, idx = d["lnc"], d["idx"]
            keep = idx + h < len(lnc)
            ii = idx[keep]
            dates = d["dates"][ii]
            y = tf.target_cumret(lnc, ii, h)
            r = np.r_[np.nan, np.diff(lnc)]
            base = {"bootstrap": tf.range_bootstrap(lnc, ii, h), "normal_ewma": tf.range_normal(r, ii, h, "ewma"),
                    "normal_expanding": tf.range_normal(r, ii, h, "expanding")}
            cand = {}
            for c in ("T25", "T30"):
                f = root / "forecasts" / "q3" / c / f"{m}.npz"
                if f.exists():
                    fd = _load(f)
                    s = pd.DataFrame(fd["q"][:, hi, :], index=list(fd["dates"]))
                    cand[c] = s.reindex(list(dates)).to_numpy()
            rows[m] = {"dates": dates, "per": _periods(dates), "y": y, "base": base, "cand": cand,
                       "hist": tf.expanding_mean_return(r, ii, h)}
        by_h[h] = rows

        def pooled(key, period, which):
            vals = [tf.pinball(v["y"][v["per"] == period], (v[which][key])[v["per"] == period])
                    for v in rows.values() if key in v[which]]
            return _mean(np.concatenate(vals)) if vals else float("nan")

        bdev = {b: pooled(b, "dev", "base") for b in ("bootstrap", "normal_ewma", "normal_expanding")}
        bsel = min(bdev, key=bdev.get)
        res = {"baseline_dev": bdev, "baseline": bsel}
        for c in ("T25", "T30"):
            if not any(c in v["cand"] for v in rows.values()):
                continue
            dmrows = [(v["dates"][v["per"] == "val"], tf.pinball(v["y"][v["per"] == "val"], v["cand"][c][v["per"] == "val"]),
                       tf.pinball(v["y"][v["per"] == "val"], v["base"][bsel][v["per"] == "val"])) for v in rows.values()]
            dm = tf.pooled_dm(dmrows, lag=max(1, h // tf.RANGE_STEP))
            cov = tf.coverage(np.concatenate([v["y"][v["per"] == "val"] for v in rows.values()]),
                              np.concatenate([v["cand"][c][v["per"] == "val"] for v in rows.values()]))
            vq, bq = pooled(c, "val", "cand"), pooled(bsel, "val", "base")
            res[c] = {"val_pinball": vq, "baseline_val_pinball": bq, "dm_val": dm, "coverage_val": cov,
                      "passes": bool(vq < bq and dm["p"] < Q3_ALPHA and 0.70 <= cov <= 0.90)}
        out["q3"][str(h)] = res
    # Q3b: the volatility-aware range against the bootstrap at one year
    rows = by_h[252]
    dmrows = [(v["dates"][v["per"] == "val"], tf.pinball(v["y"][v["per"] == "val"], v["base"]["normal_ewma"][v["per"] == "val"]),
               tf.pinball(v["y"][v["per"] == "val"], v["base"]["bootstrap"][v["per"] == "val"])) for v in rows.values()]
    dm = tf.pooled_dm(dmrows, lag=252 // tf.RANGE_STEP)
    out["q3b"] = {"dm_val": dm, "passes": bool(dm["mean_diff"] > 0 and dm["p"] < Q3B_ALPHA)}
    # Q4: the median at one year against the historical mean
    q4 = {}
    for c in ("T25", "T30"):
        if not any(c in v["cand"] for v in rows.values()):
            continue
        r2 = {}
        for per in ("dev", "val", "holdout"):
            y = np.concatenate([v["y"][v["per"] == per] for v in rows.values()])
            f = np.concatenate([v["cand"][c][v["per"] == per][:, 4] for v in rows.values()])
            b = np.concatenate([v["hist"][v["per"] == per] for v in rows.values()])
            r2[per] = tf.oos_r2(y, f, b) if np.isfinite(y).sum() >= MIN_HOLDOUT else float("nan")
        cw = tf.clark_west_pooled([(v["dates"][v["per"] == "val"], v["y"][v["per"] == "val"],
                                    v["cand"][c][v["per"] == "val"][:, 4], v["hist"][v["per"] == "val"])
                                   for v in rows.values()], lag=252 // tf.RANGE_STEP)
        q4[c] = {"oos_r2": r2, "clark_west_val": cw}
    if q4:
        pick = max(q4, key=lambda c: q4[c]["oos_r2"]["dev"])
        r = q4[pick]
        hold = r["oos_r2"]["holdout"]
        r["passes"] = bool(r["oos_r2"]["val"] > 0 and r["clark_west_val"]["p"] < Q4_ALPHA and
                           (hold > 0 if np.isfinite(hold) else True))
        q4["chosen_on_dev"] = pick
        q4["holdout_checked"] = bool(np.isfinite(hold))
    out["q4"] = q4
    return out


# --- Q5 --------------------------------------------------------------------------------------------------------------------

def q5_evaluate(root: Path) -> dict:
    stocks = sorted((root / "inputs").glob("q5_*.npz"))
    per_stock = []
    for p in stocks:
        d = _load(p)
        idx, dates = d["idx"], d["dates"][d["idx"]]
        per = _periods(dates)
        per = np.where((per == "dev") & (dates < Q5_DEV_FROM), "", per)
        y = tf.turnover_target(d["lt"], idx)
        base = tf.turnover_baselines(d["lt"], d["cov"], idx, per == "dev")
        cand = {}
        for c in Q5_CANDS:
            f = root / "forecasts" / "q5" / c / p.name.replace("q5_", "")
            if f.exists():
                fd = _load(f)
                s = pd.Series(tf.turnover_from_deciles(fd["q"]), index=list(fd["dates"]))
                cand[c] = s.reindex(list(dates)).to_numpy()
        per_stock.append({"dates": dates, "per": per, "y": y, "base": base, "cand": cand})

    def mse(key, which, period):
        v = [(s["y"][s["per"] == period] - s[which][key][s["per"] == period]) ** 2 for s in per_stock if key in s[which]]
        return _mean(np.concatenate(v)) if v else float("nan")

    bdev = {b: mse(b, "base", "dev") for b in ("mean20", "har_cal")}
    bsel = min(bdev, key=bdev.get)
    out: dict = {"stocks": len(per_stock), "baseline_dev": bdev, "baseline": bsel}
    for c in Q5_CANDS:
        have = [s for s in per_stock if c in s["cand"]]
        if not have:
            continue
        # both on the same dates: a date the candidate could not forecast (no trading in its window) is dropped for both
        def errs(s, period):
            m = (s["per"] == period) & np.isfinite(s["cand"][c]) & np.isfinite(s["base"][bsel]) & np.isfinite(s["y"])
            return s["dates"][m], (s["y"] - s["cand"][c])[m] ** 2, (s["y"] - s["base"][bsel])[m] ** 2

        rows = [errs(s, "val") for s in have]
        dm = tf.pooled_dm(rows, lag=1)
        share = float(np.mean([_mean(a) < _mean(b) for _d, a, b in rows if len(a)]))
        hold = [errs(s, "holdout") for s in have]
        hn = sum(len(a) for _d, a, _b in hold)
        ratio = (_mean(np.concatenate([a for _d, a, _b in hold])) / _mean(np.concatenate([b for _d, _a, b in hold]))
                 if hn else float("nan"))
        hold_ok = ratio <= 1.0 if hn >= MIN_HOLDOUT else True
        vm = _mean(np.concatenate([a for _d, a, _b in rows]))
        bm = _mean(np.concatenate([b for _d, _a, b in rows]))
        out[c] = {"val_mse": vm, "baseline_val_mse": bm, "dm_val": dm, "share_stocks_better": share,
                  "holdout_ratio": ratio, "passes": bool(vm < bm and dm["p"] < Q5_ALPHA and share >= 0.60 and hold_ok)}
    passing = [c for c in Q5_CANDS if out.get(c, {}).get("passes")]
    out["adopt"] = min(passing, key=lambda c: out[c]["val_mse"]) if passing else None
    return out


# --- Q6 --------------------------------------------------------------------------------------------------------------------

def q6_period(qe: str) -> str:
    for k, (a, b) in Q6_PERIODS.items():
        if a <= qe <= b:
            return k
    return ""


def q6_evaluate(root: Path) -> dict:
    d = _load(root / "inputs" / "q6.npz")
    rows = np.flatnonzero(d["forecastable"])
    per = np.array([q6_period(str(x)) for x in d["quarter_end"][rows]])
    scrip = d["scrip"][rows]
    out: dict = {}
    for target in ("ln_revenue", "margin"):
        y = d[target][rows]
        base = {}
        for b in ("same_q_last_year", "with_trailing_growth"):
            base[b] = d[f"base_{target}_{b}"][rows]
        bdev = {b: _mean(np.abs(y - f)[per == "dev"]) for b, f in base.items()}
        bsel = min(bdev, key=bdev.get)
        res: dict = {"baseline_dev": bdev, "baseline": bsel}
        for c in Q6_CANDS:
            f = root / "forecasts" / "q6" / c / f"{target}.npz"
            if not f.exists():
                continue
            fd = _load(f)
            pred = pd.Series(fd["q"][:, 4], index=fd["rows"]).reindex(rows).to_numpy()
            e_m, e_b = np.abs(y - pred), np.abs(y - base[bsel])
            v = (per == "val") & np.isfinite(e_m) & np.isfinite(e_b)
            diffs = {s: (e_b - e_m)[v & (scrip == s)] for s in np.unique(scrip[v])}
            t = tf.company_t(diffs)
            h = (per == "holdout") & np.isfinite(e_m) & np.isfinite(e_b)
            hold_ok = (_mean(e_m[h]) <= _mean(e_b[h])) if h.sum() >= MIN_HOLDOUT else True
            res[c] = {"val_mae": _mean(e_m[v]), "baseline_val_mae": _mean(e_b[v]), "company_t": t,
                      "holdout_mae": _mean(e_m[h]), "baseline_holdout_mae": _mean(e_b[h]),
                      "passes": bool(t["p"] < Q6_ALPHA and t["share_better"] >= 0.55 and hold_ok)}
        passing = [c for c in Q6_CANDS if res.get(c, {}).get("passes")]
        res["adopt"] = min(passing, key=lambda c: res[c]["val_mae"]) if passing else None
        out[target] = res
    return out


# --- Described only (no rule): the Nifty, 2020-2021, matured holdouts ---------------------------------------------------

def describe(root: Path, res: dict) -> dict:
    """Numbers the protocol says are described, not tested: the Nifty 50 (Q1/Q2, each candidate at the configuration and
    scale chosen on the ten markets' development; baselines fitted on the Nifty's own development), 2020-2021 for the
    ten markets (Q1, Q2) and Q6, and the count of matured holdout rows. Reads `res` (results.json) for the frozen choices."""
    out: dict = {}
    nifty = root / "inputs" / "q1_NIFTY50.npz"
    if nifty.exists():
        mk = Market(nifty)
        base = res["q1"]["baseline"]
        nd: dict = {}
        for per in ("dev", "val", "desc", "holdout"):
            m = mk.mask(per) & np.isfinite(mk.base[base])
            nd[per] = {"rows": int(m.sum()), "baseline_qlike": _mean(vs.qlike(mk.rv[m], mk.base[base][m])),
                       "ewma_auc": vs.auc(mk.base["ewma094"][m], mk.fall[m]) if m.sum() else float("nan"),
                       "fall_share": _mean(mk.fall[m])}
        for c, r in res["q1"]["candidates"].items():
            if c in ("F25", "C"):
                continue                                      # the Nifty is in neither fold: no out-of-market model
            raw = q1_raw(root, c, mk).get(r["config"])
            if raw is None:
                continue
            fc = tf.rv_from_deciles(raw) * r["scale"]
            sc = tf.fall_chance(tf.var_path_from_deciles(raw, r["scale"]))
            for per in nd:
                m = mk.mask(per) & np.isfinite(fc) & np.isfinite(mk.base[base])
                nd[per][c] = {"qlike": _mean(vs.qlike(mk.rv[m], fc[m])),
                              "qlike_ratio": _mean(vs.qlike(mk.rv[m], fc[m])) / _mean(vs.qlike(mk.rv[m], mk.base[base][m])),
                              "auc": vs.auc(sc[m], mk.fall[m]) if m.sum() else float("nan")}
        out["nifty_q1_q2"] = nd
    q1 = q1_evaluate(root)
    mks, cands = q1["_mks"], q1["_fc"]
    d1 = {}
    for c, r in cands.items():
        fc = r["fc"]
        bfc = {m: mks[m].base[q1["baseline"]] for m in fc}
        q, b = _pooled_qlike(mks, fc, "desc"), _pooled_qlike(mks, bfc, "desc")
        sc = {m: tf.fall_chance(r["paths"][m]) for m in fc}
        msk = {m: mks[m].mask("desc") & np.isfinite(sc[m]) for m in fc}
        d1[c] = {"qlike_ratio": q / b, "auc": tf.pooled_auc([sc[m][msk[m]] for m in fc], [mks[m].fall[msk[m]] for m in fc]),
                 "rival_auc": tf.pooled_auc([mks[m].base["ewma094"][msk[m]] for m in fc], [mks[m].fall[msk[m]] for m in fc])}
    out["q1_q2_2020_2021"] = d1
    if (root / "inputs" / "q6.npz").exists() and "q6" in res:
        d = _load(root / "inputs" / "q6.npz")
        rows = np.flatnonzero(d["forecastable"])
        qe = d["quarter_end"][rows].astype(str)
        desc = np.array([("2020-01-01" <= x <= "2021-12-31") for x in qe])
        hold = np.array([x >= "2026-01-01" for x in qe])
        d6 = {"holdout_rows": int(hold.sum()), "last_quarter_in_data": str(max(qe)) if len(qe) else None}
        for target in ("ln_revenue", "margin"):
            y, bsel = d[target][rows], res["q6"][target]["baseline"]
            e_b = np.abs(y - d[f"base_{target}_{bsel}"][rows])
            t6 = {}
            for c in Q6_CANDS:
                f = root / "forecasts" / "q6" / c / f"{target}.npz"
                if f.exists():
                    fd = _load(f)
                    e_m = np.abs(y - pd.Series(fd["q"][:, 4], index=fd["rows"]).reindex(rows).to_numpy())
                    m = desc & np.isfinite(e_m) & np.isfinite(e_b)
                    t6[c] = {"rows": int(m.sum()), "mae": _mean(e_m[m]), "baseline_mae": _mean(e_b[m]),
                             "median_ae": float(np.median(e_m[m])) if m.any() else float("nan"),
                             "baseline_median_ae": float(np.median(e_b[m])) if m.any() else float("nan")}
            d6[target] = t6
        out["q6_2020_2021"] = d6
    return out


def evaluate_all(root: Path) -> dict:
    q1 = q1_evaluate(root)
    q2 = q2_evaluate(q1)
    out = {"q1": {k: v for k, v in q1.items() if not k.startswith("_")}, "q2": q2}
    if list((root / "inputs").glob("q3_*.npz")):
        out.update(q34_evaluate(root))
    if list((root / "inputs").glob("q5_*.npz")):
        out["q5"] = q5_evaluate(root)
    if (root / "inputs" / "q6.npz").exists():
        out["q6"] = q6_evaluate(root)
    return out


def to_json(obj) -> str:
    def clean(o):
        if isinstance(o, dict):
            return {str(k): clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        if isinstance(o, (np.floating, float)):
            return None if not np.isfinite(o) else float(o)
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, np.bool_):
            return bool(o)
        return o
    return json.dumps(clean(obj), indent=1)
