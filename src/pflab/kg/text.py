"""Article text for the knowledge graph (S38): fetched only where the site's robots.txt allows it, extracted with
trafilatura, stored as plain text under data/kg/text/<doc id>.txt for the investor's personal use (never published).
Each document records its status: ok | robots_disallow | fetch_error | no_text. Requests are spaced per host.
"""
from __future__ import annotations

import time
import urllib.robotparser as rp
from pathlib import Path
from typing import Callable, Dict, Optional
from urllib.parse import urlparse

import requests

AGENT = "pflab-personal-research/1.0"


class Robots:
    def __init__(self, fetch: Optional[Callable[[str], Optional[str]]] = None):
        self._cache: Dict[str, rp.RobotFileParser] = {}
        self._fetch = fetch

    def allowed(self, url: str) -> bool:
        u = urlparse(url)
        base = f"{u.scheme}://{u.netloc}"
        if base not in self._cache:
            parser = rp.RobotFileParser()
            try:
                txt = self._fetch(base + "/robots.txt") if self._fetch else \
                    requests.get(base + "/robots.txt", headers={"User-Agent": AGENT}, timeout=15).text
                parser.parse((txt or "").splitlines())
            except Exception:
                parser.parse([])                                  # unreachable robots.txt: treated as no rules
            self._cache[base] = parser
        return self._cache[base].can_fetch(AGENT, url)


def extract(html: str, url: str = "") -> Optional[str]:
    import trafilatura
    return trafilatura.extract(html, url=url, include_comments=False, include_tables=False)


def extract_title(html: str) -> Optional[str]:
    import trafilatura
    try:
        md = trafilatura.extract_metadata(html)
        return (md.title or "").strip() or None if md else None
    except Exception:
        return None


def fetch_texts(con, out_dir: Path, limit: int = 50, robots: Optional[Robots] = None,
                get: Optional[Callable] = None, spacing: float = 2.0) -> Dict[str, int]:
    robots = robots or Robots()
    get = get or (lambda u: requests.get(u, headers={"User-Agent": AGENT}, timeout=20))
    rows = con.execute("SELECT doc_id, url FROM kg_docs WHERE kind = 'article' AND text_status IS NULL "
                       "AND url IS NOT NULL ORDER BY published_at DESC LIMIT ?", [limit]).fetchall()
    out_dir.mkdir(parents=True, exist_ok=True)
    stats: Dict[str, int] = {}
    last: Dict[str, float] = {}
    for did, url in rows:
        host = urlparse(url).netloc
        if not robots.allowed(url):
            status, path = "robots_disallow", None
        else:
            wait = spacing - (time.time() - last.get(host, 0.0))
            if wait > 0:
                time.sleep(wait)
            last[host] = time.time()
            try:
                r = get(url)
                text = extract(r.text, url) if getattr(r, "status_code", 200) == 200 else None
                if text:
                    path = out_dir / f"{did.replace(':', '_')}.txt"
                    path.write_text(text, encoding="utf-8")
                    status = "ok"
                    title = extract_title(r.text)
                    if title:                                     # the real headline replaces the URL slug
                        con.execute("UPDATE kg_docs SET title = ? WHERE doc_id = ?", [title[:500], did])
                        con.execute("UPDATE kg_nodes SET name = ? WHERE node_id = ?", [title[:200], did])
                else:
                    status, path = "no_text", None
            except Exception:
                status, path = "fetch_error", None
        con.execute("UPDATE kg_docs SET text_status = ?, text_path = ? WHERE doc_id = ?",
                    [status, str(path) if path else None, did])
        stats[status] = stats.get(status, 0) + 1
    return stats
