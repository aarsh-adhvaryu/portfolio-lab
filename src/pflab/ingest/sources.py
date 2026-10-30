"""The documents the ledger is rebuilt from (S54d): The investor's commented `sources.toml`, plus `sources.app.toml` beside it
for the documents added through the dashboard's inbox. His file is never rewritten; the app writes only its own.

Overlay rules: list keys (zerodha.tradebooks, zerodha.contract_notes_xlsx, cas.files) are extended (no repeats); a second Console funds
ledger is added (zerodha.funds_ledgers) and a second bank statement of the same account is added (bank.files): the build joins them and keeps a line
that sits in two files once, so periods may differ or overlap (2026-10-30; before, the last file silently replaced the first).
"""
from __future__ import annotations

import copy
import re
from datetime import date
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
        cur = (out.get("zerodha") or {}).get("funds_ledger")
        if cur and cur != fl:                                # a second Console ledger (another year) is added, not swapped for the first
            z = out.setdefault("zerodha", {})
            z["funds_ledgers"] = list(z.get("funds_ledgers") or []) + [p for p in [fl] if p not in (z.get("funds_ledgers") or [])]
        else:
            out.setdefault("zerodha", {})["funds_ledger"] = fl
    fls = [p for p in (over.get("zerodha") or {}).get("funds_ledgers") or []]
    if fls:                                                  # several Console ledgers (other years) all count
        z = out.setdefault("zerodha", {})
        z["funds_ledgers"] = list(z.get("funds_ledgers") or []) + [p for p in fls if p not in (z.get("funds_ledgers") or [])]
    ipos = list(out.get("ipo") or [])                       # S65: an IPO entered on the dashboard replaces one of the same id
    for i in over.get("ipo") or []:
        ipos = [x for x in ipos if x.get("ipo_id") != i["ipo_id"]] + [dict(i)]
    if ipos:
        out["ipo"] = ipos
    costs = list(out.get("opening_cost") or [])             # and an opening cost one of the same account and ISIN
    for c in over.get("opening_cost") or []:
        costs = [x for x in costs if (x.get("account"), x.get("isin")) != (c["account"], c["isin"])] + [dict(c)]
    if costs:
        out["opening_cost"] = costs
    banks = list(out.get("bank") or [])
    for b in over.get("bank") or []:
        hit = next((i for i, x in enumerate(banks) if x.get("account") == b["account"]), None)
        if hit is None:
            banks.append(dict(b))
        else:                                                # one account, several statements: all are kept (periods can differ or overlap)
            files = _files_of(banks[hit])
            files += [f for f in _files_of(b) if f not in files]
            banks[hit] = {**banks[hit], **b, **({"file": files[0], "files": files} if files else {})}
    if banks:
        out["bank"] = banks
    return out


def _files_of(b: dict) -> list:
    """The statement files of one [[bank]] entry: `file` (the first) and `files` (all of them)."""
    out = [b["file"]] if b.get("file") else []
    return out + [f for f in (b.get("files") or []) if f not in out]


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
        z = o.setdefault("zerodha", {})
        have = ([z["funds_ledger"]] if z.get("funds_ledger") else []) + list(z.get("funds_ledgers") or [])
        if not have:
            z["funds_ledger"] = path
        elif path not in have:
            z["funds_ledgers"] = list(z.get("funds_ledgers") or []) + [path]
    elif kind == "bank":
        if not account:
            raise ValueError("a bank statement needs its account")
        banks = list(o.get("bank", []))
        hit = next((b for b in banks if b.get("account") == account), None)
        if hit is None:
            banks.append({"account": account, "file": path})
        else:                                                # another statement of the same account is added, never swapped for the first
            files = _files_of(hit)
            if path not in files:
                files.append(path)
            hit.update(file=files[0], files=files)
        o["bank"] = banks
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
        if z.get("funds_ledgers"):
            lines.append("funds_ledgers = [" + ", ".join(_q(p) for p in z["funds_ledgers"]) + "]")
        lines.append("")
    c = over.get("cas") or {}
    if c.get("files"):
        lines += ["[cas]", "files = [" + ", ".join(_q(p) for p in c["files"]) + "]", ""]
    for b in over.get("bank") or []:
        fl = _files_of(b)
        lines += ["[[bank]]", f"account = {_q(b['account'])}", f"file = {_q(fl[0])}"] + (["files = [" + ", ".join(_q(p) for p in fl) + "]"] if len(fl) > 1 else []) + [""]
    for i in over.get("ipo") or []:
        lines += ["[[ipo]]"] + [f"{k} = {_v(i[k])}" for k in IPO_KEYS if i.get(k) not in (None, "")]
        lines += ["[ipo.bank_line]", f"date = {_v(i['bank_line']['date'])}", f"amount = {_v(i['bank_line']['amount'])}", ""]
    for c in over.get("opening_cost") or []:
        lines += ["[[opening_cost]]"] + [f"{k} = {_v(c[k])}" for k in COST_KEYS if c.get(k) not in (None, "")] + [""]
    return "\n".join(lines)


