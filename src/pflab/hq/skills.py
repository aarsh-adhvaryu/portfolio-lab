"""Skills for the paper team (S77; his word 2026-11-02: "it is Claude, so use skill.md files").

A skill is a folder `src/pflab/skills/<name>/SKILL.md` with frontmatter (`name`, `description`) and a body, in the format of tradermonty/claude-trading-skills (MIT; each file
says it was adapted from it). They are METHOD, adapted to NSE and rupees; numbers stay with code. `for_role` picks the skills a role needs, and `block` joins them into
ONE extra system block that `workers.converse` caches after the role's own instructions: a skill costs its tokens once per conversation, then a tenth.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

DIR = Path(__file__).resolve().parents[1] / "skills"
FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.S)
# which skills each paper-mission role reads (the coordinator plans and writes the digest, research gathers evidence, the quant decides, the reviewer judges)
BY_ROLE: Dict[str, List[str]] = {
    "coordinator": ["weekly-performance-digest", "trade-memory-postmortem", "exposure-posture"],
    "research": ["pre-trade-gate", "exposure-posture"],
    "quant": ["position-sizing", "pre-trade-gate", "drawdown-circuit-breaker", "exposure-posture", "trade-memory-postmortem"],
    "review": ["pre-trade-gate", "drawdown-circuit-breaker", "trade-memory-postmortem"],
}


def load(name: str, base: Optional[Path] = None) -> Optional[dict]:
    p = (base or DIR) / name / "SKILL.md"
    try:
        m = FRONT.match(p.read_text(encoding="utf-8").replace("\r\n", "\n"))
    except OSError:
        return None
    if not m:
        return None
    meta = {k.strip(): v.strip() for k, _, v in (ln.partition(":") for ln in m.group(1).splitlines() if ":" in ln)}
    if meta.get("name") != name or not meta.get("description"):
        return None
    return {"name": name, "description": meta["description"], "body": m.group(2).strip()}


def all_skills(base: Optional[Path] = None) -> List[dict]:
    root = base or DIR
    out = []
    for d in sorted(root.iterdir()) if root.exists() else []:
        s = load(d.name, root) if d.is_dir() else None
        if s:
            out.append(s)
    return out


def for_role(role: str, base: Optional[Path] = None) -> List[dict]:
    return [s for s in (load(n, base) for n in BY_ROLE.get(role, [])) if s]


def block(role: str, base: Optional[Path] = None) -> str:
    """The text of the role's skills for the system prompt ('' when there are none)."""
    ss = for_role(role, base)
    if not ss:
        return ""
    return ("SKILLS (method for this work; the numbers are code's, never yours):\n\n" + "\n\n---\n\n".join(f"## Skill: {s['name']}\n{s['description']}\n\n{s['body']}" for s in ss))
