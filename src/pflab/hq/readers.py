"""The readers (S59, BRAIN.md layer 3): Haiku 5.5 reads every public document about a held or listed company.

For each filing, result, article or market-data export in the graph (originals only) that no reader has read: is it
material (yes / no / unsure, with one sentence why), a summary of at most 60 words, and up to 8 figures, each with the
words around it copied from the document. Code keeps a figure only when its value and its quote are both found in the
document (no model-made numbers); dropped figures are counted. Each reading is kept (`hq_readings`) and goes into the
knowledge graph as a `reading` linked to the company, so the brain reads summaries, never raw documents.

Held names first, then the list; filings and results before articles; newest first; at most `limit` a run. Public
documents only: nothing of the investor's is in a reader's request.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from pflab.hq import egress
from pflab.hq import governor as gv
from pflab.hq import llm

DOC_CHARS = 12_000
KINDS = ("filing", "result", "article", "dataset", "email")     # "email": documents of that kind from before email was removed (2026-10-30)
MAT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["material", "why"],      # S61 slider
              "properties": {"material": {"type": "string", "enum": ["yes", "no", "unsure"]}, "why": {"type": "string"}}}
SYSTEM = (
    "You read one public document about an Indian listed company for a private investor's portfolio system. Reply "
    "with JSON only. material: 'yes' if it could change the company's earnings, risk, ownership or share price in a "
    "way an investor should know (quarterly results, guidance, large orders, mergers and acquisitions, management "
    "change, regulatory or legal action, default, rating change, fund raising, promoter pledges or sales), 'no' for "
    "routine filings (trading window, newspaper advertisements, meeting notices, routine compliance), 'unsure' "
    "otherwise. why: one sentence. summary: at most 60 words, plain, what the document says. figures: up to 8 key "
    "figures; for each give name, value copied exactly as written in the document, unit, period, page (the number "
    "of the [page N] marker the figure sits under, or empty when the document has no markers), and quote: the few "
    "words around the figure copied exactly from the document. Never compute, convert or round a figure.")
FIELDS = ("name", "value", "unit", "period", "page", "quote")
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["material", "why", "summary", "figures"],
          "properties": {
              "material": {"type": "string", "enum": ["yes", "no", "unsure"]},
              "why": {"type": "string"}, "summary": {"type": "string"},
              "figures": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False, "required": list(FIELDS),
                  "properties": {k: {"type": "string"} for k in FIELDS}}}}}
PDF_PAGES = 30
_PAGE = re.compile(r"\[page (\d+)\]")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _digits(s: str) -> str:
    return re.sub(r"[,\s]", "", s or "")


def _pages(text: str) -> Dict[str, str]:
    """'[page N]' markers -> each page's text (a document without markers is one page, '')."""
    parts = _PAGE.split(text)
    if len(parts) == 1:
        return {"": text}
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def check_figures(figures: List[dict], text: str) -> Tuple[List[dict], int]:
    """Keep a figure only when its value (commas and spaces aside) and its quote are both in the document, and on the
    page it names when the document has pages."""
    keep, gone = split_figures(figures, text)
    return keep, len(gone)


def split_figures(figures: List[dict], text: str) -> Tuple[List[dict], List[dict]]:
    """(kept, dropped): the figure's number (its digits, commas aside; the unit may be written around it) must be in
    its quote and the quote in the document. The page is set by code from where the quote is (2026-10-24: the model
    gave the PDF's printed page labels, one off from the pages); a paged document needs a quote."""
    pages = _pages(text)
    keep, gone = [], []
    for f in figures or []:
        num = re.search(r"\d[\d,]*(?:\.\d+)?", str(f.get("value", "")))
        n = num.group(0).replace(",", "") if num else ""
        q = _norm(str(f.get("quote", "")))
        if len(pages) > 1:
            on = [p for p, t in pages.items() if q and q in _norm(t)]
            ok = bool(n and on) and n in _digits(q)
            if ok:
                f = {**f, "page": on[0]}
        else:
            ok = bool(n) and n in _digits(text) and (not q or (q in _norm(text) and n in _digits(q)))
        (keep if ok else gone).append(f)
    return keep, gone