IPO_KEYS = ("ipo_id", "funding_account", "applied", "allot_date", "isin", "symbol", "qty", "price", "bid_qty", "bid_price", "demat_account",
            "assumed")
COST_KEYS = ("account", "isin", "cost_per_unit", "acquired", "basis")


def _v(x) -> str:
    """A TOML value: a date bare, a number as is, a string quoted."""
    if isinstance(x, date):
        return x.isoformat()
    if isinstance(x, bool):
        return str(x).lower()
    return repr(float(x)) if isinstance(x, float) else str(x) if isinstance(x, int) else _q(x)


def _day(v, what: str) -> date:
    try:
        return v if isinstance(v, date) else date.fromisoformat(str(v))
    except ValueError:
        raise ValueError(f"{what} is a day like 2026-04-01") from None


def _isin(v) -> str:
    v = str(v or "").strip().upper()
    if not re.match(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$", v):
        raise ValueError(f"{v!r} is not an ISIN (12 characters, such as INE123A01012)")
    return v


def ipo_entry(ipo_id: str, funding_account: str, demat_account: str, isin: str, qty: int, price: float, allot_date, bank_date,
              bank_amount: float, symbol: str = "", applied=None, bid_qty: Optional[int] = None, bid_price: Optional[float] = None,
              assumed: str = "") -> dict:
    """A validated `[[ipo]]` entry: the bank's payment line (date and amount) is replaced in the ledger by the block and the allotment."""
    if not re.match(r"^[A-Za-z0-9_.-]{3,40}$", str(ipo_id or "")):
        raise ValueError("the IPO id is 3 to 40 letters, digits or - _ .")
    if qty <= 0 or price <= 0 or bank_amount <= 0:
        raise ValueError("quantity, price and the bank amount must be above zero")
    e = {"ipo_id": ipo_id, "funding_account": funding_account, "allot_date": _day(allot_date, "the allotment date"), "isin": _isin(isin),
         "qty": int(qty), "price": float(price), "demat_account": demat_account,
         "bank_line": {"date": _day(bank_date, "the bank line's date"), "amount": float(bank_amount)}}
    for k, v in (("symbol", symbol), ("assumed", assumed)):
        if v:
            e[k] = str(v)
    if applied:
        e["applied"] = _day(applied, "the application date")
    if bid_qty:
        e["bid_qty"] = int(bid_qty)
    if bid_price:
        e["bid_price"] = float(bid_price)
    return e


def cost_entry(account: str, isin: str, cost_per_unit: float, acquired, basis: str) -> dict:
    """A validated `[[opening_cost]]`: cost and date for a holding with no history here; the basis must be said."""
    if cost_per_unit <= 0:
        raise ValueError("the cost per unit must be above zero")
    if not str(basis or "").strip():
        raise ValueError("say what the cost is based on (for example 'previous owner's cost' or 'issue price')")
    return {"account": account, "isin": _isin(isin), "cost_per_unit": float(cost_per_unit), "acquired": _day(acquired, "the acquisition date"),
            "basis": str(basis).strip()}


def with_entry(over: dict, section: str, entry: dict) -> dict:
    """The overlay with one more `ipo` or `opening_cost` entry (the same id, or account and ISIN, is replaced)."""
    if section not in ("ipo", "opening_cost"):
        raise ValueError(section)
    o = copy.deepcopy(over)
    key = (lambda x: x["ipo_id"]) if section == "ipo" else (lambda x: (x["account"], x["isin"]))
    o[section] = [x for x in o.get(section, []) if key(x) != key(entry)] + [entry]
    return o


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
