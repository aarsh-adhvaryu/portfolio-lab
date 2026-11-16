"""What the app can still reach (S94, for the cut in `docs/BUDDY_CUT.md`). Code only, reads source files, runs in seconds, changes nothing.

A module is REACHABLE when a root imports it, directly or through other reachable modules. Imports inside functions count, and so does a module named in a string
("pflab.x.y", the way cards, plug-ins and `-m` calls name code). Some code is loaded by NAME at run time; that is declared in LOADS below, not guessed: when the loader
is reachable, everything under its prefixes is too. If you add or remove such a loader, change LOADS in the same commit.

    python tools/reach.py                    the modules nothing reaches, with their lines (candidates to delete)
    python tools/reach.py --paths            the same as file paths, one a line (to pipe into `git rm`)
    python tools/reach.py --why pflab.x.y    who imports a module (reachable importers first): what keeps it alive
    python tools/reach.py --tests            test and tool files that import a module nothing reaches: "only" (delete the file) or "mixed" (cut those tests out)
    python tools/reach.py --seams A B ...    every import of the packages A, B, ... (for example core paper ledger) from OUTSIDE those packages: the seams to cut first
    python tools/reach.py --root M ...       use these roots instead of the default ones

Limits, stated: this follows imports, not calls. A function nobody calls inside a reachable module is not found here, and a module reached only through a
command of `cli.py` counts as reachable until that command is deleted. So the order is always: delete the entry point (job, route, tool, command, screen) first, then run this.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ROOTS = ["pflab.cli", "pflab.app.launcher", "pflab.app.server", "pflab.app.worker", "pflab.service.tasks"]
# loader module -> prefixes of the modules it loads by name at run time (or runs by file path in the sandbox)
LOADS: Dict[str, List[str]] = {
    "pflab.service.tasks": ["pflab.service.tasks_s79_", "pflab.service.tasks_s91_"],
    "pflab.pm.mig_s79": ["pflab.pm.mig_s79."],
    "pflab.hq.tools_s79": ["pflab.hq.tools_s79."],
    "pflab.think.wire": ["pflab.think."],
    "pflab.think.session": ["pflab.think."],
    "pflab.think.desk": ["pflab.think."],
    "pflab.app.inbox": ["pflab.ingest.bank", "pflab.ingest.bank_labels", "pflab.ingest.contract_note", "pflab.ingest.tradebook", "pflab.ingest.zerodha_ledger", "pflab.ingest.cas",
                        "pflab.ingest.fd_summary", "pflab.ingest.sniff"],
    "pflab.agents.sandbox": ["pflab.agents.workshop_runner"],
    "pflab.agents.workshop": ["pflab.agents.workshop_runner"],
    "pflab.lab.runner": ["pflab.lab.lab_runner", "pflab.lab.policies."],
    "pflab.lab.c4_study": ["pflab.lab.c4_replay"],
}
NAME = re.compile(r"pflab(?:\.\w+)+")


def modules(src: Path = SRC) -> Dict[str, Path]:
    out = {}
    for p in sorted((src / "pflab").rglob("*.py")):
        rel = p.relative_to(src).with_suffix("")
        name = ".".join(rel.parts)
        out[name[:-9] if name.endswith(".__init__") else name] = p
    return out


def _resolve(name: str, mods: Dict[str, Path]):
    while name:
        if name in mods:
            return name
        if "." not in name:
            return None
        name = name.rsplit(".", 1)[0]
    return None


def imports_of(path: Path, modname: str, mods: Dict[str, Path], top: str = "pflab") -> Set[str]:
    """The modules a file names: `import`, `from ... import` (relative ones too) at any depth, and dotted names inside strings."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    pkg = modname if path.name == "__init__.py" else modname.rsplit(".", 1)[0]
    raw: Set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            raw.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            if n.level:
                base = pkg.split(".")
                base = base[:len(base) - (n.level - 1)]
                b = ".".join(base + ([n.module] if n.module else []))
            else:
                b = n.module or ""
            raw.add(b)
            raw.update(f"{b}.{a.name}" for a in n.names)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and f"{top}." in n.value:
            raw.update(NAME.findall(n.value))
    return {r for r in (_resolve(x, mods) for x in raw) if r} - {modname}


