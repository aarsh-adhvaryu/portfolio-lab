"""The dated, sourced rows of the US sub-book (configs/us/tax_s81.toml). Same vocabulary as the tax engine's rows; a figure built from them says which rows it used and how each
was checked (primary, secondary or ESTIMATE). A row that is not there is an error, never a silent default."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from pflab import _toml

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "us" / "tax_s81.toml"
LEVELS = ("primary", "secondary", "estimate")


def rows(path: Optional[Path] = None) -> Dict[str, dict]:
    return {r["id"]: r for r in _toml.load(path or CONFIG)["fact"]}


def fact(fid: str, path: Optional[Path] = None) -> dict:
    r = rows(path).get(fid)
    if r is None:
        raise KeyError(f"no US row {fid!r}")
    if r.get("verification") not in LEVELS:
        raise ValueError(f"{fid}: verification {r.get('verification')!r} is not one of {LEVELS}")
    return r


def value(fid: str, path: Optional[Path] = None):
    return fact(fid, path)["value"]


def label(fids: List[str], path: Optional[Path] = None) -> str:
    """The sources behind a figure, for its label: 'ESTIMATE' is in it whenever any row is an estimate or secondary."""
    parts, worst = [], "primary"
    for i in fids:
        r = fact(i, path)
        parts.append(f"{i} ({r['verification']}, {r['verified_on']})")
        if LEVELS.index(r["verification"]) > LEVELS.index(worst):
            worst = r["verification"]
    head = "estimate" if worst != "primary" else "from primary sources"
    return f"{head}; rows " + ", ".join(parts)
