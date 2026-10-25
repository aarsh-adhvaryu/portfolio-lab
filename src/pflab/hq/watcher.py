"""The drive watcher (S59; the investor 2026-10-24: a local folder for now, Google Drive later).

Files placed in the drop folder (`D:\\portfolio_lab\\drop`, or PFLAB_DROP_DIR) reach the inbox by themselves: each file is
taken once it has stopped changing (its size and time the same for SETTLE_S seconds), handed to the inbox exactly as a
dropped file (`app.inbox.receive`: the same routes, checks and "your OK" before anything enters the ledger), and moved
to `drop\\taken` so it is not taken twice. Sub-folders, hidden files and partial downloads are left alone. A Google
Drive desktop folder works the same way once its path is set.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Dict, List

SETTLE_S = 10.0
SKIP_SUFFIX = (".crdownload", ".part", ".tmp", ".partial", ".download")
MAX_BYTES = 50 * 2**20                                   # the inbox's own upload limit


def folder(repo: Path) -> Path:
    return Path(os.environ.get("PFLAB_DROP_DIR") or (Path(repo) / "drop"))


def _ready(p: Path, now_s: float) -> bool:
    n = p.name.lower()
    if n.startswith((".", "~$")) or n.endswith(SKIP_SUFFIX) or n == "desktop.ini":
        return False
    try:
        st = p.stat()
    except OSError:
        return False
    return now_s - st.st_mtime >= SETTLE_S


def _taken_path(d: Path, name: str) -> Path:
    t = d / "taken" / name
    k = 1
    while t.exists():
        t = d / "taken" / f"{Path(name).stem}-{k}{Path(name).suffix}"
        k += 1
    return t


def scan(rt, now_s: float = None) -> List[Dict]:
    """Take every settled file in the drop folder into the inbox. Returns what was taken (name, item id or why not)."""
    from pflab.app import inbox as ib
    d = folder(rt.repo)
    if not d.exists():
        d.mkdir(parents=True, exist_ok=True)
        (d / "taken").mkdir(exist_ok=True)
        return []
    now_s = time.time() if now_s is None else now_s
    out = []
    for p in sorted(x for x in d.iterdir() if x.is_file()):
        if not _ready(p, now_s):
            continue
        if p.stat().st_size > MAX_BYTES:
            out.append({"name": p.name, "skipped": f"over {MAX_BYTES // 2**20} MB"})
            continue
        try:
            r = ib.receive(rt, p.name, p.read_bytes())
        except ValueError as e:                            # e.g. a bank statement needs its account: left in place
            out.append({"name": p.name, "skipped": str(e)})
            continue
        if not getattr(rt, "attended", True):              # the tick ends with the job: let the inbox finish its work
            for t in threading.enumerate():
                if t.name == f"inbox-{r['id']}":
                    t.join(600)
        t = _taken_path(d, p.name)
        t.parent.mkdir(parents=True, exist_ok=True)
        p.replace(t)
        out.append({"name": p.name, "item": r["id"], "duplicate": r.get("duplicate", False)})
    if out:
        rt.bump("inbox", "hq")
    return out


def announce(rt, taken: List[Dict]) -> None:
    """One message for what the watcher took (the messenger delivers it)."""
    from pflab.hq import messenger
    new = [t for t in taken if t.get("item") and not t.get("duplicate")]
    if not new:
        return
    names = ", ".join(t["name"] for t in new[:6]) + (f" and {len(new) - 6} more" if len(new) > 6 else "")
    messenger.send_now(rt, f"Took {len(new)} file(s) from the drop folder into the inbox: {names}. "
                           "Ledger files wait for your OK on the Inbox screen.", "inbox",
                       dedup_key="drop:" + ",".join(str(t["item"]) for t in new))