def fetch_filing_text(con, row: dict, out_dir: Path, get=None) -> Optional[str]:
    """A BSE filing's attachment (PDF) as text with '[page N]' markers, kept beside the article texts (data/kg/text);
    the document's text_path and text_status are set as for articles. None when there is no text to be had."""
    url = row.get("url") or ""
    if not url.lower().endswith(".pdf"):
        return None
    import io
    import requests
    from pypdf import PdfReader
    from pflab.data import bse_announcements as ba
    try:
        r = (get or (lambda u: requests.get(u, headers=ba.HEADERS, timeout=30)))(url)
        if getattr(r, "status_code", 200) != 200:
            raise ValueError(f"HTTP {r.status_code}")
        pdf = PdfReader(io.BytesIO(r.content))
        text = "\n".join(f"[page {i}]\n{(p.extract_text() or '').strip()}" for i, p in enumerate(pdf.pages[:PDF_PAGES], 1))
        status = "ok" if len(_PAGE.sub("", text).strip()) > 40 else "no_text"     # a scanned image has no text layer
    except Exception:
        text, status = "", "fetch_error"
    path = None
    if status == "ok":
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{row['doc_id'].replace(':', '_')}.txt"
        path.write_text(text, encoding="utf-8")
    con.execute("UPDATE kg_docs SET text_status = ?, text_path = ? WHERE doc_id = ?", [status, str(path) if path else None,
                                                                                       row["doc_id"]])
    row["text_path"] = str(path) if path else None
    return text if status == "ok" else None


def doc_text(row: dict) -> str:
    """The document as the reader sees it: its title, a result's filed figures, its kept text."""
    body = row["title"] or ""
    a = json.loads(row["attrs"] or "{}")
    if row["kind"] == "filing" and (a.get("category") or a.get("subcategory")):
        body += f"\nBSE category: {a.get('category') or ''} / {a.get('subcategory') or ''}"
    if row["kind"] == "result":
        unit = {"eps": "rupees per share"}
        body += "\n" + ", ".join(f"{k.replace('_', ' ')} {v} {unit.get(k, 'million rupees')}" for k, v in a.items()
                                 if v is not None and k not in ("basis", "date_source"))
    elif row["kind"] == "dataset":
        body += "\n" + str(a.get("text") or "")
    if row["text_path"] and Path(row["text_path"]).exists():
        body += "\n" + Path(row["text_path"]).read_text(encoding="utf-8", errors="replace")
    return body[:DOC_CHARS]


def pending(con, asof: date, held: Sequence[str], listed: Sequence[str], days: int = 3, limit: int = 40,
            stock_list: Optional[List[dict]] = None) -> List[dict]:
    """Unread public documents about held, then listed, companies, published in the last `days` days."""
    from pflab.kg import build as kb
    isins = list(dict.fromkeys([*held, *listed]))
    if not isins:
        return []
    names = kb.names_for(con, isins, stock_list if stock_list is not None else [])
    since = datetime.combine(asof - timedelta(days=days), datetime.min.time())
    q = ",".join("?" * len(isins))
    rows = con.execute(f"""SELECT d.doc_id, d.kind, d.published_at, d.title, d.source, d.url, d.attrs_json, d.text_path,
                                  list(DISTINCT substr(e.dst, 9)) AS isins
                           FROM kg_docs d JOIN kg_edges e ON e.src = d.doc_id
                           WHERE e.dst IN ({q}) AND d.kind IN ({','.join('?' * len(KINDS))}) AND d.dup_of IS NULL
                             AND d.published_at >= ? AND d.doc_id NOT IN (SELECT doc_id FROM hq_readings)
                           GROUP BY ALL""", [*[f"company:{i}" for i in isins], *KINDS, since]).fetchall()
    from pflab.agents.analyst import same_story
    read = {same_story(t) for (t,) in con.execute(
        "SELECT d.title FROM hq_readings r JOIN kg_docs d ON d.doc_id = r.doc_id WHERE d.kind = 'article' AND r.read_at >= ?",
        [since]).fetchall()}
    out = []
    for doc_id, kind, pub, title, source, url, attrs, text_path, about in sorted(rows, key=lambda r: r[2], reverse=True):
        if kind == "dataset" and not shareable(attrs):
            continue                                       # (audit 2026-10-30) an upload not explicitly shareable is never selected
        about = [i for i in about if i in isins]
        if kind == "article" and not any(kb.is_about(title, names.get(i, [])) for i in about):
            continue                                       # a passing mention is not about the company
        if kind == "article" and (not text_path or same_story(title) in read):
            continue                                       # S59: a bare headline, or a story already read, is not read again
        if kind == "article":
            read.add(same_story(title))
        out.append({"doc_id": doc_id, "kind": kind, "published": pub, "title": title, "source": source, "url": url,
                    "attrs": attrs, "text_path": text_path, "isins": about,
                    "held": any(i in held for i in about)})
    rank = {"result": 0, "filing": 1, "dataset": 2, "email": 3, "article": 4}
    out.sort(key=lambda r: (not r["held"], rank[r["kind"]], -r["published"].timestamp()))
    return out[:limit]


def shareable(attrs) -> bool:
    """An upload may go to a provider only when the inbox explicitly judged it shareable; missing or false means private."""
    try:
        a = attrs if isinstance(attrs, dict) else json.loads(attrs or "{}")
    except ValueError:
        return False
    return a.get("shareable") is True


