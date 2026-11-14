"""The readers (S85, E3, A71, A72): what he sends is screened on this PC, read by the right reader, kept, and handed to the loop through door (a), the evidence.

    read_attachment(con, now, path, name, mime, *, chat_id=None, msg_id=None) -> {"kind", "facts" [{claim, quote, page}], "summary_text", "document_id", "event_id", "isins", "cost_inr", "warnings", ...}
    check_link(con, now, url, claim=None, *, chat_id=None)                    -> {"verdict", "sources" [{n, url, kind, source, fetched}], "findings", "answer", "isins", "event_id", "node", "cost_inr", ...}
    only_sourced_in(text, source_text)                                         -> (text with every sentence that carries a number not in `source_text` removed, sentences removed)

How each kind is read (A72):
  PDF         Claude reads the PDF as a document (scanned pages too), in parts of at most 30 pages with the page numbers kept; the facts are {claim, quote, page}. A PDF whose text names his name or
              address words is NOT sent: the masked text is.
  sheet / CSV code reads it (pandas): sheet names, columns, row counts, a few rows, totals by column; Claude sees code's summary, never the rows beyond the cap.
  image       Claude's vision; the numbers are checked against the text Windows' own OCR reads from the same picture.
  text        direct, masked by the screen.
Every number in a fact or a summary must be in the source text (`only_sourced_in`): a claim whose number is not found, or whose quote is not in the source, is dropped with a visible note.
The file is kept under `<data>/received_s85/YYYYMMDD/<hash>.<ext>` with a row in `received_docs_s85`; the same bytes sent again are answered from that row (one read, one price). Door (a):
the document is an EVENT with source "you" in the graph (`kg2/you.py`, time = received, linked to ISINs only by the graph's confident rule) and its facts are a dated note `recall` finds
(`recall.write_back`, source "you"). All model calls go through `llm/gateway.py` (agent "reading", role `read`). A personal record is refused by `screen` before anything else happens.
"""
from __future__ import annotations

import base64
import hashlib
import inspect
import io
import json
import logging
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from pflab.entrance import screen


def _gw_vendor_client(secrets=None):
    """S86: the model client for the batch road comes from the gateway (`llm/gateway.py`), the one door; nothing here builds a client itself."""
    from pflab.llm import gateway
    return gateway.vendor_client(secrets)

log = logging.getLogger("pflab.readers")

PART_PAGES = 30                    # pages of a PDF in one request (A72)
MAX_PARTS = 6                      # parts read of one PDF: the rest is said, not hidden
MAX_FACTS_PART = 14
TEXT_PART_CHARS = 30_000
MAX_TEXT_PARTS = 4
MAX_SHEETS = 8
SHEET_ROWS_SHOWN = 5
FETCH_TIMEOUT = 20
FETCH_MAX_BYTES = 3_000_000
SOURCE_CHARS = 14_000              # what the model sees of one fetched page
MAX_SOURCES = 3

FACT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["headline", "summary", "facts"],
               "properties": {"headline": {"type": "string"}, "summary": {"type": "string"},
                              "facts": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["claim", "quote", "page"],
                                                                    "properties": {"claim": {"type": "string"}, "quote": {"type": "string"}, "page": {"type": "integer"}}}}}}
SYSTEM_READ = ("You read one document that the investor sent to his personal investing system. Say what the document states, and nothing else: the facts it gives about companies, markets, rules, prices and dates. "
               "Use only the document. Every number you write must be printed in the document. Each fact has a short EXACT quote from the document and the page it is on. "
               "Never give advice, a view or a forecast of your own. Write plain words. Answer with the JSON asked for only.")
LINK_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["verdict", "summary", "findings"],
               "properties": {"verdict": {"type": "string", "enum": ["supported", "contradicted", "not_found", "unclear"]}, "summary": {"type": "string"},
                              "findings": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["fact", "quote", "source"],
                                                                       "properties": {"fact": {"type": "string"}, "quote": {"type": "string"}, "source": {"type": "integer"}}}}}}
SYSTEM_LINK = ("You check one claim against pages that were fetched for you. The sources are numbered [S1], [S2]. Say whether they SUPPORT the claim, CONTRADICT it, or do not mention it (not_found), "
               "or the answer is unclear. Each finding is a fact the sources state, with an EXACT quote and the number of the source. Use only the sources. Every number you write must be printed in a source. "
               "Never give advice or a view of your own. Plain words. Answer with the JSON asked for only.")

# where a claim is checked first: the original source, by domain (code, not a model)
SOURCE_TYPES: Dict[str, Tuple[str, str]] = {
    "nseindia.com": ("exchange", "NSE"), "nsearchives.nseindia.com": ("exchange", "NSE"), "bseindia.com": ("exchange", "BSE"), "sec.gov": ("filing", "SEC"),
    "rbi.org.in": ("regulator", "RBI"), "sebi.gov.in": ("regulator", "SEBI"), "mca.gov.in": ("regulator", "MCA"), "incometax.gov.in": ("regulator", "Income Tax Department"),
}
OFFICIAL = ("exchange", "filing", "regulator", "company")


def source_type(url: str) -> Tuple[str, str]:
    """(kind, name) of a URL: an exchange, a filing, a regulator, a company's investor page, or secondary (news, blogs, anything else)."""
    u = urlparse(url if "//" in url else "//" + url)
    host = (u.hostname or "").lower()
    for dom, kn in SOURCE_TYPES.items():
        if host == dom or host.endswith("." + dom):
            return kn
    if re.match(r"^(?:investors?|ir)\.", host) or re.search(r"/(?:investors?|investor-relations|ir)(?:/|$)", u.path.lower()):
        return "company", host.removeprefix("www.")
    return "secondary", host.removeprefix("www.")


# --- numbers must be in the source ---------------------------------------------------------------------------------------------------

_DIG = re.compile(r"\d[\d,]*(?:\.\d+)?")
_TAGS = re.compile(r"\[(?:D\d+|S\d+|W\d+|inf)\]", re.I)
_DATES = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b")


def _val(s: str) -> Optional[float]:
    try:
        return round(float(s.replace(",", "").rstrip(".")), 6)
    except ValueError:
        return None


def numbers_of(text: str) -> set:
    """The numeric values written in `text` (1,234.50 and 1234.5 are the same value). Dates are not read as amounts."""
    return {v for v in (_val(n) for n in _DIG.findall(_DATES.sub(" ", _TAGS.sub(" ", text or "")))) if v is not None}


def missing_numbers(text: str, source_text: str) -> List[str]:
    """The numbers of `text` that `source_text` does not write."""
    known = numbers_of(source_text)
    return sorted({n.replace(",", "") for n in _DIG.findall(_DATES.sub(" ", _TAGS.sub(" ", text or ""))) if (_val(n) is not None and _val(n) not in known)})


