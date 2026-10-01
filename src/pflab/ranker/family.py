"""E5-A families on disk: PFLAB_DATA_DIR/e5a/<period>/features_<fam>.parquet.

A family's store sits beside A0's in the same period directory and is built
over A0's U(M) (read from A0's verified store), so a family can never add a
name. It has its own meta file, SHA-checked like A0's. A0's own files, code
and identity are untouched: a family run checks the A0 store against the
A0 part of its config (`base_config`), exactly as an A0 run would (§3: "a
family changes only the input columns").

  features_a1.parquet / meta_a1.json   §6(b) issuer events
  features_a2.parquet / meta_a2.json   §6(c) promoter positioning
  features_a3.parquet / meta_a3.json   §6(d) world exposure
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import List, Tuple

import pandas as pd

from pflab.eval import artifacts
from pflab.ranker import store
from pflab.ranker.features import A0_FEATURES

FAMILIES = ("A1", "A2", "A3")
SOURCES = {"A1": ("ranker/events.py", "ranker/family.py"),
           "A2": ("ranker/holdings.py", "ranker/family.py", "data/positioning.py"),
           "A3": ("ranker/exposure.py", "ranker/family.py", "signals/shock_betas.py")}


def features_file(fam: str) -> str:
    return f"features_{fam.lower()}.parquet"


def meta_file(fam: str) -> str:
    return f"meta_{fam.lower()}.json"


def family_of(cfg: dict) -> str:
    return str((cfg.get("e5a") or {}).get("family", "A0"))


def family_features(cfg: dict) -> List[str]:
    """The config's feature columns that are not A0's, in config order."""
    return [f for f in (cfg.get("e5a") or {}).get("features", []) if f not in A0_FEATURES]


def base_config(cfg: dict) -> dict:
    """The A0 config a family is built on: same everything, A0's columns."""
    c = copy.deepcopy(cfg)
    e = c.setdefault("e5a", {})
    e["family"] = "A0"
    e["features"] = [f for f in e.get("features", A0_FEATURES) if f in A0_FEATURES]
    for k in ("activation", "a1", "a2", "a3"):
        e.pop(k, None)
    return c


def builder_sha(fam: str) -> str:
    pkg = Path(__file__).resolve().parents[1]
    h = hashlib.sha256()
    for rel in SOURCES[fam]:
        h.update(rel.encode("utf-8"))
        h.update((pkg / rel).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def identity(cfg: dict) -> dict:
    """What a family store depends on besides A0's store: its columns and
    its own block ([e5a.a1] reader assignment, [e5a.a3] nothing yet)."""
    e = cfg.get("e5a") or {}
    fam = family_of(cfg)
    return {"family": fam, "features": family_features(cfg),
            "block": e.get(fam.lower(), {})}


def write(d: Path, fam: str, feats: pd.DataFrame, meta: dict) -> dict:
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    feats.to_parquet(d / features_file(fam), index=False)
    sha = artifacts.file_sha(d / features_file(fam))
    (d / meta_file(fam)).write_text(
        json.dumps({**meta, "file": sha}, indent=2, default=str), encoding="utf-8")
    return {features_file(fam): sha}


def file_sha(d: Path, fam: str):
    p = Path(d) / features_file(fam)
    return artifacts.file_sha(p) if p.exists() else None


def load(d: Path, fam: str) -> Tuple[pd.DataFrame, dict]:
    d = Path(d)
    if not (d / meta_file(fam)).exists():
        raise FileNotFoundError(f"no {fam} store at {d}; build it with "
                                f"tools/build_e5a_family.py --family {fam}")
    meta = json.loads((d / meta_file(fam)).read_text(encoding="utf-8"))
    if file_sha(d, fam) != meta.get("file"):
        raise store.StaleStore(f"{d}: {features_file(fam)} does not match meta")
    return store._as_dates(pd.read_parquet(d / features_file(fam))), meta


def check(meta: dict, cfg: dict, period, a0_meta: dict) -> None:
    """Refuse a family store not built for this period, config, code and A0
    store."""
    fam = family_of(cfg)
    why = []
    if meta.get("period") != period.name or meta.get("period_end") != str(period.end):
        why.append("period differs")
    if meta.get("builder_sha") != builder_sha(fam):
        why.append(f"the {fam} builder code has changed since the build")
    if meta.get("a0_files") != a0_meta.get("files"):
        why.append("it was built over a different A0 store")
    if json.loads(json.dumps(meta.get("identity"), default=str)) != \
            json.loads(json.dumps(identity(cfg), default=str)):
        why.append("the family's columns or block differ")
    if why:
        raise store.StaleStore(
            f"E5-A {fam} store does not match this run: " + "; ".join(why) +
            f". Rebuild: python tools\\build_e5a_family.py --family {fam} "
            f"--config <config> --period {period.name}")