def params(text: str) -> dict:
    return {"model": gv.HAIKU, "max_tokens": gv.LIMITS["reader"].max_out,
            "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            "messages": [{"role": "user", "content": text}]}


PERSONAL = ("account number", "address", "PAN", "UPI id", "IFSC code", "his name")


class Withheld(Exception):
    """A document that may not leave this PC (S67): the reason is kept, the document is not retried."""


def email_for_api(row: dict, gate) -> str:
    """The text of an email-kind document as it may go to the API, or `Withheld`. An email is never a public kind: it goes only when
    (1) its provenance holds: the mail reader cleared it (`attrs.cleared` = the SHA-256 of the text it checked, when it named none of
    his ids) and the stored text still has that hash; and (2) the text is redacted and passes the full identity check NOW, as private
    text (not by the document-kind shortcut that public filings get). Raw email is never allowed out by kind alone."""
    import hashlib
    from pflab.hq import redact
    attrs = json.loads(row["attrs"] or "{}")
    p = row.get("text_path")
    if not attrs.get("cleared") or not p or not Path(p).exists():
        raise Withheld("the email has no clearance from the mail reader (provenance missing)")
    body = Path(p).read_text(encoding="utf-8", errors="replace")
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != attrs["cleared"]:
        raise Withheld("the stored email text changed after it was cleared")
    text = f"{row['title'] or ''}\n{body}"[:DOC_CHARS]
    clean, counts = redact.redact(text, gate, lines=False)          # a research desk's phone or e-mail is redacted and may go; his ids may not
    personal = sorted(k for k in counts if k in PERSONAL)
    if personal:
        raise Withheld("the email carries his own details (" + ", ".join(personal) + "): it is not public research")
    try:
        egress.check(clean, gate)
    except egress.EgressBlocked as e:
        raise Withheld(str(e))
    return clean


def withhold(con, row: dict, now: datetime, why: str) -> dict:
    """Record that a document was not sent, so it is not tried again and the screen can say why."""
    con.execute("INSERT INTO hq_readings VALUES (?,?,?,?,?,?,?,?,?,?)",
                [row["doc_id"], now, "none (not sent)", "no", f"withheld: {why}"[:400], "", "[]", 0, None, json.dumps(row["isins"])])
    return {"doc_id": row["doc_id"], "material": "no", "held": row["held"], "cost": 0.0, "dropped": 0, "withheld": why}


def read_one(con, row: dict, client, gate, now: datetime, mode: str, cfg: Optional[dict] = None) -> dict:
    from pflab.kg import graph as g
    if row["kind"] == "email":                          # provenance first: an email is private until the mail reader cleared it
        try:
            text = email_for_api(row, gate)
        except Withheld as e:
            return withhold(con, row, now, str(e))
        kinds, private = (), text                       # checked as private text, in full
    elif row["kind"] == "dataset":
        if not shareable(row.get("attrs")):
            return withhold(con, row, now, "a file you uploaded that is not marked shareable: it stays on this PC")
        text = doc_text(row)
        kinds, private = (row["kind"],), text           # even a shareable upload is checked as private text, in full
    else:
        text, kinds, private = doc_text(row), (row["kind"],), ""
    sent = llm.call(con, "reader", params(text), client, now=now, mode=mode, private_text=private, gate=gate,
                    doc_kinds=kinds, topic=",".join(row["isins"]), question=f"read {row['doc_id']}", cfg=cfg)
    out = sent.json()
    material = out.get("material") if out.get("material") in ("yes", "no", "unsure") else "unsure"
    from pflab.hq import brain
    mm, extra = brain.slider("materiality", gv.HAIKU), 0.0
    if mm != gv.HAIKU:                                  # S61: the slider moved materiality: that model's verdict stands
        p = {**params(text), "model": mm,
             "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": MAT_SCHEMA}}}
        ms = llm.call(con, "reader", p, client, now=now, mode=mode, private_text=private, gate=gate, doc_kinds=kinds,
                      topic=",".join(row["isins"]), question=f"materiality {row['doc_id']}", cfg=cfg)
        m, extra = ms.json(), ms.cost_inr
        if m.get("material") in ("yes", "no", "unsure"):
            material, out["why"] = m["material"], m.get("why", out.get("why", ""))
    figs, gone = split_figures(out.get("figures", []), text)
    dropped = len(gone)
    summary = str(out.get("summary", ""))[:600]
    con.execute("INSERT INTO hq_readings VALUES (?,?,?,?,?,?,?,?,?,?)",
                [row["doc_id"], now, gv.HAIKU, material, str(out.get("why", ""))[:400], summary, json.dumps(figs),
                 dropped, sent.call_id, json.dumps(row["isins"])])
    doc = g.doc(con, "reading", f"reading:{row['doc_id']}", row["published"], (row["title"] or "")[:200],
                source="reader (Haiku 5.5)", attrs={"material": material, "why": out.get("why", ""), "summary": summary,
                                                     "figures": figs, "of": row["doc_id"], "dropped": dropped,
                                                     "dropped_figures": gone}, now=now)
    for isin in row["isins"]:
        g.edge(con, doc, "about", f"company:{isin}", row["published"], "reader", row["doc_id"], now=now)
    return {"doc_id": row["doc_id"], "material": material, "held": row["held"], "cost": sent.cost_inr + extra,
            "dropped": dropped}