def only_sourced_in(text: str, source_text: str) -> Tuple[str, int]:
    """`analyst.only_sourced_numbers` extended to documents: every sentence of `text` that carries a number that `source_text` does not write is removed. Returns (text, sentences removed); a note
    says so when something was removed."""
    keep, dropped = [], 0
    for line in (text or "").split("\n"):
        out = []
        for s in re.split(r"(?<=[.!?])\s+", line):
            if missing_numbers(s, source_text):
                dropped += 1
            else:
                out.append(s)
        keep.append(" ".join(out))
    clean = re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).strip()
    if dropped:
        clean += f"\n\n({dropped} sentence(s) removed: they carried numbers that are not in the document.)"
    return clean, dropped


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[‘’“”]", "'", str(s or ""))).strip().lower()


def check_facts(raw: Sequence[dict], pages: Sequence[Tuple[int, str]], source_text: str, *, numbers_checkable: bool = True) -> Tuple[List[dict], List[str]]:
    """Facts that survive code's checks: the quote is IN the source (where the source has text), and every number of the claim is in the source. `pages` is [(page number, text)]; the page of a
    fact is the page where its quote was found (code decides, not the model). Returns (facts, notes for the dropped ones)."""
    out, notes = [], []
    have_text = bool(re.sub(r"\s+", "", source_text))
    norm_pages = [(p, _norm(t)) for p, t in pages]
    for f in raw or []:
        claim, quote = " ".join(str(f.get("claim") or "").split()), " ".join(str(f.get("quote") or "").split())
        if not claim:
            continue
        page = f.get("page") if isinstance(f.get("page"), int) else None
        if have_text:
            q = _norm(quote)
            found = [p for p, t in norm_pages if q and q in t]
            if not found:
                notes.append(f"dropped a claim: its quote is not in the document (\"{quote[:60]}\")")
                continue
            page = page if page in found else found[0]
            bad = missing_numbers(claim, source_text)
            if bad:
                notes.append(f"dropped a claim: the number {', '.join(bad[:3])} is not in the document")
                continue
        elif missing_numbers(claim, "") and not numbers_checkable:
            notes.append("dropped a claim with numbers that could not be checked (no text of the page could be read here)")
            continue
        out.append({"claim": claim, "quote": quote, "page": page})
    return out, notes


# --- the model door ---------------------------------------------------------------------------------------------------------------------

gateway_call: Optional[Callable] = None          # tests and callers may inject a call; None = `llm.gateway.call`


def _supports(fn: Callable, name: str) -> bool:
    try:
        ps = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in ps or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in ps.values())


def ask(con, now: datetime, system: str, text: str, *, schema: Optional[dict] = None, documents: Optional[List[dict]] = None, images: Optional[List[dict]] = None, purpose: str = "reading",
        chat_id: Optional[int] = None, role: str = "read", max_tokens: int = 3000) -> dict:
    """One call through the gateway. `documents`: [{"name", "media_type", "data" (base64), "title"}]; `images`: [{"media_type", "data" (base64)}]. A gateway that does not take `documents` / `images` as
    arguments is given them as the vendor's content blocks inside the message, so the same call works before and after the gateway grows them."""
    from pflab.llm import gateway
    fn = gateway_call or gateway.call
    kw: Dict[str, Any] = {"purpose": purpose, "now": now, "max_tokens": max_tokens, "schema": schema}
    agents = getattr(gateway, "AGENTS", ())
    if _supports(fn, "agent"):
        kw["agent"] = "reading" if "reading" in agents else ("desk" if "desk" in agents else "think")
    if chat_id is not None and _supports(fn, "chat_id"):
        kw["chat_id"] = chat_id
    blocks: List[dict] = []
    if documents and _supports(fn, "documents"):
        kw["documents"] = documents
    else:
        blocks += [{"type": "document", "source": {"type": "base64", "media_type": d.get("media_type", "application/pdf"), "data": d["data"]}, "title": str(d.get("title") or d.get("name") or "document")[:200]}
                   for d in documents or []]
    if images and _supports(fn, "images"):
        kw["images"] = images
    else:
        blocks += [{"type": "image", "source": {"type": "base64", "media_type": i.get("media_type", "image/png"), "data": i["data"]}} for i in images or []]
    content: Any = blocks + [{"type": "text", "text": text}] if blocks else [{"type": "text", "text": text}]
    return fn(con, role, system, [{"role": "user", "content": content}], **kw)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# --- the received files --------------------------------------------------------------------------------------------------------------

def received_dir(now: datetime) -> Path:
    from pflab.data import data_dir
    return data_dir() / "received_s85" / f"{now:%Y%m%d}"


def keep_file(path: Path, sha: str, now: datetime) -> Path:
    d = received_dir(now)
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{sha[:24]}{Path(path).suffix.lower()}"
    if not dest.exists():
        shutil.copyfile(path, dest)
    return dest


def _scope() -> dict:
    from pflab.data import data_dir
    from pflab.kg2 import scope as sc
    try:
        return sc.load(data_dir())
    except Exception:
        return {"version": 1, "names": [], "extra_isins": []}


def _name_of(scope: dict, isin: str) -> str:
    for n in scope.get("names", []):
        if n["isin"] == isin:
            return str(n.get("symbol") or n.get("name") or isin)
    return isin


def _storylines(con, isin: str) -> List[str]:
    try:
        return [str(r[0]) for r in con.execute("SELECT s.claim FROM storyline_exposure_s80 e JOIN storylines_s80 s USING (storyline_id) WHERE e.isin=? AND s.status IN ('open','active','confirmed','weakening') "
                                               "ORDER BY s.opened_on DESC LIMIT 3", [isin]).fetchall()]
    except Exception:
        return []


def node_of(isin: str) -> dict:
    """The graph's node for an ISIN: the id and the route that shows it (`/api/graph/node`)."""
    return {"id": f"company:{isin}", "url": f"/api/graph/node?id=company:{isin}"}


def _door_a(con, now: datetime, *, sha: str, title: str, text: str, headline: str, facts: List[dict], summary: str, ref: str, name: str) -> dict:
    """Door (a): the EVENT (source "you", time received, ISINs by the graph's confident rule only) and the dated note `recall` finds. Returns {"isins", "event_ids", "note_doc", "links", "scope"}."""
    from pflab.kg2 import you
    from pflab.think import recall
    scope = _scope()
    links = you.link(text, scope, title=f"{title} {headline}")
    rows = [you.row(l["isin"], l["rule"], l["proof"], sha=sha, received_at=now, headline=f"{headline or title} (from you: {name})", ref=ref) for l in links]
    you.add(con, _data_root(), rows, now)
    bullets = [f"- {f['claim']}" + (f" [p. {f['page']}]" if f.get("page") else "") for f in facts[:12]]
    body = "\n".join([(summary or "").strip()] + bullets).strip()
    note_doc = None
    try:
        label = f"{(headline or title)[:200]} ({name})"
        if links:
            for l in links:
                d = recall.write_back(con, now, isin=l["isin"], symbol=_name_of(scope, l["isin"]), title=label, text=body or title, source="you")
                note_doc = note_doc or d
        elif body.strip():
            note_doc = recall.write_back(con, now, topic=(headline or title)[:80], title=label, text=body, source="you")
    except Exception as e:                           # the note is a convenience for recall; the event and the row already hold the evidence
        log.warning("note not written: %s", e)
    return {"isins": [l["isin"] for l in links], "event_ids": [r["event_id"] for r in rows], "note_doc": note_doc, "links": links, "scope": scope}


