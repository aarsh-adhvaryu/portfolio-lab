"""Verify an experiment is locked and its locked span has not moved.

    python tools/check_lock.py E1d            # exit 0 if sound
    python tools/check_lock.py --all

`run_locked.ps1` calls this before it will run anything. A sweep computed
from a charter that moved after its lock is not evidence about that
charter, and nothing downstream can detect it afterwards -- the numbers
look exactly the same.

The registry below is the record. Each entry is the span the charter froze
and the hash it froze at, copied from that experiment's readiness note. A
charter with no entry cannot be run by `run_locked.ps1`, which is the
intended failure: an experiment nobody recorded a hash for is an
experiment nobody locked.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

# experiment -> (charter path, first section, stop section, chars, sha256)
REGISTRY = {
    "E1":   ("docs/strategies/E1.md",   2, 14, 9861,
             "f33713822fc109e557cdb46d4b825b9943eee378709e8f1a86437d4d6639be65"),
    "E1b":  ("docs/strategies/E1b.md",  3, 8, 2956,
             "786594f2811d9499277ff591fd8202fb3fc9f54f2b9dc8d3d1e45975a1d67d24"),
    "E1-P": ("docs/strategies/E1-P.md", 3, 8, 2255,
             "bbf90dc8a7b6ebdc6784f18fa9364e71565218f1867fa55d1c2782c643230143"),
    "E1c":  ("docs/strategies/E1c.md",  3, 8, 3588,
             "10c6f6eee677a16c7dad299cc353ec4f864b9a56e913e040ebca24114de96c10"),
    "E1d":  ("docs/strategies/E1d.md",  3, 8, 2727,
             "5ba0b73d830f7118b00124574a93b1eb8337287c15b2d308dfbb08c13666274e"),
    "E2-A": ("docs/strategies/E2-A.md", 3, 9, 5819,
             "f2972309a9793cd53c07551e19408112fef56543baf90b43aa4708e1541bf0b9"),
    "E3-R": ("docs/strategies/E3-R.md", 3, 8, 2757,
             "e1cf6470d35aa6f5f1cabc4eceafb0232dbac9f6f9295547b39e53942c9599df"),
    # A0 (2026-09-29); each family gets its own entry at its lock, over the
    # same span (a family changes only columns, read with E5-A §14)
    "E5-A": ("docs/strategies/E5-A.md", 2, 14, 13096,
             "9455930e65a2edce0d40d1cdebf65b0a1a434a0662d366c57652c2640cb2ec5f"),
    "E5-A-A1": ("docs/strategies/E5-A.md", 2, 14, 13096,
                "9455930e65a2edce0d40d1cdebf65b0a1a434a0662d366c57652c2640cb2ec5f"),
    "E5-A-A3": ("docs/strategies/E5-A.md", 2, 14, 13096,
                "9455930e65a2edce0d40d1cdebf65b0a1a434a0662d366c57652c2640cb2ec5f"),
    "E5-A-A2": ("docs/strategies/E5-A.md", 2, 14, 13096,
                "9455930e65a2edce0d40d1cdebf65b0a1a434a0662d366c57652c2640cb2ec5f"),
    "E5-A-ALL": ("docs/strategies/E5-A.md", 2, 14, 13096,
                 "9455930e65a2edce0d40d1cdebf65b0a1a434a0662d366c57652c2640cb2ec5f"),
    "E5-A-A5": ("docs/strategies/E5-A.md", 2, 14, 13096,
                "9455930e65a2edce0d40d1cdebf65b0a1a434a0662d366c57652c2640cb2ec5f"),
}


def span(text: str, first: int, stop: int) -> str | None:
    """The locked span, by the one extractor every charter is measured with:
    from `## <first>.` up to but not including `## <stop>.`, trailing
    whitespace stripped and one newline restored."""
    m1 = re.search(rf"^## {first}\.", text, re.M)
    m2 = re.search(rf"^## {stop}\.", text, re.M)
    if not m1 or not m2:
        return None
    return text[m1.start():m2.start()].rstrip() + "\n"


def check_span(experiment: str, root: Path | None = None) -> tuple[bool, str]:
    if experiment not in REGISTRY:
        return False, (f"{experiment} has no entry in check_lock.REGISTRY -- "
                       f"an experiment nobody recorded a hash for is an "
                       f"experiment nobody locked")
    rel, first, stop, want_chars, want_hash = REGISTRY[experiment]
    p = (root or Path(".")) / rel
    if not p.exists():
        return False, f"{p} not found"
    s = span(p.read_text(encoding="utf-8"), first, stop)
    if s is None:
        return False, f"{rel}: could not find sections {first}..{stop}"
    got = hashlib.sha256(s.encode("utf-8")).hexdigest()
    if got != want_hash:
        return False, (f"{experiment} §{first}-§{stop - 1} MOVED since its "
                       f"lock: {len(s)} chars / {got[:16]}... expected "
                       f"{want_chars} / {want_hash[:16]}...")
    return True, f"{experiment} §{first}-§{stop - 1} unchanged ({len(s)} chars, {got[:16]}...)"


def check_tag(experiment: str) -> tuple[bool, str]:
    tag = f"lock/{experiment}"
    try:
        out = subprocess.run(["git", "tag", "--list", tag],
                             capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception as e:
        return False, f"git tag failed: {e!r}"
    if out != tag:
        return False, f"tag {tag} does not exist -- lock the experiment first"
    sha = subprocess.run(["git", "rev-list", "-n", "1", tag],
                         capture_output=True, text=True).stdout.strip()
    return True, f"{tag} -> {sha[:12]}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--skip-tag", action="store_true",
                    help="verify the span only (used by the end-to-end test)")
    a = ap.parse_args(argv)

    names = sorted(REGISTRY) if a.all else ([a.experiment] if a.experiment else [])
    if not names:
        ap.error("name an experiment or pass --all")
    bad = 0
    for n in names:
        ok, msg = check_span(n)
        print(("  OK   " if ok else "  FAIL ") + msg)
        bad += (not ok)
        if not a.skip_tag and not a.all:
            ok2, msg2 = check_tag(n)
            print(("  OK   " if ok2 else "  FAIL ") + msg2)
            bad += (not ok2)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
