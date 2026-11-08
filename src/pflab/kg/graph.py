"""The knowledge graph (S38): nodes, time-aware edges, documents, in the PM store (migration 16).

Model (after Graphiti's bi-temporal edges, kept to what this system needs):
    an edge (src, rel, dst) is true from `valid_from` (when it became true or public: a trade date, a filing's
    dissemination time, a result's usable-from date, an article's GDELT time) until `valid_to` (NULL = still
    true). State relations (`owns`, `guard_status`, `in_sector`, `watches`) are functional per (src, rel): a new
    value closes the old edge at the change time, it never overwrites it, so "what did the graph say on date
    M" is answerable. Event relations (`about`, `mentions`, `has_theme`) never close.
Node ids: person:investor, company:<ISIN>, sector:<name>, doc:<kind>:<id>, theme:<code>, org:<name>,
person:<name>, verdict:<name>. Every edge carries its source (kind and reference).
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Iterable, List, Optional, Sequence

import pandas as pd

from pflab.kg import switch

STATE_RELS = {"owns", "guard_status", "in_sector", "watches"}


def _ts(x) -> datetime:
    if isinstance(x, datetime):
        return x
    if isinstance(x, date):
        return datetime(x.year, x.month, x.day)
    return pd.Timestamp(x).to_pydatetime()


def node(con, node_id: str, kind: str, name: Optional[str] = None, attrs: Optional[dict] = None,
         now: Optional[datetime] = None) -> None:
    if not switch.on():                                       # 2026-11-08: the graph is off until its design is agreed (kg/switch.py)
        return
    con.execute("INSERT INTO kg_nodes VALUES (?,?,?,?,?) ON CONFLICT (node_id) DO UPDATE SET "
                "name = COALESCE(excluded.name, kg_nodes.name), attrs_json = COALESCE(excluded.attrs_json, kg_nodes.attrs_json), "
                "updated_at = excluded.updated_at",
                [node_id, kind, name, json.dumps(attrs, default=str) if attrs else None, now or datetime.now()])


def edge(con, src: str, rel: str, dst: str, valid_from, source_kind: str, source_ref: str = "",
         attrs: Optional[dict] = None, now: Optional[datetime] = None) -> bool:
    """Add an edge. For a state relation, an open edge (src, rel) to a different dst is closed at `valid_from`;
    the same open edge again is a no-op. Returns True when something was added."""
    if not switch.on():
        return False
    vf = _ts(valid_from)
    if rel in STATE_RELS:
        cur = con.execute("SELECT dst, valid_from FROM kg_edges WHERE src=? AND rel=? AND valid_to IS NULL",
                          [src, rel]).fetchall()
        if rel == "owns" or rel == "watches":                 # many open dsts allowed; one open edge per dst
            if any(d == dst for d, _ in cur):
                return False
        else:
            if any(d == dst for d, _ in cur):
                return False
            for d, f in cur:
                if f <= vf:
                    con.execute("UPDATE kg_edges SET valid_to=? WHERE src=? AND rel=? AND dst=? AND valid_from=?",
                                [vf, src, rel, d, f])
    n0 = con.execute("SELECT count(*) FROM kg_edges").fetchone()[0]
    con.execute("INSERT INTO kg_edges VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                [src, rel, dst, vf, None, source_kind, source_ref, json.dumps(attrs, default=str) if attrs else None,
                 now or datetime.now()])
    return con.execute("SELECT count(*) FROM kg_edges").fetchone()[0] > n0


def close(con, src: str, rel: str, dst: str, at, ) -> int:
    """End an open state edge (a position sold, a name taken off the list)."""
    if not switch.on():
        return 0
    r = con.execute("UPDATE kg_edges SET valid_to=? WHERE src=? AND rel=? AND dst=? AND valid_to IS NULL",
                    [_ts(at), src, rel, dst])
    return r.fetchone()[0] if r.description else 0


def doc(con, kind: str, key: str, published_at, title: str = "", url: str = "", source: str = "",
        tone: Optional[float] = None, themes: str = "", attrs: Optional[dict] = None,
        now: Optional[datetime] = None) -> str:
    did = f"doc:{kind}:{hashlib.sha1(key.encode()).hexdigest()[:16]}"
    con.execute("INSERT INTO kg_docs (doc_id, kind, url, title, source, published_at, tone, themes, attrs_json, text_path, "
                "text_status, ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                [did, kind, url or None, title[:500], source, _ts(published_at), tone, themes,
                 json.dumps(attrs, default=str) if attrs else None, None, None, now or datetime.now()])
    node(con, did, kind, title[:200], None, now)
    return did


def as_of(con, src: str, rel: str, at) -> List[str]:
    """Destinations of `rel` edges from `src` that were true at `at` (point in time)."""
    t = _ts(at)
    return [r[0] for r in con.execute(
        "SELECT dst FROM kg_edges WHERE src=? AND rel=? AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?) "
        "ORDER BY dst", [src, rel, t, t]).fetchall()]


def timeline(con, company: str, since, until=None, kinds: Sequence[str] = ("filing", "result", "article"),
             limit: int = 50) -> pd.DataFrame:
    """Documents about or mentioning a company, newest first, published in [since, until]."""
    until = _ts(until) if until else datetime(2999, 1, 1)
    q = f"""SELECT d.published_at, d.kind, d.title, d.source, d.tone, d.url, d.doc_id, d.text_status
            FROM kg_edges e JOIN kg_docs d ON d.doc_id = e.src
            WHERE e.dst = ? AND e.rel IN ('about', 'mentions') AND d.published_at BETWEEN ? AND ? AND d.dup_of IS NULL
              AND d.kind IN ({','.join('?' * len(kinds))})
            ORDER BY d.published_at DESC LIMIT {int(limit)}"""
    return con.execute(q, [company, _ts(since), until, *kinds]).df()


def neighbours(con, node_id: str, at=None) -> pd.DataFrame:
    t = _ts(at) if at else datetime.now()
    return con.execute("""SELECT rel, dst AS other, valid_from, valid_to, source_kind FROM kg_edges
                          WHERE src = ? AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)
                          UNION ALL
                          SELECT rel || ' (in)', src, valid_from, valid_to, source_kind FROM kg_edges
                          WHERE dst = ? AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)
                          ORDER BY valid_from DESC""", [node_id, t, t, node_id, t, t]).df()