def _data_root() -> Path:
    from pflab.data import data_dir
    return data_dir()


def _what_i_did(door: dict) -> str:
    if not door["isins"]:
        return "I did not tie it to a stock (no company is named clearly enough); it is kept as a dated note from you that the system finds when it thinks about the market."
    scope = door["scope"]
    parts = [f"{_name_of(scope, l['isin'])} ({l['isin']}): {l['proof']}" for l in door["links"]]
    return "Linked to " + "; ".join(parts) + ". Kept as evidence from you, dated now: the storylines and the thinking loop read it at their next step."


# --- the store ---------------------------------------------------------------------------------------------------------------------

def _row(con, sha: str):
    return con.execute("SELECT doc_id, status, result_json, path FROM received_docs_s85 WHERE sha=? ORDER BY doc_id DESC LIMIT 1", [sha]).fetchone()


def _save_row(con, doc_id: int, **cols) -> None:
    sets = ", ".join(f"{k}=?" for k in cols)
    con.execute(f"UPDATE received_docs_s85 SET {sets} WHERE doc_id=?", [*cols.values(), doc_id])


def _result(kind: str, name: str, **kw) -> dict:
    base = {"kind": kind, "name": name, "facts": [], "summary_text": "", "document_id": None, "event_id": None, "isins": [], "cost_inr": 0.0, "warnings": [], "refused": None, "cached": False, "pages": None}
    base.update(kw)
    return base


# --- readers by kind ----------------------------------------------------------------------------------------------------------------

def _split_pdf(data: bytes) -> List[Tuple[int, int, bytes]]:
    """[(first page, last page (1-based, inclusive), bytes of that part)] in parts of at most PART_PAGES pages."""
    from pypdf import PdfReader, PdfWriter
    rd = PdfReader(io.BytesIO(data))
    n = len(rd.pages)
    if n <= PART_PAGES:
        return [(1, n, data)]
    out = []
    for a in range(0, n, PART_PAGES):
        w = PdfWriter()
        for i in range(a, min(a + PART_PAGES, n)):
            w.add_page(rd.pages[i])
        buf = io.BytesIO()
        w.write(buf)
        out.append((a + 1, min(a + PART_PAGES, n), buf.getvalue()))
    return out


def _read_pdf(con, now, path: Path, name: str, data: bytes, verdict: dict, chat_id) -> dict:
    texts, _ = screen.pdf_pages_text(data, limit=2000)
    scanned = bool(verdict.get("scanned"))
    warnings: List[str] = []
    ocr_pages: Dict[int, str] = {}
    cost, facts, summaries, headline = 0.0, [], [], ""
    total = len(texts)
    parts = _split_pdf(data)
    if len(parts) > MAX_PARTS:
        warnings.append(f"This PDF has {total} pages: I read the first {MAX_PARTS * PART_PAGES} (page numbers kept).")
        parts = parts[:MAX_PARTS]
    if scanned:                                                       # the numbers of a scan are checked against Windows' OCR of the same pages
        try:
            for i, png in enumerate(screen.render_pages(data, 0, min(total, MAX_PARTS * PART_PAGES) - 1), start=1):
                t = screen.ocr_png(png)
                if t:
                    ocr_pages[i] = t
        except Exception as e:
            warnings.append(f"The scan could not be read by the OCR on this PC ({type(e).__name__}); numbers from it cannot be checked.")
    page_text = [(i + 1, ocr_pages.get(i + 1, "") if scanned else t) for i, t in enumerate(texts)]
    mask_text = bool(verdict.get("mask_needed"))
    gate = screen.gate_for(con)
    for a, b, part in parts:
        src = "\n".join(t for p, t in page_text if a <= p <= b)
        prompt = (f"The document is '{name}'. This excerpt is pages {a} to {b} of {total}. Give page numbers as in the original file (the first page of this excerpt is page {a}). "
                  f"Return the headline (the document's own title in a few words), a summary of at most 80 words, and up to {MAX_FACTS_PART} facts it states.")
        if mask_text:                                                 # his name or address words are in the text: only the masked text goes, never the file
            r = ask(con, now, SYSTEM_READ, prompt + "\n\nTEXT OF THE EXCERPT (identity details masked):\n" + "\n".join(f"[page {p}]\n" + screen.mask(t, gate)[0] for p, t in page_text if a <= p <= b),
                    schema=FACT_SCHEMA, purpose="reading", chat_id=chat_id)
        else:
            r = ask(con, now, SYSTEM_READ, prompt, schema=FACT_SCHEMA,
                    documents=[{"name": name, "media_type": "application/pdf", "data": _b64(part), "title": f"{name} pages {a}-{b}"}], purpose="reading", chat_id=chat_id)
        cost += float(r.get("cost_rupees") or 0.0)
        js = r.get("json") or {}
        if not js:
            warnings.append(f"Pages {a}-{b}: the reader gave no usable answer ({r.get('json_error') or 'empty'}).")
            continue
        checked, notes = check_facts(js.get("facts") or [], [(p, t) for p, t in page_text if a <= p <= b], src, numbers_checkable=bool(src.strip()))
        facts += checked
        warnings += notes
        headline = headline or str(js.get("headline") or "")
        s, dropped = only_sourced_in(str(js.get("summary") or ""), src)
        if s.strip():
            summaries.append(s if len(parts) == 1 else f"Pages {a}-{b}: {s}")
    return {"facts": facts, "summary": "\n".join(summaries), "headline": headline, "text": "\n".join(t for _, t in page_text), "pages": total, "warnings": warnings, "cost": cost}


def _fmt_num(x: float) -> str:
    return f"{x:,.2f}".rstrip("0").rstrip(".") if abs(x) < 1e15 else f"{x:.6g}"


