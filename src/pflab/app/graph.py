"""S54e: the Knowledge graph screen. The graph holds thousands of documents, organisations, people and themes; the screen
draws it around the companies the investor owns or watches: each company, its sector and guard verdict, and the organisations,
people and themes its documents name most often (weighted by how many documents), as of any date (the growth slider).
Documents themselves are counted, not drawn; clicking a company lists its latest ones.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence

KINDS = ("company", "sector", "verdict", "org", "person", "theme")
DEFAULT_KINDS = ("company", "sector", "verdict", "org", "person")
TOP = 6                                    # neighbours of each kind per company
_THEME_NOISE = re.compile(r"^(TAX_|CRISISLEX_|EPU_|USPEC_|GENERAL_|UNGP_|SOC_|WB_\d+_?$)")


def theme_label(t: str) -> str:
    """GDELT theme codes as words: WB_1804_AIRPORTS -> airports, ECON_STOCKMARKET -> econ stockmarket."""
    t = re.sub(r"^WB_\d+_", "", t)
    return t.replace("_", " ").lower()


def clean_label(label, node_id: str) -> str:
    """A node's label as words: a missing name (None, NaN, 'nan', empty) falls back to the node's own id."""
    t = "" if label is None else str(label).strip()
    if t.lower() in ("", "nan", "none", "null", "<na>"):
        tail = str(node_id).split(":", 1)[-1].strip()
        return tail if tail and tail.lower() not in ("nan", "none") else str(node_id)
    return t


def _ts(upto: Optional[date]) -> datetime:
    return datetime.combine(upto, datetime.max.time()) if upto else datetime(2100, 1, 1)


def view(con, upto: Optional[date] = None, kinds: Sequence[str] = DEFAULT_KINDS, top: int = TOP) -> dict:
    kinds = [k for k in kinds if k in KINDS] or list(DEFAULT_KINDS)
    t = _ts(upto)
    comp = con.execute("""
        SELECT n.node_id, coalesce(i.symbol, n.name, n.node_id), lower(coalesce(i.name, n.name, '')) FROM kg_nodes n
        LEFT JOIN instruments i ON i.isin = split_part(n.node_id, ':', 2)
        WHERE n.kind = 'company'""").fetchall()
    ids = {c for c, _, _ in comp}
    nodes: Dict[str, dict] = {c: {"id": c, "kind": "company", "label": lab, "docs": 0} for c, lab, _ in comp}
    own_words = {c: {lab.lower(), (nm.split() or [""])[0]} - {""} for c, lab, nm in comp}
    edges: List[dict] = []
    owned = {d for (d,) in con.execute("SELECT dst FROM kg_edges WHERE rel='owns' AND valid_to IS NULL "
                                       "AND valid_from <= ?", [t]).fetchall()}
    watched = {d for (d,) in con.execute("SELECT dst FROM kg_edges WHERE rel='watches' AND valid_to IS NULL "
                                         "AND valid_from <= ?", [t]).fetchall()}
    for c in nodes.values():
        c["owned"], c["watched"] = c["id"] in owned, c["id"] in watched
    counts = con.execute("""
        SELECT e.dst, d.kind, count(DISTINCT e.src) FROM kg_edges e JOIN kg_docs d ON d.doc_id = e.src
        WHERE e.rel IN ('about', 'mentions') AND e.dst LIKE 'company:%' AND d.published_at <= ? AND d.dup_of IS NULL
        GROUP BY 1, 2""", [t]).fetchall()
    for c, k, n in counts:
        if c in nodes:
            nodes[c]["docs"] += int(n)
            nodes[c].setdefault("by_kind", {})[k] = int(n)
    for rel, kind in (("in_sector", "sector"), ("guard_status", "verdict")):
        if kind not in kinds:
            continue
        for src, dst, name in con.execute(f"""
                SELECT e.src, e.dst, coalesce(n.name, e.dst) FROM kg_edges e LEFT JOIN kg_nodes n ON n.node_id = e.dst
                WHERE e.rel = '{rel}' AND e.valid_to IS NULL AND (e.rel = 'in_sector' OR e.valid_from <= ?)""", [t]).fetchall():
            if src in ids:
                nodes.setdefault(dst, {"id": dst, "kind": kind, "label": name, "docs": 0})
                edges.append({"a": src, "b": dst, "w": 1, "rel": rel})
    near = [k for k in ("org", "person", "theme") if k in kinds]
    if near:
        rows = con.execute(f"""
            WITH cd AS (SELECT DISTINCT e.dst AS company, e.src AS doc FROM kg_edges e JOIN kg_docs d ON d.doc_id = e.src
                        WHERE e.rel IN ('about', 'mentions') AND e.dst LIKE 'company:%' AND d.published_at <= ?
                          AND d.dup_of IS NULL),
            nb AS (SELECT cd.company, e.dst AS other, split_part(e.dst, ':', 1) AS kind, count(DISTINCT cd.doc) AS w
                   FROM cd JOIN kg_edges e ON e.src = cd.doc AND e.rel IN ('names', 'has_theme')
                   WHERE split_part(e.dst, ':', 1) IN ({','.join('?' * len(near))}) GROUP BY 1, 2, 3)
            SELECT nb.company, nb.other, nb.kind, nb.w, coalesce(n.name, nb.other) FROM nb
            LEFT JOIN kg_nodes n ON n.node_id = nb.other
            ORDER BY nb.company, nb.kind, nb.w DESC""", [t, *near]).fetchall()
        taken: Dict[tuple, int] = {}
        for c, other, kind, w, name in rows:
            if c not in ids or (kind == "theme" and _THEME_NOISE.match(name or "")):
                continue
            if kind == "org" and name and (name.split() or [""])[0].lower() in own_words[c]:
                continue                                                    # the company naming itself
            k = (c, kind)
            if taken.get(k, 0) >= top or w < 2:                             # one document is not a link worth drawing
                continue
            taken[k] = taken.get(k, 0) + 1
            label = theme_label(name) if kind == "theme" else name
            n = nodes.setdefault(other, {"id": other, "kind": kind, "label": label, "docs": 0})
            n["docs"] = n["docs"] + int(w)
            edges.append({"a": c, "b": other, "w": int(w), "rel": "named with"})
    total = con.execute("SELECT (SELECT count(*) FROM kg_nodes), (SELECT count(*) FROM kg_edges), "
                        "(SELECT count(*) FROM kg_docs WHERE published_at <= ? AND dup_of IS NULL)", [t]).fetchone()
    for n in nodes.values():                                                # S68: a missing name is never drawn as "nan" or "None"
        n["label"] = clean_label(n.get("label"), n["id"])
    return {"nodes": list(nodes.values()), "edges": edges, "upto": str(upto) if upto else None, "kinds": kinds,
            "totals": {"nodes": total[0], "edges": total[1], "docs": total[2]}, "growth": growth(con)}


def growth(con, months: int = 24) -> List[dict]:
    """Documents added to the graph per month, by their own date (the slider's scale)."""
    start = (date.today().replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1)
    rows = con.execute("SELECT strftime(date_trunc('month', published_at), '%Y-%m') m, kind, count(*) FROM kg_docs "
                       "WHERE published_at >= ? GROUP BY 1, 2 ORDER BY 1", [start]).fetchall()
    out: Dict[str, dict] = {}
    for m, k, n in rows:
        out.setdefault(m, {"month": m})[k] = int(n)
    return list(out.values())


def node(con, node_id: str, upto: Optional[date] = None, limit: int = 15) -> dict:
    """A company's latest documents (title, kind, date, source); for another node, the companies it is named with."""
    t = _ts(upto)
    if node_id.startswith("company:"):
        docs = con.execute("""
            SELECT d.doc_id, d.kind, d.title, d.source, d.published_at FROM kg_edges e JOIN kg_docs d ON d.doc_id = e.src
            WHERE e.dst = ? AND e.rel IN ('about', 'mentions') AND d.published_at <= ? AND d.dup_of IS NULL
            GROUP BY ALL ORDER BY d.published_at DESC LIMIT ?""", [node_id, t, limit]).fetchall()
        return {"id": node_id, "docs": [{"id": i, "kind": k, "title": ti, "source": s, "at": str(p)[:10]}
                                         for i, k, ti, s, p in docs]}
    rows = con.execute("""
        SELECT c.dst, count(DISTINCT e.src) FROM kg_edges e JOIN kg_edges c ON c.src = e.src
        JOIN kg_docs d ON d.doc_id = e.src
        WHERE e.dst = ? AND c.rel IN ('about', 'mentions') AND c.dst LIKE 'company:%' AND d.published_at <= ?
        GROUP BY 1 ORDER BY 2 DESC LIMIT ?""", [node_id, t, limit]).fetchall()
    return {"id": node_id, "companies": [{"id": c, "docs": int(n)} for c, n in rows]}


__all__ = ["view", "node", "growth", "theme_label", "KINDS"]
