"""Where the learner reads from (S62, PLAN A22): free sources only, nothing paid, nothing of the investor's leaves.

    arxiv      the arXiv API: new papers in quantitative finance (portfolio management, statistical finance, trading)
    openalex   the OpenAlex API: open-access papers for standing searches (anomalies, Indian and emerging markets)
    rss        investing and quant blogs' feeds (the list in configs/learner.toml); an article's text by trafilatura
    drop       files the investor puts in the drop folder's `learn` sub-folder (books, papers, articles: PDF, text, HTML); the
               watcher leaves sub-folders alone, and the files stay where they are
Each source is kept once (its `ref`), with its abstract; a cheap word screen by code drops what is not about stock
returns before any model reads it. Requests carry no identity (no e-mail in the API's polite pool), only the searches.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from pflab import _toml

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "learner.toml"
TEXT_CHARS = 60_000
RELEVANT = re.compile(r"\b(stock|equit\w*|share price|return\w*|anomal\w*|momentum|reversal|volatilit\w*|factor\w*|"
                      r"cross[- ]section\w*|earnings|announcement\w*|calendar|turn of the month|52[- ]week|lottery|"
                      r"illiquid\w*|liquidity|dividend\w*|india\w*|nifty|sensex|emerging market\w*|drift)\b", re.I)
OFF_TOPIC = re.compile(r"\b(crypto\w*|bitcoin|option pricing|blockchain|insurance|mortgage|deep hedging)\b", re.I)
logging.getLogger("pypdf").setLevel(logging.ERROR)          # font warnings from papers' PDFs are noise here
UA = {"User-Agent": "pflab-learner/1.0 (personal research; contact via the repository)"}

Get = Callable[[str, dict], str]


def config(path: Optional[Path] = None) -> dict:
    p = path or CONFIG
    return _toml.load(p) if p.exists() else {}


def http_get(url: str, params: dict) -> str:
    import requests
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=30)
            r.raise_for_status()
            return r.text
        except requests.RequestException:
            if attempt == 2:
                raise
            import time
            time.sleep(2 * (attempt + 1))
    return ""


def relevant(title: str, abstract: str) -> bool:
    t = f"{title} {abstract}"
    return bool(RELEVANT.search(t)) and not OFF_TOPIC.search(t)


def _add(con, now: datetime, origin: str, ref: str, title: str, authors: str, year: Optional[int], url: str,
         abstract: str, text_path: Optional[str] = None) -> Optional[int]:
    from pflab.pm.store import next_id
    if con.execute("SELECT 1 FROM learn_sources WHERE ref=?", [ref]).fetchone():
        return None
    ok = relevant(title, abstract)
    sid = next_id(con, "learn_sources", "src_id")
    con.execute("INSERT INTO learn_sources (src_id, found_at, origin, ref, title, authors, year, url, abstract, text_path, "
                "status, why) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [sid, now, origin, ref, title[:500], authors[:300], year, url[:600], abstract[:6000], text_path,
                 "new" if ok else "skipped", None if ok else "not about stock returns (word screen)"])
    return sid


# --- arXiv ---------------------------------------------------------------------------------------------------------------

ATOM = {"a": "http://www.w3.org/2005/Atom"}


def arxiv(con, now: datetime, get: Get = http_get, cfg: Optional[dict] = None) -> int:
    c = (cfg if cfg is not None else config()).get("arxiv", {})
    cats = c.get("categories", ["q-fin.PM", "q-fin.ST", "q-fin.TR"])
    xml = get("http://export.arxiv.org/api/query", {"search_query": " OR ".join(f"cat:{x}" for x in cats),
                                                    "sortBy": "submittedDate", "sortOrder": "descending",
                                                    "max_results": int(c.get("max_results", 50))})
    n = 0
    for e in ET.fromstring(xml).findall("a:entry", ATOM):
        aid = (e.findtext("a:id", "", ATOM) or "").rsplit("/", 1)[-1]
        title = " ".join((e.findtext("a:title", "", ATOM) or "").split())
        abstract = " ".join((e.findtext("a:summary", "", ATOM) or "").split())
        authors = ", ".join(a.findtext("a:name", "", ATOM) for a in e.findall("a:author", ATOM))
        year = int((e.findtext("a:published", "", ATOM) or "0000")[:4] or 0) or None
        if aid and _add(con, now, "arxiv", f"arxiv:{aid}", title, authors, year, f"https://arxiv.org/abs/{aid}", abstract):
            n += 1
    return n


# --- OpenAlex ------------------------------------------------------------------------------------------------------------

def inverted(idx: Optional[Dict[str, List[int]]]) -> str:
    """OpenAlex keeps abstracts as word -> positions."""
    if not idx:
        return ""
    pos = {p: w for w, ps in idx.items() for p in ps}
    return " ".join(pos[k] for k in sorted(pos))


def openalex(con, now: datetime, get: Get = http_get, cfg: Optional[dict] = None) -> int:
    c = (cfg if cfg is not None else config()).get("openalex", {})
    n = 0
    for q in c.get("searches", []):
        js = json.loads(get("https://api.openalex.org/works", {
            "search": q, "filter": f"is_oa:true,from_publication_date:{c.get('from', '2000-01-01')}",
            "sort": "relevance_score:desc", "per-page": int(c.get("per_search", 10))}))
        for w in js.get("results", []):
            url = ((w.get("open_access") or {}).get("oa_url") or w.get("doi") or w.get("id") or "")
            authors = ", ".join(((a.get("author") or {}).get("display_name") or "") for a in (w.get("authorships") or [])[:6])
            if _add(con, now, "openalex", f"openalex:{w.get('id', '').rsplit('/', 1)[-1]}", w.get("title") or "", authors,
                    w.get("publication_year"), url, inverted(w.get("abstract_inverted_index"))):
                n += 1
    return n


# --- blogs ---------------------------------------------------------------------------------------------------------------

def rss(con, now: datetime, get: Get = http_get, cfg: Optional[dict] = None) -> int:
    """RSS 2.0 and Atom feeds; the item's summary stands as its abstract (the article is fetched when read)."""
    feeds = (cfg if cfg is not None else config()).get("rss", {}).get("feeds", [])
    n = 0
    for f in feeds:
        try:
            root = ET.fromstring(get(f, {}))
        except Exception:                                    # one broken feed never stops the others
            continue
        items = root.findall(".//item") or root.findall(".//a:entry", ATOM)
        for it in items[:20]:
            title = (it.findtext("title") or it.findtext("a:title", "", ATOM) or "").strip()
            link = (it.findtext("link") or "").strip()
            if not link:
                le = it.find("a:link", ATOM)
                link = le.get("href", "") if le is not None else ""
            desc = it.findtext("description") or it.findtext("a:summary", "", ATOM) or ""
            desc = " ".join(re.sub(r"<[^>]+>", " ", desc).split())
            date_ = it.findtext("pubDate") or it.findtext("a:updated", "", ATOM) or ""
            year = int(m.group(0)) if (m := re.search(r"\b(19|20)\d{2}\b", date_)) else None
            if link and _add(con, now, "rss", f"rss:{link}", title, f.split("/")[2] if "//" in f else f, year, link, desc):
                n += 1
    return n