def sheet_summary(data: bytes, name: str) -> str:
    """Code's summary of a table: sheet names, columns, row counts, the first rows, and the count, sum, smallest and largest of each numeric column. Numbers are written with thousands separators."""
    import pandas as pd
    ext = Path(name).suffix.lower()
    if ext in (".csv", ".tsv"):
        books = {"(csv)": pd.read_csv(io.BytesIO(data), sep="\t" if ext == ".tsv" else None, engine="python", encoding_errors="replace")}
    else:
        books = pd.read_excel(io.BytesIO(data), sheet_name=None)
    lines = [f"Sheets: {', '.join(map(str, books))}"]
    for k, (sheet, df) in enumerate(books.items()):
        if k >= MAX_SHEETS:
            lines.append(f"({len(books) - MAX_SHEETS} more sheets not summarised)")
            break
        df = df.dropna(how="all").dropna(axis=1, how="all")
        lines.append(f"Sheet '{sheet}': {len(df)} rows, {len(df.columns)} columns")
        lines.append("Columns: " + ", ".join(str(c)[:40] for c in list(df.columns)[:30]))
        for i, row in enumerate(df.head(SHEET_ROWS_SHOWN).itertuples(index=False), start=1):
            lines.append(f"Row {i}: " + " | ".join("" if v != v else str(v)[:40] for v in list(row)[:12]))
        num = df.select_dtypes("number")
        for c in list(num.columns)[:12]:
            s = num[c].dropna()
            if len(s):
                lines.append(f"Column '{str(c)[:40]}': {len(s)} values, total {_fmt_num(float(s.sum()))}, smallest {_fmt_num(float(s.min()))}, largest {_fmt_num(float(s.max()))}")
    return "\n".join(lines)


def _read_sheet(con, now, path: Path, name: str, data: bytes, verdict: dict, chat_id) -> dict:
    gate = screen.gate_for(con)
    summary, _k, _s = screen.mask(sheet_summary(data, name), gate)
    prompt = f"The file '{name}' is a table. Code read it; this is code's summary (the only thing you see of it). Return a headline, a summary of at most 60 words, and up to 8 facts the summary states.\n\n{summary}"
    r = ask(con, now, SYSTEM_READ, prompt, schema=FACT_SCHEMA, purpose="reading", chat_id=chat_id)
    js = r.get("json") or {}
    facts, notes = check_facts(js.get("facts") or [], [(None, summary)], summary)
    s, _ = only_sourced_in(str(js.get("summary") or ""), summary)
    warn = notes + ([] if js else [f"The reader gave no usable answer ({r.get('json_error') or 'empty'})."])
    return {"facts": facts, "summary": s, "headline": str(js.get("headline") or name), "text": summary, "pages": None, "warnings": warn, "cost": float(r.get("cost_rupees") or 0.0), "table": summary}


def _read_text(con, now, path: Path, name: str, data: bytes, verdict: dict, chat_id) -> dict:
    gate = screen.gate_for(con)
    raw = data.decode("utf-8-sig", "replace")
    if Path(name).suffix.lower() in (".html", ".htm"):
        try:
            import trafilatura
            raw = trafilatura.extract(raw) or raw
        except Exception:
            pass
    masked, _k, _s = screen.mask(raw, gate)
    chunks = [masked[i:i + TEXT_PART_CHARS] for i in range(0, len(masked), TEXT_PART_CHARS)][:MAX_TEXT_PARTS]
    cost, facts, notes, summaries, headline = 0.0, [], [], [], ""
    for k, ch in enumerate(chunks, start=1):
        prompt = f"The file '{name}' (part {k} of {len(chunks)}). Return the headline, a summary of at most 80 words, and up to {MAX_FACTS_PART} facts it states.\n\nTEXT:\n{ch}"
        r = ask(con, now, SYSTEM_READ, prompt, schema=FACT_SCHEMA, purpose="reading", chat_id=chat_id)
        cost += float(r.get("cost_rupees") or 0.0)
        js = r.get("json") or {}
        if not js:
            notes.append(f"Part {k}: the reader gave no usable answer ({r.get('json_error') or 'empty'}).")
            continue
        f, n = check_facts(js.get("facts") or [], [(None, ch)], ch)
        facts += f
        notes += n
        headline = headline or str(js.get("headline") or "")
        s, _ = only_sourced_in(str(js.get("summary") or ""), ch)
        summaries.append(s)
    if len(masked) > TEXT_PART_CHARS * MAX_TEXT_PARTS:
        notes.append(f"Long file: I read the first {TEXT_PART_CHARS * MAX_TEXT_PARTS:,} characters.")
    return {"facts": facts, "summary": "\n".join(x for x in summaries if x), "headline": headline or name, "text": raw, "pages": None, "warnings": notes, "cost": cost}


def _read_image(con, now, path: Path, name: str, data: bytes, verdict: dict, chat_id, mime: str) -> dict:
    ocr = verdict.get("ocr_text") or ""
    mt = mime if (mime or "").startswith("image/") else {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}.get(Path(name).suffix.lower(), "image/png")
    prompt = (f"The file '{name}' is a picture. Return a headline, a summary of at most 60 words of what it shows, and up to 8 facts it states. "
              "Quote the text printed in the picture exactly; every number must be printed in it.")
    r = ask(con, now, SYSTEM_READ, prompt, schema=FACT_SCHEMA, images=[{"media_type": mt, "data": _b64(data)}], purpose="reading", chat_id=chat_id)
    js = r.get("json") or {}
    facts, notes = check_facts(js.get("facts") or [], [(None, ocr)], ocr, numbers_checkable=bool(ocr.strip()))
    s, _ = only_sourced_in(str(js.get("summary") or ""), ocr) if ocr.strip() else (re.sub(r"[^\s]*\d[^\s]*", "", str(js.get("summary") or "")), 0)
    return {"facts": facts, "summary": s, "headline": str(js.get("headline") or name), "text": ocr, "pages": None,
            "warnings": notes + ([] if js else [f"The reader gave no usable answer ({r.get('json_error') or 'empty'})."]), "cost": float(r.get("cost_rupees") or 0.0)}


def _words_of(n: int) -> str:
    return "1 page" if n == 1 else f"{n} pages"


