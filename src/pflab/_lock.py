"""A PID lock, so two collectors never hit the same endpoint at once.

Two processes downloading the same archive concurrently get their connections
reset by NSE -- observed on 2015-12 during the Phase 1 backfill, where it
surfaced as ConnectionError on days that were perfectly fine. Task Scheduler
can also start a daily run while the previous one is still going.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


class LockBusy(RuntimeError):
    pass


def _alive(pid: str) -> bool:
    if not str(pid).isdigit():
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


class FileLock:
    """Context manager. Raises LockBusy if a live process already holds it."""

    def __init__(self, path, name: str = "job"):
        self.path = Path(path)
        self.name = name

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            prev = self.path.read_text(encoding="utf-8").strip()
            if _alive(prev.split()[0] if prev else ""):
                raise LockBusy(f"{self.name} already running ({prev}); "
                               f"delete {self.path} if it is stale")
            print(f"  clearing stale lock from {prev}")
        self.path.write_text(f"{os.getpid()} {datetime.now():%Y-%m-%d %H:%M:%S}",
                             encoding="utf-8")
        return self

    def __exit__(self, *exc) -> None:
        self.path.unlink(missing_ok=True)
