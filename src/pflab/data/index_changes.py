"""Index constituent changes, from NSE Indices press releases.

Charter E1b §3/§4. This is the source layer; `index_membership` turns what it
returns into a point-in-time table.

Why not the F&O circulars
-------------------------
The obvious source is NSE's "Change in the Constituents of Indices" circular
series, and it is the wrong one. Those circulars exist because an index change
moves the F&O contracts, so they cover only derivative-eligible indices.
Across all 98 of them, 2006-2026:

    Nifty 200 sections:   0
    Nifty 500 sections:   3   (2006-2007 only)
    Nifty 100 sections:  10   (2006-2008 only)

Nifty 200 and Nifty 500 have no derivatives, so their reconstitutions are
never announced there. See docs/data/index_membership_finding.md.

The real source
---------------
NSE Indices Limited publishes every index change as a press release at
`niftyindices.com/Press_Release/ind_prs<DDMMYYYY>.pdf`. The archive listed on
`/media` holds 1,486 of them, 1998-2026, and it does carry the broad indices:

    Nifty 500       227 releases, continuous from 1998
    Nifty 100        56 releases, from 2006
    Nifty Midcap 100 48 releases, from 2005
    Nifty 200        58 releases, from 2011  <- the index did not exist before

Reading them
------------
`pypdf` first. It returns some of the older releases out of reading order --
whole sections ahead of their own headings -- which does not raise, it parses
cleanly into the wrong answer, attaching a company to whichever heading
happens to precede it. `validate` looks for exactly that (a row before the
first heading, a company repeated inside one index) and only a parse that
fails it is retried with `pdfplumber`, which is the only use CLAUDE.md 7
sanctions for that library. A release neither reader can parse cleanly is
reported as suspect rather than half-trusted.

pdfplumber renders these releases' faux-bold text as doubled glyphs
("IInnddiiaabbuullllss"), so `_dedouble_line` collapses it. The decision is
made per LINE, not per word: NSE bolds whole runs, and a per-word rule leaves
"77," undoubled -- the comma makes the token odd-length -- so "December 77,
2011" fails to parse and the change silently takes the announcement date, a
week early. Judging the line first also protects a real "77" on a plain line.
"""
from __future__ import annotations

import datetime
import io
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests

from pflab.data import data_dir

for _n in ("pypdf", "pdfminer", "pdfplumber", "pdfminer.pdfinterp"):
    logging.getLogger(_n).setLevel(logging.ERROR)

LISTING_URL = "https://www.niftyindices.com/media"
PRESS_RELEASE_BASE = "https://www.niftyindices.com/Press_Release/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
           "Accept": "*/*", "Referer": LISTING_URL}

# Index headings, as they appear over twenty years of house style. The names
# changed twice (IISL "S&P CNX" -> "CNX" -> NSE Indices "Nifty"), so each
# canonical index carries every spelling it has ever had.
_H = r"(?:\(?\d{1,2}[\)\.]\s*)?"          # optional "1)" / "2." list numbering
INDEX_PATTERNS = [
    ("NIFTY200", re.compile(_H + r"(?:S&\s*P\s+)?(?:CNX|NIFTY)\s*200(?:\s*Index)?", re.I)),
    ("NIFTY500", re.compile(_H + r"(?:S&\s*P\s+)?(?:CNX|NIFTY)\s*500(?:\s*Index)?", re.I)),
    ("NIFTY100", re.compile(_H + r"(?:S&\s*P\s+)?(?:CNX|NIFTY)\s*100(?:\s*Index)?", re.I)),
    # CNX Midcap -> Nifty Midcap 100 -> (Apr 2016) Nifty Free Float Midcap 100
    # -> Nifty Midcap 100 again. The 2016-02-22 restructure release says it
    # outright: "rebranding of existing Nifty Midcap 100 and Nifty Smallcap 100
    # indices ... published under the new names Nifty Free Float Midcap 100 and
    # Nifty Free Float Smallcap 100". Missing that alias cost both 2016 and
    # 2017 entirely -- two semi-annual review years with zero changes parsed.
    # "Nifty FULL Midcap 100" is a DIFFERENT index launched in the same
    # restructure and must not match.
    ("NIFTY_MIDCAP100", re.compile(
        _H + r"(?:CNX|NIFTY)\s*(?:Free\s*Float\s+)?Midcap(?:\s*100)?"
        r"(?:\s*Index)?", re.I)),
]

