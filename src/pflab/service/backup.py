"""Backups of the PM ledger (PLAN S9). Built, but DISABLED until a target is set (The investor's decision):
`PFLAB_BACKUP_DIR` or `[backup] target` in configs/service.toml.

A backup is a checkpointed copy of `ledger.duckdb` named by time, verified by opening the copy
read-only and comparing every table's row count with the source. A backup that does not verify is
deleted and the job fails. Old backups beyond `keep` are pruned. The target must not sit inside the
PM directory (a backup in the thing it protects is no backup).
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import duckdb

from pflab import _toml

PREFIX = "ledger-"
SUFFIX = ".duckdb"


class BackupError(RuntimeError):
    pass


def target_dir(config_path: Optional[Path] = None) -> Optional[Path]:
    env = os.environ.get("PFLAB_BACKUP_DIR", "").strip()
    if env:
        return Path(env)
    try:                                                    # S78: the folder he sets in Settings (it survives updates; the config file in the release does not)
        from pflab.app import settings as st
        from pflab.pm import store
        v = str(st.load(store.pm_dir()).get("backup_dir", "") or "").strip()
        if v:
            return Path(v)
    except Exception:
        pass
    cfg = config_path or Path(__file__).resolve().parents[3] / "configs" / "service.toml"
    t = (_toml.load(cfg).get("backup") or {}).get("target", "") if cfg.exists() else ""
    return Path(t) if t else None


def declined(config_path: Optional[Path] = None) -> Optional[str]:
    """The date the investor decided against a backup target ([backup] declined), else None."""
    cfg = config_path or Path(__file__).resolve().parents[3] / "configs" / "service.toml"
    return str((_toml.load(cfg).get("backup") or {}).get("declined", "") or "") or None if cfg.exists() else None


def keep_count(config_path: Optional[Path] = None) -> int:
    cfg = config_path or Path(__file__).resolve().parents[3] / "configs" / "service.toml"
    return int((_toml.load(cfg).get("backup") or {}).get("keep", 30)) if cfg.exists() else 30


def _counts_of(con) -> Dict[str, int]:
    tables = [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables "
                                        "WHERE table_schema='main' AND table_catalog=current_database() ORDER BY 1").fetchall()]
    return {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}


def _counts(path: Path) -> Dict[str, int]:
    con = duckdb.connect(str(path), read_only=True)
    try:
        return _counts_of(con)
    finally:
        con.close()


def backup(con, db_path: Path, target: Path, now: datetime, keep: int = 30) -> dict:
    """Copy the live ledger to `target`, verify, prune. `con` is the open connection: on Windows the
    database file is locked while it is open, so the copy is made by DuckDB itself (ATTACH + COPY FROM
    DATABASE), never by copying the file."""
    db_path, target = Path(db_path).resolve(), Path(target)
    if db_path.parent in target.resolve().parents or target.resolve() == db_path.parent:
        raise BackupError(f"backup target {target} is inside the PM directory {db_path.parent}")
    target.mkdir(parents=True, exist_ok=True)
    dest = target / f"{PREFIX}{now:%Y%m%d-%H%M%S}{SUFFIX}"
    try:
        con.execute("CHECKPOINT")
        src = _counts_of(con)
        con.execute(f"ATTACH '{dest.as_posix()}' AS pflab_backup")
        try:
            con.execute("COPY FROM DATABASE " + _current_db(con) + " TO pflab_backup")
        finally:
            con.execute("DETACH pflab_backup")
        got = _counts(dest)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise BackupError(f"backup failed: {e}") from e
    if src != got:
        dest.unlink(missing_ok=True)
        diff = {t: (src.get(t), got.get(t)) for t in set(src) | set(got) if src.get(t) != got.get(t)}
        raise BackupError(f"backup does not match the ledger: {diff}")
    pruned = prune(target, keep)
    return {"file": str(dest), "bytes": dest.stat().st_size, "tables": len(got), "rows": sum(got.values()),
            "pruned": pruned}


def _current_db(con) -> str:
    return con.execute("SELECT current_database()").fetchone()[0]


def listing(target: Path) -> List[Path]:
    return sorted(Path(target).glob(f"{PREFIX}*{SUFFIX}"))


def prune(target: Path, keep: int) -> int:
    files = listing(target)
    old = files[:-keep] if keep > 0 and len(files) > keep else []
    for f in old:
        f.unlink()
    return len(old)


def latest(target: Path) -> Optional[Tuple[Path, datetime]]:
    files = listing(target)
    if not files:
        return None
    f = files[-1]
    return f, datetime.strptime(f.name[len(PREFIX):-len(SUFFIX)], "%Y%m%d-%H%M%S")


def restore_check(backup_file: Path, scratch: Path) -> dict:
    """Restore the backup into `scratch` (a temp dir) and open it: the monthly drill's first step. The
    full drill (S32) then re-runs reconciliation on the restored copy."""
    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    dest = scratch / "ledger.duckdb"
    shutil.copy2(backup_file, dest)
    counts = _counts(dest)
    return {"restored_to": str(dest), "tables": len(counts), "rows": sum(counts.values()), "counts": counts}
