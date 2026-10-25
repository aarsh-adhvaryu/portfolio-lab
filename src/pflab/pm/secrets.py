r"""Secrets loader (PLAN §2). Keys, tokens and CAS passwords live in
`%USERPROFILE%\.pflab\secrets.toml`, outside the repo and OneDrive.

Values are never printed: `repr`/`str` of `Secrets` list names only, and
`redact` scrubs known values out of any text before it is logged.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from pflab import _toml

MASK = "***"


class SecretsError(RuntimeError):
    pass


def default_path() -> Path:
    env = os.environ.get("PFLAB_SECRETS_FILE")
    return Path(env) if env else Path.home() / ".pflab" / "secrets.toml"


def _unsafe_location(p: Path) -> Optional[str]:
    p = p.resolve()
    if any("onedrive" in part.lower() for part in p.parts):
        return "inside OneDrive"
    for d in [p.parent, *p.parent.parents]:
        if (d / ".git").exists():
            return f"inside a git repo ({d})"
    return None


class Secrets:
    def __init__(self, data: dict):
        self._data = data

    def get(self, section: str, key: str) -> str:
        try:
            v = self._data[section][key]
        except KeyError:
            raise SecretsError(f"secret [{section}] {key} is not set") from None
        return str(v)

    def has(self, section: str, key: str) -> bool:
        return key in self._data.get(section, {})

    def names(self) -> list:
        return sorted(f"{s}.{k}" for s, d in self._data.items()
                      if isinstance(d, dict) for k in d)

    def _values(self) -> list:
        return [str(v) for d in self._data.values() if isinstance(d, dict)
                for v in d.values() if str(v)]

    def redact(self, text: Any) -> str:
        out = str(text)
        for v in sorted(self._values(), key=len, reverse=True):
            out = out.replace(v, MASK)
        return out

    def __repr__(self) -> str:
        return f"Secrets({', '.join(self.names())})"

    __str__ = __repr__


def load(path: Optional[Path] = None) -> Secrets:
    p = Path(path) if path else default_path()
    if not p.exists():
        raise SecretsError(f"no secrets file at {p}")
    bad = _unsafe_location(p)
    if bad:
        raise SecretsError(f"secrets file {p} is {bad}; move it")
    return Secrets(_toml.load(p))
