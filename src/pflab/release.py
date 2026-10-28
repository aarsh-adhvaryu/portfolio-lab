r"""The app and the workshop (S65, docs/PLAN.md section 3).

The APP is an install of a release tag in its own folder; it carries a `release.toml` at the root of its clone (written by
`tools/install_app.ps1`, never in git):

    [app]
    channel = "stable"
    tag = "v2026.10.28"            # the checked-out release
    previous_tag = ""              # what `pflab update --rollback` returns to
    folder = 'D:\PortfolioLabApp'  # the app's own folder: clone, data, pm, backups
    [paths]
    data = 'D:\PortfolioLabApp\data'
    pm = 'D:\PortfolioLabApp\pm'

The WORKSHOP is a checkout without `release.toml` (the developer's beta). Its channel is `beta` unless `PFLAB_CHANNEL` says
otherwise (the test suite sets `stable`). When `release.toml` exists it WINS over the environment: `apply()` (run when `pflab` is
imported) sets `PFLAB_DATA_DIR`, `PFLAB_PM_DIR` and `PFLAB_CHANNEL` from it, so an app never depends on a user-level variable
that may still point at the workshop.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
FILE = "release.toml"
CHANNELS = ("stable", "beta")


def path(root: Optional[Path] = None) -> Path:
    return Path(root or ROOT) / FILE


def load(root: Optional[Path] = None) -> Optional[dict]:
    """The release file as a dict, or None in the workshop."""
    p = path(root)
    if not p.exists():
        return None
    from pflab import _toml
    return _toml.load(p)


def channel(root: Optional[Path] = None) -> str:
    """release.toml's channel; else PFLAB_CHANNEL when valid; else `beta` (a checkout with no release file is the workshop)."""
    r = load(root)
    if r is not None:
        c = str((r.get("app") or {}).get("channel", "stable")).lower()
        return c if c in CHANNELS else "stable"
    e = os.environ.get("PFLAB_CHANNEL", "").strip().lower()
    return e if e in CHANNELS else "beta"


def is_app(root: Optional[Path] = None) -> bool:
    return path(root).exists()


def apply(root: Optional[Path] = None) -> bool:
    """Set the environment from release.toml (it overrides what is there). Returns True when a release file was applied."""
    r = load(root)
    if r is None:
        return False
    paths = r.get("paths") or {}
    if paths.get("data"):
        os.environ["PFLAB_DATA_DIR"] = str(paths["data"])
    if paths.get("pm"):
        os.environ["PFLAB_PM_DIR"] = str(paths["pm"])
    os.environ["PFLAB_CHANNEL"] = channel(root)
    return True


def write(root: Path, folder: Path, tag: str, previous_tag: str = "", channel_: str = "stable") -> Path:
    """Write the release file for an app folder: the clone at `root`, data and pm beside it under `folder`."""
    from datetime import date
    if channel_ not in CHANNELS:
        raise ValueError(f"channel is one of {CHANNELS}")
    q = lambda p: "'" + str(p) + "'"                          # noqa: E731  (TOML literal strings: backslashes stay as they are)
    text = ("# Written by tools/install_app.ps1 and `pflab update`; not in git. Overrides the environment (src/pflab/release.py).\n"
            f"[app]\nchannel = \"{channel_}\"\ntag = \"{tag}\"\nprevious_tag = \"{previous_tag}\"\nfolder = {q(folder)}\ninstalled_on = {date.today().isoformat()}\n\n"
            f"[paths]\ndata = {q(Path(folder) / 'data')}\npm = {q(Path(folder) / 'pm')}\n")
    p = path(root)
    p.write_text(text, encoding="utf-8")
    return p


def main(argv=None) -> int:
    """`python -m pflab.release write --root R --folder F --tag T`: what tools/install_app.ps1 calls to write release.toml."""
    import argparse
    ap = argparse.ArgumentParser(prog="pflab.release")
    ap.add_argument("action", choices=["write", "show"])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--folder")
    ap.add_argument("--tag", default="")
    ap.add_argument("--previous", default="")
    ap.add_argument("--channel", default="stable", choices=CHANNELS)
    a = ap.parse_args(argv)
    if a.action == "show":
        print(load(Path(a.root)) or "no release.toml: this is the workshop (beta)")
        return 0
    if not a.folder:
        ap.error("--folder is required")
    print(f"wrote {write(Path(a.root), Path(a.folder), a.tag, a.previous, a.channel)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
