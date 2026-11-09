"""The graph's switch (S81 B7): `configs/kg2.toml` `[kg] on`, default OFF. `PFLAB_KG2=on|off` in the environment wins (tests).

`on()` is the file's setting. `active(con, day)` is what callers use: the switch AND a passed audit no older than three days. A graph whose audit failed is never
loaded into the store (`job.run`), so its events never reach the exit manager or the storylines.
"""
from __future__ import annotations

import os
import tomllib
from datetime import date
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "kg2.toml"


def on() -> bool:
    env = os.environ.get("PFLAB_KG2", "").strip().lower()
    if env in ("on", "off"):
        return env == "on"
    try:
        return bool(tomllib.loads(CONFIG.read_text(encoding="utf-8")).get("kg", {}).get("on", False))
    except (OSError, ValueError):
        return False


def active(con, day: date) -> bool:
    from pflab.kg2 import audit
    return on() and audit.last_passed(con, day)
