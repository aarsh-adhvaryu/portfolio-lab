"""What the system has found, what it has read, and what it cannot yet say (S67 local). Accounts are found from the statements themselves (bank and the
last four digits, a depository id, a folio), not from a list typed beforehand, so an account the old setup never knew still appears. Every finding
is kept even when nothing else can be done with it yet: an account that is not set up, a file that is locked, a document that no parser reads, a
mail with no attachment. The picture is called complete only when ALL of this holds: the mailboxes were walked to their horizon, nothing is open as
a gap, every discovered account is set up, and the investor has confirmed the inventory. Email alone can never prove that no account is missing, so
the inventory is always put to him once, together with the other places an account might be.

Nothing here reads a statement's content beyond what `sniff` already returns (kind, bank, last four digits, depository ids). Accounts are shown masked.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Dict, List, Optional

KIND_WORD = {"bank": "bank account", "cas": "demat / mutual fund account", "tradebook": "broker account", "contract_note": "broker account",
             "funds_ledger": "broker account", "fd_certificate": "fixed deposit", "gift_city": "broker account (GIFT City)"}


def label(kind: str, bank: Optional[str], last4: Optional[str], dp_ids: Optional[str] = None) -> str:
    """Masked: a bank name and the last four digits only, never a full number."""
    who = (bank or "unknown institution").strip()[:40]
    tail = f" ending {last4}" if last4 else (f" (depository id ending {str(dp_ids)[-4:]})" if dp_ids else "")
    return f"{who} {KIND_WORD.get(kind, kind)}{tail}"


def key_of(kind: str, bank: Optional[str], last4: Optional[str], dp_ids: Optional[str]) -> str:
    return hashlib.sha1(f"{kind}|{(bank or '').lower()}|{last4 or ''}|{dp_ids or ''}".encode()).hexdigest()[:16]


def note_account(con, info: dict, source: str, now: datetime, file_sha: str = "") -> Optional[str]:
    """A statement showed an account: keep it, by what the file itself says. Returns the candidate key (None when the file shows no account)."""
    kind = info.get("kind")
    if kind in (None, "other") or not (info.get("bank") or info.get("last4") or info.get("dp_ids")):
        return None
    k = key_of(kind, info.get("bank"), info.get("last4"), info.get("dp_ids"))
    r = con.execute("SELECT n_files, sources FROM account_candidates WHERE cand_key=?", [k]).fetchone()
    if r:
        srcs = set(str(r[1] or "").split(",")) | {source}
        con.execute("UPDATE account_candidates SET last_seen=?, n_files=?, sources=? WHERE cand_key=?",
                    [now, int(r[0]) + (1 if file_sha else 0), ",".join(sorted(s for s in srcs if s)), k])
    else:
        con.execute("INSERT INTO account_candidates (cand_key, first_seen, last_seen, kind, bank, last4, dp_ids, label, n_files, sources, state) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?, 'discovered')",
                    [k, now, now, kind, info.get("bank"), info.get("last4"), str(info.get("dp_ids") or "") or None,
                     label(kind, info.get("bank"), info.get("last4"), info.get("dp_ids")), 1 if file_sha else 0, source])
    return k


def note_gap(con, kind: str, ref: str, detail: str, now: datetime) -> None:
    """A file or message that cannot be used yet stays visible as a gap (locked | unsupported | link_only | no_attachment | period)."""
    from pflab.app import readiness
    readiness.open_gap(con, f"coverage:{kind}:{ref}", "coverage", detail, now)


def _set_up(con) -> List[dict]:
    try:
        rows = con.execute("SELECT account_id, kind, provider, dp_or_folio, closed FROM accounts ORDER BY account_id").fetchall()
    except Exception:
        return []
    return [{"id": a, "kind": k, "provider": p, "ref": d, "closed": c} for a, k, p, d, c in rows]


def _months(con, account: str) -> List[str]:
    try:
        return [r[0] for r in con.execute("SELECT DISTINCT strftime(trade_date, '%Y-%m') FROM events WHERE account_id=? ORDER BY 1", [account]).fetchall()]
    except Exception:
        return []


def _between(months: List[str]) -> List[str]:
    """Months between the first and last month with activity that have none. Either a quiet month or a missing statement: the system cannot tell
    which from the ledger alone, so it lists them and does not call the account whole."""
    if len(months) < 2:
        return []
    y, m = map(int, months[0].split("-"))
    ey, em = map(int, months[-1].split("-"))
    have, out = set(months), []
    while (y, m) < (ey, em):
        key = f"{y:04d}-{m:02d}"
        if key not in have:
            out.append(key)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def matrix(con, now: datetime) -> List[dict]:
    """One row per account the system knows of: how it was found, whether it is set up, the months with activity in the ledger, what is open against it."""
    out: List[dict] = []
    set_up = _set_up(con)
    last4_up = {str(a["ref"] or "")[-4:] for a in set_up if a["ref"]}
    by_last4 = {}
    for a in set_up:
        m = _months(con, a["id"])
        silent = _between(m)
        out.append({"account": f"{a['provider'] or a['kind']} ({a['id']})", "silent_months": silent, "state": "set up" + (", closed" if a["closed"] else ""), "found_in": "your setup",
                    "months_with_activity": len(m), "first_month": m[0] if m else None, "last_month": m[-1] if m else None,
                    "verified": bool(m), "files_seen": 0, "next": None if m else "no ledger activity yet: its statements have not been read"})
        if a["ref"]:
            by_last4[str(a["ref"])[-4:]] = out[-1]
    for k, lab, n, srcs, st, l4 in con.execute("SELECT cand_key, label, n_files, sources, state, last4 FROM account_candidates ORDER BY first_seen").fetchall():
        if st == "not_mine":
            continue
        if l4 and l4 in by_last4:                              # the same account as one that is set up: one row, with the files seen added
            row = by_last4[l4]
            row["files_seen"] += int(n)
            row["found_in"] = f"{row['found_in']}, {srcs}" if srcs else row["found_in"]
            continue
        out.append({"account": lab, "state": "discovered, not set up", "found_in": srcs or "statements",
                    "files_seen": int(n), "months_with_activity": None, "verified": False,
                    "next": "confirm it is yours in Setup, or tell me it is not"})
    return out


def gaps(con) -> List[dict]:
    from pflab.app import readiness
    return [g for g in readiness.gaps(con) if g["key"].startswith(("coverage:", "mail:msg:"))]


def mailboxes(con, now: datetime) -> List[dict]:
    from pflab.ingest import gmail
    return gmail.coverage(con, now)


CONFIRMED = "coverage:inventory:confirmed"


def inventory_confirmed(con) -> bool:
    """Only the investor's explicit confirmation counts (`confirm_inventory`, from the screen); a reply to the question may add an account instead."""
    return bool(con.execute("SELECT count(*) FROM memory WHERE kind='answer' AND subject=? AND valid_to IS NULL", [CONFIRMED]).fetchone()[0])


