"""What may leave the PC in a paid HQ call (The investor 2026-10-24, docs/BUILT.md decision 1).

May go: his portfolio (holdings, amounts, weights, gains, lots, cash, goals and limits) and public documents.
Never: his identity and banking details: PAN, account, folio, client and DP numbers, bank account details (IFSC, UPI,
"account number"), addresses, phone, e-mail, his name, and the statement files themselves.

The text an HQ call sends that code built from his data or that he wrote is checked here; documents are checked by
provenance (a public kind from the graph, or a portfolio view built by code), never by scanning, since filings are full
of company phone numbers and e-mails. The analyst's older, stricter gate stays on its own paths (research, web search,
the workshop). A block names the kind of data found, never the value.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Set

from pflab import _toml
from pflab.agents import analyst as an

EgressBlocked = an.EgressBlocked

NEVER = {
    **an._IDS,                                                       # PAN, e-mail, phone, account-like digit runs
    "IFSC code": re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"),
    "UPI id": re.compile(r"\b[\w.-]{2,}@[a-z]{2,}\b(?![.@\w])", re.I),
    "bank account details": re.compile(r"\b(a/c|account|acct|folio|client|dp|demat)\s*(no\.?|number|id)\b", re.I),
    "address": re.compile(r"\b(pin ?code|postal code|flat no|house no|address)\b", re.I),
}
DOC_KINDS = an.PUBLIC_KINDS + ("portfolio",)       # portfolio: a view of his holdings built by code (no account ids)


@dataclass
class Gate:
    ids: Set[str] = field(default_factory=set)       # account numbers, depository and folio ids, FD ids
    names: List[str] = field(default_factory=list)   # his name, from api_budget.toml [egress] names
    address: List[str] = field(default_factory=list)  # words of his address (S60), [egress] address


def names(path: Optional[Path] = None, key: str = "names", min_len: int = 1) -> List[str]:
    from pflab.pm import store
    p = path or store.pm_dir() / "api_budget.toml"
    return [str(n).lower() for n in (_toml.load(p).get("egress", {}).get(key, []) if p.exists() else [])
            if len(str(n).strip()) >= min_len]


def load(con, path: Optional[Path] = None) -> Gate:
    """The ids that identify him, read from the ledger. An account id that is only a bank's or broker's name is not one
    (it would block every mention of that bank's shares); one with digits is an account number."""
    g = Gate(names=names(path), address=names(path, "address", 3))
    for (acc,) in con.execute("SELECT account_id FROM accounts").fetchall():
        if acc and len(acc) >= 4 and re.search(r"\d", acc):
            g.ids.add(acc)
    for (dp,) in con.execute("SELECT dp_or_folio FROM accounts WHERE dp_or_folio IS NOT NULL").fetchall():
        if len(str(dp)) >= 4:
            g.ids.add(str(dp))
    for (fid,) in con.execute("SELECT fd_id FROM fds").fetchall():
        if fid and len(str(fid)) >= 4:
            g.ids.add(str(fid))
    return g


def check(text: str, gate: Gate, doc_kinds: Sequence[str] = (), skip: Sequence[str] = ()) -> None:
    """Raise EgressBlocked naming what was found; return quietly when the call may go. `skip`: patterns not read
    (S60: a tool result skips "address", the word public filings use for a company's office; his own address words
    are replaced by `redact` before this check)."""
    found = []
    if any(k not in DOC_KINDS for k in doc_kinds):
        found.append("a document that is not public or a portfolio view (statement files never leave)")
    for name, rx in NEVER.items():
        if name not in skip and rx.search(text):
            found.append(name)
    low = text.lower()
    if any(re.search(r"\b" + re.escape(n) + r"\b", low) for n in gate.names):
        found.append("his name")
    if any(re.search(r"\b" + re.escape(a) + r"\b", low) for a in gate.address):
        found.append("his address")
    if any(i in text for i in gate.ids):
        found.append("an account, depository, folio or deposit id")
    if found:
        raise EgressBlocked("not sent: " + "; ".join(sorted(set(found))))
