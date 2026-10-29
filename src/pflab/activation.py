r"""The first-launch gate (S67 local). A fresh personal profile starts DORMANT: `pm/activation.json` says `pending`, and until the investor
double-clicks the desktop icon nothing reaches a real mailbox or broker, no collector or job runs on it, and no personal picture is
built. The icon's launcher (`app/launcher.py`, the window path) is the only thing that turns it `active`; the installer, the verifier,
the headless worker, imports and the scheduled tick only ever read the state, so none of them can open it by accident.

A profile with no `activation.json` (the running app of today, the workshop, every test) is active: the gate exists only where a
reset or the installer wrote `pending`. Once `active` it stays so across restarts and updates (a later icon click resumes; it never
resets). Synthetic test profiles exercise the gate in isolation by writing `pending` into their own folder.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

FILE = "activation.json"
PENDING, ACTIVE = "pending", "active"


class ActivationPending(RuntimeError):
    """The profile has not been launched by the investor yet; nothing real may run on it."""


def _dir(pm: Optional[Path] = None) -> Path:
    if pm is not None:
        return Path(pm)
    from pflab.pm import store
    return store.pm_dir()


def path(pm: Optional[Path] = None) -> Path:
    return _dir(pm) / FILE


def read(pm: Optional[Path] = None) -> dict:
    try:
        return json.loads(path(pm).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def state(pm: Optional[Path] = None) -> str:
    """`pending` only when the file says so. A damaged or unreadable file that exists is read as pending (closed, not open)."""
    p = path(pm)
    if not p.exists():
        return ACTIVE
    return ACTIVE if read(pm).get("state") == ACTIVE else PENDING


def is_pending(pm: Optional[Path] = None) -> bool:
    return state(pm) == PENDING


def guard(what: str, pm: Optional[Path] = None) -> None:
    """Call before anything that reaches a real source or builds the personal picture."""
    if is_pending(pm):
        raise ActivationPending(f"{what}: this profile is waiting for its first launch; start Portfolio Lab from its desktop icon")


def write_pending(pm: Optional[Path] = None, profile: str = "") -> Path:
    """Used by the reset/installer on a NEW profile folder. Refuses to take an already active profile back to pending: a later reset
    makes a new profile (and archives the old), it never re-arms this one."""
    p = path(pm)
    if p.exists() and read(pm).get("state") == ACTIVE:
        raise ValueError("this profile is already active; a fresh start makes a new profile")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"state": PENDING, "profile": profile, "armed_at": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    os.replace(tmp, p)
    return p


def activate(pm: Optional[Path] = None, via: str = "") -> bool:
    """The icon's launcher opens the gate (`via='icon'`). Anything else is refused. True when this call opened it, False when it was
    already open."""
    if via != "icon":
        raise ActivationPending("only the desktop icon starts a fresh profile")
    if not is_pending(pm):
        return False
    old = read(pm)
    p = path(pm)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({**old, "state": ACTIVE, "activated_at": datetime.now().isoformat(timespec="seconds"), "via": via}), encoding="utf-8")
    os.replace(tmp, p)
    return True