TEXT_DAYS, TEXT_PER_ROUND, TEXT_PAUSE_S = 120, 25, 1.0


def keep_texts(con, held: Sequence[str], listed: Sequence[str], text_dir: Path, now: datetime, days: int = TEXT_DAYS,
               limit: int = TEXT_PER_ROUND, get=None, pause: float = TEXT_PAUSE_S) -> dict:
    """S60 (The investor 2026-10-25: filings constantly up to date): every filing of a held or listed company keeps its
    attachment's text on this PC, whether or not a reader reads it: newest first, `limit` a round, back `days` days. Free
    (BSE, its own headers); a failed fetch is tried again while the filing is under a week old."""
    import time
    isins = list(dict.fromkeys([*held, *listed]))
    if not isins:
        return {"kept": 0, "failed": 0, "left": 0}
    q = ",".join("?" * len(isins))
    rows = con.execute(f"""SELECT DISTINCT d.doc_id, d.url, d.published_at FROM kg_docs d JOIN kg_edges e ON e.src = d.doc_id
                           WHERE e.dst IN ({q}) AND d.kind = 'filing' AND d.url ILIKE '%.pdf' AND d.published_at >= ?
                             AND (d.text_status IS NULL OR (d.text_status = 'fetch_error' AND d.published_at >= ?))
                           ORDER BY d.published_at DESC""",
                       [*[f"company:{i}" for i in isins], now - timedelta(days=days), now - timedelta(days=7)]).fetchall()
    kept = failed = 0
    for k, (doc_id, url, _) in enumerate(rows[:limit]):
        if k and pause:
            time.sleep(pause)                                 # polite to BSE
        if fetch_filing_text(con, {"doc_id": doc_id, "url": url}, text_dir, get):
            kept += 1
        else:
            failed += 1
    return {"kept": kept, "failed": failed, "left": max(0, len(rows) - limit)}


def run(con, asof: date, client, gate, now: datetime, mode: str, held: Sequence[str], listed: Sequence[str],
        limit: int = 40, days: int = 3, stock_list: Optional[List[dict]] = None, text_dir: Optional[Path] = None,
        get=None) -> dict:
    """Read what is pending; stop at the first refusal by the governor (the limits hold for the rest too). A filing's
    attachment is fetched first (`text_dir`); one without text is read from its title and BSE category."""
    done, stopped, failed = [], None, 0
    for row in pending(con, asof, held, listed, days, limit, stock_list):
        if row["kind"] == "filing" and not row["text_path"] and text_dir is not None:
            fetch_filing_text(con, row, text_dir, get)
        try:
            done.append(read_one(con, row, client, gate, now, mode))
        except gv.BudgetRefused as e:
            stopped = str(e)
            break
        except Exception:                                   # one bad document never stops the rest
            failed += 1
    return {"read": len(done), "withheld": sum(1 for d in done if d.get("withheld")), "material": sum(d["material"] == "yes" for d in done),
            "material_held": [d["doc_id"] for d in done if d["material"] == "yes" and d["held"]],
            "cost_inr": round(sum(d["cost"] for d in done), 2), "failed": failed, "stopped": stopped}


def recent(con, since: datetime, material_only: bool = True) -> List[dict]:
    """Readings of documents PUBLISHED since `since` (the brain's input): newest first. S64: the filter was the time of
    reading, so a document read late but published weeks ago looked new."""
    rows = con.execute("""SELECT r.doc_id, r.read_at, r.material, r.why, r.summary, r.figures_json, r.isins_json,
                                 d.kind, d.published_at, d.title
                          FROM hq_readings r JOIN kg_docs d ON d.doc_id = r.doc_id
                          WHERE d.published_at >= ? """ + ("AND r.material = 'yes' " if material_only else "") +
                       "ORDER BY d.published_at DESC", [since]).fetchall()
    keys = ["doc_id", "read_at", "material", "why", "summary", "figures", "isins", "kind", "published", "title"]
    out = []
    for r in rows:
        d = dict(zip(keys, r))
        d["figures"], d["isins"] = json.loads(d["figures"] or "[]"), json.loads(d["isins"] or "[]")
        out.append(d)
    return out