_MONTH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
          r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|"
          r"Dec(?:ember)?)")
EFFECTIVE_RE = re.compile(
    r"(?:w\.?\s*e\.?\s*f\.?|(?:become|becomes|shall\s+become|will\s+become)?\s*"
    r"effective\s+(?:from\s+)?|with\s+effect\s+from)\s*"
    r"(" + _MONTH + r"\s+\d{1,2}\s*,?\s*\d{4})", re.I)
# NSE's house style for the noun changed repeatedly over twenty years:
# "company/companies" (most), "security/securities" (~1,460 occurrences) and
# "scrip/scrips" (~112). Matching only the first silently drops whole years --
# it is what made 2016, a semi-annual review year inside E1b's development
# window, come back with zero Nifty 200 changes.
_THING = r"(?:compan(?:y|ies)|securit(?:y|ies)|scrips?|stocks?)"
# "is being excluded", "are being excluded" and "will be excluded" are all
# in use, sometimes in the same year.
ACTION_RE = re.compile(
    r"following\s+" + _THING + r"\s+(?:is|are|will)(?:\s+(?:being|be))?\s+"
    r"(excluded|included)", re.I)
# "1 Redington (India) Limited REDINGTON" -- the symbol is upper-case, has no
# lower-case letters, and is the last token.
ROW_RE = re.compile(r"^(\d{1,3})\s+(.+?)\s+([A-Z][A-Z0-9&\-\*\.]{1,14})\s*$")
ROW_NOSYM_RE = re.compile(r"^(\d{1,3})\s+([A-Za-z][A-Za-z0-9&\.\,\-\(\)\' ]{4,80}?)\s*\*?$")
# The table's third column is not always the symbol. Releases up to about
# 2009 print "Sr. No. | Company Name | Industry", and reading that as a symbol
# takes "BANKS" for Bank of Punjab and leaves the industry glued to the
# company name, so the row resolves to nothing. The header decides which.
HEADER_SYMBOL_RE = re.compile(r"sr\.?\s*no\.?.*\bsymbol\b", re.I)
HEADER_INDUSTRY_RE = re.compile(r"sr\.?\s*no\.?.*\bindustry\b", re.I)
# an industry is a run of upper-case words at the end of the row
ROW_INDUSTRY_RE = re.compile(r"^(\d{1,3})\s+(.+?)\s+([A-Z][A-Z&\-\. ]{3,40})\s*$")

_NOISE_RE = re.compile(
    r"^(sr\.?\s*no\.?|no\.?|compan[a-z]?\s*n\s*ame|scrip\s+name|security\s+name|"
    r"constituents?|symbol|industry|place\s*:|date\s*:|page\s+\d+|"
    r"press\s+release|for\s+and\s+on\s+behalf|national\s+stock\s+exchange|"
    r"nse\s+indices|iisl|india\s+index\s+services)", re.I)

# The index's size is fixed by construction, so a correctly reconstructed
# membership has exactly this many names on every date. Any drift is a missed
# or misparsed change, not a fact about the market.
INDEX_SIZE = {"NIFTY200": 200, "NIFTY500": 500, "NIFTY100": 100,
              "NIFTY_MIDCAP100": 100}


class PressReleaseMissing(RuntimeError):
    """The archive lists the release but the server does not serve it."""


# -- listing and fetching ----------------------------------------------
def _date_of(filename: str) -> Optional[datetime.date]:
    m = re.match(r"ind_prs(\d{2})(\d{2})(\d{4})", filename)
    if not m:
        return None
    try:
        return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def press_release_index(root: Optional[Path] = None,
                        refresh: bool = False) -> pd.DataFrame:
    """Every press release the archive lists: file, date, url."""
    root = root or data_dir()
    cache = root / "index_membership" / "raw" / "press_release_listing.txt"
    if refresh or not cache.exists():
        r = requests.get(LISTING_URL, headers=HEADERS, timeout=90)
        r.raise_for_status()
        files = sorted(set(re.findall(
            r"/Press_Release/(ind_prs[0-9a-zA-Z_]+\.pdf)", r.text)))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("\n".join(files), encoding="utf-8")
    files = [ln.strip() for ln in cache.read_text(encoding="utf-8").splitlines()
             if ln.strip()]
    df = pd.DataFrame({"file": files})
    df["date"] = df["file"].map(_date_of)
    df["url"] = PRESS_RELEASE_BASE + df["file"]
    return df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def fetch(filename: str, root: Optional[Path] = None,
          refresh: bool = False) -> bytes:
    """One press release, cached on disk."""
    root = root or data_dir()
    p = root / "index_membership" / "raw" / "press_releases" / filename
    if refresh or not p.exists() or p.stat().st_size == 0:
        r = requests.get(PRESS_RELEASE_BASE + filename, headers=HEADERS, timeout=90)
        r.raise_for_status()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(r.content)
    return p.read_bytes()