def graph(mods: Dict[str, Path]) -> Dict[str, Set[str]]:
    return {m: imports_of(p, m, mods) for m, p in mods.items()}


def reachable(mods: Dict[str, Path], edges: Dict[str, Set[str]], roots: List[str], loads: Dict[str, List[str]] = LOADS) -> Set[str]:
    seen: Set[str] = set()
    stack = [r for r in roots if r in mods]
    while stack:
        m = stack.pop()
        if m in seen:
            continue
        seen.add(m)
        stack.extend(edges.get(m, ()))
        parent = m
        while "." in parent:                                       # importing a.b.c runs a/__init__ and a/b/__init__
            parent = parent.rsplit(".", 1)[0]
            if parent in mods:
                stack.append(parent)
        for pre in loads.get(m, ()):
            stack.extend(x for x in mods if x.startswith(pre) or x == pre.rstrip("."))
    return seen


def _lines(p: Path) -> int:
    return sum(1 for _ in p.open(encoding="utf-8", errors="ignore"))


def outside_users(folder: Path, mods: Dict[str, Path]) -> Dict[Path, Set[str]]:
    """test or tool file -> the pflab modules it imports."""
    out = {}
    for p in sorted(folder.rglob("*.py")):
        got = imports_of(p, "x.y", mods)
        if got:
            out[p] = got
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="what the app can still reach")
    ap.add_argument("--paths", action="store_true")
    ap.add_argument("--why")
    ap.add_argument("--tests", action="store_true")
    ap.add_argument("--seams", nargs="+")
    ap.add_argument("--root", nargs="+")
    a = ap.parse_args(argv)
    mods = modules()
    edges = graph(mods)
    live = reachable(mods, edges, a.root or ROOTS)
    dead = sorted(set(mods) - live)
    if a.why:
        users = sorted(m for m, ts in edges.items() if a.why in ts)
        loaders = [k for k, v in LOADS.items() if any(a.why.startswith(p) or a.why == p.rstrip(".") for p in v)]
        print(f"{a.why}: {'REACHABLE' if a.why in live else 'not reachable'}; imported by {len(users)} module(s)")
        for u in sorted(users, key=lambda u: (u not in live, u)):
            print(f"  {'live' if u in live else 'dead'}  {u}")
        for k in loaders:
            print(f"  loaded by name from {k} ({'live' if k in live else 'dead'})")
        return 0
    if a.seams:
        pk = tuple(f"pflab.{s}" for s in a.seams)
        inside = lambda m: any(m == p or m.startswith(p + ".") for p in pk)   # noqa: E731
        rows = defaultdict(set)
        for m, ts in edges.items():
            if inside(m) or m not in live:
                continue
            for t in ts:
                if inside(t) and t not in pk:
                    rows[m].add(t)
        n = sum(len(v) for v in rows.values())
        print(f"{n} import(s) of {', '.join(a.seams)} from {len(rows)} reachable module(s) outside:")
        for m in sorted(rows):
            print(f"  {m.replace('pflab.', ''):34s} <- {', '.join(sorted(t.replace('pflab.', '') for t in rows[m]))}")
        return 0
    if a.tests:
        gone = set(dead)
        for folder in (ROOT / "tests", ROOT / "tools"):
            for p, got in outside_users(folder, mods).items():
                hit = sorted(got & gone)
                if hit:
                    kind = "only " if not (got - gone) else "mixed"
                    print(f"{kind} {p.relative_to(ROOT).as_posix():46s} {', '.join(h.replace('pflab.', '') for h in hit[:6])}{' ...' if len(hit) > 6 else ''}")
        return 0
    if a.paths:
        for m in dead:
            print(mods[m].relative_to(ROOT).as_posix())
        return 0
    total = 0
    for m in dead:
        n = _lines(mods[m])
        total += n
        print(f"{n:6d}  {m}")
    print(f"{len(dead)} module(s) nothing reaches, {total} lines; {len(live)} of {len(mods)} reachable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
