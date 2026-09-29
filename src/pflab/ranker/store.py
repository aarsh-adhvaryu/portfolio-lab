"""The E5-A feature store on disk: PFLAB_DATA_DIR/e5a/<period>/.

One directory per evaluation period, built by `tools/build_e5a_features.py`
from `runner.prepare` -- the panel cut at that period's end by
`truncate_end` -- so a store can hold nothing dated after its period.

  features_a0.parquet   §6 long format, family (a)
  labels.parquet        §4 labels with their intervals
  meta.json             what it was built from, including the panel's
                        content fingerprint, which a sweep must match
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Tuple

import pandas as pd

from pflab.eval import artifacts

FEATURES = "features_a0.parquet"
LABELS = "labels.parquet"
META = "meta.json"
DATE_COLS = ("month_end", "usable_from", "label_start", "label_end",
             "observable_at", "target_observable_at")


class StaleStore(RuntimeError):
    """The store was built from different data or a different universe."""


def store_dir(period_name: str, root=None) -> Path:
    from pflab.data import data_dir
    return Path(root or data_dir()) / "e5a" / period_name


def _as_dates(df: pd.DataFrame) -> pd.DataFrame:
    for c in DATE_COLS:
        if c in df.columns:
            df[c] = [None if (x is None or pd.isna(x)) else
                     (x if type(x) is date else pd.Timestamp(x).date())
                     for x in df[c]]
    return df


def write(d: Path, features: pd.DataFrame, labels: pd.DataFrame, meta: dict) -> dict:
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    features.to_parquet(d / FEATURES, index=False)
    labels.to_parquet(d / LABELS, index=False)
    shas = file_shas(d)
    (d / META).write_text(json.dumps({**meta, "files": shas}, indent=2, default=str),
                          encoding="utf-8")
    return shas


def file_shas(d: Path) -> dict:
    d = Path(d)
    return {f: artifacts.file_sha(d / f) for f in (FEATURES, LABELS)
            if (d / f).exists()}


def load(d: Path) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    d = Path(d)
    if not (d / META).exists():
        raise FileNotFoundError(f"no E5-A store at {d}; build it with "
                                f"tools/build_e5a_features.py")
    meta = json.loads((d / META).read_text(encoding="utf-8"))
    now = file_shas(d)
    if now != meta.get("files"):
        raise StaleStore(f"{d}: files do not match the shas in meta.json "
                         f"({now} vs {meta.get('files')})")
    return (_as_dates(pd.read_parquet(d / FEATURES)),
            _as_dates(pd.read_parquet(d / LABELS)), meta)


BUILDER_SOURCES = ("ranker/features.py", "ranker/labels.py", "backtest/engine.py",
                   "signals/momentum.py", "signals/vol_scaled.py")


def builder_sha() -> str:
    """SHA-256 over the source that turns a panel into this store: the
    feature and label code, and the engine code that defines U(M) and the
    stack's score. A store built by other code is stale even on the same
    data."""
    import hashlib
    pkg = Path(__file__).resolve().parents[1]
    h = hashlib.sha256()
    for rel in BUILDER_SOURCES:
        h.update(rel.encode("utf-8"))
        # line endings normalised: git's autocrlf checks a locked worktree
        # out with CRLF, and the same code must hash the same there
        h.update((pkg / rel).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def identity(config: dict) -> dict:
    """The config the store depends on: the universe (U(M)), the stack's
    score (a feature, and the fallback) and the §9 confirm window (labels)."""
    s = config.get("strategy", {})
    return {"universe": {k: v for k, v in sorted((config.get("universe") or {}).items())},
            "stack_signal": {k: s.get(k) for k in
                             ("fallback_signal", "skip_sessions", "lookback_sessions",
                              "score_windows", "score_order",
                              "delist_confirm_sessions")},
            "e5a_family": (config.get("e5a") or {}).get("family", "A0"),
            "features": list((config.get("e5a") or {}).get("features", [])),
            "horizons": list((config.get("e5a") or {}).get("horizons", [1, 3, 12]))}


def check(meta: dict, config: dict, period, panel_fingerprint: str) -> None:
    """Refuse a store that does not describe this run's data and config."""
    why = []
    if meta.get("period") != period.name or meta.get("period_end") != str(period.end):
        why.append(f"period {meta.get('period')}/{meta.get('period_end')} "
                   f"!= {period.name}/{period.end}")
    if meta.get("panel_fingerprint") != panel_fingerprint:
        why.append("the panel's content fingerprint differs")
    if meta.get("builder_sha") != builder_sha():
        why.append("the feature, label or universe code has changed since the build")
    if json.loads(json.dumps(meta.get("identity"), default=str)) != \
            json.loads(json.dumps(identity(config), default=str)):
        why.append("the universe, stack score or feature list differs")
    if why:
        raise StaleStore(
            "E5-A store does not match this run: " + "; ".join(why) +
            f". Rebuild: python tools\\build_e5a_features.py --config <config> "
            f"--period {period.name}")
