"""Redaction before text leaves the PC (S60, PLAN A18; the investor 2026-10-24: statements may go to Claude, redacted).

`redact(text, gate)` replaces his identity and banking details with tokens and returns the text and the counts by kind
(never the values):

    PAN                 [PAN]
    e-mail, phone       [EMAIL], [PHONE]
    UPI id, IFSC        [UPI], [IFSC]
    account numbers     [ACCOUNT-1], [ACCOUNT-2], ... one token per distinct value: the ledger's account, depository,
                        folio and deposit ids (`egress.Gate.ids`), a labelled number ("A/c No: ...", "Folio No ...",
                        "Client ID ...", "DP ID ..."), a depository id (IN + 14 digits) and any run of 9 to 18 digits
    his name            [NAME] (api_budget.toml [egress] names)
    address             [ADDR] for a line with an address word or a PIN code beside one, a line with his address words
                        (api_budget.toml [egress] address), and the address-word lines within BLOCK lines of those
                        (an address runs over several lines)

`for_api(text, gate)` redacts and then runs the egress check on the result: it returns only text that passes, else it
raises. Transaction rows (dates, amounts, scheme and company names) stay: The investor's decision is that they may go.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from pflab.hq import egress

LABEL = re.compile(r"\b(?:a/c|acct|account|folio|client|dp|demat|bo|beneficiary|customer|cif|crn|ucc)\b\.?\s*"
                   r"(?:no\.?|number|num|id|code)?\s*[:#.-]?\s*([A-Z0-9][A-Z0-9/-]{3,})", re.I)
LABEL_WORD = re.compile(r"\b(?:a/c|account|acct|folio|client|dp|demat)\s*(?:no\.?|number|id)\b", re.I)
DEPOSITORY = re.compile(r"\bIN\d{14}\b")
DIGITS = re.compile(r"(?<![\d.,])\d{9,18}(?![\d.,])")
PIN = re.compile(r"\b[1-9]\d{5}\b")
BLOCK = 3                                            # lines: an address block's reach
ADDRESS_WORDS = re.compile(r"\b(address|flat|floor|apartment|apt|building|bldg|road|rd|street|lane|nagar|society|sector|"
                           r"near|opp|taluka|tehsil|district|dist|pin ?code|pincode|postal code|house no|plot)\b", re.I)
SIMPLE = [("PAN", egress.NEVER["PAN"], "[PAN]"), ("e-mail", egress.NEVER["e-mail"], "[EMAIL]"),
          ("UPI id", egress.NEVER["UPI id"], "[UPI]"), ("IFSC code", egress.NEVER["IFSC code"], "[IFSC]"),
          ("phone", egress.NEVER["phone"], "[PHONE]")]


def redact(text: str, gate: egress.Gate, address: Optional[List[str]] = None,
           lines: bool = True) -> Tuple[str, Dict[str, int]]:
    """`address`: his address words (default `gate.address`, from api_budget.toml [egress] address). `lines=False` (a
    tool's JSON result, one line of public and code-made text): no address-line rule, only his own address words are
    replaced; a filing that names its registered office is not his address."""
    counts: Dict[str, int] = {}
    tokens: Dict[str, str] = {}

    def acct(value: str) -> str:
        if value not in tokens:
            tokens[value] = f"[ACCOUNT-{len(tokens) + 1}]"
        counts["account number"] = counts.get("account number", 0) + 1
        return tokens[value]

    addr = [w for w in (address if address is not None else gate.address) if w]
    if lines:
        kept = text.split("\n")
        worded = {i for i, line in enumerate(kept) if ADDRESS_WORDS.search(line)}
        hit = {i for i, line in enumerate(kept)
               if egress.NEVER["address"].search(line) or (i in worded and PIN.search(line))
               or any(w in line.lower() for w in addr)
               or (PIN.search(line) and len(line.strip()) <= 60 and any(abs(i - j) <= BLOCK for j in worded))}
        grew = True
        while grew:                                  # an address runs over lines: its neighbours with address words
            more = {i for i, line in enumerate(kept) if i not in hit and ADDRESS_WORDS.search(line)
                    and any(abs(i - j) <= BLOCK for j in hit)}
            hit |= more
            grew = bool(more)
        for i in hit:
            kept[i] = "[ADDR]"                       # not "[ADDRESS]": the egress list reads that word
        if hit:
            counts["address"] = len(hit)
        out = "\n".join(kept)
    else:
        out = text
        for w in addr:
            out, n = re.subn(re.escape(w), "[ADDR]", out, flags=re.I)
            if n:
                counts["address"] = counts.get("address", 0) + n
    for i in sorted(gate.ids, key=len, reverse=True):            # the ledger's own ids first, whole
        if i in out:
            out = out.replace(i, acct(i))
    out = LABEL.sub(lambda m: acct(m.group(1).upper()) if re.search(r"\d", m.group(1)) else m.group(0), out)
    out = LABEL_WORD.sub("[ACCOUNT-LABEL]", out)
    out = DEPOSITORY.sub(lambda m: acct(m.group(0)), out)
    for kind, rx, tok in SIMPLE:                                 # before the digit runs: a phone is a phone
        out, n = rx.subn(tok, out)
        if n:
            counts[kind] = counts.get(kind, 0) + n
    out = DIGITS.sub(lambda m: acct(m.group(0)), out)
    for n_ in sorted(gate.names, key=len, reverse=True):
        out, n = re.subn(r"\b" + re.escape(n_) + r"\b", "[NAME]", out, flags=re.I)
        if n:
            counts["his name"] = counts.get("his name", 0) + n
    return out, counts


def for_api(text: str, gate: egress.Gate, address: Optional[List[str]] = None) -> Tuple[str, Dict[str, int]]:
    """Redacted text that passes the egress check (raises egress.EgressBlocked naming what is left otherwise)."""
    out, counts = redact(text, gate, address)
    egress.check(out, gate)
    return out, counts


# --- statements on this PC, and his address words from them ----------------------------------------------------------

def statement_text(path: Path, passwords: Sequence[str] = ()) -> str:
    """A statement file's text, read on this PC: PDF (pypdf, trying each password), Excel (`ingest.bank`: encrypted
    .xlsx and legacy .xls), CSV. Raises when it cannot be opened."""
    import io
    raw = Path(path).read_bytes()
    suf = Path(path).suffix.lower()
    if suf == ".pdf":
        from pypdf import PdfReader
        rd = PdfReader(io.BytesIO(raw))
        if rd.is_encrypted and not any(_try(rd, p) for p in ["", *passwords]):
            raise ValueError("no password opened it")
        return "\n".join((pg.extract_text() or "") for pg in rd.pages)
    if suf == ".csv":
        return raw.decode("utf-8-sig", "replace")
    from pflab.ingest import bank
    last: Exception = ValueError("not opened")
    for p in [None, *passwords]:
        try:
            return "\n".join("\t".join("" if v is None else str(v) for v in r) for r in bank._sheet_rows(raw, p))
        except Exception as e:
            last = e
    raise last


def _try(reader, password: str) -> bool:
    try:
        return bool(reader.decrypt(password))
    except Exception:
        return False


NEAR_NAME = 6                                        # lines after his name where a statement prints his address
COMMON_MIN = 3                                       # a word in this many public document titles is not his address


def address_from(texts: Sequence[str], gate: egress.Gate, common: Set[str]) -> List[str]:
    """His address words: from the address lines printed within NEAR_NAME lines after his name, the words of 4+ letters
    that are not address vocabulary, his name, or common in public documents (`common`), found in at least two
    statements (an address repeats; a one-off line does not)."""
    seen: Dict[str, int] = {}
    name = set(w for n in gate.names for w in re.findall(r"[a-z]+", n))
    for text in texts:
        lines = text.split("\n")
        mine = set()
        for i, line in enumerate(lines):
            if any(re.search(r"\b" + re.escape(n) + r"\b", line.lower()) for n in gate.names):
                for j in range(i + 1, min(len(lines), i + 1 + NEAR_NAME)):
                    if ADDRESS_WORDS.search(lines[j]) or PIN.search(lines[j]) or egress.NEVER["address"].search(lines[j]):
                        mine |= {w for w in re.findall(r"[a-z]{4,}", lines[j].lower())
                                 if not ADDRESS_WORDS.fullmatch(w) and not ADDRESS_WORDS.fullmatch(w[:-1])   # plurals
                                 and w not in name and w not in common}
        for w in mine:
            seen[w] = seen.get(w, 0) + 1
    return sorted(w for w, n in seen.items() if n >= 2)


def common_words(con) -> Set[str]:
    """Words in at least COMMON_MIN public document titles of the knowledge graph (cities, banks, everyday words)."""
    counts: Dict[str, int] = {}
    for (t,) in con.execute("SELECT title FROM kg_docs WHERE kind IN ('filing', 'result', 'article') AND title IS NOT NULL"
                            ).fetchall():
        for w in set(re.findall(r"[a-z]{4,}", t.lower())):
            counts[w] = counts.get(w, 0) + 1
    return {w for w, n in counts.items() if n >= COMMON_MIN}


def write_address(path: Path, words: Sequence[str]) -> None:
    """Set `address = [...]` under [egress] in api_budget.toml, keeping every other line as it is."""
    lines = Path(path).read_text(encoding="utf-8").split("\n") if Path(path).exists() else []
    value = "address = [" + ", ".join(f'"{w}"' for w in words) + "]   # his address words (S60, from his statements)"
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "[egress]")
    except StopIteration:
        lines += ["", "[egress]", value]
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
        at = next((i for i in range(start + 1, end) if re.match(r"\s*address\s*=", lines[i])), None)
        if at is None:
            lines.insert(start + 1, value)
        else:
            lines[at] = value
    Path(path).write_text("\n".join(lines), encoding="utf-8")
