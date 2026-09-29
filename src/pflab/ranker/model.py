"""E5-A §5: the model, and the purged training set it is fitted on.

A model fitted at refit date R trains only on label rows whose target is
observable by the close of R (§4): `target_observable_at <= R`, which implies
the row's own `observable_at <= R`. That is the whole purge -- derived from
each label's stored interval, never from a fixed session count -- and it is
the only way a label reaches a fit.

Fits are deterministic: LightGBM's `deterministic=true`, row-wise histograms,
a fixed thread count and fixed seeds, on rows in a fixed (M, ISIN) order. The
model file is `Booster.model_to_string()`; its SHA-256 identifies the model.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

SEED = 20260927
# §5 fixed: 300 trees, bagging 0.8 every iteration, feature fraction 0.8.
FIXED = {"num_iterations": 300, "bagging_fraction": 0.8, "bagging_freq": 1,
         "feature_fraction": 0.8}
# Determinism, not modelling choices: §5's "deterministic=true, fixed thread
# count and seeds".
DETERMINISM = {"objective": "regression", "deterministic": True,
               "force_row_wise": True, "num_threads": 1, "verbose": -1}


def lightgbm_version() -> str:
    import lightgbm
    return lightgbm.__version__


@dataclass
class Fit:
    """One fitted model, or the reason there is none."""
    h: int
    refit: date
    n_rows: int
    n_cross_sections: int
    text: Optional[str] = None
    sha256: Optional[str] = None
    gain: Dict[str, float] = field(default_factory=dict)
    reason: Optional[str] = None
    _booster: object = None

    @property
    def fitted(self) -> bool:
        return self.text is not None

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self._booster.predict(X, num_threads=1)


def params(tuned: dict, seed: int = SEED, fixed: Optional[dict] = None,
           num_threads: int = 1) -> dict:
    """Every LightGBM parameter a fit uses. `tuned` holds §5's grid keys."""
    p = {**DETERMINISM, **(fixed or FIXED), **tuned}
    p["seed"] = int(seed)
    p["num_threads"] = int(num_threads)
    return dict(sorted(p.items()))


def training_rows(labels: pd.DataFrame, h: int, R: date) -> pd.DataFrame:
    """The purged training set for horizon h at refit date R (§4)."""
    L = labels[labels["h"] == h]
    tob = L["target_observable_at"]
    ok = L["target"].notna() & tob.notna()
    ok &= pd.Series([t is not None and t <= R for t in tob], index=L.index)
    own = L["observable_at"]
    ok &= pd.Series([o is not None and o <= R for o in own], index=L.index)
    return L[ok].sort_values(["month_end", "isin"], kind="mergesort")


def design(features_wide: pd.DataFrame, rows: pd.DataFrame,
           features: Sequence[str]) -> np.ndarray:
    """Feature matrix for label rows, in the rows' order."""
    idx = pd.MultiIndex.from_arrays([rows["month_end"].to_numpy(),
                                     rows["isin"].to_numpy()])
    return features_wide.reindex(idx)[list(features)].to_numpy(dtype=float)


def fit(features_wide: pd.DataFrame, labels: pd.DataFrame, h: int, R: date,
        p: dict, features: Sequence[str], min_cross_sections: int = 12) -> Fit:
    """Fit horizon h at R, or return why not (fewer than the minimum
    cross-sections: §5, the stack's rank is then used)."""
    rows = training_rows(labels, h, R)
    n_xs = int(rows["month_end"].nunique())
    if n_xs < min_cross_sections:
        return Fit(h, R, int(len(rows)), n_xs,
                   reason=f"{n_xs} cross-sections < {min_cross_sections}")
    import lightgbm as lgb
    X = design(features_wide, rows, features)
    y = rows["target"].to_numpy(dtype=float)
    train = {k: v for k, v in p.items() if k != "num_iterations"}
    ds = lgb.Dataset(X, label=y, feature_name=list(features),
                     params={"verbose": -1}, free_raw_data=True)
    booster = lgb.train(train, ds, num_boost_round=int(p["num_iterations"]))
    text = booster.model_to_string()
    gain = dict(zip(features, map(float, booster.feature_importance("gain"))))
    return Fit(h, R, int(len(rows)), n_xs, text=text,
               sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
               gain=gain, _booster=booster)


def spearman(a, b) -> Optional[float]:
    """Rank correlation of two aligned vectors (average ranks), or None."""
    a, b = pd.Series(a, dtype=float), pd.Series(b, dtype=float)
    ok = a.notna() & b.notna()
    if ok.sum() < 3:
        return None
    ra, rb = a[ok].rank(), b[ok].rank()
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])
