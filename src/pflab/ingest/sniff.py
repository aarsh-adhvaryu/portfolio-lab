"""What is this file? Decided by its content, not its name (S65, S64 Phase 7 item 3).

A PDF's first pages (pypdf) or a workbook's / CSV's first rows are read for the signs of each kind:

    tradebook      Zerodha Console tradebook columns (symbol, isin, trade_type, trade_id ...)
    funds_ledger   Console funds ledger (particulars, posting date, voucher type, debit, credit, net balance)
    contract_note  a Zerodha contract note workbook
    cas            a depository consolidated account statement (NSDL or CDSL), with the DP / client ids it lists
    bank           a bank statement: the bank's name and the last four digits of the account number
    gift_city      a Zerodha GIFT City (IFSC) statement
    fd_summary     a bank's fixed deposit summary (account, principal, maturity amount and date, rate, start)
    other          anything else (the name-based guess then stands)

An encrypted file is opened with the passwords of the secrets file's [passwords] section, tried in turn, in memory; none is
printed. Nothing here writes. `match_account` maps a bank statement to the account the investor set up (his bank name and the
last four digits), or says it does not know: then the system asks which account it is.
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence

BANKS = {"SBI": ("state bank of india", "sbi "), "HDFC": ("hdfc bank",), "ICICI": ("icici bank",), "AXIS": ("axis bank",),
         "KOTAK": ("kotak mahindra",), "IDFC": ("idfc first",), "YES": ("yes bank",), "PNB": ("punjab national bank",),
         "BOB": ("bank of baroda",), "CANARA": ("canara bank",), "UNION": ("union bank of india",)}
MAX_ROWS = 60


def _pairs(passwords) -> List[tuple]:
    """Passwords as (name, value): a bare value has no name."""
    return [p if isinstance(p, tuple) else (None, p) for p in passwords]


def _pdf_text(data: bytes, passwords=(), pages: int = 2) -> tuple:
    """(text, the name of the password that opened it, or None)."""
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(data))
    used = None
    if r.is_encrypted:
        for name, pw in _pairs(passwords):
            if r.decrypt(pw):
                used = name
                break
        else:
            return "", None
    return "\n".join((r.pages[i].extract_text() or "") for i in range(min(pages, len(r.pages)))), used


def _rows(data: bytes, name: str, passwords=()) -> tuple:
    """(the first rows of a workbook or CSV as text, the name of the password that opened it, or None)."""
    ext = Path(name).suffix.lower()
    if ext == ".csv":
        import csv
        text = data.decode("utf-8-sig", errors="replace")
        return [r for _, r in zip(range(MAX_ROWS), csv.reader(io.StringIO(text)))], None
    from pflab.ingest import bank, tradebook
    data = tradebook.name_sheets(data)                  # some Console exports name no sheet: filled in memory, as the ledger's parser does
    last = None
    for pname, pw in [(None, None)] + _pairs(passwords):
        try:
            rows = bank._sheet_rows(data, pw)
            return [[("" if c is None else str(c)) for c in r] for r in rows[:MAX_ROWS]], pname
        except bank.StatementError as e:
            last = e
    raise last or bank.StatementError("unreadable workbook")


def _low(rows: List[list]) -> List[str]:
    return [str(c).strip().lower() for r in rows for c in r if str(c).strip()]


def from_text(text: str) -> Dict[str, Optional[str]]:
    """Kind, bank and last four digits from a PDF's text."""
    t = re.sub(r"\s+", " ", text).lower()
    out: Dict[str, Optional[str]] = {"kind": "other", "bank": None, "last4": None, "dp_ids": None}
    if re.search(r"year\s+ended\s+31st\s+march\s+\d{4}", t) and "interest" in t and ("tdr" in t or "stdr" in t or "deposit" in t):
        out["kind"] = "fd_certificate"                          # a deposit interest certificate (SBI's layout: ingest/sbi_interest_cert.py)
        out["bank"] = "SBI" if "state bank" in t else None
    elif "gift city" in t or "ifsc unit" in t or "international financial services centre" in t and "zerodha" in t:
        out["kind"] = "gift_city"
    elif re.search(r"contract\s*note\s*no", t) and "trade date" in t and "zerodha" in t:
        out["kind"] = "contract_note"                           # one day's Zerodha contract note as a PDF (2026-10-31)
    elif "transaction with holding statement" in t or "statement of transaction" in t:
        out["kind"] = "other"                                   # a broker DP's own statement, not a CAS the ledger can read
    elif "consolidated account statement" in t and ("nsdl" in t or "cdsl" in t or "depository" in t):
        out["kind"] = "cas"
        out["dp_ids"] = ",".join(sorted(set(re.findall(r"dp\s*id\s*[:\-]?\s*([a-z0-9]{8})", t)))) or None
    else:
        for code, names in BANKS.items():
            if any(n in t for n in names) and ("account statement" in t or "statement of account" in t or "account no" in t
                                               or "account number" in t):
                out["kind"], out["bank"] = "bank", code
                m = re.search(r"account\s*(?:no\.?|number)\s*[:\-]?\s*[x*\s]*(\d[\d\s]{2,})", t)
                if m:
                    out["last4"] = re.sub(r"\D", "", m.group(1))[-4:]
                break
    return out


