"""The local screen (S85, A71): what is checked ON THIS PC before anything he sends can reach an API.

    check_text(text, con=None)   -> {"ok", "text" (masked), "masked" (kinds, never values), "flagged", "refused" (a one-line reply or None)}
    check_file(path, name, mime) -> {"ok", "kind" ("pdf" "sheet" "image" "text" "statement" "other"), "refused" (a one-line reply or None), "reason", "score", "mask_needed", "pages", "scanned", ...}

What may go (A71): his portfolio (holdings, amounts, weights, goals). What never goes: his identity and banking details (PAN, Aadhaar, account, folio, client and DP numbers, IFSC, UPI, card, phone,
e-mail, name, address words) and a personal record (A36: a bank or broker statement, a contract note, a tax paper, a deposit or bank letter). The screen reads:
  * the terms file `%USERPROFILE%\\.pflab\\privacy_terms.json` (through `hq.security.load_terms`; its content is never printed), and the ledger's own ids when a connection is given (`hq.egress.load`);
  * patterns: PAN, Aadhaar, bank account numbers (a labelled number, a run of 9 to 18 digits), IFSC, UPI, a card number (13 to 19 digits that pass the Luhn check), phone, e-mail;
  * the statement detector: `ingest.sniff` (the kinds the ledger reads) plus content markers scored below.
A message that only NAMES a term is masked (`hq.redact`) and goes on; a message with a number of that kind is masked too and `flagged`. A file that is a personal record is REFUSED: the caller stores nothing,
sends nothing and gives him `refused` as the one line. A file that cannot be checked (locked, a scan with no OCR on this PC) is refused as well: the screen fails closed.
"""
from __future__ import annotations

import io
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pflab.hq import egress, redact

log = logging.getLogger("pflab.screen")