# -- text extraction ---------------------------------------------------
def _split_token(tok: str) -> tuple:
    m = re.match(r"^(\W*)(.*?)(\W*)$", tok, re.S)
    return m.groups() if m else ("", tok, "")


def _is_doubled(core: str) -> bool:
    return len(core) >= 2 and len(core) % 2 == 0 and core[0::2] == core[1::2]


def _dedouble_line(line: str) -> str:
    """Undo pdfplumber's faux-bold glyph doubling, one line at a time.

    Line-level and not word-level, because the decision needs context. NSE
    doubles whole runs of text, so a line is either bold or it is not; judging
    each word alone gets "77," wrong -- the comma makes the token odd-length,
    the word survives undoubled, and "December 77, 2011" then fails to parse
    as a date and silently falls back to the announcement date, which is a
    week early. Judging the line first also protects a genuine "77" on a line
    that was never bold.
    """
    toks = line.split(" ")
    eligible = [c for _, c, _ in map(_split_token, toks) if len(c) >= 4 and len(c) % 2 == 0]
    if len(eligible) < 2 or sum(map(_is_doubled, eligible)) / len(eligible) < 0.5:
        return line
    out = []
    for tok in toks:
        lead, core, trail = _split_token(tok)
        out.append(lead + (core[0::2] if _is_doubled(core) else core) + trail)
    # Punctuation is doubled too ("((India))", "&&"). Collapsing a repeated
    # punctuation mark is only safe once the line is known to be bold, which
    # is why it lives here and not in the general cleanup.
    return re.sub(r"([^\w\s])\1", r"\1", " ".join(out))


def _dedouble(text: str) -> str:
    return "\n".join(_dedouble_line(ln) for ln in text.splitlines())


def _pypdf_text(content: bytes) -> str:
    import pypdf
    return "\n".join(p.extract_text() or ""
                     for p in pypdf.PdfReader(io.BytesIO(content)).pages)


def _pdfplumber_text(content: bytes) -> str:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def _generic_heading(line: str) -> bool:
    """Any index name on its own line, recognised or not.

    An unrecognised heading MUST still close the section above it. Without
    this, "4) CNX Realty Index" is invisible and its companies are read as
    part of the Midcap section immediately above -- a silent wrong answer,
    which is worse than a failed parse.
    """
    t = re.sub(r"\s+", " ", line.strip().rstrip(":").strip())
    if not t or len(t) > 60:
        return False
    return bool(re.fullmatch(
        r"(?:\(?\d{1,2}[\)\.]\s*)?(?:S&\s*P\s+)?(?:CNX|NIFTY|Nifty)"
        r"[A-Za-z0-9 &/\-\.:]{0,45}", t, re.I))


def text_of(content: bytes, reader: str = "pypdf") -> str:
    if not content.lstrip()[:5].startswith(b"%PDF"):
        raise PressReleaseMissing("not a PDF (the server served an error page)")
    return (_pypdf_text(content) if reader == "pypdf"
            else _dedouble(_pdfplumber_text(content)))


def validate(changes: list, text: str,
             empty_sections: Optional[List[str]] = None) -> list:
    """Reasons this parse cannot be trusted. Empty list means it can.

    Every check here is for a SILENT failure. A PDF that will not open is
    obvious; a PDF whose text comes back out of reading order parses cleanly
    and attaches companies to the wrong index, which is the failure that would
    actually reach the portfolio.
    """
    problems = []

    seen = set()
    for c in changes:
        key = (c["index"], c["action"], c["company"])
        if key in seen:
            problems.append(f"duplicate row {key}")
        seen.add(key)

    lines = [ln.strip() for ln in text.splitlines()]
    first_heading = next((i for i, ln in enumerate(lines)
                          if _generic_heading(ln)), None)
    first_body = next((i for i, ln in enumerate(lines)
                       if ACTION_RE.search(ln)
                       or (ROW_RE.match(ln) and not _NOISE_RE.match(ln))), None)
    if first_body is not None and (first_heading is None or first_body < first_heading):
        problems.append("a table row or action line precedes the first heading")

    if changes:
        n_sym = sum(1 for c in changes if c.get("symbol"))
        if 0 < n_sym < len(changes):
            problems.append(f"only {n_sym} of {len(changes)} rows carry a symbol")

    # A heading with "the following companies are being excluded" under it and
    # no rows means the table did not come back with its section. The release
    # says a change happened; we just cannot see it. That is the one case that
    # must never be recorded as "no change".
    if empty_sections:
        problems.append(f"section(s) with an action line but no rows: "
                        f"{sorted(set(empty_sections))}")
    return problems


