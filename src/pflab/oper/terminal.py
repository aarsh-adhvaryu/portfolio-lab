"""S87 icon: "Open the operator in Claude Code": a terminal Claude Code session in the operator's folder (its CLAUDE.md, skills and subagents load by themselves), on his plan, with no API key in its environment."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from pflab.llm import claude_plan as cp
from pflab.oper import workspace


def command(data_dir: Optional[str] = None) -> dict:
    ws = workspace.ensure(data_dir)
    env = {k: v for k, v in os.environ.items() if k not in cp.child_env()}
    return {"cwd": str(ws), "argv": [cp.cli_path()], "env": env}


def open_terminal(data_dir: Optional[str] = None, popen=subprocess.Popen) -> dict:
    s = cp.signin()
    if not s["ok"]:
        return {"ok": False, "detail": s["detail"]}
    c = command(data_dir)
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    popen(c["argv"], cwd=c["cwd"], env=c["env"], creationflags=flags)
    return {"ok": True, "cwd": c["cwd"]}
