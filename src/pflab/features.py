"""Beta features (S65): built and tested, not yet trusted with his money.

configs/features.toml lists them. A beta feature is ON on the beta channel (the workshop, PFLAB_CHANNEL=beta) and OFF on the
stable channel (the app) unless his own switch in Settings (`features` in the dashboard settings) says otherwise. His switch
always wins. Collection of a beta feature's data is never gated here: history builds while the feature is off.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

from pflab import _toml

CONFIG = Path(__file__).resolve().parents[2] / "configs" / "features.toml"
CHANNELS = ("stable", "beta")


def channel() -> str:
    c = os.environ.get("PFLAB_CHANNEL", "stable").strip().lower()
    return c if c in CHANNELS else "stable"


def load(path: Optional[Path] = None) -> Dict[str, dict]:
    return {k: v for k, v in _toml.load(path or CONFIG).items() if isinstance(v, dict)}


def enabled(name: str, settings: Optional[dict] = None, path: Optional[Path] = None) -> bool:
    """Is the feature on? An unknown name is off. `settings` is the dashboard's settings dict (read from the PM folder if None)."""
    spec = load(path).get(name)
    if spec is None:
        return False
    if settings is None:
        from pflab.app import settings as st
        from pflab.pm import store
        settings = st.load(store.pm_dir())
    chosen = (settings.get("features") or {}).get(name)
    if isinstance(chosen, bool):
        return chosen
    return channel() == "beta" if spec.get("beta") else True


def listing(settings: Optional[dict] = None, path: Optional[Path] = None) -> list:
    """For Settings: each feature with its title, whether it is beta, and whether it is on now."""
    return [{"name": k, "title": v.get("title", k), "about": v.get("about", ""), "beta": bool(v.get("beta")),
             "on": enabled(k, settings, path)} for k, v in load(path).items()]