# -- parsing -----------------------------------------------------------
def _index_of_heading(line: str) -> Optional[str]:
    s = re.sub(r"\s+", " ", line.strip().rstrip(":").strip())
    if not s or len(s) > 60:
        return None
    for canon, pat in INDEX_PATTERNS:
        if pat.fullmatch(s):
            return canon
    return None


def _parse_effective(s: str) -> Optional[datetime.date]:
    s = re.sub(r"\s*,\s*", " ", s.strip())
    for fmt in ("%B %d %Y", "%b %d %Y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def parse(text: str, default_effective: Optional[datetime.date] = None,
          empty_out: Optional[List[str]] = None) -> List[dict]:
    """Every inclusion and exclusion in one release.

    Returns [{"index", "action", "company", "symbol", "effective"}]. Only the
    four indices in INDEX_PATTERNS are returned; a release that also changes
    Nifty Bank or Nifty IT simply contributes nothing for those.
    """
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]

    # Effective dates. Searched over the JOINED text, not line by line:
    # "...effective from December 7 , 2011" is routinely split across a line
    # break, and a per-line search silently finds nothing and falls back to
    # the announcement date, which is days or weeks too early.
    import bisect
    starts, pos = [], 0
    for ln in lines:
        starts.append(pos)
        pos += len(ln) + 1
    joined = " ".join(lines)
    # `joined` uses one space per newline, so offsets still line up with
    # `starts`, which counted one character per line break.

    eff_at: Dict[int, datetime.date] = {}
    for m in EFFECTIVE_RE.finditer(joined):
        d = _parse_effective(m.group(1))
        if d:
            eff_at.setdefault(max(0, bisect.bisect_right(starts, m.start()) - 1), d)

    # Sections run from one index heading to the NEXT heading of any kind.
    all_heads = [i for i, ln in enumerate(lines) if _generic_heading(ln)]
    ours = [(i, _index_of_heading(lines[i])) for i in all_heads]
    ours = [(i, c) for i, c in ours if c]
    if not ours:
        return []
    bounds = {}
    for n, (i, canon) in enumerate(ours):
        nxt = [h for h in all_heads if h > i]
        bounds[n] = (i, nxt[0] if nxt else len(lines), canon)

    def effective_for(start: int, end: int) -> Optional[datetime.date]:
        """Nearest stated date: inside the section first, then the closest one
        anywhere. Modern releases put it after the rows, older ones before."""
        inside = [d for i, d in eff_at.items() if start <= i < end]
        if inside:
            return inside[0]
        if eff_at:
            nearest = min(eff_at, key=lambda i: (abs(i - start), i))
            return eff_at[nearest]
        return default_effective

    out: List[dict] = []
    empty_sections: List[str] = []
    for n in sorted(bounds):
        start, end, canon = bounds[n]
        eff = effective_for(start, end)
        action, column = None, None
        n_rows = 0
        for ln in lines[start + 1:end]:
            a = ACTION_RE.search(ln)
            if a:
                action = a.group(1).lower()
                continue
            if HEADER_SYMBOL_RE.search(ln):
                column = "symbol"
                continue
            if HEADER_INDUSTRY_RE.search(ln):
                column = "industry"
                continue
            if not ln or _NOISE_RE.match(ln) or action is None:
                continue

            if column == "industry":
                m = ROW_INDUSTRY_RE.match(ln)
                company = (m.group(2) if m else
                           (ROW_NOSYM_RE.match(ln).group(2)
                            if ROW_NOSYM_RE.match(ln) else None))
                if company:
                    out.append({"index": canon, "action": action,
                                "company": company.strip(), "symbol": None,
                                "effective": eff})
                    n_rows += 1
                continue

            m = ROW_RE.match(ln)
            if m and not re.search(r"[a-z]", m.group(3)):
                out.append({"index": canon, "action": action,
                            "company": m.group(2).strip(), "symbol": m.group(3),
                            "effective": eff})
                n_rows += 1
                continue
            m2 = ROW_NOSYM_RE.match(ln)
            if m2:
                out.append({"index": canon, "action": action,
                            "company": m2.group(2).strip(), "symbol": None,
                            "effective": eff})
                n_rows += 1
        if action is not None and n_rows == 0:
            empty_sections.append(canon)
    if empty_out is not None:
        empty_out.extend(empty_sections)
    return out