def read_attachment(con, now: datetime, path, name: str = "", mime: str = "", *, chat_id: Optional[int] = None, msg_id: Optional[int] = None) -> dict:
    """Screen, read, keep and hand on one file. A personal record is refused: {"refused": his line, "facts": []} with nothing stored and no call made. The same bytes again: the stored answer, cost 0.
    Errors of the model door are reported in `warnings` and the file stays kept (status 'failed') so sending it again reads it again; an egress refusal removes what was kept."""
    from pflab.pm import store
    path = Path(path)
    name = name or path.name
    v = screen.check_file(path, name, mime, con=con)
    if not v["ok"]:
        return _result(v["kind"], name, summary_text=v["refused"], refused=v["refused"], warnings=[v.get("reason", "")] if v.get("reason") else [])
    kind = v["kind"]
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    old = _row(con, sha)
    if old and old[1] == "read":
        res = json.loads(old[2] or "{}")
        res.update(cached=True, cost_inr=0.0, document_id=old[0])
        res["summary_text"] = "(Already read on " + str(res.get("read_on", "an earlier day")) + ": no new read.)\n" + str(res.get("summary_text", ""))
        return res
    if kind == "other":
        return _result("other", name, summary_text="I cannot read this kind of file yet (a PDF, a spreadsheet, a picture or a text file I can). Nothing was kept or sent.",
                       warnings=["unsupported kind of file"])
    kept = keep_file(path, sha, now)
    if old:
        doc_id = old[0]
    else:
        doc_id = store.next_id(con, "received_docs_s85", "doc_id")
        con.execute("INSERT INTO received_docs_s85 (doc_id, sha, name, mime, kind, path, size_bytes, received_at, chat_id, msg_id, pages, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [doc_id, sha, name[:200], mime, kind, str(kept), len(data), now, chat_id, msg_id, v.get("pages"), "reading"])
    try:
        from pflab.entrance import store as estore          # the chat's own store, when it is merged: the attachment is shown in the thread
        if msg_id and not old:
            have = con.execute("SELECT attachment_id FROM chat_attachments_s85 WHERE msg_id=? AND name=? LIMIT 1", [msg_id, name]).fetchone()
            if have:                                          # the intake already attached it when the message came in: only fill in what was read
                estore.set_attachment(con, int(have[0]), kind=kind)
            else:
                estore.attach(con, msg_id, str(kept), name, mime, kind)
    except Exception:
        pass
    try:
        if kind == "pdf":
            out = _read_pdf(con, now, kept, name, data, v, chat_id)
        elif kind == "sheet":
            out = _read_sheet(con, now, kept, name, data, v, chat_id)
        elif kind == "image":
            out = _read_image(con, now, kept, name, data, v, chat_id, mime)
        else:
            out = _read_text(con, now, kept, name, data, v, chat_id)
    except Exception as e:
        from pflab.hq import egress
        from pflab.llm import gateway
        if isinstance(e, egress.EgressBlocked):             # something identity-like got through the screen: remove what was kept, send nothing
            con.execute("DELETE FROM received_docs_s85 WHERE doc_id=?", [doc_id])
            try:
                kept.unlink()
            except OSError:
                pass
            return _result(kind, name, refused="Part of that file looks like identity or banking details, so nothing was sent and nothing was kept.", summary_text="Nothing was sent or kept.",
                           warnings=[str(e)[:200]])
        why = gateway.refusal_reason(e) or f"{type(e).__name__}: {str(e)[:200]}"
        _save_row(con, doc_id, status="failed", warnings_json=json.dumps([why]))
        return _result(kind, name, document_id=doc_id, summary_text=f"I kept the file but could not read it now: {why}. Send it again when that clears.", warnings=[why])
    title = out["headline"] or Path(name).stem
    door = _door_a(con, now, sha=sha, title=title, text=out["text"], headline=out["headline"], facts=out["facts"], summary=out["summary"], ref=f"you:{sha[:16]}", name=name)
    lines = [f"Read {name}" + (f" ({_words_of(out['pages'])})" if out.get("pages") else "") + (f": {out['headline']}" if out.get("headline") else "") + "."]
    if out["summary"].strip():
        lines.append(out["summary"].strip())
    for f in out["facts"][:8]:
        lines.append(f"- {f['claim']}" + (f" (page {f['page']})" if f.get("page") else ""))
    if len(out["facts"]) > 8:
        lines.append(f"({len(out['facts']) - 8} more facts kept)")
    lines.append(_what_i_did(door))
    for l in door["links"]:
        lines.append(f"Graph: {node_of(l['isin'])['id']} ({node_of(l['isin'])['url']})")
        st = _storylines(con, l["isin"])
        if st:
            lines.append("Storylines that read this name: " + "; ".join(st))
    links = []
    if kind in ("pdf", "text"):
        try:
            links = [resolve_link(u, sha) for u in links_in(out["text"])]
        except Exception:
            links = []
    for l in links:
        host = urlparse(l["url"]).hostname or l["url"]
        if l["same_file"]:
            lines.append(f"The link printed in the file ({host}) leads to this same file: nothing more to read there.")
        elif l["error"]:
            lines.append(f"The link printed in the file ({host}) could not be opened: {l['error']}.")
        else:
            lines.append(f"The link printed in the file ({host}) leads to a different page or file ({(l['content_type'] or 'unknown type').split(';')[0]}): say \"check that link\" and I will read it.")
    if not out["facts"]:
        why = why_unreadable(kept) or "the reader found no fact in it that the file itself states (a plain table of figures, or a page of pictures with a few words)"
        out["warnings"].append("No fact could be taken from this file: " + why)
        lines.append("Nothing was taken from this file because " + why + ".")
    lines += [f"Note: {w}" for w in out["warnings"][:4]]
    res = _result(kind, name, links=links, facts=out["facts"], summary_text="\n".join(lines), document_id=doc_id, event_id=(door["event_ids"] or [None])[0], isins=door["isins"],
                  cost_inr=round(out["cost"], 4), warnings=out["warnings"], pages=out.get("pages"), headline=out["headline"], note_doc=door["note_doc"], event_ids=door["event_ids"],
                  read_on=f"{now:%Y-%m-%d}", graph_nodes=[node_of(i) for i in door["isins"]])
    _save_row(con, doc_id, status="read", pages=out.get("pages"), summary=out["summary"], facts_json=json.dumps(out["facts"]), isins_json=json.dumps(door["isins"]),
              event_id=res["event_id"], note_doc=door["note_doc"], cost_inr=res["cost_inr"], warnings_json=json.dumps(out["warnings"]), result_json=json.dumps(res, default=str))
    return res


def why_unreadable(path) -> Optional[str]:
    """S86b C5.3: the TRUE reason in plain words why a file gives nothing, by looking at the file itself (code, free, offline); None when the file does have something to read. A file ends in one of two
    ways only: read with at least one sourced fact, or this reason; never a bare "nothing readable"."""
    p = Path(path)
    if not p.exists():
        return "the file is no longer on this PC"
    ext = p.suffix.lower()
    try:
        head = p.read_bytes()[:8]
        if ext == ".pdf":
            import pypdf
            r = pypdf.PdfReader(str(p))
            if r.is_encrypted:
                try:
                    if not r.decrypt(""):
                        return "this PDF is password-protected: send it again without the password, or tell me the password in the secrets file"
                except Exception:
                    return "this PDF is password-protected and could not be opened"
            n = len(r.pages)
            chars = sum(len((pg.extract_text() or "").strip()) for pg in r.pages[:10])
            if chars >= 40:
                return None
            pics = sum(len(pg.images) for pg in r.pages[:3])
            if pics:
                return f"this PDF is a scan with no text layer ({n} pages of pictures): it needs this PC's OCR, which reads the numbers from the pictures"
            return f"this PDF has {n} page(s) and no text and no pictures: it is empty"
        if ext in (".xlsx", ".xlsm"):
            if head[:4] == b"\xd0\xcf\x11\xe0":
                return "this workbook is password-protected (an encrypted Excel file): remove the password and send it again"
            import openpyxl
            wb = openpyxl.load_workbook(str(p), data_only=True, read_only=False)
            filled, hidden, formulas_only = 0, 0, 0
            for ws in wb.worksheets:
                n = sum(1 for row in ws.iter_rows() for c in row if c.value is not None)
                filled += n
                hidden += int(ws.sheet_state != "visible")
            if filled:
                return None
            wf = openpyxl.load_workbook(str(p), data_only=False)
            formulas_only = sum(1 for ws in wf.worksheets for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("="))
            if formulas_only:
                return f"this workbook holds {formulas_only} formula cell(s) whose results were never saved (it was made by a program and never opened in Excel): open and save it in Excel, then send it again"
            return f"this workbook has {len(wb.worksheets)} sheet(s) ({hidden} hidden) and every cell is empty"
        if ext == ".xls":
            if head[:4] != b"\xd0\xcf\x11\xe0":
                return "this .xls file is not an Excel file"
            import xlrd
            try:
                wb = xlrd.open_workbook(str(p))
            except Exception as e:
                return f"this old Excel file could not be opened ({type(e).__name__}): it may be password-protected"
            filled = sum(1 for sh in wb.sheets() for r in range(sh.nrows) for c in range(sh.ncols) if str(sh.cell_value(r, c)).strip())
            return None if filled else f"this workbook has {wb.nsheets} sheet(s) and every cell is empty"
        if ext in (".csv", ".txt"):
            t = p.read_bytes()[:200000].decode("utf-8", "replace").strip()
            return None if t else "this file is empty"
    except Exception as e:
        return f"this file could not be opened ({type(e).__name__}: {str(e)[:80]})"
    return None


# --- links ---------------------------------------------------------------------------------------------------------------------------

_URL_RX = re.compile(r"https?://[^\s<>\"')\]]+")


def links_in(text: str, limit: int = 3) -> List[str]:
    """The distinct web links printed in a document's text, at most `limit`, trailing punctuation removed (S86b C5.3: a briefing PDF says "Read now: <link>" and the chat answered that it had not opened it)."""
    out: List[str] = []
    for m in _URL_RX.findall(text or ""):
        u = m.rstrip(".,;:!?")
        if u not in out:
            out.append(u)
    return out[:limit]


def resolve_link(url: str, own_sha: str, *, timeout: int = 10, max_bytes: int = 8_000_000, getter: Optional[Callable] = None) -> dict:
    """Follow one link found INSIDE a file (free, public hosts only, bounded) and say where it leads: {"url", "final_url", "status", "content_type", "same_file" (the bytes are this very file), "error"}. A link
    that leads to the same file needs no second read; another page or file is offered for `check_link`, never read without being asked."""
    out = {"url": url, "final_url": url, "status": None, "content_type": "", "same_file": False, "error": None}
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname or _private_host(u.hostname):
        out["error"] = "not a public web address: not opened"
        return out
    try:
        import requests
        r = (getter or requests.get)(url, headers={"User-Agent": _user_agent(u.hostname.lower())}, timeout=timeout, stream=True, allow_redirects=True)
        out.update(final_url=r.url, status=r.status_code, content_type=r.headers.get("Content-Type", ""))
        if _private_host(urlparse(r.url).hostname or ""):
            out["error"] = "the link redirected to a private address: not opened"
            return out
        if r.status_code >= 400:
            out["error"] = f"the site answered {r.status_code}"
            return out
        body = r.raw.read(max_bytes + 1, decode_content=True) if hasattr(r, "raw") and getattr(r, "raw", None) is not None else getattr(r, "content", b"")
        out["same_file"] = hashlib.sha256(body[:max_bytes]).hexdigest() == own_sha and len(body) <= max_bytes
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    return out


def _private_host(host: str) -> bool:
    import ipaddress
    import socket
    h = (host or "").strip("[]").lower()
    if not h or h == "localhost" or h.endswith((".local", ".internal", ".localhost")):
        return True
    try:
        ips = [str(ipaddress.ip_address(h))]
    except ValueError:
        try:
            ips = [i[4][0] for i in socket.getaddrinfo(h, None)]
        except OSError:
            return False                                      # an unresolvable name fails at the fetch, not here
    for ip in ips:
        a = ipaddress.ip_address(ip)
        if a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast:
            return True
    return False


def _user_agent(host: str) -> str:
    ua = "pflab/1.0 (personal research; public pages only)"
    if host.endswith("sec.gov"):                              # the SEC asks automated clients for a contact: the one in the secrets file, never printed
        try:
            from pflab.pm import secrets as sec
            c = sec.load().get("sec", "user_agent")
            if c:
                return str(c)
        except Exception:
            pass
    return ua


def fetch(url: str, *, timeout: int = FETCH_TIMEOUT, max_bytes: int = FETCH_MAX_BYTES) -> dict:
    """The app's own fetch of one PUBLIC page: {"ok", "status", "url" (final), "content_type", "text", "fetched" (ISO time), "date" (the page's own Last-Modified / Date), "links" (hrefs), "error"}.
    Private and local addresses are refused (also after a redirect); robots.txt is respected on pages that are not an official source; HTML goes through trafilatura, a PDF through pypdf."""
    import requests
    u = urlparse(url)
    out = {"ok": False, "status": None, "url": url, "content_type": "", "text": "", "fetched": datetime.now().isoformat(timespec="seconds"), "date": None, "links": [], "error": None}
    if u.scheme not in ("http", "https") or not u.hostname:
        out["error"] = "only http and https links are opened"
        return out
    if _private_host(u.hostname):
        out["error"] = "that address is on this PC or a private network: not opened"
        return out
    kind, _ = source_type(url)
    if kind == "secondary":
        try:
            from pflab.kg.text import Robots
            if not Robots().allowed(url):
                out["error"] = "the site's robots.txt asks not to be fetched"
                return out
        except Exception:
            pass
    try:
        r = requests.get(url, headers={"User-Agent": _user_agent(u.hostname.lower()), "Accept": "text/html,application/pdf,text/plain;q=0.9,*/*;q=0.5"}, timeout=timeout, stream=True, allow_redirects=True)
        if _private_host(urlparse(r.url).hostname or ""):
            out["error"] = "the link redirected to a private address: not opened"
            return out
        body = r.raw.read(max_bytes + 1, decode_content=True)
        out.update(status=r.status_code, url=r.url, content_type=r.headers.get("Content-Type", ""), date=r.headers.get("Last-Modified") or r.headers.get("Date"))
        if r.status_code >= 400:
            out["error"] = f"the site answered {r.status_code}"
            return out
        if len(body) > max_bytes:
            body = body[:max_bytes]
            out["error"] = "page cut at 3 MB"
        ct = out["content_type"].lower()
        if "pdf" in ct or body[:5] == b"%PDF-":
            pages, locked = screen.pdf_pages_text(body, limit=30)
            out["text"] = "\n".join(f"[page {i}] {t}" for i, t in enumerate(pages, start=1))
        elif "html" in ct or body[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
            html = body.decode(r.encoding or "utf-8", "replace")
            out["links"] = re.findall(r"""href=["'](https?://[^"'#\s]+)""", html)[:400]
            import trafilatura
            out["text"] = trafilatura.extract(html, url=r.url, include_comments=False, include_tables=True) or re.sub(r"<[^>]+>", " ", html)
        else:
            out["text"] = body.decode(r.encoding or "utf-8", "replace")
        out["text"] = re.sub(r"[ \t]+", " ", out["text"]).strip()
        out["ok"] = bool(out["text"])
        if not out["text"]:
            out["error"] = out["error"] or "no text could be read from the page"
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:150]}"
    return out


