"""The documents the ledger is rebuilt from (S54d): The investor's commented `sources.toml`, plus `sources.app.toml` beside it
for the documents added through the dashboard's inbox. His file is never rewritten; the app writes only its own.

Overlay rules: list keys (zerodha.tradebooks, zerodha.contract_notes_xlsx, cas.files) are extended (no repeats);
zerodha.funds_ledger is replaced (Console's ledger covers the whole period); a bank statement replaces that account's
file (a statement downloaded from the start covers the whole period).
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import List, Optional

from pflab import _toml

LIST_KEYS = {"tradebook": ("zerodha", "tradebooks"), "contract_note": ("zerodha", "contract_notes_xlsx"),
             "cas": ("cas", "files")}


def overlay_path(sources: Path) -> Path:
    return Path(sources).with_name("sources.app.toml")


def merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for kind, (sec, key) in LIST_KEYS.items():
        add = (over.get(sec) or {}).get(key) or []
        if add:
            cur = list((out.setdefault(sec, {})).get(key) or [])
            out[sec][key] = cur + [p for p in add if p not in cur]
    fl = (over.get("zerodha") or {}).get("funds_ledger")
    if fl:
        out.setdefault("zerodha", {})["funds_ledger"] = fl
    banks = list(out.get("bank") or [])
    for b in over.get("bank") or []:
        hit = next((i for i, x in enumerate(banks) if x.get("account") == b["account"]), None)
        if hit is None:
            banks.append(dict(b))
        else:
            banks[hit] = {**banks[hit], **b}
    if banks:
        out["bank"] = banks
    return out


def base(sources: Path) -> dict:
    """The investor's own file alone."""
    return _toml.load(Path(sources))


def load(sources: Path) -> dict:
    return merge(base(sources), load_overlay(sources))


def with_document(over: dict, kind: str, path: str, account: Optional[str] = None) -> dict:
    """The overlay with one more document (kind: tradebook | contract_note | cas | funds_ledger | bank)."""
    o = copy.deepcopy(over)
    if kind in LIST_KEYS:
        sec, key = LIST_KEYS[kind]
        lst = o.setdefault(sec, {}).setdefault(key, [])
        if path not in lst:
            lst.append(path)
    elif kind == "funds_ledger":
        o.setdefault("zerodha", {})["funds_ledger"] = path
    elif kind == "bank":
        if not account:
            raise ValueError("a bank statement needs its account")
        banks = [b for b in o.get("bank", []) if b.get("account") != account]
        o["bank"] = banks + [{"account": account, "file": path}]
    else:
        raise ValueError(f"not a ledger document: {kind}")
    return o


def _q(s: str) -> str:
    return '"' + s.replace("\\", "/").replace('"', '\\"') + '"'


def dumps(over: dict) -> str:
    """The overlay as TOML (its fixed shape only)."""
    lines = ["# Written by the dashboard's inbox (S54d): documents added after sources.toml. The investor's file is unchanged.", ""]
    z = over.get("zerodha") or {}
    if z:
        lines.append("[zerodha]")
        for key in ("tradebooks", "contract_notes_xlsx"):
            if z.get(key):
                lines.append(f"{key} = [" + ", ".join(_q(p) for p in z[key]) + "]")
        if z.get("funds_ledger"):
            lines.append(f"funds_ledger = {_q(z['funds_ledger'])}")
        lines.append("")
    c = over.get("cas") or {}
    if c.get("files"):
        lines += ["[cas]", "files = [" + ", ".join(_q(p) for p in c["files"]) + "]", ""]
    for b in over.get("bank") or []:
        lines += ["[[bank]]", f"account = {_q(b['account'])}", f"file = {_q(b['file'])}", ""]
    return "\n".join(lines)


def save_overlay(sources: Path, over: dict) -> None:
    p = overlay_path(sources)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(dumps(over), encoding="utf-8")
    tmp.replace(p)


def load_overlay(sources: Path) -> dict:
    p = overlay_path(sources)
    return _toml.load(p) if p.exists() else {}


def bank_accounts(sources: Path) -> List[str]:
    src = load(sources)
    return [k for k, v in (src.get("accounts") or {}).items() if v.get("kind") == "bank"]
