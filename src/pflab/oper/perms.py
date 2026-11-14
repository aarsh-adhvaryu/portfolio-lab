"""S87 O2/O4: what a session may do, enforced by the SDK's permission callback (not by words alone). Pure functions: `decide(kind, tool, input, root)` -> (allowed, reason).

kind "answer": the chat's operator. Writes only under <root>/notes and <root>/research; shell only from an allow-list (pflab read commands, `python -I research/<script>.py`); reads inside the folder; no network.
kind "build":  a build session in the workshop checkout. Writes only under src/ and tests/ (and docs/s87*); shell: git (status, diff, log, add, commit, checkout -b fix/..., branch), the test run, the privacy
               grep; never push, merge, reset --hard, checkout of another branch, or touch main.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

META = re.compile(r"[;&|<>`$\n\r]|\$\(")
PFLAB_READ = ("pm networth", "pm guards", "pm alerts", "pm propose", "pm advise", "pm simulate", "pm fd show", "list", "kg", "learner status", "service status", "alarm status", "problems", "conductor",
              "hq", "us", "engine list", "ask")
READ_TOOLS = ("Read", "Glob", "Grep")
FREE_TOOLS = ("Skill", "Agent", "Task", "TodoWrite")
BUILD_GIT = re.compile(r"^git (status|diff|log|add|commit|branch|show|stash list|rev-parse|checkout -b fix/[A-Za-z0-9._/-]+|switch -c fix/[A-Za-z0-9._/-]+)\b")


def _inside(p: Path, base: Path) -> bool:
    try:
        p.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _path(inp: dict, root: Path) -> Optional[Path]:
    raw = inp.get("file_path") or inp.get("path") or inp.get("notebook_path")
    if raw is None:
        return None
    p = Path(str(raw))
    return p if p.is_absolute() else root / p


def decide(kind: str, tool: str, inp: dict, root: Path, branch: Optional[str] = None) -> Tuple[bool, str]:
    root = Path(root)
    inp = inp or {}
    if tool.startswith("mcp__oper__") or tool.startswith("mcp__nse__") or tool in FREE_TOOLS:
        return True, ""
    if tool in READ_TOOLS:
        p = _path(inp, root)
        if p is None:
            return True, ""                                                  # Glob / Grep without a path run in the folder
        return (True, "") if _inside(p, root) else (False, "reads stay inside the workspace folder")
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        p = _path(inp, root)
        if p is None:
            return False, "no path"
        if kind == "answer":
            ok = _inside(p, root / "notes") or _inside(p, root / "research")
            return (True, "") if ok else (False, "in an answer, files may be written only under notes/ and research/")
        if kind == "build":
            if branch is not None and not branch.startswith("fix/"):
                return False, "edits only on a fix/ branch"
            ok = _inside(p, root / "src") or _inside(p, root / "tests") or any(_inside(p, root / "docs" / n) for n in ("s87_build_notes",))
            return (True, "") if ok else (False, "a build may change only src/ and tests/ on its branch")
    if tool == "Bash":
        cmd = str(inp.get("command") or "").strip()
        if META.search(cmd):
            return False, "no pipes, chains, redirects or substitutions"
        if kind == "answer":
            if cmd.startswith("pflab ") and any(cmd[6:].startswith(c) for c in PFLAB_READ) and " --live" not in cmd and " --paid" not in cmd:
                return True, ""
            m = re.match(r"^python(?:\.exe)? -I (research/[A-Za-z0-9_./-]+\.py)(?: [A-Za-z0-9_./=-]+)*$", cmd)
            if m and ".." not in m.group(1):
                return True, ""
            return False, "shell is limited to read-only pflab commands and python -I on research/ scripts"
        if kind == "build":
            if re.search(r"git (push|merge|reset|rebase|checkout (?!-b fix/)|switch (?!-c fix/)|branch -[dD]|clean|remote|config)", cmd):
                return False, "no push, merge, reset, rebase, other checkouts or branch deletion in a build"
            if BUILD_GIT.match(cmd):
                return True, ""
            if re.match(r"^(\.venv[\\/]Scripts[\\/])?python(\.exe)? -m (pytest|pflab\.hq\.security)\b", cmd):
                return True, ""
            return False, "shell is limited to git (no push/merge), pytest and the privacy grep"
    return False, f"{tool} is not allowed in this session"