TEXT_EXT = {".txt", ".md", ".markdown", ".json", ".log", ".html", ".htm"}
SHEET_EXT = {".xlsx", ".xls", ".xlsm", ".csv", ".tsv"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
MAX_TEXT_CHARS = 600_000                              # what is screened of one text; the rest is not read at all
SCAN_PAGES = 400                                      # pages of a PDF whose text is screened
REFUSE_AT = 3                                         # the personal-record score at which a file is refused
OCR_PS1 = Path(__file__).resolve().parents[3] / "tools" / "ocr.ps1"

LINE_REFUSED = ("That looks like a personal record of yours (a bank or broker statement, a tax paper or a deposit letter). I do not read, keep or send those: "
                "nothing was stored and nothing left this PC.")

# --- patterns --------------------------------------------------------------------------------------------------------------------------
PAN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{5}\d{4}[A-Za-z](?![A-Za-z0-9])")
PERSON_PAN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{3}[Pp][A-Za-z]\d{4}[A-Za-z](?![A-Za-z0-9])")        # the fourth letter P: an individual (a company's PAN is not his identity)
AADHAAR = re.compile(r"(?<![\d,.])[2-9]\d{3}[ -]\d{4}[ -]\d{4}(?!\d|[.,]\d)")
AADHAAR_LABELLED = re.compile(r"(?:aadhaar|aadhar|uidai|uid)\b\D{0,12}([2-9]\d{11})(?!\d)", re.I)
IFSC = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{4}0[A-Za-z0-9]{6}(?![A-Za-z0-9])")
CARD = re.compile(r"(?<![\d.,])(?:\d[ -]?){12,18}\d(?!\d|[.,]\d)")
BARE_ACCOUNT = re.compile(r"(?<![\d.,])\d{9,18}(?!\d|[.,]\d)")
ADDR_PHRASE = re.compile(r"\b(?:pin ?code|postal code|flat no\.?|house no\.?)\s*[:#.-]?\s*[\w/-]+", re.I)
ACCOUNT_LABELLED = re.compile(r"\b(?:a/c|acct|account|folio|client|dp|demat|beneficiary|customer|cif|crn|ucc)\b\.?\s*(?:no\.?|number|num|id|code)?\s*[:#.-]?\s*([A-Z0-9][A-Z0-9/-]{5,})", re.I)

STRONG_MARKERS = ("statement of account", "account statement", "bank statement", "consolidated account statement", "transaction with holding statement", "statement of transaction",
                  "holding statement", "demat statement", "contract note", "form 26as", "form no. 26as", "annual information statement", "itr-v", "itr v ", "income tax return acknowledgement",
                  "income tax return", "form 16", "form no. 16", "tds certificate", "fixed deposit receipt", "deposit receipt", "fd receipt", "interest certificate", "passbook",
                  "capital gains statement", "tax p&l", "tradebook", "trade book", "funds statement", "ledger statement", "balance confirmation", "account opening form",
                  "know your customer", "kyc form", "cancelled cheque", "cheque book", "fund transfer receipt", "loan statement", "credit card statement", "salary slip", "payslip")
PUBLIC_MARKERS = ("circular", "securities and exchange board of india", "press release", "annual report", "investor presentation", "notice of", "regulations,")
DATE_ROW = re.compile(r"\b\d{1,2}[-/ ](?:\d{1,2}|[A-Za-z]{3})[-/ ]\d{2,4}\b")
AMOUNT = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?(?![\w])|(?<![\w.])\d+\.\d{2}(?![\w])")


def _luhn(digits: str) -> bool:
    s, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        s += d
        alt = not alt
    return s % 10 == 0


def _cards(text: str) -> List[str]:
    out = []
    for m in CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            out.append(m.group(0))
    return out


# --- his terms -------------------------------------------------------------------------------------------------------------------------

def gate_for(con=None) -> egress.Gate:
    """His ids, name and address words: the terms file (`hq.security.load_terms`), and the ledger's own ids and api_budget.toml when a store connection is given. Missing sources leave the others."""
    g = egress.Gate()
    try:
        from pflab.hq import security
        t = security.load_terms()
        if t:
            g.ids |= set(t[0].ids)
            g.names += [n for n in t[0].names if n not in g.names]
            g.address += [a for a in t[0].address if a not in g.address]
    except Exception as e:                           # an unreadable terms file never stops the screen: the other sources and the patterns still run
        log.debug("terms file not read: %s", e)
    if con is not None:
        try:
            h = egress.load(con)
            g.ids |= h.ids
            g.names += [n for n in h.names if n not in g.names]
            g.address += [a for a in h.address if a not in g.address]
        except Exception as e:
            log.debug("ledger ids not read: %s", e)
    return g


def _term_hits(text: str, gate: egress.Gate) -> List[str]:
    """Which of his TERMS the text names (kinds only): his name, his address words, one of his ids."""
    out = []
    low = text.lower()
    if any(re.search(r"\b" + re.escape(n) + r"\b", low) for n in gate.names if n):
        out.append("his name")
    if any(re.search(r"\b" + re.escape(a) + r"\b", low) for a in gate.address if a):
        out.append("his address words")
    if any(i and re.search(r"(?<![A-Za-z0-9])" + re.escape(i) + r"(?![A-Za-z0-9])", text) for i in gate.ids):
        out.append("an account, depository, folio or deposit id")
    return out


# --- text ------------------------------------------------------------------------------------------------------------------------------

def mask(text: str, gate: egress.Gate) -> Tuple[str, List[str], List[str]]:
    """(masked text, kinds masked, kinds that were NUMBERS of his identity or banking). Nothing of the value is kept."""
    kinds: Dict[str, int] = {}
    sensitive: List[str] = []
    out = text[:MAX_TEXT_CHARS]

    def sub(rx, token: str, kind: str, number: bool = True, fn=None) -> None:
        nonlocal out
        out, n = rx.subn(fn or token, out)
        if n:
            kinds[kind] = kinds.get(kind, 0) + n
            if number and kind not in sensitive:
                sensitive.append(kind)

    for c in _cards(out):                                           # before the digit-run rule: a card is a card
        out = out.replace(c, "[CARD]")
        kinds["card number"] = kinds.get("card number", 0) + 1
        if "card number" not in sensitive:
            sensitive.append("card number")
    sub(AADHAAR_LABELLED, "", "Aadhaar number", fn=lambda m: m.group(0).replace(m.group(1), "[AADHAAR]"))
    sub(AADHAAR, "[AADHAAR]", "Aadhaar number")
    sub(ADDR_PHRASE, "[ADDR]", "address", number=False)
    sub(BARE_ACCOUNT, "[ACCOUNT]", "account number")                  # a run of 9 to 18 digits; one that ends a sentence too (redact leaves a digit run followed by a full stop alone)
    masked, counts = redact.redact(out, gate, lines=False)          # PAN, e-mail, UPI, IFSC, phone, ids, labelled and bare account numbers, his name, his address words
    for k, n in counts.items():
        kinds[k] = kinds.get(k, 0) + n
        if k in ("PAN", "account number", "IFSC code", "UPI id") and k not in sensitive:
            sensitive.append(k)
    return masked, sorted(kinds), sensitive


def personal_record(text: str, gate: egress.Gate, *, rows_text: Optional[str] = None) -> Tuple[int, List[str]]:
    """(score, reasons) of how much `text` looks like a personal record (A36). The caller refuses at `REFUSE_AT`. A public document (a circular, an annual report) that only NAMES a record kind
    scores 0: the header marker counts 3 and the public-document word takes 3 off, so a regulator's circular on contract notes is read; an actual contract note also carries ids, rows or an IFSC."""
    score, why = 0, []
    low = re.sub(r"\s+", " ", text[:MAX_TEXT_CHARS]).lower()
    head = low[:1500]
    hit_head = [m for m in STRONG_MARKERS if m in head]
    hit_any = [m for m in STRONG_MARKERS if m in low]
    if hit_head:
        score += 3
        why.append(f"header says '{hit_head[0]}'")
    elif hit_any:
        score += 2
        why.append(f"mentions '{hit_any[0]}'")
    if _term_hits(text, gate).count("an account, depository, folio or deposit id"):
        score += 3
        why.append("carries one of his account ids")
    if PERSON_PAN.search(text) or AADHAAR.search(text) or AADHAAR_LABELLED.search(text):
        score += 3
        why.append("carries a personal PAN or Aadhaar number")
    if IFSC.search(text) and re.search(r"\b(?:a/c|account)\b", low):
        score += 2
        why.append("an IFSC code beside an account")
    if any(re.search(r"\d", m.group(1)) for m in ACCOUNT_LABELLED.finditer(text)):
        score += 1
        why.append("a labelled account, folio or client number")
    src = rows_text if rows_text is not None else text
    rows = sum(1 for line in src.split("\n") if DATE_ROW.search(line) and len(AMOUNT.findall(line)) >= 2)
    if rows >= 5:
        score += 2
        why.append(f"{rows} dated transaction rows")
    if score and any(m in head for m in PUBLIC_MARKERS) and not _term_hits(text, gate):
        score -= 3
    return score, why


def check_text(text: str, con=None) -> dict:
    """A chat message (or any text on its way out). ok is False only when the text is itself a personal record (pasted statement text): `refused` is then his one line and nothing may be used. Otherwise
    `text` is the masked text to send; `masked` the kinds replaced (never values); `flagged` is True when a NUMBER of his identity or banking was in it."""
    gate = gate_for(con)
    text = text or ""
    if len(text) >= 400 or text.count("\n") >= 6:
        score, why = personal_record(text, gate)
        if score >= REFUSE_AT:
            return {"ok": False, "text": "", "masked": [], "flagged": True, "refused": LINE_REFUSED, "reason": "; ".join(why), "score": score}
    masked, kinds, sensitive = mask(text, gate)
    try:                                                          # a last look at what is left: the egress check the API door runs, so a leftover is caught HERE and not as an error there
        egress.check(masked, gate, skip=("address",))
    except egress.EgressBlocked as e:
        return {"ok": False, "text": "", "masked": kinds, "flagged": True, "reason": str(e),
                "refused": "Part of that looks like identity or banking details that I could not mask safely, so nothing was sent. Please send it again without them.", "score": 0}
    return {"ok": True, "text": masked, "masked": kinds, "flagged": bool(sensitive), "refused": None, "reason": "", "score": 0}


# --- files -----------------------------------------------------------------------------------------------------------------------------

def kind_of(name: str, mime: str = "") -> str:
    ext = Path(name or "").suffix.lower()
    mime = (mime or "").lower()
    if ext == ".pdf" or mime == "application/pdf":
        return "pdf"
    if ext in SHEET_EXT or "spreadsheet" in mime or mime in ("text/csv", "application/vnd.ms-excel"):
        return "sheet"
    if ext in IMAGE_EXT or mime.startswith("image/"):
        return "image"
    if ext in TEXT_EXT or mime.startswith("text/") or mime in ("application/json",):
        return "text"
    return "other"


def ocr_text(path: Path) -> Optional[str]:
    """Windows' own OCR on an image file (`tools/ocr.ps1`; nothing leaves the PC). None when it cannot run (no OCR language, not Windows, a failure): the caller then cannot check the image."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(OCR_PS1), "-Path", str(path)], capture_output=True, timeout=120)
        if r.returncode != 0:
            return None
        return r.stdout.decode("utf-8", "replace").strip()
    except Exception as e:
        log.debug("OCR did not run: %s", e)
        return None


def render_pages(data: bytes, first: int = 0, last: int = 1) -> List[bytes]:
    """PNG bytes of pages `first`..`last` (0-based, inclusive) of a PDF, rendered on this PC (pypdfium2)."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(data)
    out = []
    try:
        for i in range(first, min(last + 1, len(pdf))):
            buf = io.BytesIO()
            pdf[i].render(scale=2).to_pil().save(buf, format="PNG")
            out.append(buf.getvalue())
    finally:
        pdf.close()
    return out


def ocr_png(png: bytes) -> Optional[str]:
    with tempfile.TemporaryDirectory(prefix="pflab_ocr_") as d:
        p = Path(d) / "page.png"
        p.write_bytes(png)
        return ocr_text(p)


def pdf_pages_text(data: bytes, limit: int = SCAN_PAGES) -> Tuple[List[str], bool]:
    """([text of each page], encrypted). Raises on a damaged file."""
    from pypdf import PdfReader
    rd = PdfReader(io.BytesIO(data))
    if rd.is_encrypted:
        return [], True
    return [(rd.pages[i].extract_text() or "") for i in range(min(limit, len(rd.pages)))], False


def sheet_text(data: bytes, name: str, cap_rows: int = 3000) -> str:
    """Every cell of a workbook or CSV as text (the first `cap_rows` rows of each sheet), for the screen only."""
    ext = Path(name).suffix.lower()
    if ext in (".csv", ".tsv"):
        return data.decode("utf-8-sig", "replace")[:MAX_TEXT_CHARS]
    import pandas as pd
    out = []
    book = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, nrows=cap_rows, dtype=str)
    for sheet, df in book.items():
        out.append(f"# {sheet}")
        out += ["\t".join("" if v != v or v is None else str(v) for v in row) for row in df.values.tolist()]
    return "\n".join(out)[:MAX_TEXT_CHARS]


