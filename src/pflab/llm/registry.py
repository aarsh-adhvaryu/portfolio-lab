"""Model picks, prompt registry and the `llm_runs` log (PLAN S21).

* A pick (role -> model) is registered in `configs/llm_models.toml` with a timestamp BEFORE it is
  evaluated; `require_registered` refuses an evaluation run that has no earlier registration.
* A prompt is identified by the SHA-256 of its exact text; the SHA goes into every run record, so a
  changed prompt is a different prompt.
* Every model call is logged in `llm_runs` with the model's digest (from Ollama), prompt SHA, the
  documents it read, the guard's verdict, token counts and seconds.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from pflab import _toml

PICKS_PATH = Path(__file__).resolve().parents[3] / "configs" / "llm_models.toml"


class NotRegistered(RuntimeError):
    pass


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PromptRegistry:
    """name -> exact text; `register` returns the SHA and refuses to silently change a name's text."""

    def __init__(self):
        self._p: Dict[str, str] = {}

    def register(self, name: str, text: str) -> str:
        if name in self._p and self._p[name] != text:
            raise ValueError(f"prompt {name!r} already registered with different text: use a new name (version it)")
        self._p[name] = text
        return sha(text)

    def get(self, name: str) -> str:
        return self._p[name]

    def sha_of(self, name: str) -> str:
        return sha(self._p[name])


def load_picks(path: Path = PICKS_PATH) -> List[dict]:
    return _toml.load(path).get("pick", [])


def pick_for(role: str, path: Path = PICKS_PATH) -> Optional[dict]:
    """The latest registered pick for a role."""
    ps = [p for p in load_picks(path) if p["role"] == role]
    return max(ps, key=lambda p: p["registered_at"]) if ps else None


def require_registered(role: str, model: str, run_at: datetime, path: Path = PICKS_PATH) -> dict:
    """The registered pick for (role, model), provided it was registered before `run_at`; else raise."""
    for p in load_picks(path):
        if p["role"] == role and p["model"] == model:
            if p["registered_at"] < run_at:
                return p
            raise NotRegistered(f"{role}/{model} was registered at {p['registered_at']}, not before this run at {run_at}")
    raise NotRegistered(f"no registered pick for role {role!r} with model {model!r}: register it in "
                        "configs/llm_models.toml (with its protocol) BEFORE evaluating it")


def chosen(use: str, path: Path = PICKS_PATH) -> Optional[str]:
    """The model the S42 evaluation chose for `use` ('general' or 'routing'): a pick whose decision reads
    'chosen ...' naming that use. None before any decision (the agents then run facts-only)."""
    ps = [p for p in load_picks(path)
          if str(p.get("decision", "")).startswith("chosen") and use in str(p.get("decision", ""))]
    return max(ps, key=lambda p: str(p.get("evaluated_at", "")))["model"] if ps else None


def record_decision(role: str, model: str, decision: str, when: datetime, path: Path = PICKS_PATH) -> bool:
    """Fill `evaluated_at` and `decision` of the pick (role, model) in place; every other line is untouched."""
    text = path.read_text(encoding="utf-8")
    blocks = text.split("[[pick]]")
    for i, b in enumerate(blocks[1:], start=1):
        if f'role = "{role}"' in b and f'model = "{model}"' in b:
            b = b.replace('evaluated_at = ""', f"evaluated_at = {when.replace(microsecond=0).isoformat()}", 1)
            b = b.replace('decision = ""', f'decision = "{decision}"', 1)
            blocks[i] = b
            path.write_text("[[pick]]".join(blocks), encoding="utf-8")
            return True
    return False


def log_run(con, started_at: datetime, model: str, *, role: Optional[str] = None, model_digest: Optional[str] = None,
            prompt_name: Optional[str] = None, prompt_sha: Optional[str] = None, sources: Optional[List[str]] = None,
            guard_result: Optional[str] = None, attempts: int = 1, tokens_in: int = 0, tokens_out: int = 0,
            seconds: float = 0.0, status: str = "ok", note: str = "") -> int:
    from pflab.pm.store import next_id
    rid = next_id(con, "llm_runs", "run_id")
    con.execute("INSERT INTO llm_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [rid, started_at, role, model, model_digest, prompt_name, prompt_sha, json.dumps(sources or []),
                 guard_result, attempts, tokens_in, tokens_out, seconds, status, note])
    return rid