def parse_release(filename: str, root: Optional[Path] = None) -> dict:
    """One release end to end: {"changes", "reader", "problems", "error"}.

    pypdf first, as CLAUDE.md 7 requires. `validate` decides whether its text
    came back in reading order; only a parse that fails validation is retried
    with pdfplumber, and if that fails too the release is reported for review
    rather than half-trusted.
    """
    try:
        content = fetch(filename, root)
    except Exception as e:
        return {"changes": [], "reader": None, "problems": [],
                "error": f"{type(e).__name__}: {e}"}

    attempts = []
    for reader in ("pypdf", "pdfplumber"):
        try:
            text = text_of(content, reader)
        except PressReleaseMissing as e:
            return {"changes": [], "reader": None, "problems": [],
                    "error": f"PressReleaseMissing: {e}"}
        except Exception as e:
            attempts.append((reader, [], [f"{type(e).__name__}: {e}"]))
            continue
        empty: List[str] = []
        changes = parse(text, default_effective=_date_of(filename),
                        empty_out=empty)
        problems = validate(changes, text, empty_sections=empty)
        attempts.append((reader, changes, problems))
        if not problems:
            break

    clean = [x for x in attempts if not x[2]]
    reader, changes, problems = (clean[0] if clean else
                                 (attempts[-1] if attempts else
                                  ("pypdf", [], ["no reader produced text"])))
    for c in changes:
        c["source_file"] = filename
        c["announced"] = _date_of(filename)
    return {"changes": changes, "reader": reader, "problems": problems,
            "error": None}


def collect(root: Optional[Path] = None, refresh: bool = False,
            listing: Optional[pd.DataFrame] = None) -> tuple:
    """Every change in the whole archive. (DataFrame, report)."""
    listing = press_release_index(root, refresh) if listing is None else listing
    rows: List[dict] = []
    readers: Dict[str, int] = {}
    errors: List[dict] = []
    suspect: List[dict] = []
    for r in listing.itertuples(index=False):
        res = parse_release(r.file, root)
        if res["error"]:
            errors.append({"file": r.file, "date": str(r.date),
                           "error": res["error"]})
            continue
        readers[res["reader"]] = readers.get(res["reader"], 0) + 1
        if res["problems"]:
            # A release about Nifty Bank trips the heuristics and yields
            # nothing for us, which is harmless. Only a suspect release that
            # DID contribute a change needs a human to look at it, so the two
            # are counted separately rather than as one alarming number.
            suspect.append({"file": r.file, "date": str(r.date),
                            "problems": res["problems"][:4],
                            "yielded_changes": bool(res["changes"])})
        rows.extend(res["changes"])
    df = pd.DataFrame(rows, columns=["index", "action", "company", "symbol",
                                     "effective", "announced", "source_file"])
    report = {
        "releases_listed": int(len(listing)),
        "releases_read": int(len(listing) - len(errors)),
        "releases_unavailable": len(errors),
        "unavailable": errors,
        "readers": readers,
        "releases_suspect": len(suspect),
        "releases_suspect_with_changes": sum(1 for x in suspect
                                             if x["yielded_changes"]),
        "suspect": suspect,
        "changes": int(len(df)),
        "by_index": ({k: int(v) for k, v in df.groupby("index").size().items()}
                     if len(df) else {}),
        "missing_symbol": int(df["symbol"].isna().sum()) if len(df) else 0,
        "missing_effective": int(df["effective"].isna().sum()) if len(df) else 0,
    }
    return df, report


def write(df: pd.DataFrame, root: Optional[Path] = None) -> Path:
    root = root or data_dir()
    p = root / "index_membership" / "changes.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    return p


def load(root: Optional[Path] = None) -> pd.DataFrame:
    root = root or data_dir()
    return pd.read_parquet(root / "index_membership" / "changes.parquet")
