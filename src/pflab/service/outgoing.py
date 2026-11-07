"""A drop folder for messages to him (S79b): a text file written to `<pm>/outgoing/*.txt` is queued on Telegram by the running app (job `outgoing`), once, then renamed `.queued`.

Why: the workshop sends nothing outward and the app holds its store, so a development session leaves its report as a file; the app, which owns the Telegram credentials and the
outbox, sends it. The file name is the dedup key; the first line may be `kind: summary|reminder|reply` (default `summary`, a direct kind that goes out at once).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List


def drain(con, pm_dir: Path, now: datetime) -> List[str]:
    from pflab.service import telegram as tgm
    d = Path(pm_dir) / "outgoing"
    if not d.is_dir():
        return []
    done = []
    for f in sorted(d.glob("*.txt")):
        try:
            text = f.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        kind = "summary"
        if text.lower().startswith("kind:"):
            head, _, text = text.partition("\n")
            k = head.split(":", 1)[1].strip().lower()
            kind = k if k in ("summary", "reminder", "reply") else "summary"
        if not text:
            f.rename(f.with_suffix(".empty"))
            continue
        tgm.enqueue(con, text, kind, dedup_key=f"outgoing:{f.name}", now=now)
        f.rename(f.with_suffix(".queued"))
        done.append(f.name)
    return done
