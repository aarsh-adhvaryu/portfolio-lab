"""His preferences, changed by the AI when HE asks (S65; his words 2026-10-28: "if I want to change it or alter things, AI can: power should be there").

The AI never changes them on its own judgement. When he asks (chat, Telegram, the brain), the change is written as ONE exact edit and put to him
(`limit_proposals` kind `preference`, a Needs-from-you question); his yes applies it to his own file, after a dated backup; a change that would
leave the file invalid is undone and declined with the reason. What can change:

    targets     new target weights for one or more buckets, as {bucket: weight}; the whole targets file must still validate (weights sum to 1)
    stock_list  add or remove a name (key "add" or "remove", value the symbol)
    api_cap     the monthly rupee cap for paid calls (key "monthly", value rupees)
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

KINDS = ("targets", "stock_list", "api_cap")
MAX_CAP = 50_000.0                       # a cap above this is read as a typing slip, not an instruction


class PrefError(ValueError):
    pass


def _pm() -> Path:
    from pflab.pm import store
    return store.pm_dir()


def _backup(path: Path, now: datetime) -> Optional[Path]:
    if not path.exists():
        return None
    d = _pm() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    b = d / f"{path.name}.{now:%Y%m%d_%H%M%S}.bak"
    shutil.copy2(path, b)
    return b


def check(kind: str, key: str, value) -> str:
    """The change in his words, or PrefError if it is not one this module can make."""
    if kind == "targets":
        w = json.loads(value) if isinstance(value, str) else dict(value)
        if not w or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in w.values()):
            raise PrefError("target weights are shares between 0 and 1, for example {\"equity\": 0.55, \"debt\": 0.25}")
        return "set target weights: " + ", ".join(f"{b} {v:.0%}" for b, v in w.items())
    if kind == "stock_list":
        if key not in ("add", "remove") or not re.fullmatch(r"[A-Za-z0-9&-]{2,20}", str(value or "")):
            raise PrefError("stock list: key add or remove, and an NSE symbol")
        return f"{key} {str(value).upper()} {'to' if key == 'add' else 'from'} your stock list"
    if kind == "api_cap":
        v = float(value)
        if not 0 <= v <= MAX_CAP:
            raise PrefError(f"the monthly cap is between Rs 0 and Rs {MAX_CAP:,.0f}")
        return f"set the monthly cap for paid calls to Rs {v:,.0f}"
    raise PrefError(f"kind is one of {KINDS}")


def propose(con, kind: str, key: str, value, why: str, now: datetime) -> Optional[int]:
    """Put the exact change to him. Returns the proposal id (None if the same one is already waiting)."""
    from pflab.risk import themes
    words = check(kind, key, value)
    v = json.dumps(value) if kind == "targets" and not isinstance(value, str) else str(value)
    return themes.propose(con, "preference", f"{kind}:{key}", v, {"why": why[:300], "kind": kind}, f"You asked me to {words}. {why[:200]}",
                          now, revise=True)


def _set_targets(weights: dict, now: datetime) -> str:
    from pflab.plan import targets as tg
    path = tg.default_path()
    if not path.exists() or path.parent != _pm():
        raise PrefError("your own targets file (in the PM folder) does not exist yet: targets are set there first")
    text = path.read_text(encoding="utf-8")
    new = text
    for bucket, w in weights.items():
        pat = re.compile(r"(^\[bucket\." + re.escape(bucket) + r"\][^\[]*?^target\s*=\s*)([0-9.]+)", re.M | re.S)
        if not pat.search(new):
            raise PrefError(f"no [bucket.{bucket}] with a target in your file: add that bucket by hand first")
        new = pat.sub(lambda m: m.group(1) + f"{float(w):.4f}".rstrip("0").rstrip("."), new, count=1)
    b = _backup(path, now)
    path.write_text(new, encoding="utf-8")
    try:
        tg.load(path)
    except Exception as e:
        shutil.copy2(b, path)
        raise PrefError(f"the targets would not validate ({str(e)[:160]}): nothing changed")
    return f"targets changed; the old file is kept as {b.name}"


def _set_cap(rupees: float, now: datetime) -> str:
    path = _pm() / "api_budget.toml"
    if not path.exists():
        raise PrefError("no api_budget.toml in the PM folder")
    text = path.read_text(encoding="utf-8")
    from pflab import release
    key = "dev_monthly_cap_rupees" if release.channel() == "beta" else "monthly_cap_rupees"     # S68: the key the running channel reads
    pat = re.compile(r"(^\s*" + key + r"\s*=\s*)([0-9.]+)", re.M)
    if not pat.search(text):
        raise PrefError(f"no {key} line in api_budget.toml")
    b = _backup(path, now)
    path.write_text(pat.sub(lambda m: m.group(1) + f"{rupees:g}", text, count=1), encoding="utf-8")
    return f"monthly cap set to Rs {rupees:,.0f}; the old file is kept as {b.name}"


def apply(con, kind: str, key: str, value: str, now: datetime) -> str:
    """Make the change he said yes to. Raises PrefError (and changes nothing) when it cannot be made."""
    check(kind, key, value)
    if kind == "targets":
        return _set_targets(json.loads(value), now)
    if kind == "stock_list":
        from pflab.plan import stock_list as sl
        b = _backup(sl.path(), now)
        if key == "add":
            sl.add(con, str(value).upper(), now.date(), run_agents=False)
        elif not sl.remove(str(value).upper()):
            raise PrefError(f"{str(value).upper()} is not on your stock list")
        return f"stock list: {key} {str(value).upper()}" + (f"; the old list is kept as {b.name}" if b else "")
    return _set_cap(float(value), now)
