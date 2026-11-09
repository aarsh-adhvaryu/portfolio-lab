"""Fetch a page an answer already cited (S60, PLAN A18; the investor 2026-10-24).

Only a URL the system already holds as a source may be fetched: a page an analyst note or web answer cited, or a
public filing or result in the knowledge graph. Anthropic's web fetch tool reads it (the basic `web_fetch_20250910`:
S59 found the dynamic-filtering variants drop citations), one fetch, restricted to that URL's host. Sonnet reads (the
workers' layer); the call is priced with the page at its content cap and governed like any other. The answer keeps a
sentence only when every number in it appears in the fetched text (no model-made numbers); it is kept as a note in the
graph beside the URL. BSE refuses Anthropic's fetcher (checked 2026-10-25: `url_not_accessible`), so for a filing the
readers' local copy (fetched here with BSE's headers when there is none) is read by Sonnet instead, and the note says so.
"""
from __future__ import annotations

import base64
import io
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Set
from urllib.parse import urlparse

from pflab.hq import egress, governor as gv, llm

TOOL = "web_fetch_20250910"
CONTENT_CAP = 40_000                    # tokens of fetched text at most (PDFs are not capped by the API: priced the same)
CITED_DAYS = 365
REFUSES = ("www.bseindia.com", "bseindia.com")      # url_not_accessible to Anthropic's fetcher (2026-10-25)
LOCAL_CHARS = 60_000                   # of a filing's local text read instead, when the site refuses the fetch
LOCAL_SYSTEM = ("You read one public filing for a private investor's portfolio system in India and answer the question "
                "from the DOCUMENT only, in at most 200 words of plain English. Copy every number exactly as the document "
                "writes it; say plainly what it does not state.")
_URL = re.compile(r"https?://[^\s)\]>\"']+")
SYSTEM = ("You read one public page or filing for a private investor's portfolio system in India. Fetch the URL you are "
          "given with the web_fetch tool, then answer the question from that document only, in at most 200 words of "
          "plain English. Copy every number exactly as the document writes it; say plainly what the document does not "
          "state.")


def cited_urls(con, now: datetime, days: int = CITED_DAYS) -> Set[str]:
    since = now - timedelta(days=days)
    out: Set[str] = set()
    for (attrs,) in con.execute("SELECT attrs_json FROM kg_docs WHERE kind = 'analyst_note' AND published_at >= ?",
                                [since]).fetchall():
        out |= {u.rstrip(".,;") for u in _URL.findall(json.loads(attrs or "{}").get("answer", "") or "")}
    for (u,) in con.execute("SELECT url FROM kg_docs WHERE kind IN ('filing', 'result') AND url IS NOT NULL AND "
                            "published_at >= ?", [since]).fetchall():
        out.add(u)
    return out


def fetched_text(message) -> str:
    """The document the fetch returned (text as it came; a PDF read with pypdf)."""
    parts = []
    for b in message.content:
        if getattr(b, "type", "") != "web_fetch_tool_result":
            continue
        doc = getattr(getattr(b, "content", None), "content", None)
        src = getattr(doc, "source", None)
        data, mt = getattr(src, "data", "") or "", getattr(src, "media_type", "") or ""
        if mt == "application/pdf":
            from pypdf import PdfReader
            try:
                rd = PdfReader(io.BytesIO(base64.b64decode(data)))
                parts.append("\n".join((p.extract_text() or "") for p in rd.pages))
            except Exception:
                continue
        else:
            parts.append(str(data))
    return "\n".join(parts)


def run(con, url: str, question: str, client, gate: egress.Gate, now: datetime, mode: str, cfg: Optional[dict] = None,
        text_dir: Optional[Path] = None) -> dict:
    from pflab.agents import analyst as an
    from pflab.kg import graph as g
    url = url.strip()
    if url not in cited_urls(con, now):
        raise ValueError("only a page the system already cites can be fetched (an analyst note's source or a filing in "
                         "the graph)")
    host = urlparse(url).hostname
    if not host:
        raise ValueError("not a web address")
    from pflab.hq import brain
    model = brain.slider("fetch", gv.SONNET)                       # S61: the slider's `fetch` job
    page, cost, how, s, err = "", 0.0, "web fetch", None, "this site refuses the fetcher"
    if host not in REFUSES:
        p = {"model": model, "max_tokens": gv.LIMITS["fetch"].max_out, "system": SYSTEM,
             "thinking": {"type": "adaptive"}, "output_config": {"effort": "low"},
             "tools": [{"type": TOOL, "name": "web_fetch", "max_uses": 1, "allowed_domains": [host],
                        "citations": {"enabled": True}, "max_content_tokens": CONTENT_CAP}],
             "messages": [{"role": "user", "content": f"URL: {url}\nQUESTION: {question}"}]}
        s = llm.call(con, "fetch", p, client, now=now, mode=mode, private_text=question, gate=gate, doc_kinds=("filing",),
                     topic="fetch", question=f"{question[:300]} ({url})", cfg=cfg, extra_in=CONTENT_CAP)
        page, cost, err = fetched_text(s.message), s.cost_inr, fetch_error(s.message)
    if not page.strip():
        local = local_text(con, url, text_dir)                # the readers' copy of a filing
        if not local:
            return {"text": f"The page could not be read ({err or 'no document came back'}).", "url": url,
                    "call_id": s.call_id if s else None, "cost": cost, "dropped": 0}
        page = local[:LOCAL_CHARS]
        q = {"model": model, "max_tokens": gv.LIMITS["fetch"].max_out, "system": LOCAL_SYSTEM,
             "thinking": {"type": "adaptive"}, "output_config": {"effort": "low"},
             "messages": [{"role": "user", "content": f"DOCUMENT ({url}):\n{page}\n\nQUESTION: {question}"}]}
        s = llm.call(con, "fetch", q, client, now=now, mode=mode, private_text=question, gate=gate, doc_kinds=("filing",),
                     topic="fetch", question=f"{question[:300]} ({url}, local copy)", cfg=cfg)
        cost, how = cost + s.cost_inr, f"local copy ({err})"
    answer, dropped = an.only_sourced_numbers(s.text, an.Request(page + "\n" + question, "fetch", [], [], True))
    g.doc(con, "analyst_note", f"fetch-{s.call_id}", now, question[:200], url=url, source=f"fetch ({model}, {how})",
          attrs={"answer": answer, "call_id": s.call_id, "fetched": url, "how": how}, now=now)
    return {"text": answer, "url": url, "call_id": s.call_id, "cost": cost, "dropped": dropped, "how": how}


def fetch_error(message) -> Optional[str]:
    for b in message.content:
        if getattr(b, "type", "") == "web_fetch_tool_result":
            c = getattr(b, "content", None)
            if getattr(c, "type", "") == "web_fetch_tool_result_error":
                return str(getattr(c, "error_code", "error"))
    return None


def local_text(con, url: str, text_dir: Optional[Path]) -> Optional[str]:
    """The kept text of a filing at `url`, when this PC has it."""
    r = con.execute("SELECT doc_id, url, text_path FROM kg_docs WHERE url = ? AND kind IN ('filing', 'result') LIMIT 1",
                    [url]).fetchone()
    if not r:
        return None
    if r[2] and Path(r[2]).exists():
        return Path(r[2]).read_text(encoding="utf-8", errors="replace")
    return None                                            # (the on-demand download went with the readers, S80 phase 4)
