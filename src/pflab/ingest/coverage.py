"""What the system has found, what it has read, and what it cannot yet say (S67 local). Accounts are found from the statements themselves (bank and the
last four digits, a depository id, a folio), not from a list typed beforehand, so an account the old setup never knew still appears. Every finding
is kept even when nothing else can be done with it yet: an account that is not set up, a file that is locked, a document that no parser reads.

An account counts as covered only by its STATEMENTS (audit 2026-10-30): the ledger build records the period of every statement file it was made from
(`statement_periods`, written only when every balance check passed). A gap between two statements, a start later than the rest of the history and
an end older than STALE_DAYS are named; transactions alone prove nothing. The picture is called complete only when ALL of this holds: nothing is
open as a gap, every discovered account is set up (or left out by him), every set-up account's statements run without gaps to a recent date, and
the investor has confirmed the inventory. Files alone can never prove that no account is missing, so the inventory is always his to confirm.

Nothing here reads a statement's content beyond what `sniff` already returns (kind, bank, last four digits, depository ids). Accounts are shown masked.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

KIND_WORD = {"bank": "bank account", "cas": "demat / mutual fund account", "tradebook": "broker account", "contract_note": "broker account",
             "funds_ledger": "broker account", "fd_certificate": "fixed deposit", "gift_city": "broker account (GIFT City)"}
GAP_DAYS = 7              # two statements further apart than this leave a stretch no statement covers
STALE_DAYS = 45           # statements that end longer ago than this are behind
LATE_START_DAYS = 31      # an account whose statements begin this much later than the rest: opened later, or its first statements are missing
PERIOD_KIND = {"bank": ("bank",), "demat": ("cas", "funds_ledger"), "broker": ("funds_ledger", "cas")}   # the statements that prove each kind


def label(kind: str, bank: Optional[str], last4: Optional[str], dp_ids: Optional[str] = None) -> str:
    """Masked: a bank name and the last four digits only, never a full number."""
    if kind == "cas" and not bank:                              # a depository statement names the demat, not a bank
        return f"demat account (depository id ending {str(dp_ids)[-4:]})" if dp_ids else "demat account"
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
    dps = [d.strip().upper() for d in str(info.get("dp_ids") or "").split(",") if d.strip()]
    if kind == "cas" and len(dps) > 1:                          # one statement covering two demats is two accounts, not one blurred one
        keys = [note_account(con, {**info, "dp_ids": d}, source, now, file_sha) for d in dps]
        return keys[0]
    k = key_of(kind, info.get("bank"), info.get("last4"), info.get("dp_ids"))
    r = con.execute("SELECT n_files, sources FROM account_candidates WHERE cand_key=?", [k]).fetchone()
    if r:
        srcs = set(str(r[1] or "").split(",")) | {source}
        con.execute("UPDATE account_candidates SET last_seen=?, n_files=?, sources=? WHERE cand_key=?",
                    [now, int(r[0]) + (1 if file_sha else 0), ",".join(sorted(s for s in srcs if s)), k])
        if file_sha:                                            # he gave a file for an account he had left out: he wants it counted now
            con.execute("UPDATE account_candidates SET state='discovered' WHERE cand_key=? AND state='left_out'", [k])
    else:
        con.execute("INSERT INTO account_candidates (cand_key, first_seen, last_seen, kind, bank, last4, dp_ids, label, n_files, sources, state) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?, 'discovered')",
                    [k, now, now, kind, info.get("bank"), info.get("last4"), str(info.get("dp_ids") or "") or None,
                     label(kind, info.get("bank"), info.get("last4"), info.get("dp_ids")), 1 if file_sha else 0, source])
    return k


def note_gap(con, kind: str, ref: str, detail: str, now: datetime) -> None:
    """A file that cannot be used yet stays visible as a gap (locked | unsupported | period)."""
    from pflab.app import readiness
    readiness.open_gap(con, f"coverage:{kind}:{ref}", "coverage", detail, now)


def _set_up(con) -> List[dict]:
    try:
        rows = con.execute("SELECT account_id, kind, provider, dp_or_folio, closed FROM accounts ORDER BY account_id").fetchall()
    except Exception:
        return []
    return [{"id": a, "kind": k, "provider": p, "ref": d, "closed": c} for a, k, p, d, c in rows]


def _d(x) -> Optional[date]:
    if x is None:
        return None
    return x.date() if isinstance(x, datetime) else x


def periods(con, account: str, kinds=None) -> List[tuple]:
    """(first, last) of each statement of the account the last checked build was made from, oldest first. `kinds`: the statement kinds that count."""
    kinds = (kinds,) if isinstance(kinds, str) else tuple(kinds or ())
    try:
        q = "SELECT first_date, last_date FROM statement_periods WHERE account_id=? AND first_date IS NOT NULL"
        q += (f" AND kind IN ({','.join('?' * len(kinds))})" if kinds else "")
        return sorted((_d(a), _d(b)) for a, b in con.execute(q + " ORDER BY first_date", [account] + list(kinds)).fetchall())
    except Exception:
        return []


def statement_cover(ps: List[tuple], earliest: Optional[date], today: date) -> dict:
    """From statement periods: the stretch covered, every hole between statements, a late start and a stale end. Pure; tested by hand-made periods."""
    if not ps:
        return {"from": None, "to": None, "holes": [], "late_start": False, "stale": True}
    holes, cur_from, cur_to = [], ps[0][0], ps[0][1]
    for a, b in ps[1:]:
        if a > cur_to + timedelta(days=GAP_DAYS):
            holes.append(f"{cur_to + timedelta(days=1)} to {a - timedelta(days=1)}")
        cur_to = max(cur_to, b)
    return {"from": cur_from, "to": cur_to, "holes": holes,
            "late_start": bool(earliest and cur_from > earliest + timedelta(days=LATE_START_DAYS)),
            "stale": (today - cur_to).days > STALE_DAYS}


def _earliest(con) -> Optional[date]:
    """Where his history is meant to begin: the start of his setup (recorded by the build), else the earliest statement."""
    try:
        r = con.execute("SELECT max(first_date) FROM statement_periods WHERE kind='start'").fetchone()[0]
        return _d(r) if r else _d(con.execute("SELECT min(first_date) FROM statement_periods WHERE kind <> 'start'").fetchone()[0])
    except Exception:
        return None


def _same_institution(a: Optional[str], b: Optional[str]) -> bool:
    a, b = str(a or "").strip().lower(), str(b or "").strip().lower()
    return bool(a and b and (a in b or b in a))                 # an unknown institution never matches: it stays its own row for him to confirm


def _same_kind(cand_kind: Optional[str], acc_kind: Optional[str]) -> bool:
    bankish = {"bank", "fd_certificate"}
    return (cand_kind in bankish) == (acc_kind in ("bank", "fd", "deposit"))


def matrix(con, now: datetime) -> List[dict]:
    """One row per account the system knows of: how it was found, whether it is set up, what its statements cover, what is open against it."""
    out: List[dict] = []
    set_up = _set_up(con)
    by_last4: Dict[str, list] = {}
    by_dp: Dict[str, dict] = {}
    earliest, today = _earliest(con), now.date()
    confirmed = inventory_confirmed(con) and _confirmed_covers_all(con)
    for a in set_up:
        pk = PERIOD_KIND.get(a["kind"])
        cov = statement_cover(periods(con, a["id"], pk), earliest, today) if pk else None
        if cov is None:
            nxt, ok = "no statement kind proves this account yet (its figures come from the other statements)", False
        elif cov["from"] is None:
            nxt, ok = "no statement of it has been read into the ledger yet", False
        else:
            bits = ([f"no statement covers {', '.join(cov['holes'][:3])}"] if cov["holes"] else []) + \
                   ([f"statements end {cov['to']}: newer ones are missing"] if cov["stale"] else []) + \
                   ([f"statements begin {cov['from']}, later than the rest: opened later, or the first ones are missing"]
                    if cov["late_start"] and not confirmed else [])        # (2026-10-31) he confirmed every account and file: it was opened then
            nxt, ok = ("; ".join(bits) or None), not bits
        out.append({"account": f"{a['provider'] or a['kind']} ({a['id']})", "state": "set up" + (", closed" if a["closed"] else ""), "found_in": "your setup",
                    "covered_from": str(cov["from"]) if cov and cov["from"] else None, "covered_to": str(cov["to"]) if cov and cov["to"] else None,
                    "statement_holes": (cov or {}).get("holes", []), "verified": ok, "files_seen": 0, "next": nxt})
        if a["ref"]:                                           # (audit F4) the last four digits alone are not an identity: kept with the institution and kind
            by_last4.setdefault(str(a["ref"])[-4:], []).append((out[-1], str(a["provider"] or "").lower(), a["kind"]))
            if a["kind"] in ("demat", "broker"):
                by_dp[str(a["ref"]).strip().upper()] = out[-1]          # a depository id is a full identity on its own
    for ck, lab, n, srcs, st, l4, cbank, ckind in con.execute("SELECT cand_key, label, n_files, sources, state, last4, bank, kind FROM account_candidates "
                                                              "ORDER BY first_seen").fetchall():
        if st == "not_mine":
            continue
        if st == LEFT_OUT:                                     # his choice: shown, never counted as a gap, never asked about
            out.append({"account": lab, "state": "left out by you (add later)", "found_in": srcs or "you said so", "files_seen": int(n),
                        "verified": False, "key": ck, "next": "drop its statements in Inbox and files when you want it counted, or press Add back"})
            continue
        same = [r for r, prov, k in by_last4.get(l4 or "", []) if _same_institution(cbank, prov) and _same_kind(ckind, k)] if l4 else []
        if not same:
            row = con.execute("SELECT dp_ids FROM account_candidates WHERE cand_key=?", [ck]).fetchone()
            dps_c = [x.strip().upper() for x in str((row or [None])[0] or "").split(",") if x.strip()]
            same = list({id(by_dp[d]): by_dp[d] for d in dps_c if d in by_dp}.values())
            if dps_c and all(d in by_dp for d in dps_c):
                same = same[:1]                            # one statement listing several demats that are ALL set up: nothing new, one row
        if len(same) == 1:                                     # the same account as one that is set up: one row, with the files seen added
            row = same[0]
            row["files_seen"] += int(n)
            row["found_in"] = f"{row['found_in']}, {srcs}" if srcs else row["found_in"]
            continue
        out.append({"account": lab, "state": "discovered, not set up", "found_in": srcs or "statements", "files_seen": int(n), "verified": False, "key": ck,
                    "next": "confirm it is yours in Setup, leave it out for now, or tell me it is not yours"})
    return out


LEFT_OUT = "left_out"


def leave_out(con, key: str) -> bool:
    """His choice: an account he will not add now (inactive, no login, little in it). It stays listed, is never a gap or a question, and comes back when he
    gives a statement for it or presses Add back."""
    n = con.execute("SELECT count(*) FROM account_candidates WHERE cand_key=? AND state<>?", [key, LEFT_OUT]).fetchone()[0]
    con.execute("UPDATE account_candidates SET state=? WHERE cand_key=?", [LEFT_OUT, key])
    return bool(n)


def add_back(con, key: str) -> bool:
    n = con.execute("SELECT count(*) FROM account_candidates WHERE cand_key=? AND state=?", [key, LEFT_OUT]).fetchone()[0]
    con.execute("UPDATE account_candidates SET state='discovered' WHERE cand_key=? AND state=?", [key, LEFT_OUT])
    return bool(n)


def declare_left_out(con, text: str, now: datetime) -> Optional[str]:
    """An account he has but that no file of his shows (it never will, or not now): written down as left out, so the inventory is honest about it."""
    text = " ".join(str(text or "").split())[:60]
    if not text:
        return None
    k = key_of("declared", text.lower(), None, None)
    if not con.execute("SELECT 1 FROM account_candidates WHERE cand_key=?", [k]).fetchone():
        con.execute("INSERT INTO account_candidates (cand_key, first_seen, last_seen, kind, bank, last4, dp_ids, label, n_files, sources, state) "
                    "VALUES (?,?,?,'declared',NULL,NULL,NULL,?,0,'you said so',?)", [k, now, now, text, LEFT_OUT])
    return k


def gaps(con) -> List[dict]:
    from pflab.app import readiness
    return [g for g in readiness.gaps(con) if g["key"].startswith("coverage:")]


CONFIRMED = "coverage:inventory:confirmed"


def inventory_confirmed(con) -> bool:
    """Only the investor's explicit confirmation counts (`confirm_inventory`, from the screen); a reply to the question may add an account instead."""
    return bool(con.execute("SELECT count(*) FROM memory WHERE kind='answer' AND subject=? AND valid_to IS NULL", [CONFIRMED]).fetchone()[0])