# --- the investor's files -------------------------------------------------------------------------------------------------------

def drop_folder(repo: Path) -> Path:
    from pflab.hq import watcher
    return watcher.folder(repo) / "learn"


def read_file(p: Path) -> str:
    s = p.suffix.lower()
    if s == ".pdf":
        from pypdf import PdfReader
        out = []
        for page in PdfReader(str(p)).pages:
            out.append(page.extract_text() or "")
            if sum(map(len, out)) > TEXT_CHARS * 4:
                break
        return "\n".join(out)
    raw = p.read_text(encoding="utf-8", errors="replace")
    if s in (".html", ".htm"):
        import trafilatura
        return trafilatura.extract(raw) or ""
    return raw


def drop(con, now: datetime, repo: Path, text_dir: Path) -> int:
    """Books and papers he drops in `drop\\learn`: kept by content hash, text stored here for the reading step."""
    d = drop_folder(repo)
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in sorted(x for x in d.iterdir() if x.is_file() and x.suffix.lower() in (".pdf", ".txt", ".md", ".html", ".htm")):
        h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        if con.execute("SELECT 1 FROM learn_sources WHERE ref=?", [f"drop:{h}"]).fetchone():
            continue
        text = read_file(p)
        text_dir.mkdir(parents=True, exist_ok=True)
        tp = text_dir / f"drop_{h}.txt"
        tp.write_text(text, encoding="utf-8")
        sid = _add(con, now, "drop", f"drop:{h}", p.stem.replace("_", " "), "", None, str(p), text[:3000], str(tp))
        if sid is not None:
            con.execute("UPDATE learn_sources SET status='new', why=NULL WHERE src_id=?", [sid])   # his choice: read it
            n += 1
    return n


def fetch_text(con, src_id: int, text_dir: Path, get: Get = http_get) -> str:
    """The full text of a source to read: his file's stored text; an arXiv paper's PDF; a blog article by trafilatura;
    else the abstract. Kept on this PC."""
    origin, ref, url, abstract, tp = con.execute(
        "SELECT origin, ref, url, abstract, text_path FROM learn_sources WHERE src_id=?", [src_id]).fetchone()
    if tp and Path(tp).exists():
        return Path(tp).read_text(encoding="utf-8")[:TEXT_CHARS]
    text = ""
    try:
        if origin == "arxiv":
            import io
            import requests
            from pypdf import PdfReader
            r = requests.get(f"https://arxiv.org/pdf/{ref.split(':', 1)[1]}", headers=UA, timeout=60)
            r.raise_for_status()
            text = "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(r.content)).pages[:30])
        elif origin == "rss":
            import trafilatura
            text = trafilatura.extract(get(url, {})) or ""
    except Exception:                                        # the abstract still stands
        text = ""
    text = text or abstract or ""
    text_dir.mkdir(parents=True, exist_ok=True)
    p = text_dir / f"src_{src_id}.txt"
    p.write_text(text[:TEXT_CHARS], encoding="utf-8")
    con.execute("UPDATE learn_sources SET text_path=? WHERE src_id=?", [str(p), src_id])
    return text[:TEXT_CHARS]


def collect(con, now: datetime, repo: Path, text_dir: Path, get: Get = http_get, cfg: Optional[dict] = None) -> dict:
    """Every source once; a failing one is reported, never fatal."""
    out = {}
    for name, fn in (("arxiv", lambda: arxiv(con, now, get, cfg)), ("openalex", lambda: openalex(con, now, get, cfg)),
                     ("rss", lambda: rss(con, now, get, cfg)), ("drop", lambda: drop(con, now, repo, text_dir))):
        try:
            out[name] = fn()
        except Exception as e:
            out[name] = f"failed: {type(e).__name__}: {str(e)[:150]}"
    return out
