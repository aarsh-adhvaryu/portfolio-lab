"""Targets and bands (PLAN S17). The file ships with no values; loading it raises `TargetsNotSet`
until the investor has set them, so no plan can be built on a default."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pflab import _toml
from pflab.risk.exposure import BUCKETS

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "configs" / "targets.toml"
TOL = 1e-6


class TargetsNotSet(RuntimeError):
    """The investor has not set targets: nothing is proposed until he does."""


class TargetsInvalid(ValueError):
    pass


@dataclass(frozen=True)
class BucketTarget:
    bucket: str
    target: float
    soft_band: float
    hard_band: float
    buy: Tuple[Tuple[str, float], ...] = ()      # (isin, weight)


@dataclass(frozen=True)
class Targets:
    set_by: str
    effective_from: date
    buckets: Dict[str, BucketTarget] = field(default_factory=dict)
    cash_floor: float = 0.0                     # rupees always kept as cash, outside the weights

    def get(self, bucket: str) -> Optional[BucketTarget]:
        return self.buckets.get(bucket)


def parse(doc: dict) -> Targets:
    buckets = doc.get("bucket") or {}
    if not buckets:
        raise TargetsNotSet("no targets are set in configs/targets.toml: The investor sets them, "
                            "the allocator proposes nothing until he does")
    meta = doc.get("meta") or {}
    if not meta.get("set_by") or not meta.get("effective_from"):
        raise TargetsNotSet("targets need [meta] set_by and effective_from (who set them and when)")
    eff = meta["effective_from"]
    if not isinstance(eff, date):
        raise TargetsInvalid("effective_from must be a date (YYYY-MM-DD)")
    out: Dict[str, BucketTarget] = {}
    for name, t in buckets.items():
        if name not in BUCKETS or name == "unclassified":
            raise TargetsInvalid(f"unknown bucket {name!r}; one of {[b for b in BUCKETS if b != 'unclassified']}")
        tgt, soft, hard = float(t["target"]), float(t["soft_band"]), float(t["hard_band"])
        if not 0 <= tgt <= 1:
            raise TargetsInvalid(f"{name}: target must be between 0 and 1")
        if not 0 <= soft <= hard <= 1:
            raise TargetsInvalid(f"{name}: need 0 <= soft_band <= hard_band <= 1")
        buy = tuple((b["isin"], float(b["weight"])) for b in t.get("buy", []))
        if buy and abs(sum(w for _, w in buy) - 1.0) > TOL:
            raise TargetsInvalid(f"{name}: buy weights must sum to 1.0")
        if name == "cash" and buy:
            raise TargetsInvalid("cash has nothing to buy")
        out[name] = BucketTarget(name, tgt, soft, hard, buy)
    total = sum(b.target for b in out.values())
    if abs(total - 1.0) > TOL:
        raise TargetsInvalid(f"target weights sum to {total:.4f}, not 1.0")
    floor = float(meta.get("cash_floor", 0.0))
    if floor < 0:
        raise TargetsInvalid("cash_floor cannot be negative")
    return Targets(str(meta["set_by"]), eff, out, floor)


def default_path() -> Path:
    """The investor's own file in PFLAB_PM_DIR when it exists (his weights and picks stay out of git), else the
    shipped template in configs/ (which has no values and so refuses to plan)."""
    from pflab.pm import store
    own = store.pm_dir() / "targets.toml"
    return own if own.exists() else DEFAULT_PATH


def load(path: Optional[Path] = None) -> Targets:
    return parse(_toml.load(path or default_path()))
