"""Dashboard settings, kept in PFLAB_PM_DIR/app/settings.json (The investor's, never in git)."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULTS: Dict[str, Any] = {
    "theme": "dark",              # dark | light | system
    "privacy": False,             # weights and percentages instead of rupees
    "telegram_send": False,       # held until switch-on: the outbox is never flushed while False
    "port": 8765,
    "scheduler": True,            # run the system's jobs while the window is open
    "live_prices": True,          # poll Kite in market hours when logged in
    "preset": "full",             # off | light | full | marathon: how much the system does while it runs
    "sims_hour": 22,              # the nightly simulation starts after this hour (full: 10,000 paths; marathon: 100,000)
    "brain": "economy",           # S59: off | economy | normal: how often the brain may think (hq/governor.py)
    "drop_watch": True,           # S59: files placed in the drop folder reach the inbox by themselves
    "models": {},                 # S61: the slider, job -> model; a job not set takes its measured default (hq/models.py)
    "features": {},               # S65: his switch per beta feature (configs/features.toml); none set = the channel's default
    "abilities": {},              # S78: what the AI may see and use (ABILITIES); a missing key means ON. Enforced where the thing is used, not just shown
}
# S78: the abilities he can switch off. Each is checked by code where it is used: `tools.run` (charts, web, calculations), the live quote paths (kite_live), the chat front (local_first).
ABILITIES = {"charts": "Look at candlestick charts (the picture and the figures beside it)", "web": "Search the web and read pages", "calculations": "Run its own calculations in the closed box",
             "kite_live": "Use Kite's live prices and candles (read only; orders are blocked in code)", "local_first": "Let the local model take small jobs and the front of the chat first"}
CHOICES = {"theme": ("dark", "light", "system"), "preset": ("off", "light", "full", "marathon"),
           "brain": ("off", "economy", "normal")}

# What each preset runs. Light keeps the data and the checks current and leaves out the heavy agents; full runs every
# job; marathon adds the nightly 100,000-path simulation. The outbox stays held until Telegram is switched on.
LIGHT_JOBS = ("collect", "prices", "nav", "filings", "global", "guards", "tradecheck", "backup", "conductor", "plans",
              "hq", "summary_morning", "summary_evening", "watches",
              "watches_close", "idle_cash", "twin", "backfill", "sandbox")                     # S59: his orders, reminders and the drop folder; the paid agents only on full
PRESETS = {
    "off": "nothing runs on its own; live prices and the screens still work",
    "light": "data and checks only: prices, NAVs, filings, world markets, guards, trades against the ledger, backup",
    "full": "every job: also the knowledge graph, research, forecasts, the analyst batch; a 10,000-path simulation nightly",
    "marathon": "every job and a 100,000-path simulation of every mix nightly",
}


def ability(name: str, pm_dir: Optional[Path] = None, current: Optional[Dict[str, Any]] = None) -> bool:
    """Is this ability on? On unless he switched it off. Reads the settings file when none is given (the quote paths and the tools have no runtime at hand)."""
    try:
        s = current if current is not None else load(pm_dir or __import__("pflab.pm.store", fromlist=["x"]).pm_dir())
        return bool((s.get("abilities") or {}).get(name, True))
    except Exception:
        return True


def jobs_for(preset: str, registry) -> list:
    if preset == "off":
        return []
    if preset == "light":
        return [j for j in registry if j in LIGHT_JOBS]
    return list(registry)


def sims_paths(preset: str):
    return {"full": 10_000, "marathon": 100_000}.get(preset)


def path(pm_dir: Path) -> Path:
    return Path(pm_dir) / "app" / "settings.json"


def load(pm_dir: Path) -> Dict[str, Any]:
    p = path(pm_dir)
    out = dict(DEFAULTS)
    if p.exists():
        try:
            out.update({k: v for k, v in json.loads(p.read_text(encoding="utf-8")).items() if k in DEFAULTS})
        except (ValueError, OSError):
            pass                          # a damaged file falls back to the defaults; saving rewrites it
    return out


_SAVE = threading.Lock()


def save(pm_dir: Path, changes: Dict[str, Any], current: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One save at a time (S58 drill 1: two clicks raced on one temp file); Windows may hold the file a moment (an
    indexer or virus scan), so the swap is retried."""
    with _SAVE:
        return _save(pm_dir, changes, current)


def _save(pm_dir: Path, changes: Dict[str, Any], current: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cur = dict(current or load(pm_dir))
    for k, v in changes.items():
        if k == "models" and isinstance(v, dict):               # S61: only known jobs and their allowed models
            from pflab.hq import models
            m = {**cur.get("models", {}), **models.valid(v)}
            cur["models"] = {j: c for j, c in m.items() if v.get(j) != "default"}     # "default": back to the measured one
        elif k == "features" and isinstance(v, dict):           # S65: only listed features, only true or false
            from pflab import features
            known = features.load()
            cur["features"] = {**cur.get("features", {}), **{f: b for f, b in v.items() if f in known and isinstance(b, bool)}}
        elif k == "abilities" and isinstance(v, dict):          # S78: only the listed abilities, only true or false
            cur["abilities"] = {**cur.get("abilities", {}), **{a: b for a, b in v.items() if a in ABILITIES and isinstance(b, bool)}}
        elif k in DEFAULTS and type(v) is type(DEFAULTS[k]) and v in CHOICES.get(k, (v,)):
            cur[k] = v
    p = path(pm_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"settings.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(cur, indent=1), encoding="utf-8")
    for i in range(10):
        try:
            tmp.replace(p)
            break
        except PermissionError:
            if i == 9:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.05 * (i + 1))
    return cur
