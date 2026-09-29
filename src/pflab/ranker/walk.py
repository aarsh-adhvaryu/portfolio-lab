"""E5-A §5 and §7: walk-forward refits, the composite score, the fallback.

The model that scores decision month-end M is the one fitted at the latest
refit date R strictly before M: the December month-end for an annual refit
(§5, "that model scores the twelve month-ends that follow"), the previous
month-end for S6's monthly refit. If, at R, any horizon's training set holds
fewer than `min_cross_sections` month-end cross-sections, no model is used
and M is decided by the stack's own rank -- the per-decision fallback, which
the engine records.

Composite at M (§7): each horizon model's prediction over the scored names of
U(M), turned into a percentile within U(M), averaged across horizons. Its
descending rank replaces the stack's ranking signal; nothing else changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from pflab.ranker import model as mdl
from pflab.ranker.features import A0_FEATURES, to_wide

GRID_KEYS = ("num_leaves", "min_data_in_leaf", "learning_rate")


def observed(labels: pd.DataFrame) -> pd.Series:
    """Label returns observable in this store, indexed (M, h, ISIN): the rows
    an IC is scored on. A store cut at T holds as `pending` every label not
    observable by T, so this is "observable by T"."""
    from pflab.ranker.labels import DEFINED
    L = labels[labels["kind"].isin(DEFINED) & labels["ret"].notna()]
    return L.set_index(["month_end", "h", "isin"])["ret"].astype(float)


@dataclass(frozen=True)
class Spec:
    features: Tuple[str, ...]
    horizons: Tuple[int, ...]
    tuned: Tuple[Tuple[str, float], ...]
    fixed: Tuple[Tuple[str, float], ...]
    seed: int
    num_threads: int
    refit: str
    refit_month: int
    min_cross_sections: int

    @property
    def params(self) -> dict:
        return mdl.params(dict(self.tuned), self.seed, dict(self.fixed),
                          self.num_threads)


def spec_from_config(cfg: dict) -> Spec:
    """E5-A's model spec from a config's [e5a] block. The tuned point has no
    default: §5 says it is written into the charter, and so into the config."""
    e = cfg.get("e5a") or {}
    p = e.get("params") or {}
    missing = [k for k in GRID_KEYS if k not in p]
    if missing:
        raise ValueError(f"e5a.params.{missing} must come from E5-A §5's tuned "
                         f"point; there is no default")
    refit = str(e.get("refit", "annual"))
    if refit not in ("annual", "monthly"):
        raise ValueError(f"unknown e5a.refit {refit!r}")
    return Spec(features=tuple(e.get("features", A0_FEATURES)),
                horizons=tuple(int(h) for h in e.get("horizons", (1, 3, 12))),
                tuned=tuple(sorted((k, p[k]) for k in GRID_KEYS)),
                fixed=tuple(sorted((e.get("fixed") or mdl.FIXED).items())),
                seed=int(e.get("seed", mdl.SEED)),
                num_threads=int(e.get("num_threads", 1)),
                refit=refit, refit_month=int(e.get("refit_month", 12)),
                min_cross_sections=int(e.get("min_cross_sections", 12)))


def refit_date(m: date, month_ends: Sequence[date], spec: Spec) -> Optional[date]:
    """The latest refit date strictly before decision month-end m."""
    cands = [r for r in month_ends if r < m
             and (spec.refit == "monthly" or r.month == spec.refit_month)]
    return max(cands) if cands else None


class Walk:
    """Fits cached by (horizon, refit date, parameters): rows that share a
    model (S1-S3 share the base's, S7 all of them) fit it once."""

    def __init__(self, features_wide: pd.DataFrame, labels: pd.DataFrame,
                 universe: Dict[date, pd.Index], month_ends: Sequence[date]):
        self.fw = features_wide
        self.labels = labels
        self.universe = universe
        self.month_ends = sorted(month_ends)
        self.fits: Dict[tuple, mdl.Fit] = {}

    def fit(self, spec: Spec, h: int, R: date) -> mdl.Fit:
        key = (h, R, tuple(sorted(spec.params.items())), spec.features,
               spec.min_cross_sections)
        if key not in self.fits:
            self.fits[key] = mdl.fit(self.fw, self.labels, h, R, spec.params,
                                     spec.features, spec.min_cross_sections)
        return self.fits[key]

    def scored_names(self, m: date, features: Sequence[str]) -> pd.DataFrame:
        """U(M)'s names with at least one feature available at M."""
        if m not in self.fw.index.get_level_values(0):
            return pd.DataFrame(columns=list(features))
        X = self.fw.loc[m].reindex(list(self.universe.get(m, [])))[list(features)]
        return X[X.notna().any(axis=1)]

    def score(self, spec: Spec, months: Sequence[date]) -> dict:
        """{"scores": {M: Series}, "fallback": {M: bool}, "info": {M: ...},
        "predictions": {(M, h): Series}}."""
        scores, fallback, info, preds = {}, {}, {}, {}
        for m in months:
            R = refit_date(m, self.month_ends, spec)
            fits = [self.fit(spec, h, R) for h in spec.horizons] if R else []
            ok = bool(fits) and all(f.fitted for f in fits)
            info[m] = {"refit": R, "fits": [(f.h, f.sha256, f.n_rows,
                                             f.n_cross_sections, f.reason)
                                            for f in fits]}
            if not ok:
                fallback[m] = True
                continue
            X = self.scored_names(m, spec.features)
            if X.empty:
                fallback[m] = True
                info[m]["reason"] = "no scored names"
                continue
            pct = []
            for f in fits:
                p = pd.Series(f.predict(X.to_numpy(dtype=float)), index=X.index)
                preds[(m, f.h)] = p
                pct.append(p.rank(method="average", pct=True))
            scores[m] = pd.concat(pct, axis=1).mean(axis=1).sort_index()
            fallback[m] = False
        return {"scores": scores, "fallback": fallback, "info": info,
                "predictions": preds}


def ic_by_year(predictions: dict, labels: pd.DataFrame,
               horizons: Sequence[int]) -> dict:
    """§11: mean monthly Spearman IC per horizon per year, against the labels
    observable in this panel (a rank IC: the percentile would not change it)."""
    L = observed(labels)
    out: Dict[str, dict] = {}
    for (m, h), p in sorted(predictions.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        try:
            y = L.loc[(m, h)]
        except KeyError:
            continue
        ic = mdl.spearman(p, y.reindex(p.index))
        if ic is not None:
            out.setdefault(f"h{h}", {}).setdefault(str(m.year), []).append(ic)
    return {h: {y: {"mean_ic": float(np.mean(v)), "months": len(v)}
                for y, v in ys.items()} for h, ys in out.items()}


class SweepScores:
    """The sweep's score provider: `provider(cfg, row)` returns the engine's
    `scores=` argument for that row, and keeps every model it fitted so the
    sweep can write and hash them."""

    def __init__(self, features: pd.DataFrame, labels: pd.DataFrame, period):
        self.period = period
        self.fw = to_wide(features)
        self.universe = {m: pd.Index(sorted(g["isin"].unique()))
                         for m, g in features.groupby("month_end")}
        mes = sorted(self.universe)
        self.labels = labels
        self.walk = Walk(self.fw, labels, self.universe, mes)
        self.months = [m for m in mes if period.start <= m <= period.end]
        self.rows: Dict[str, dict] = {}

    def __call__(self, cfg: dict, row: str) -> dict:
        spec = spec_from_config(cfg)
        res = self.walk.score(spec, self.months)
        self.rows[row] = {"spec": spec, "result": res}
        return {"scores": res["scores"], "fallback": res["fallback"]}

    @staticmethod
    def model_file(f: mdl.Fit) -> str:
        return f"models/h{f.h}_{f.refit}_{f.sha256[:16]}.txt"

    def attachments(self) -> Dict[str, str]:
        return {self.model_file(f): f.text for f in self.walk.fits.values()
                if f.fitted}

    def manifest(self) -> dict:
        return {"lightgbm": mdl.lightgbm_version(),
                "models": {self.model_file(f): f.sha256
                           for f in sorted(self.walk.fits.values(),
                                           key=lambda f: (f.h, f.refit, f.sha256 or ""))
                           if f.fitted},
                "rows": {r: {"params": v["spec"].params,
                             "horizons": list(v["spec"].horizons),
                             "refit": v["spec"].refit}
                         for r, v in self.rows.items()}}

    def row_extras(self, row: str, res) -> dict:
        """§11 for one row: fallback share of decisions and of buy value, rank
        IC per horizon per year, and gain importance per refit."""
        v = self.rows.get(row)
        if v is None:
            return {}
        spec, r = v["spec"], v["result"]
        decs = [d for d in (res.decisions or ())
                if self.period.start <= d["month_end"] <= self.period.end]
        fb = [d["month_end"] for d in decs if d.get("score_source") == "fallback"]
        buys = res.trades[res.trades["side"] == "BUY"] if len(res.trades) else res.trades
        ends = sorted(d["month_end"] for d in decs)
        fbset, tot, fbv = set(fb), 0.0, 0.0
        for t, q, px in zip(buys.get("date", []), buys.get("qty", []),
                            buys.get("fill_price", [])):
            prior = [e for e in ends if e < t]
            val = float(q) * float(px)
            tot += val
            if prior and prior[-1] in fbset:
                fbv += val
        gain = {}
        for f in self.walk.fits.values():
            if f.fitted and f.h in spec.horizons and \
                    any(f.sha256 == s for m in r["info"].values()
                        for (_, s, *_rest) in m["fits"]):
                gain.setdefault(f"h{f.h}", {})[str(f.refit)] = f.gain
        return {"fallback_decisions": len(fb), "decisions": len(decs),
                "fallback_share_decisions": (len(fb) / len(decs)) if decs else None,
                "fallback_share_buy_value": (fbv / tot) if tot else None,
                "fallback_months": [str(m) for m in fb],
                "rank_ic": ic_by_year(r["predictions"], self.labels, spec.horizons),
                "gain_importance": gain,
                "models": [{"month_end": str(m), "refit": str(i["refit"]),
                            "fits": [{"h": h, "sha256": s, "rows": n, "cross_sections": x,
                                      "reason": why} for h, s, n, x, why in i["fits"]]}
                           for m, i in sorted(r["info"].items())]}