def _verdict(kind: str, score: int, why: List[str], gate: egress.Gate, text: str, **extra) -> dict:
    if score >= REFUSE_AT:
        return {"ok": False, "kind": "statement", "refused": LINE_REFUSED, "reason": "; ".join(why), "score": score, "mask_needed": False, **extra}
    hits = _term_hits(text, gate)
    return {"ok": True, "kind": kind, "refused": None, "reason": "", "score": score, "mask_needed": bool(hits), "term_kinds": hits, **extra}


def _refuse(kind: str, reason: str, line: str) -> dict:
    return {"ok": False, "kind": kind, "refused": line, "reason": reason, "score": REFUSE_AT, "mask_needed": False}


def check_file(path, name: str = "", mime: str = "", con=None) -> dict:
    """The kind of the file and whether it may be read: {"ok", "kind", "refused" (his one line), "reason", "score", "mask_needed" (his name or address words are in the text: only MASKED text may be sent),
    "pages", "scanned"}. A personal record is refused (kind "statement"); a file that cannot be checked is refused too. Nothing is stored or sent here."""
    path = Path(path)
    name = name or path.name
    kind = kind_of(name, mime)
    gate = gate_for(con)
    try:
        data = path.read_bytes()
    except OSError as e:
        return _refuse(kind, f"unreadable: {e}", "I could not open that file here.")
    from pflab.ingest import sniff
    try:
        info = sniff.sniff(data, name)                                # the ledger's own recogniser (tradebooks, contract notes, CAS, bank statements, FD papers)
    except Exception:
        info = {"kind": "other"}
    if info.get("kind") not in (None, "other", "market"):
        return {"ok": False, "kind": "statement", "refused": LINE_REFUSED, "reason": f"recognised as {info['kind']}", "score": REFUSE_AT, "mask_needed": False}
    if kind == "pdf":
        try:
            pages, locked = pdf_pages_text(data)
        except Exception as e:
            return _refuse("pdf", f"not readable: {type(e).__name__}", "I could not open that PDF to check it, so it was not read or sent.")
        if locked:
            return _refuse("pdf", "password-protected", "That PDF is locked, so I cannot check what it is. Send an unlocked copy of a public document; I do not read locked files.")
        text = "\n".join(pages)
        scanned = len(re.sub(r"\s+", "", text)) < 40
        if scanned:
            try:
                shots = render_pages(data, 0, 1)
            except Exception as e:
                return _refuse("pdf", f"scan not rendered: {type(e).__name__}", "That PDF is a scan and I could not check it on this PC, so it was not read or sent.")
            ocr = [ocr_png(s) for s in shots]
            if not shots or any(o is None for o in ocr):
                return _refuse("pdf", "scan, OCR unavailable", "That PDF is a scan and I could not check it on this PC, so it was not read or sent.")
            text = "\n".join(ocr)
        score, why = personal_record(text, gate)
        return _verdict("pdf", score, why, gate, text, pages=len(pages) if pages else 0, scanned=scanned)
    if kind == "sheet":
        if sniff.is_encrypted(data, name):
            return _refuse("sheet", "password-protected", "That file is locked, so I cannot check what it is. I do not read locked files.")
        try:
            text = sheet_text(data, name)
        except Exception as e:
            return _refuse("sheet", f"not readable: {type(e).__name__}", "I could not open that spreadsheet to check it, so it was not read or sent.")
        score, why = personal_record(text, gate, rows_text=text)
        return _verdict("sheet", score, why, gate, text)
    if kind == "image":
        text = ocr_text(path)
        if text is None:
            return _refuse("image", "OCR unavailable", "I could not check that picture on this PC, so it was not read or sent.")
        score, why = personal_record(text, gate)
        v = _verdict("image", score, why, gate, text, ocr_text=text)
        if v["ok"] and v["mask_needed"]:                              # a picture cannot be masked: it shows his name, address or an id
            return _refuse("image", "shows his identity terms", "That picture shows details of yours that must not leave this PC (a name, an address or an id), so it was not read or sent.")
        return v
    if kind == "text":
        text = data.decode("utf-8-sig", "replace")
        if Path(name).suffix.lower() in (".html", ".htm"):
            try:
                import trafilatura
                text = trafilatura.extract(text) or text
            except Exception:
                pass
        score, why = personal_record(text, gate)
        return _verdict("text", score, why, gate, text)
    return {"ok": True, "kind": "other", "refused": None, "reason": "", "score": 0, "mask_needed": False}


__all__ = ["check_text", "check_file", "kind_of", "gate_for", "mask", "personal_record", "LINE_REFUSED"]
