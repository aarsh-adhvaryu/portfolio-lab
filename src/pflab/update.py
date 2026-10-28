r"""`pflab update` and `pflab update --rollback`: the app updates like an app (S65, docs/S65_PLAN.md section 3).

The app is a clone of the private GitHub repo checked out at a release tag (`vYYYY.MM.DD`, or `vYYYY.MM.DD.N`), with a
`release.toml` (src/pflab/release.py). An update, in order:

    1. refuse in the workshop (no release.toml), while another process holds the store, or with edited files in the clone
    2. back up the store (`ledger.duckdb`) into `<app folder>\backups` (never overwritten)
    3. `git fetch --tags`, pick the newest tag, `git checkout` it, install the requirements
    4. self-test: the store opens and migrates, the program starts
    5. write release.toml (new tag, `previous_tag` = the old one, `backup` = the file of step 2)
    A failure at 3 or 4 puts the old tag back and the store as it was (the backup), and says so.

`--rollback` returns to `previous_tag` and restores the backup of the last update; the store as it is now is kept beside it as
`ledger_before_rollback_<date>.duckdb` (nothing is deleted): records written since the update are in that file, not in the
restored one, and this is said in the result. A migration in an update runs on his real store: the backup comes first, every time.
Git, the installer and the self-test are passed in so the whole thing is tested on a temporary repository.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from pflab import release

TAG_RE = re.compile(r"^v\d{4}\.\d{2}\.\d{2}(\.\d+)?$")
Run = Callable[[List[str], Path], Tuple[int, str]]


class UpdateError(RuntimeError):
    pass


def run_cmd(cmd: List[str], cwd: Path) -> Tuple[int, str]:
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout + p.stderr).strip()


def _python(root: Path) -> str:
    for rel in (".venv/Scripts/python.exe", ".venv/bin/python"):
        if (Path(root) / rel).exists():
            return str(Path(root) / rel)
    return sys.executable


def default_install(root: Path, run: Run = run_cmd) -> None:
    rc, out = run([_python(root), "-m", "pip", "install", "-e", ".", "--quiet"], root)
    if rc:
        raise UpdateError(f"installing the requirements failed: {out[-300:]}")


def default_selftest(root: Path, run: Run = run_cmd) -> Tuple[bool, str]:
    """The program starts and the store opens and migrates (a new migration runs here, on the backed-up store)."""
    rc, out = run([_python(root), "-m", "pflab.cli", "pm", "init"], root)
    return rc == 0, out[-300:]


def _git(run: Run, root: Path, *args: str) -> str:
    rc, out = run(["git", *args], root)
    if rc:
        raise UpdateError(f"git {' '.join(args)} failed: {out[-300:]}")
    return out


def tags(root: Path, run: Run = run_cmd) -> List[str]:
    """Release tags, newest first."""
    out = _git(run, root, "tag", "--list", "v*", "--sort=-v:refname")
    return [t for t in out.splitlines() if TAG_RE.match(t.strip())]


def checked_out(root: Path, run: Run = run_cmd) -> str:
    rc, out = run(["git", "describe", "--tags", "--exact-match"], root)
    return out.strip() if rc == 0 else ""


def _set_release(root: Path, tag: str, previous: str, backup: str) -> None:
    r = release.load(root) or {}
    app = r.get("app") or {}
    release.write(root, Path(app.get("folder", root.parent)), tag, previous, app.get("channel", "stable"))
    if backup:
        p = release.path(root)
        p.write_text(p.read_text(encoding="utf-8").replace("\n[paths]", f'backup = \'{backup}\'\n\n[paths]', 1), encoding="utf-8")


def backup_store(pm_dir: Path, folder: Path, tag: str, now: Optional[datetime] = None) -> Path:
    """Copy the ledger beside the app (never over an earlier backup)."""
    now = now or datetime.now()
    src = Path(pm_dir) / "ledger.duckdb"
    dst_dir = Path(folder) / "backups"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"ledger_before_{tag or 'update'}_{now:%Y%m%d_%H%M%S}.duckdb"
    if src.exists():
        shutil.copy2(src, dst)
    return dst


def _guard(root: Path, pm_dir: Path) -> dict:
    r = release.load(root)
    if r is None:
        raise UpdateError("this is the workshop (no release.toml): it is the source of releases, not an app to update")
    from pflab.pm import reset
    if reset.holds_store(pm_dir):
        raise UpdateError("another process holds the store (the dashboard, the bot or a job): close it first")
    return r


def update(root: Path, pm_dir: Path, run: Run = run_cmd, install: Optional[Callable[[Path], None]] = None,
           selftest: Optional[Callable[[Path], Tuple[bool, str]]] = None, check_only: bool = False,
           now: Optional[datetime] = None) -> dict:
    root, pm_dir = Path(root), Path(pm_dir)
    r = _guard(root, pm_dir)
    app = r.get("app") or {}
    cur = str(app.get("tag", "")) or checked_out(root, run)
    if _git(run, root, "status", "--porcelain").strip():
        raise UpdateError("the app's folder has edited files: an app is never edited (git status shows them)")
    _git(run, root, "fetch", "--tags", "--force", "origin")
    found = tags(root, run)
    if not found:
        raise UpdateError("no release tags on GitHub yet")
    newest = found[0]
    out = {"from": cur, "newest": newest, "updated": False}
    if newest == cur or (cur in found and found.index(cur) <= found.index(newest)):
        out["note"] = f"already on the newest release ({cur})"
        return out
    if check_only:
        out["note"] = f"{newest} is available (you are on {cur or 'no tag'}); run pflab update to install it"
        return out
    bk = backup_store(pm_dir, Path(app.get("folder", root.parent)), cur, now)
    out["backup"] = str(bk)
    try:
        _git(run, root, "checkout", "--detach", newest)
        (install or (lambda p: default_install(p, run)))(root)
        ok, msg = (selftest or (lambda p: default_selftest(p, run)))(root)
        if not ok:
            raise UpdateError(f"the self-test failed on {newest}: {msg}")
    except Exception as e:
        _back_out(root, pm_dir, run, cur, bk, install)
        out["error"] = f"{type(e).__name__}: {e}"
        out["note"] = f"update to {newest} failed and was undone: back on {cur or 'the old code'}, the store restored from {bk.name}"
        return out
    _set_release(root, newest, cur, str(bk))
    out.update(updated=True, note=f"updated {cur or '(untagged)'} -> {newest}; the store was backed up first ({bk.name}); "
                                  "undo with pflab update --rollback")
    return out


def _back_out(root: Path, pm_dir: Path, run: Run, tag: str, backup: Path, install) -> None:
    """Put the old tag and the old store back after a failed update."""
    if tag:
        run(["git", "checkout", "--detach", tag], root)
        try:
            (install or (lambda p: default_install(p, run)))(root)
        except Exception:
            pass
    if backup.exists():
        shutil.copy2(backup, Path(pm_dir) / "ledger.duckdb")


def rollback(root: Path, pm_dir: Path, run: Run = run_cmd, install: Optional[Callable[[Path], None]] = None,
             now: Optional[datetime] = None) -> dict:
    root, pm_dir = Path(root), Path(pm_dir)
    r = _guard(root, pm_dir)
    app = r.get("app") or {}
    prev, bk = str(app.get("previous_tag", "")), str(app.get("backup", ""))
    if not prev:
        raise UpdateError("there is no earlier release to return to (previous_tag is empty)")
    now = now or datetime.now()
    kept = None
    live = pm_dir / "ledger.duckdb"
    if bk and Path(bk).exists() and live.exists():
        kept = Path(app.get("folder", root.parent)) / "backups" / f"ledger_before_rollback_{now:%Y%m%d_%H%M%S}.duckdb"
        kept.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live, kept)
    _git(run, root, "checkout", "--detach", prev)
    (install or (lambda p: default_install(p, run)))(root)
    if bk and Path(bk).exists():
        shutil.copy2(bk, live)
    cur = str(app.get("tag", ""))
    _set_release(root, prev, "", "")
    note = f"back on {prev}"
    if kept:
        note += (f"; the store is the backup from before the update; what was written since is kept in {kept.name} "
                 "(nothing was deleted)")
    return {"from": cur, "to": prev, "note": note, "kept": str(kept) if kept else None}
