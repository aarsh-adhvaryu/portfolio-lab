"""Start the record again (S65, S64 Phase 7 item 8): `pflab pm reset`.

His store is his record (the ledger, the learner's test counter, the suggestions, the journal, his answers): the running system is
never wiped, and an update never does it. This command exists for one deliberate fresh start (a clean-room test, or his own
wish). It MOVES the whole PM folder to `<name>_old_<date>` beside it and leaves an empty folder; it deletes nothing and does not touch
`data\\`. It refuses while another process holds the store (the dashboard, the bot, a job) and without the confirmation word.
Without the word it only lists what would move.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import List, Tuple

CONFIRM = "erase-my-record"


def holds_store(pm_dir: Path) -> bool:
    """True when another process has the ledger open (DuckDB lets one writer in)."""
    import duckdb
    db = Path(pm_dir) / "ledger.duckdb"
    if not db.exists():
        return False
    try:
        duckdb.connect(str(db)).close()
        return False
    except duckdb.IOException:
        return True


def listing(pm_dir: Path) -> List[Tuple[str, int]]:
    """What is in the folder: (relative name, bytes), files only."""
    root = Path(pm_dir)
    return sorted((str(p.relative_to(root)), p.stat().st_size) for p in root.rglob("*") if p.is_file())


def target_for(pm_dir: Path, today: date) -> Path:
    pm_dir = Path(pm_dir)
    t = pm_dir.parent / f"{pm_dir.name}_old_{today:%Y%m%d}"
    n = 1
    while t.exists():
        n += 1
        t = pm_dir.parent / f"{pm_dir.name}_old_{today:%Y%m%d}_{n}"
    return t


def reset(pm_dir: Path, today: date, confirm: str = "") -> dict:
    """Move the PM folder aside. Returns what was (or would be) moved and where. Raises if the store is held."""
    pm_dir = Path(pm_dir)
    if not pm_dir.exists():
        raise FileNotFoundError(f"{pm_dir} does not exist: nothing to reset")
    files = listing(pm_dir)
    target = target_for(pm_dir, today)
    out = {"from": str(pm_dir), "to": str(target), "files": files, "bytes": sum(b for _, b in files), "moved": False}
    if confirm != CONFIRM:
        out["note"] = f"nothing moved: pass --confirm {CONFIRM} to move it"
        return out
    if holds_store(pm_dir):
        raise RuntimeError("another process holds the store (the dashboard, the bot or a job): close it first")
    os.replace(pm_dir, target)
    pm_dir.mkdir(parents=True)
    out["moved"] = True
    out["note"] = (f"moved to {target.name}; delete it yourself once the new ledger's checks pass (your personal inputs go after "
                   "calibration)")
    return out
