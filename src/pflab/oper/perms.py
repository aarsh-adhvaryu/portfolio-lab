"""S87 O2/O4: what a session may do, enforced by the SDK's permission callback (not by words alone). Pure functions: `decide(kind, tool, input, root)` -> (allowed, reason).

kind "answer": the chat's operator. Writes only under <root>/notes and <root>/research; shell only from an allow-list (pflab read commands: NO script run, S91); reads inside the folder; no network. Model-written code runs only in the Docker sandbox (`agents/sandbox.py`, fail-closed), never as a shell command here.
kind "build":  a build session in the workshop checkout. Writes only under src/ and tests/ (and docs/s87*); shell: git (status, diff, log, add, commit, checkout -b fix/..., branch), the test run, the privacy
               grep; never push, merge, reset --hard, checkout of another branch, or touch main.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

WEB_TOOLS = ("WebSearch", "WebFetch")
# S91: a public search or page read must not carry his money: amounts, quantities, "my holdings", identity numbers. Company names and public questions are fine.
PRIVATE_WORDS = re.compile(r"(\b(my|our)\s+(holdings?|portfolio|shares?|positions?|account|demat|folio|pan|aadhaar|bank)\b|\bi\s+(hold|own|bought|sold|invested)\b|\b\d[\d,]*\s*(shares|units|qty|lakh|crore)\b|(₹|\brs\.?|\binr)\s?\d)", re.I)
PRIVATE_IDS = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b|\b\d{4}\s?\d{4}\s?\d{4}\b")           # a PAN, a 12-digit Aadhaar-shaped number


def web_ok(tool: str, inp: dict) -> Tuple[bool, str]:
    """The public-research tools, for an answer session only: https pages on the open web, never a local or private address, and nothing of his in the words."""
    from urllib.parse import urlparse
    import ipaddress
    text = " ".join(str(v) for v in (inp or {}).values())
    if PRIVATE_WORDS.search(text) or PRIVATE_IDS.search(text):
        return False, "a public search carries nothing of his: no amounts, quantities, holdings or identity numbers; ask it as a question about the company"
    if tool == "WebFetch":
        u = urlparse(str(inp.get("url") or ""))
        host = (u.hostname or "").lower()
        if u.scheme != "https" or not host or u.username or u.password:
            return False, "only plain https pages"
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, "no local or private addresses"
        except ValueError:
            if host in ("localhost",) or host.endswith((".local", ".internal", ".lan")) or "." not in host:
                return False, "no local or private addresses"
        if re.search(r"(token|secret|password|apikey|api_key|access_key)=", u.query, re.I):
            return False, "the address carries a secret"
    return True, ""


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
    if tool.startswith("mcp__oper__") or tool.startswith("mcp__nse") or tool.startswith("mcp__kite__") or tool in FREE_TOOLS:
        return True, ""
    if tool in WEB_TOOLS:
        return web_ok(tool, inp) if kind == "answer" else (False, f"{tool} is not allowed in a {kind} session")
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
            return False, "shell is limited to read-only pflab commands: a script is never run from an answer (python -I is not a filesystem boundary); the Lab tools and the sandbox tool run the maths"
        if kind == "build":
            if re.search(r"git (push|merge|reset|rebase|checkout (?!-b fix/)|switch (?!-c fix/)|branch -[dD]|clean|remote|config)", cmd):
                return False, "no push, merge, reset, rebase, other checkouts or branch deletion in a build"
            if BUILD_GIT.match(cmd):
                return True, ""
            if re.match(r"^(\.venv[\\/]Scripts[\\/])?python(\.exe)? -m (pytest|pflab\.hq\.security)\b", cmd):
                return True, ""
            return False, "shell is limited to git (no push/merge), pytest and the privacy grep"
    return False, f"{tool} is not allowed in this session"
