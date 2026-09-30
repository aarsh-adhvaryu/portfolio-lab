"""Credit-rating revision attachments: fetch, extract, mask (A1 plan §2).

    python tools/rating_pdfs.py --audit      # the audit's 21 rows (~1 min)
    python tools/rating_pdfs.py --history    # every revision 2010-2026 (Aarsh's job)

`--audit` writes `docs/data/rating_pdf_labels.md`: one row per PDF with the
audit row number and a masked extract around the rating lines, and an empty
column for Aarsh to mark UP, DOWN or NO CHANGE. No returns and no company
names. `--history` only fetches and caches; nothing reads the files yet.

WHERE THE AUDIT ROWS COME FROM
-----------------------------
`docs/data/flag_audit.md` was drawn at 041ec33 (2026-09-25). The 2026-09-27
D1/D2 repairs widened E1's eligible universe, so today's code draws a
different sample (254 rows). The drawing commit's eligible set, run on
today's data, reproduces the committed file exactly (251/251), and
`flag_audit_sample.build(eligible=...)` with that set gives each row's
announcement. That mapping is saved once to
`data/bse_attachments/audit_rows.json` (row, attachment, company; gitignored,
because it names companies) and read from there.

FETCHING
--------
Old-style names are served from `corpfiling/AttachHis/`; the UUID names are
not, and resolve through `stockinfo/AnnPdfOpen.aspx?Pname=`, which redirects
to `CorpAttachment/<year>/<month>/`. Files are cached under
`data/bse_attachments/` and never fetched twice. 0.8 s between requests, the
collectors' pace.

A scanned PDF yields no text; it is counted and left unlabelled. No OCR
(CLAUDE.md 7).
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from flag_audit_sample import mask_text  # noqa: E402

logging.getLogger("pypdf").setLevel(logging.ERROR)   # font-encoding chatter

HIS = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/"
LIVE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
OPEN = "https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname="
PAUSE = 0.8
REVISION = re.compile(r"revis", re.I)

# lines that carry a rating, its direction or its instrument ...
_RATING_LINE = re.compile(
    r"rating|revis|upgrad|downgrad|reaffirm|affirm|withdraw|outlook|watch|"
    r"raised|lowered|existing|stable|negative|positive|"
    r"CRISIL|ICRA|CARE|IND[- ]?A|ACUITE|BWR|Brickwork|Moody|Fitch|S&P", re.I)
# ... and never the letterhead, address or regulatory boilerplate, which is
# where a letter names its company
_SKIP_LINE = re.compile(
    r"regulation|SEBI|listing|exchange|plot|office|attn|\btel\b|fax|floor|"
    r"tower|dalal|bandra|mumbai|road|group|dear|sir|madam|^\s*(?:ref|re)\s*:",
    re.I)


def _root() -> Path:
    from pflab.data import data_dir
    d = data_dir() / "bse_attachments"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch(name: str, session: requests.Session, root: Path) -> Path | None:
    """The cached PDF, fetching it first if needed; None if BSE has none."""
    out = root / name
    if out.exists() and out.stat().st_size:
        return out
    from pflab.data.bse_announcements import HEADERS
    h = dict(HEADERS, Accept="application/pdf,*/*")
    for url in (HIS + name, OPEN + name, LIVE + name):
        time.sleep(PAUSE)
        r = session.get(url, headers=h, timeout=60, allow_redirects=True)
        if r.status_code == 200 and r.content[:5] == b"%PDF-":
            out.write_bytes(r.content)
            return out
    return None


def extract(path: Path) -> tuple[str, int]:
    """(text, pages). Empty text means a scanned PDF."""
    from pypdf import PdfReader
    rd = PdfReader(str(path))
    parts = []
    for p in rd.pages:
        try:
            parts.append(p.extract_text() or "")
        except Exception:                      # a broken page, not a broken file
            parts.append("")
    return "\n".join(parts), len(rd.pages)


def mask_pdf(text: str, company: str, also: list | None = None) -> str:
    """mask_text line by line, plus the identifiers a letter carries and a
    headline does not: CIN, ISIN, e-mail, web address, scrip code, phone,
    and `also` -- named entities found on review (a subsidiary, a group),
    kept per row in the gitignored mapping."""
    out = []
    for ln in text.splitlines():
        for term in also or []:
            ln = re.sub(re.escape(term), "[ENTITY]", ln, flags=re.I)
        ln = re.sub(r"\bIN[A-Z0-9]\d{3}[A-Z0-9]{5}\d\b", "[ISIN]", ln)
        ln = re.sub(r"\b[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b", "[CIN]", ln)
        ln = re.sub(r"\S+@\S+", "[EMAIL]", ln)
        ln = re.sub(r"(?:https?://|www\.)\S+", "[WEB]", ln, flags=re.I)
        ln = re.sub(r"\b\d{6}\b", "[CODE]", ln)
        ln = re.sub(r"\+?\d[\d\s-]{8,}\d", "[PHONE]", ln)
        ln = mask_text(ln, company)
        if ln:
            out.append(ln)
    return "\n".join(out)


def rating_extract(masked: str, limit: int = 900) -> str:
    """The lines that state ratings, in order, up to `limit` characters."""
    keep = [ln for ln in masked.splitlines()
            if _RATING_LINE.search(ln) and not _SKIP_LINE.search(ln)]
    s = " / ".join(keep)
    return s[:limit] + (" …" if len(s) > limit else "")


def audit(out_md: Path) -> int:
    root = _root()
    rows = json.loads((root / "audit_rows.json").read_text(encoding="utf-8"))
    ses = requests.Session()
    t0, recs = time.time(), []
    for r in rows:
        p = fetch(r["attachment"], ses, root)
        if p is None:
            recs.append({**r, "status": "NOT FOUND", "pages": 0, "chars": 0, "extract": ""})
            continue
        text, pages = extract(p)
        if not text.strip():
            recs.append({**r, "status": "SCANNED", "pages": pages, "chars": 0, "extract": ""})
            continue
        m = mask_pdf(text, r["company"], r.get("also_mask"))
        recs.append({**r, "status": "text", "pages": pages, "chars": len(text),
                     "extract": rating_extract(m)})
    secs = time.time() - t0
    n_scan = sum(x["status"] == "SCANNED" for x in recs)
    n_miss = sum(x["status"] == "NOT FOUND" for x in recs)
    lines = [
        "# Rating-revision attachments — for Aarsh to mark direction",
        "",
        f"Fetched {pd.Timestamp.today():%Y-%m-%d} by `tools/rating_pdfs.py --audit` "
        f"({secs:.0f} s). The {len(recs)} RATING_DOWNGRADE rows of",
        "`docs/data/flag_audit.md` whose headline says \"revision\" with no",
        "direction (all UNCLEAR in `flag_audit_labels.md`). Text by `pypdf`,",
        "masked by `flag_audit_sample.mask_text` plus CIN, ISIN, e-mail, web,",
        "6-digit code and phone masks, and named entities found on review",
        "(`[ENTITY]`). The extract keeps only lines that state a rating, in",
        "order, and drops letterhead, address and regulatory boilerplate.",
        "**No returns and no company names in this file.**",
        "",
        f"Scanned (no text, not OCR'd): **{n_scan}**. Not found at BSE: **{n_miss}**.",
        "",
        "Mark **UP**, **DOWN** or **NO CHANGE** (reaffirmed, or an outlook or",
        "instrument change with the rating unchanged). A letter that moves two",
        "instruments in opposite directions: mark the long-term issuer or",
        "long-term debt rating and say so in the note. UNSURE is allowed.",
        "",
        "| row | pages | text | masked extract (rating lines) | direction | note |",
        "|---|---|---|---|---|---|",
    ]
    for x in recs:
        e = x["extract"].replace("|", "\\|") if x["status"] == "text" else f"({x['status']})"
        lines.append(f"| {x['row']} | {x['pages']} | {x['status']} | {e} |  |  |")
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(recs)} PDFs, {n_scan} scanned, {n_miss} not found, {secs:.0f} s -> {out_md}")
    return 0


def history() -> int:
    """Every RATING_DOWNGRADE event 2010-2026 worded as a revision, fetched
    and cached. Resumable: cached files are skipped."""
    from pflab.data import data_dir, red_flag_events as rfe
    root = _root()
    ev = rfe.load()
    ev = ev[(ev["flag"] == "RATING_DOWNGRADE") & ev["headline"].fillna("").str.contains(REVISION)]
    names = []
    for (y, d), g in ev.groupby([ev["key_dt"].dt.year, ev["key_dt"].dt.date]):
        f = data_dir() / "bse_announcements" / str(int(y)) / f"{d}.parquet"
        if not f.exists():
            continue
        a = pd.read_parquet(f, columns=["scrip_code", "headline", "attachment"])
        a["scrip_code"] = a["scrip_code"].astype(str).str.strip()
        m = a.merge(g[["scrip_code", "headline"]].astype(str), on=["scrip_code", "headline"])
        names += [n for n in m["attachment"].dropna().astype(str) if n]
    names = sorted(set(names))
    print(f"{len(ev)} revision events, {len(names)} attachments", flush=True)
    ses, t0, got, miss = requests.Session(), time.time(), 0, []
    for i, n in enumerate(names, 1):
        (got := got + 1) if fetch(n, ses, root) else miss.append(n)
        if i % 50 == 0:
            print(f"  {i}/{len(names)}  {(time.time() - t0) / i:.1f} s each", flush=True)
    (root / "_history.json").write_text(json.dumps(
        {"finished": time.strftime("%Y-%m-%d %H:%M:%S"), "attachments": len(names),
         "cached": got, "not_found": miss}, indent=1), encoding="utf-8")
    print(f"DONE -> {root}  cached {got}, not found {len(miss)}", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--audit", action="store_true")
    g.add_argument("--history", action="store_true")
    ap.add_argument("--out", default="docs/data/rating_pdf_labels.md")
    a = ap.parse_args(argv)
    return audit(Path(a.out)) if a.audit else history()


if __name__ == "__main__":
    sys.exit(main())
