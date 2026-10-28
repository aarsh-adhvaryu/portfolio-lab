"""Setup: his answers become `sources.toml`; what is still missing becomes Needs-from-you items (S65, S64 Phase 7 item 2).

The Setup page (and `POST /api/setup`) takes the accounts and the start date:

    start    the first day the ledger must cover (documents from then on are asked for)
    broker   {account, provider, cas_dp}              the Zerodha account and its demat's DP id (optional)
    demats   [{name, provider, cas_dp, dormant, read_only}]   other depositories (for example a family demat he only holds)
    banks    [{name, bank, last4, password_name}]     last four digits only; an account number is never stored

It writes the base `sources.toml` with the accounts and empty document lists (documents arrive through the inbox into
`sources.app.toml`). His own file is never overwritten: a second Setup is refused unless `overwrite` is given. `needed` lists the
documents the ledger build still lacks, in his words; `ask_needed` files each as a Needs-from-you item, once.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from pflab.agents import questions

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
ZERODHA_DP_PREFIX = "120816"            # the six digits Zerodha Broking's CDSL depository participant ids start with
AGENT = "setup"


class SetupError(ValueError):
    pass


def _name(v, what: str) -> str:
    v = str(v or "").strip()
    if not NAME_RE.match(v):
        raise SetupError(f"{what}: letters, digits and underscores, starting with a letter (got {v!r})")
    return v


def _dp(v) -> str:
    v = str(v or "").strip().upper()
    if v and not re.match(r"^[A-Z0-9]{8}$", v):
        raise SetupError(f"a DP id is 8 letters or digits (got {v!r})")
    return v


def normalise(a: dict) -> dict:
    """Validated answers -> the `sources` dict (what `ingest/sources.py` and tools/build_pm_ledger.py read)."""
    try:
        start = date.fromisoformat(str(a.get("start")))
    except ValueError:
        raise SetupError("the start date is a day like 2026-04-01") from None
    b = a.get("broker") or {}
    broker = _name(b.get("account") or "zer", "broker account")
    accounts = {broker: {"kind": "broker", "provider": str(b.get("provider") or "Zerodha")}}
    if _dp(b.get("cas_dp")):
        accounts[broker]["cas_dp"] = _dp(b.get("cas_dp"))
    for d in a.get("demats") or []:
        n = _name(d.get("name"), "demat name")
        if n in accounts:
            raise SetupError(f"{n} is used twice")
        accounts[n] = {"kind": "demat", "provider": str(d.get("provider") or ""), "dormant": bool(d.get("dormant")),
                       "read_only": bool(d.get("read_only"))}
        if _dp(d.get("cas_dp")):
            accounts[n]["cas_dp"] = _dp(d.get("cas_dp"))
    banks = []
    for k in a.get("banks") or []:
        n = _name(k.get("name"), "bank account name")
        last4 = str(k.get("last4") or "").strip()
        if n in accounts:
            raise SetupError(f"{n} is used twice")
        if not re.match(r"^\d{4}$", last4):
            raise SetupError(f"{n}: give the last four digits only (got {len(last4)} characters)")
        accounts[n] = {"kind": "bank", "bank": str(k.get("bank") or "").strip().upper(), "last4": last4}
        pw = str(k.get("password_name") or "").strip()
        banks.append({"account": n, **({"password_env": _name(pw, "password name")} if pw else {})})
    if not banks:
        raise SetupError("add at least one bank account")
    cas = {"files": []}
    if a.get("cas_password_name"):
        cas["password_env"] = _name(a["cas_password_name"], "CAS password name")
    return {"start": start, "zerodha": {"account": broker, "tradebooks": [], "contract_notes_xlsx": []}, "cas": cas, "bank": banks,
            "accounts": accounts}


def _q(s) -> str:
    return '"' + str(s).replace("\\", "/").replace('"', '\\"') + '"'


def dumps(src: dict) -> str:
    lines = ["# Written by Setup (ingest/setup_sources.py). Your documents are added to sources.app.toml by the inbox; edit this file",
             "# only to change an account. Never put an account number here: the last four digits are enough.", "",
             f"start = {src['start'].isoformat()}", "", "[zerodha]", f"account = {_q(src['zerodha']['account'])}", "tradebooks = []",
             "contract_notes_xlsx = []", "", "[cas]", "files = []"]
    if src["cas"].get("password_env"):
        lines.append(f"password_env = {_q(src['cas']['password_env'])}")
    for b in src["bank"]:
        lines += ["", "[[bank]]", f"account = {_q(b['account'])}"] + ([f"password_env = {_q(b['password_env'])}"] if b.get("password_env") else [])
    for name, v in src["accounts"].items():
        lines += ["", f"[accounts.{name}]"]
        for k, val in v.items():
            lines.append(f"{k} = {str(val).lower()}" if isinstance(val, bool) else f"{k} = {_q(val)}")
    return "\n".join(lines) + "\n"


def write(path: Path, answers: dict, overwrite: bool = False) -> dict:
    """Write sources.toml from the answers; refuses to replace an existing file (his own) unless `overwrite`."""
    src = normalise(answers)
    path = Path(path)
    if path.exists() and not overwrite:
        raise SetupError(f"{path.name} already exists; Setup never replaces your file")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(dumps(src), encoding="utf-8")
    tmp.replace(path)
    return src


def needed(src: dict, optional: bool = True) -> List[str]:
    """The documents the ledger build still lacks, as sentences (`src` merged with the overlay). Empty: ready to build. With
    `optional` False only what the build cannot run without (the contract notes are a check, not a need)."""
    out: List[str] = []
    since = str(src.get("start") or "the start of your history")
    z = src.get("zerodha") or {}
    if not z.get("tradebooks"):
        out.append(f"Console tradebook(s) from {since}")
    if not z.get("funds_ledger"):
        out.append(f"Console funds ledger from {since}")
    if optional and z.get("tradebooks") and not z.get("contract_notes_xlsx"):
        out.append("Console contract notes (xlsx) for the days you traded")
    if not (src.get("cas") or {}).get("files"):
        dps = [v["cas_dp"] for v in (src.get("accounts") or {}).values() if v.get("cas_dp")]
        out.append(f"depository CAS from {since}" + (f" (covering DP {', '.join(dps)})" if dps else ""))
    have = {b["account"] for b in src.get("bank") or [] if b.get("file")}
    for name, v in (src.get("accounts") or {}).items():
        if v.get("kind") == "bank" and name not in have:
            out.append(f"bank statement for {v.get('bank') or name} account ending {v.get('last4', '????')} from {since}")
    return out


def ask_needed(con, src: dict, now: Optional[datetime] = None) -> int:
    """One Needs-from-you item per missing document, once. Returns how many were new."""
    n = 0
    for text in needed(src):
        key = "setup:file:" + re.sub(r"[^a-z0-9]+", "-", text.lower())[:60]
        if questions.ask(con, AGENT, key, f"Drop this in Inbox and files: {text}.", now or datetime.now()):
            n += 1
    return n


def infer(con, today: date) -> dict:
    """S65: Setup from the files themselves. What the inbox read from each dropped file (its bank and last four digits, the name of the password
    that opened it) becomes proposed answers: one bank account per distinct bank and last four digits, the Zerodha account, the start of the
    current financial year. He presses once to accept (or edits); nothing is written here."""
    import json
    from collections import Counter
    kinds: Counter = Counter()
    banks: dict = {}
    dps: Counter = Counter()
    cas_pw = None
    unread = 0
    for kind, rj in con.execute("SELECT kind, result_json FROM inbox_items WHERE status <> 'removed'").fetchall():
        info = (json.loads(rj or "{}").get("sniff") or {})
        kinds[kind] += 1
        if kind == "bank":
            if not info.get("last4"):
                unread += 1
                continue
            key = (info.get("bank") or "BANK", info["last4"])
            banks.setdefault(key, info.get("password_name"))
        elif kind == "cas":
            cas_pw = info.get("password_name") or cas_pw
            dps.update({d.strip().upper() for d in (info.get("dp_ids") or "").split(",") if d.strip()})
    fy = today.year if today.month >= 4 else today.year - 1
    zer = sorted((d for d in dps if d.startswith(ZERODHA_DP_PREFIX)), key=lambda d: (-dps[d], d))     # the one most CAS files show
    answers = {"start": date(fy, 4, 1).isoformat(), "broker": {"account": "ZER", "provider": "Zerodha", **({"cas_dp": zer[0]} if zer else {})},
               "demats": [{"name": f"DEMAT_{d}", "provider": "a demat held outside Zerodha (holdings from the CAS only)", "cas_dp": d,
                           "read_only": True} for d in sorted(set(dps) - set(zer))],
               "banks": [{"name": f"{b}_{l4}", "bank": b, "last4": l4, **({"password_name": pw} if pw else {})}
                         for (b, l4), pw in sorted(banks.items())]}
    if cas_pw:
        answers["cas_password_name"] = cas_pw
    return {"answers": answers, "files": dict(kinds), "banks_unread": unread,
            "note": "read from the files you dropped; the start is this financial year's first day: change it if your history starts earlier"}
