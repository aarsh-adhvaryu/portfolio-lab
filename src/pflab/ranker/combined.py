"""E5-A-ALL (§14 2026-10-01): A0 plus A1's, A2's and A3's columns together.

No store of its own: ALL reads each member's store, built and checked exactly
as that member's (its builder hash, its block, A0's store), through a member
config cut from ALL's -- A0's part plus that member's columns and block. So
ALL can never use a column its member would not, and a member store rebuilt
for any reason is checked here too. Activation per member is in
`walk.Spec.groups`. Kept out of `family.py`, whose source is inside the A1
and A3 builder hashes (their locks).
"""
from __future__ import annotations

import copy
from typing import List, Tuple

import pandas as pd

from pflab.ranker import family
from pflab.ranker.features import A0_FEATURES

NAME = "ALL"
MEMBERS = ("A1", "A2", "A3")


def is_all(cfg: dict) -> bool:
    return family.family_of(cfg) == NAME


def member_config(cfg: dict, fam: str) -> dict:
    """ALL's config as member `fam` alone: its columns and its block."""
    c = copy.deepcopy(cfg)
    e = c["e5a"]
    groups = e.pop("groups")
    e["family"] = fam
    e["features"] = [f for f in e["features"] if f in A0_FEATURES] + list(groups[fam])
    for other in MEMBERS:
        if other != fam:
            e.pop(other.lower(), None)
    return c


def load(sdir, cfg: dict, period, a0_meta: dict) -> Tuple[pd.DataFrame, dict]:
    """Every member's store, each checked against its member config."""
    parts, metas = [], {}
    for fam in MEMBERS:
        feats, meta = family.load(sdir, fam)
        family.check(meta, member_config(cfg, fam), period, a0_meta)
        parts.append(feats)
        metas[fam] = {"file": meta["file"], "code": meta.get("code")}
    return pd.concat(parts, ignore_index=True), metas


def columns(cfg: dict) -> List[str]:
    return list(cfg["e5a"]["features"])