def confirm_inventory(con, now: datetime) -> int:
    """He says: this is every account and every file. Kept as a dated answer; adding an account later does not undo it, but a NEW account
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
    now_keys = {k[0] for k in con.execute("SELECT cand_key FROM account_candidates WHERE state NOT IN ('not_mine', 'left_out')").fetchall()}
    return now_keys <= listed


def status(con, now: datetime) -> dict:
    """{label, reasons}: nothing read yet | partial | complete. `complete` needs every condition; each missing one is a reason."""
    from pflab.ledger import system
    if system.active():                                      # S77: the account is the system's own: there is nothing of his to cover or confirm
        return {"label": "complete", "reasons": [], "accounts": 2, "open_gaps": 0, "left_out": [], "note": "the system's own account: no statements, nothing to confirm"}
    mx = matrix(con, now)
    gp = gaps(con)
    reasons: List[str] = []
    if not mx:
        return {"label": "nothing read yet", "reasons": ["no statement has been read yet and no account has been found"], "accounts": 0, "open_gaps": 0,
                "left_out": []}
    if gp:
        reasons.append(f"{len(gp)} file(s) could not be used and are listed")
    from pflab.app import readiness
    diffs = readiness.gaps(con, "ledger")                    # (audit 2026-10-30) a record that does not yet agree with the statements is not complete
    if diffs:
        reasons.append(f"{len(diffs)} difference(s) between the record and the statements are still open")
    un =[r for r in mx if r["state"] == "discovered, not set up"]
    if un:
        reasons.append(f"{len(un)} account(s) were found in statements but are not set up")
    unv = [r for r in mx if r["state"].startswith("set up") and not r["verified"]]
    for r in unv[:4]:
        reasons.append(f"{r['account']}: {r['next']}")
    if len(unv) > 4:
        reasons.append(f"and {len(unv) - 4} more set-up account(s) whose statements do not yet cover their history")
    if not inventory_confirmed(con):
        reasons.append("you have not confirmed that this is every account and every file you have")
    elif not _confirmed_covers_all(con):
        reasons.append("an account was found after you confirmed the list: please confirm again")
    return {"label": "partial" if reasons else "complete", "reasons": reasons, "accounts": len(mx), "open_gaps": len(gp),
            "left_out": [r["account"] for r in mx if r["state"].startswith("left out")],
            "note": "files alone cannot show that no account is missing: the inventory is always yours to confirm"}


def ask_inventory(con, now: datetime) -> Optional[int]:
    """Once there is an inventory: ONE grouped question listing the masked accounts and asking for what is absent. Never twice."""
    from pflab.agents import questions
    mx = matrix(con, now)
    if not mx:
        return None
    lines = "; ".join(f"{r['account']} [{r['state']}]" for r in mx[:12])
    text = (f"Here is every account I have found so far: {lines}. Tell me in one reply: which of these are not yours or are closed; any account, "
            "broker, bank or deposit that is NOT in this list (or that you will add later: say so and it is written down as left out). "
            "I will not call the picture complete until you confirm.")
    return questions.ask(con, "companion", "coverage:inventory", text[:1200], now)