def from_rows(rows: List[list]) -> Dict[str, Optional[str]]:
    """Kind, bank and last four digits from a workbook's or CSV's first rows."""
    cells = _low(rows)
    text = " | ".join(cells)
    out: Dict[str, Optional[str]] = {"kind": "other", "bank": None, "last4": None, "dp_ids": None}
    heads = [set(str(c).strip().lower().replace(" ", "_") for c in r if str(c).strip()) for r in rows]   # "Trade Type" (xlsx) = "trade_type" (csv)
    has = lambda *cols: any(all(c in h for c in cols) for h in heads)       # noqa: E731
    if has("symbol", "isin", "trade_type", "trade_id"):
        out["kind"] = "tradebook"
    elif has("particulars", "posting_date", "voucher_type") or has("particulars", "debit", "credit", "net_balance"):
        out["kind"] = "funds_ledger"
    elif "contract note" in text:
        out["kind"] = "contract_note"
    elif _fd_summary(rows):
        from pflab.ingest import fd_summary
        out["kind"], out["bank"] = "fd_summary", fd_summary.bank_of(rows)            # a bank's fixed deposit summary (2026-10-31)
    elif any(("txn date" in c or c == "date") for c in cells) and any(d in c for c in cells for d in ("description", "narration", "details")) \
            and any(d in c for c in cells for d in ("debit", "withdrawal")) and any(d in c for c in cells for d in ("credit", "deposit")):
        out["kind"] = "bank"
        for code, names in BANKS.items():
            if any(n in text + " " for n in names):
                out["bank"] = code
                break
        m = re.search(r"account\s*(?:no\.?|number)\s*[:\-]?\s*[x*\s]*(\d[\d\s]{2,})", text)
        if m:
            out["last4"] = re.sub(r"\D", "", m.group(1))[-4:]
    elif "tijori" in text or "screener" in text:
        out["kind"] = "market"
    return out


def _fd_summary(rows) -> bool:
    from pflab.ingest import fd_summary
    return fd_summary.is_summary(rows)


def sniff(data: bytes, name: str, passwords=()) -> Dict[str, Optional[str]]:
    """Look inside the file. A file that cannot be opened (a wrong password, a damaged file) is `other` with a reason. `passwords`: values, or
    (name, value) pairs; the NAME of the one that opened the file is returned as `password_name` (the value never)."""
    ext = Path(name).suffix.lower()
    try:
        if data[:5] == b"%PDF-" or ext == ".pdf":
            text, used = _pdf_text(data, passwords)
            if not text.strip():
                return {"kind": "other", "bank": None, "last4": None, "dp_ids": None, "why": "no text read (a password, or a scan)"}
            return {**from_text(text), **({"password_name": used} if used else {})}
        if ext in (".xlsx", ".xls", ".csv"):
            rows, used = _rows(data, name, passwords)
            return {**from_rows(rows), **({"password_name": used} if used else {})}
    except Exception as e:                                          # a damaged or locked file is "other", not a crash
        return {"kind": "other", "bank": None, "last4": None, "dp_ids": None, "why": f"{type(e).__name__}"}
    return {"kind": "other", "bank": None, "last4": None, "dp_ids": None}


def is_encrypted(data: bytes, name: str) -> bool:
    """A password-protected PDF or Office file (its content is not read)."""
    try:
        if data[:5] == b"%PDF-":
            from pypdf import PdfReader
            return bool(PdfReader(io.BytesIO(data)).is_encrypted)
        from pflab.ingest import bank
        if data[:8] == bank.OLE_MAGIC:
            import msoffcrypto
            return bool(msoffcrypto.OfficeFile(io.BytesIO(data)).is_encrypted())
    except Exception:
        return False
    return False


def match_account(info: Dict[str, Optional[str]], accounts: Dict[str, dict]) -> Optional[str]:
    """The set-up bank account whose bank and last four digits this statement shows; None when none or two fit."""
    if info.get("kind") != "bank" or not info.get("last4"):
        return None
    hits = [k for k, v in accounts.items() if v.get("kind") == "bank" and str(v.get("last4", "")) == info["last4"]
            and (not info.get("bank") or str(v.get("bank", "")).upper() in ("", info["bank"]))]
    return hits[0] if len(hits) == 1 else None


def passwords_from_secrets() -> List[tuple]:
    """(name, value) of the secrets file's [passwords] (statement passwords), for opening encrypted files in memory; only the NAME of the one
    that opened a file is ever kept."""
    try:
        from pflab.pm import secrets as sec
        s = sec.load()
        return [(k.split(".", 1)[1], s.get("passwords", k.split(".", 1)[1])) for k in s.names() if k.startswith("passwords.")]
    except Exception:
        return []