def _window(text: str, claim: str, n: int = SOURCE_CHARS) -> str:
    """The first part of the page and the windows around the claim's own words, up to `n` characters (code picks what the model sees)."""
    if len(text) <= n:
        return text
    words = [w for w in re.findall(r"[A-Za-z0-9&.%-]{4,}", claim or "") if not w.isdigit()][:8]
    keep = text[: n // 3]
    spans = []
    low = text.lower()
    for w in words:
        i = low.find(w.lower(), n // 3)
        if i >= 0:
            spans.append((max(n // 3, i - 600), min(len(text), i + 1000)))
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    for a, b in merged:
        if len(keep) + (b - a) > n:
            break
        keep += "\n...\n" + text[a:b]
    return keep[:n]


def _web_lookup(con, now: datetime, question: str) -> dict:
    """Last resort when a page cannot be fetched here: the API's web tools (`analyst.web_search`, gated, priced, logged). {"text", "urls", "cost"}; empty when not available."""
    try:
        from pflab.agents import analyst as an
        from pflab.llm import gateway
        client = gateway.client_override or _gw_vendor_client(None)
        o = an.web_search(con, question, client, now=now, topic="link_check")
        urls = re.findall(r"https?://[^\s)\]]+", o.text or "")
        return {"text": o.text if o.status in ("done", "reused") else "", "urls": urls, "cost": float(o.cost_inr or 0.0)}
    except Exception as e:
        log.info("web lookup unavailable: %s", e)
        return {"text": "", "urls": [], "cost": 0.0}


def check_link(con, now: datetime, url: str, claim: Optional[str] = None, *, chat_id: Optional[int] = None, fetcher: Optional[Callable[[str], dict]] = None, web: bool = True) -> dict:
    """Open the link, find the claim, check it at its original source where one exists, answer with citations, and hand the checked fact to the loop (door a). Returns {"verdict", "sources", "findings",
    "answer", "isins", "event_id", "node", "cost_inr", "warnings", "refused"}. `fetcher(url)` replaces the app's own fetch (tests: recorded pages)."""
    fetcher = fetcher or fetch
    warnings: List[str] = []
    res = {"verdict": None, "sources": [], "findings": [], "answer": "", "isins": [], "event_id": None, "node": None, "cost_inr": 0.0, "warnings": warnings, "refused": None, "cached": False, "url": url}
    u = urlparse(url or "")
    if u.scheme not in ("http", "https") or not u.hostname or re.match(r"^(?:localhost|127\.|10\.|192\.168\.|169\.254\.)", u.hostname):
        res.update(refused="I only open public web links (http or https).", answer="I only open public web links (http or https).")
        return res
    chk = screen.check_text((claim or "") + "\n" + (u.query or ""), con=con) if (claim or u.query) else {"ok": True, "text": "", "refused": None}
    if not chk["ok"]:
        res.update(refused=chk["refused"], answer=chk["refused"])
        return res
    safe_claim = " ".join((chk["text"] or "").split()[: 120]) if claim else ""
    safe_url = url if not u.query else url.split("?", 1)[0] + "?" + screen.mask(u.query, screen.gate_for(con))[0]
    old = con.execute("SELECT link_id, result_json FROM link_checks_s85 WHERE url=? AND coalesce(claim,'')=? AND checked_at >= ? AND verdict IS NOT NULL ORDER BY link_id DESC LIMIT 1",
                      [url, safe_claim, datetime.combine(now.date(), datetime.min.time())]).fetchone()
    if old:
        r = json.loads(old[1] or "{}")
        r.update(cached=True, cost_inr=0.0)
        return r
    pages: List[dict] = []
    cost = 0.0
    first = fetcher(url)
    if not first.get("ok"):
        warnings.append(f"Could not open {u.hostname}: {first.get('error')}")
        if web:
            look = _web_lookup(con, now, f"What do the exchange, regulator or company filings say about: {safe_claim or url}? Give the source URLs.")
            cost += look["cost"]
            if look["text"]:
                pages.append({"url": url, "kind": "secondary", "name": "web search", "fetched": now.isoformat(timespec="seconds"), "date": None, "text": look["text"]})
                for ou in [x for x in look["urls"] if source_type(x)[0] in OFFICIAL][:2]:
                    p = fetcher(ou)
                    if p.get("ok"):
                        k, nme = source_type(ou)
                        pages.append({"url": p["url"], "kind": k, "name": nme, "fetched": p["fetched"], "date": p.get("date"), "text": p["text"]})
    else:
        k, nme = source_type(first["url"])
        pages.append({"url": first["url"], "kind": k, "name": nme, "fetched": first["fetched"], "date": first.get("date"), "text": first["text"]})
        if k == "secondary":                                    # the original source, where one exists: official links the page itself points to
            seen = {first["url"]}
            for ou in first.get("links", []):
                if source_type(ou)[0] in OFFICIAL and ou not in seen and len(pages) < MAX_SOURCES:
                    seen.add(ou)
                    p = fetcher(ou)
                    if p.get("ok"):
                        k2, n2 = source_type(ou)
                        pages.append({"url": p["url"], "kind": k2, "name": n2, "fetched": p["fetched"], "date": p.get("date"), "text": p["text"]})
            if not any(p["kind"] in OFFICIAL for p in pages):
                warnings.append("No original source (an exchange file, a filing or a regulator's page) was found behind this link: the answer rests on the page itself.")
    pages = pages[:MAX_SOURCES]
    if not pages:
        res.update(verdict="not_found", answer=f"I could not open that link ({first.get('error')}) and found nothing else about it.", cost_inr=round(cost, 4))
        _save_link(con, now, url, safe_claim, chat_id, res)
        return res
    from pflab.hq import redact
    gate = screen.gate_for(con)
    blocks, srcs = [], []
    for n, p in enumerate(pages, start=1):
        shown = _window(p["text"], safe_claim)
        p["shown"] = shown
        srcs.append({"n": n, "url": p["url"], "kind": p["kind"], "source": p["name"], "fetched": p["fetched"], "page_date": p.get("date")})
        # the URL stays out of the prompt: its digits (a CIK, an accession number) look like an account number to the egress check; the answer lists the URLs itself
        blocks.append(f"[S{n}] {p['kind']} source: {p['name']} ({urlparse(p['url']).hostname}), fetched {p['fetched'][:10]}\n" + redact.redact(shown, gate, lines=False)[0])
    prompt = (("CLAIM TO CHECK: " + safe_claim + "\n\n") if safe_claim else "Summarise what the sources state; there is no claim to check.\n\n") + "SOURCES:\n\n" + "\n\n".join(blocks)
    try:
        r = ask(con, now, SYSTEM_LINK, prompt, schema=LINK_SCHEMA, purpose="reading", chat_id=chat_id)
    except Exception as e:
        from pflab.llm import gateway
        why = gateway.refusal_reason(e) or f"{type(e).__name__}: {str(e)[:200]}"
        res.update(sources=srcs, cost_inr=round(cost, 4), answer=f"I opened the page but could not check it now: {why}.", warnings=warnings + [why])
        return res
    cost += float(r.get("cost_rupees") or 0.0)
    js = r.get("json") or {}
    by_n = {i + 1: p for i, p in enumerate(pages)}
    findings, dropped_notes = [], []
    for f in js.get("findings") or []:
        p = by_n.get(f.get("source"))
        fact, quote = " ".join(str(f.get("fact") or "").split()), " ".join(str(f.get("quote") or "").split())
        if not p or not fact:
            continue
        if _norm(quote) not in _norm(p["text"]):
            dropped_notes.append(f"dropped a finding: its quote is not in source [S{f.get('source')}]")
            continue
        bad = missing_numbers(fact, p["text"] + " " + safe_claim)
        if bad:
            dropped_notes.append(f"dropped a finding: the number {', '.join(bad[:3])} is not in source [S{f.get('source')}]")
            continue
        findings.append({"fact": fact, "quote": quote, "source": f["source"], "kind": p["kind"]})
    warnings += dropped_notes
    verdict = str(js.get("verdict") or "unclear") if js else "unclear"
    if not safe_claim:
        verdict = "n/a"
    elif verdict in ("supported", "contradicted") and not findings:
        verdict = "unclear"
        warnings.append("The reader's verdict was not backed by a quote that could be found in the sources: shown as unclear.")
    official = any(f["kind"] in OFFICIAL for f in findings)
    all_text = " ".join(p["text"] for p in pages) + " " + safe_claim
    summary, _ = only_sourced_in(str(js.get("summary") or ""), all_text)
    head = {"supported": ("Checked at the original source: supported." if official else "Found on the page, not confirmed at an original source: supported by the page."),
            "contradicted": ("Checked at the original source: NOT as claimed." if official else "The page says otherwise (no original source found)."),
            "not_found": "The sources do not mention it.", "unclear": "I could not tell from the sources.", "n/a": "Here is what the page says."}[verdict]
    lines = ["Opened: " + "; ".join(f"[{s['n']}] {s['kind']} ({s['source']}) {s['url']}, fetched {s['fetched'][:10]}" for s in srcs) + ".", head]
    if safe_claim:
        lines.insert(1, f"Your claim: {safe_claim[:300]}")
    if summary.strip():
        lines.append(summary.strip())
    lines += [f"- {f['fact']} [S{f['source']}] \"{f['quote'][:160]}\"" for f in findings[:6]]
    link_text = " ".join([safe_claim, " ".join(f["fact"] for f in findings), " ".join(p["text"][:2000] for p in pages)])
    door: Dict[str, Any] = {"isins": [], "event_ids": [], "note_doc": None, "links": [], "scope": _scope()}
    if verdict == "supported":                                  # a supported fact is evidence: an event "from you" in the graph and a dated note
        sha = hashlib.sha256((url + "|" + safe_claim + f"|{now:%Y-%m-%d}").encode("utf-8")).hexdigest()
        door = _door_a(con, now, sha=sha, title=safe_claim[:120] or url, text=link_text, headline=(safe_claim or summary or url)[:200], facts=[{"claim": f["fact"], "page": None} for f in findings],
                       summary=f"Checked: {safe_claim or url}. Verdict: {verdict}. " + summary, ref=url, name=u.hostname)
    elif safe_claim:                                            # a claim that failed or could not be checked is a note, never graph evidence
        door = _note_only(con, now, safe_claim, verdict, summary, findings, link_text, url, door)
    lines.append(_what_i_did(door) if door["links"] else ("Kept as a dated note from you." if door["note_doc"] else "Nothing was stored."))
    for l in door["links"]:
        lines.append(f"Graph: {node_of(l['isin'])['id']} ({node_of(l['isin'])['url']})")
    lines += [f"Note: {w}" for w in warnings[:4]]
    res.update(verdict=verdict, sources=srcs, findings=findings, answer="\n".join(lines), isins=door["isins"], event_id=(door["event_ids"] or [None])[0], cost_inr=round(cost, 4),
               node=(node_of(door["isins"][0]) if door["isins"] else None), note_doc=door["note_doc"])
    _save_link(con, now, url, safe_claim, chat_id, res, door)
    return res


def _note_only(con, now, subject: str, verdict: str, summary: str, findings: List[dict], text: str, url: str, door: dict) -> dict:
    """A claim that did not check out (or a page with nothing to check): a dated note from him that `recall` finds, with the verdict, and NO graph event."""
    from pflab.kg2 import you
    from pflab.think import recall
    scope = door["scope"]
    links = you.link(text, scope, title=subject)
    body = f"He sent a link and a claim: {subject[:300]}. Checked against the sources: {verdict}. {summary}".strip()
    note = None
    try:
        for l in links[:1] or [None]:
            note = recall.write_back(con, now, isin=(l or {}).get("isin"), symbol=(_name_of(scope, l["isin"]) if l else None), topic=(None if l else subject[:80]),
                                     title=f"Checked claim ({verdict}): {subject[:120]}", text=body, source="you")
    except Exception as e:
        log.warning("note not written: %s", e)
    return {"isins": [l["isin"] for l in links[:1]], "event_ids": [], "note_doc": note, "links": links[:1], "scope": scope}


def _save_link(con, now, url, claim, chat_id, res: dict, door: Optional[dict] = None) -> None:
    from pflab.pm import store
    try:
        lid = store.next_id(con, "link_checks_s85", "link_id")
        con.execute("INSERT INTO link_checks_s85 (link_id, url, claim, checked_at, chat_id, verdict, sources_json, answer, isins_json, event_id, note_doc, cost_inr, warnings_json, result_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [lid, url, claim, now, chat_id, res.get("verdict"), json.dumps(res.get("sources")), res.get("answer"), json.dumps(res.get("isins")), res.get("event_id"), res.get("note_doc"),
                     res.get("cost_inr"), json.dumps(res.get("warnings")), json.dumps(res, default=str)])
    except Exception as e:
        log.warning("link check not stored: %s", e)


__all__ = ["read_attachment", "check_link", "only_sourced_in", "source_type", "fetch", "sheet_summary", "check_facts", "numbers_of", "missing_numbers", "node_of"]
