"""The knowledge graph's one switch (his decision 2026-11-08: the graph was deleted and is OFF until its design is agreed with him).

`configs/kg.toml` `[graph] on = false` stops every write to the graph (nodes, links, aliases, hypotheses, name cleaning and its questions). Documents (`kg_docs`: filing and
news texts) are still stored, but nothing links them to a company while the graph is off, so filing-driven investigations and company document lookups find nothing.
`PFLAB_KG=on|off` in the environment wins over the file (the test suite keeps the graph on to test its code).
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "kg.toml"
WHY = "the knowledge graph is switched off (his decision 2026-11-08: deleted, rebuilt only after its design is agreed)"


def on() -> bool:
    env = os.environ.get("PFLAB_KG", "").strip().lower()
    if env in ("on", "off"):
        return env == "on"
    try:
        return bool(tomllib.loads(CONFIG.read_text(encoding="utf-8")).get("graph", {}).get("on", True))
    except (OSError, ValueError):
        return True
