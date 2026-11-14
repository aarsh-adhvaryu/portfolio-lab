"""S87 O2: the operator's own folder, `<PFLAB_DATA_DIR>/operator/`: CLAUDE.md, .claude/skills, .claude/agents, settings, notes/ and research/. Separate from the workshop checkout."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from pflab.oper import texts

FM_END = "\n---\n"


def root(data_dir: Optional[str] = None) -> Path:
    d = data_dir or os.environ.get("PFLAB_DATA_DIR") or str(Path.home() / ".pflab" / "data")
    return Path(d) / "operator"


def _tagged(body: str) -> str:
    """The version tag goes after the front matter (a skill or agent file must begin with the front matter's dashes)."""
    if body.startswith("---"):
        head, _, rest = body[3:].partition(FM_END)
        return "---" + head + FM_END + texts.TAG + "\n" + rest
    return body


def _write_if_older(p: Path, content: str) -> None:
    if p.exists() and texts.TAG in p.read_text(encoding="utf-8", errors="ignore"):
        return                                                               # current version: leave it (an edit by hand is kept)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def ensure(data_dir: Optional[str] = None) -> Path:
    r = root(data_dir)
    for d in ("notes", "research", ".claude/skills", ".claude/agents"):
        (r / d).mkdir(parents=True, exist_ok=True)
    _write_if_older(r / "CLAUDE.md", texts.CLAUDE_MD)
    for name, body in texts.SKILLS.items():
        _write_if_older(r / ".claude" / "skills" / name / "SKILL.md", _tagged(body))
    for name, (desc, prompt) in texts.AGENTS.items():
        _write_if_older(r / ".claude" / "agents" / f"{name}.md", _tagged(f"---\nname: {name}\ndescription: {desc}\ntools: Read, Grep, Glob\nmodel: sonnet\n---\n{prompt}\n"))
    sp = r / ".claude" / "settings.json"
    if not sp.exists():
        sp.write_text(json.dumps(texts.SETTINGS, indent=2), encoding="utf-8")
    return r