def confirm_inventory(con, now: datetime) -> int:
    """He says: this is every account, mailbox and export. Kept as a dated answer; adding an account later does not undo it, but a NEW account
    found after it opens the question again (the candidate is not in the confirmed list)."""
    from pflab.agents import memory
    keys = sorted(r[0] for r in con.execute("SELECT cand_key FROM account_candidates").fetchall())
    return memory.remember(con, "answer", f"inventory confirmed as complete; {len(keys)} discovered account(s): {','.join(keys)}", subject=CONFIRMED,
                           source="investor", now=now)


def _confirmed_covers_all(con) -> bool:
    r = con.execute("SELECT text FROM memory WHERE kind='answer' AND subject=? AND valid_to IS NULL ORDER BY mem_id DESC LIMIT 1", [CONFIRMED]).fetchone()
    if not r:
        return False
    listed = set(str(r[0]).rsplit(": ", 1)[-1].split(",")) if ": " in str(r[0]) else set()
    now_keys = {k[0] for k in con.execute("SELECT cand_key FROM account_candidates WHERE state <> 'not_mine'").fetchall()}
    return now_keys <= listed


def status(con, now: datetime) -> dict:
    """{label, reasons}: nothing read yet | discovery in progress | partial | complete. `complete` needs every condition; each missing one is a reason."""
    mbs = mailboxes(con, now)
    mx = matrix(con, now)
    gp = gaps(con)
    reasons: List[str] = []
    if not mbs and not mx:
        return {"label": "nothing read yet", "reasons": ["no mailbox has been walked and no account has been found"], "accounts": 0, "mailboxes": 0, "open_gaps": 0}
    behind = [m for m in mbs if not m["reached_horizon"]]
    if behind:
        reasons.append(f"{len(behind)} mailbox(es) are still being read back through their history (reached {', '.join(m['read_back_to'] for m in behind)})")
    if gp:
        reasons.append(f"{len(gp)} file(s) or message(s) could not be used and are listed")
    un = [r for r in mx if r["state"] == "discovered, not set up"]
    if un:
        reasons.append(f"{len(un)} account(s) were found in statements but are not set up")
    unv = [r for r in mx if r["state"].startswith("set up") and not r["verified"]]
    if unv:
        reasons.append(f"{len(unv)} set-up account(s) have no ledger activity yet")
    silent = [r for r in mx if r.get("silent_months")]
    if silent:
        reasons.append(f"{len(silent)} account(s) have months with no activity, which is either quiet or a missing statement: " +
                       "; ".join(f"{r['account']}: {', '.join(r['silent_months'][:4])}" for r in silent[:3]))
    if not inventory_confirmed(con):
        reasons.append("you have not confirmed that this is every account, mailbox and export")
    elif not _confirmed_covers_all(con):
        reasons.append("an account was found after you confirmed the list: please confirm again")
    if behind:
        label_ = "discovery in progress"
    elif reasons:
        label_ = "partial"
    else:
        label_ = "complete"
    return {"label": label_, "reasons": reasons, "accounts": len(mx), "mailboxes": len(mbs), "open_gaps": len(gp),
            "note": "email alone cannot show that no account is missing: the inventory is always yours to confirm"}


def ask_inventory(con, now: datetime) -> Optional[int]:
    """After discovery has something to show: ONE grouped question listing the masked inventory and asking for what is absent. None until there is an
    inventory (or while the first walk has not finished a window), and never twice."""
    from pflab.agents import questions
    mx = matrix(con, now)
    mbs = mailboxes(con, now)
    if not mx or not mbs or not all(m["reached_horizon"] for m in mbs):
        return None                                        # asked when reading has gone as far back as email can take it, so the list is as full as it will be
    lines = "; ".join(f"{r['account']} [{r['state']}]" for r in mx[:12])
    text = (f"Here is every account I have found so far: {lines}. Tell me in one reply: which of these are not yours or are closed; any account, "
            "broker, bank or deposit that is NOT in this list; any other email address that receives statements; and any statement you can "
            "only download as a file (not by email). I keep reading in the meantime, and I will not call the picture complete until you confirm.")
    return questions.ask(con, "companion", "coverage:inventory", text[:1200], now)
