r"""Setting the secrets file up by command or form (S65, S64 Phase 7 item 1): `pflab setup secrets`.

Writes `%USERPROFILE%\.pflab\secrets.toml` (never inside the repo or OneDrive: `secrets._unsafe_location` refuses) from values
typed through `getpass` (nothing echoed) or posted by the dashboard's Settings form. A value is NEVER printed, logged or read
back: `status()` returns names only. The previous file is kept once as `secrets.toml.bak`; writes are atomic.
Statement passwords go under [passwords] with the name the sources file gives them (for example `password_env = "BANK1_PW"`).
"""
from __future__ import annotations

import getpass
import os
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from pflab import _toml
from pflab.pm import secrets as sec

FIELDS: Dict[str, List[Tuple[str, str, bool]]] = {          # section -> (key, what it is, required)
    "kite": [("api_key", "Kite Connect API key", True), ("api_secret", "Kite Connect API secret", True),
             ("redirect_url", "Kite redirect URL (optional)", False)],
    "telegram": [("token", "Telegram bot token", True), ("chat_id", "Telegram chat id", True)],
    "anthropic": [("api_key", "Anthropic API key (the analyst, the brain)", True), ("workspace_id", "Anthropic workspace id (optional)", False)],
    "openai": [("api_key", "OpenAI API key (an alternative engine behind the one door; optional)", False)],      # S85: engines (llm/gateway.py)
    "sec": [("user_agent", "SEC contact: 'Name email' sent with each request (optional)", False)],
}
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


class SetupError(ValueError):
    pass


def _q(v) -> str:
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ") + '"'


def dumps(data: dict) -> str:
    """The secrets as TOML: top-level scalars, then one table per section of strings (what this file ever holds)."""
    lines = []
    for k, v in data.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {_q(v) if isinstance(v, str) else v!r}")
    for sec_name, d in data.items():
        if isinstance(d, dict):
            lines += ["", f"[{sec_name}]"] + [f"{k} = {_q(v)}" for k, v in d.items()]
    return "\n".join(lines).lstrip("\n") + "\n"


def _read(p: Path) -> dict:
    return _toml.load(p) if p.exists() else {}


def set_values(changes: Dict[Tuple[str, str], str], path: Optional[Path] = None) -> List[str]:
    """Set `(section, key) -> value` and return the names set (`section.key`), never the values. A blank value is skipped."""
    p = Path(path) if path else sec.default_path()
    bad = sec._unsafe_location(p)
    if bad:
        raise SetupError(f"{p} is {bad}: keys must live outside the repo and OneDrive")
    data = _read(p)
    done = []
    for (section, key), value in changes.items():
        if not NAME_RE.match(section) or not NAME_RE.match(key):
            raise SetupError(f"not a usable name: {section}.{key}")
        if section != "passwords" and key not in {k for k, _, _ in FIELDS.get(section, [])}:
            raise SetupError(f"unknown secret {section}.{key}")
        value = str(value).strip()
        if not value:
            continue
        data.setdefault(section, {})[key] = value
        done.append(f"{section}.{key}")
    if done:
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            p.with_name(p.name + ".bak").write_bytes(p.read_bytes())
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(dumps(data), encoding="utf-8")
        if os.name != "nt":
            tmp.chmod(0o600)
        tmp.replace(p)
    return done


def status(path: Optional[Path] = None) -> Dict[str, bool]:
    """Which secrets are set (names only): every known field, plus each statement password's name."""
    data = _read(Path(path) if path else sec.default_path())
    out = {f"{s}.{k}": k in (data.get(s) or {}) for s, fs in FIELDS.items() for k, _, _ in fs}
    out.update({f"passwords.{k}": True for k in (data.get("passwords") or {})})
    return out


def password_names(sources: dict) -> List[str]:
    """The statement-password names his sources file asks for (`password_env`), for the prompt and the setup page."""
    names = [b["password_env"] for b in sources.get("bank", []) if b.get("password_env")]
    if (sources.get("cas") or {}).get("password_env"):
        names.append(sources["cas"]["password_env"])
    return sorted(set(names))


def prompt(sections: Optional[List[str]] = None, passwords: Optional[List[str]] = None, path: Optional[Path] = None,
           ask: Callable[[str], str] = getpass.getpass, say: Callable[[str], None] = print, change: bool = False) -> List[str]:
    """Ask for each missing field (all with `change`) through `ask`; Enter skips one. Returns the names set."""
    have = status(path)
    wanted: Dict[Tuple[str, str], str] = {}
    for s in (sections or list(FIELDS)):
        for k, what, _ in FIELDS[s]:
            if have.get(f"{s}.{k}") and not change:
                say(f"{s}.{k}: already set")
                continue
            wanted[(s, k)] = ask(f"{what} (Enter to skip): ")
    for name in passwords or []:
        if have.get(f"passwords.{name}") and not change:
            say(f"passwords.{name}: already set")
            continue
        wanted[("passwords", name)] = ask(f"Password for the statement file '{name}' (Enter to skip): ")
    done = set_values(wanted, path)
    say("set: " + (", ".join(done) if done else "nothing"))
    return done
