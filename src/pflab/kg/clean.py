"""S57 knowledge-graph cleanup (PLAN A8; the investor: "keep the KG clean, no overlapping statements"; the rule he chose for
the dashboard's cleanup: automatic when exact, ask when unsure). Nothing is thrown away: a merged name becomes an alias,
a syndicated copy points at its original, an older note gets its end date.

    names        organisations that are one name once legal endings are taken off ("Indian Oil Corp" = "Indian Oil
                 Corporation Ltd") merge into one node; an organisation that is one of the graph's companies by the same
                 rule ("Widget Co Ltd" = Widget Co Limited, company:INE999W01011) merges into the company. Anything less
                 certain about one of his companies (one extra word: "Gadget Industries Group") is asked, once; his
                 yes merges it, his no keeps them apart for good.
    copies       articles with the same headline on the same day (one wire story, many outlets) point at the earliest
                 (`dup_of`): counts, news spikes and the analyst's documents use the original only
    memory       per company, the newest analyst note is current; earlier ones get their end date (they stay readable)

Each run returns what it did, for the cleanup log; the knowledge-graph job runs it every night.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

ENDINGS = {"ltd", "limited", "inc", "incorporated", "corp", "corporation", "co", "plc", "llc", "llp"}
LEADING = {"the", "company", "m/s"}
UNSURE_WORDS = {"group", "india", "holdings", "industries", "enterprises", "ventures"}
# "<company> International" and "<company> Global" are a different entity in practice (the foreign arm or a subsidiary, e.g. Tata Power International): the system keeps
# them apart by itself and does not ask him (2026-11-08: he was asked whether "tata power international" was Tata Power, an answer the system could give).
KEEP_APART_WORDS = {"international", "global"}


def name_key(name: str) -> str:
    """Lower case, '&' as 'and', punctuation as space, a leading 'the'/'company' and trailing legal endings removed;
    'private'/'pvt' only as part of 'private limited' ("Nifty Private Bank" keeps it)."""
    w = re.sub(r"[^a-z0-9/ ]", " ", (name or "").lower().replace("&", " and ")).split()
    while len(w) > 1 and w[0] in LEADING:
        w = w[1:]
    cut = False
    while len(w) > 1 and w[-1] in ENDINGS:
        w, cut = w[:-1], True
    if cut and len(w) > 1 and w[-1] in ("private", "pvt"):
        w = w[:-1]
    return " ".join(w)


def _alias(con, alias: str, canonical: str, how: str, now: datetime) -> None:
    con.execute("INSERT INTO kg_aliases VALUES (?,?,?,?) ON CONFLICT (alias) DO UPDATE SET canonical=excluded.canonical, "
                "how=excluded.how, decided_at=excluded.decided_at", [alias, canonical, how, now])


def merge(con, alias: str, canonical: str) -> int:
    """Move every edge of `alias` onto `canonical` (an edge already there stays once) and drop the alias node."""
    cols = "valid_from, valid_to, source_kind, source_ref, attrs_json, ingested_at"
    n = con.execute("SELECT count(*) FROM kg_edges WHERE dst = ? OR src = ?", [alias, alias]).fetchone()[0]
    con.execute(f"INSERT INTO kg_edges SELECT src, rel, ?, {cols} FROM kg_edges WHERE dst = ? ON CONFLICT DO NOTHING",
                [canonical, alias])
    con.execute(f"INSERT INTO kg_edges SELECT ?, rel, dst, {cols} FROM kg_edges WHERE src = ? ON CONFLICT DO NOTHING",
                [canonical, alias])
    con.execute("DELETE FROM kg_edges WHERE dst = ? OR src = ?", [alias, alias])
    con.execute("DELETE FROM kg_nodes WHERE node_id = ?", [alias])
    return n


YES = {"yes", "y", "yeah", "yep", "same", "correct", "true", "right", "sure", "haan", "han", "ha", "ok", "okay"}
NO = {"no", "n", "nope", "not", "different", "false", "wrong", "nahi", "na", "separate"}


def yes_no(answer) -> Optional[bool]:
    """True, False, or None when the answer says neither ("not the same" is a no; "same" alone is a yes)."""
    w = re.findall(r"[a-z]+", str(answer or "").lower())
    if not w:
        return None
    if w[0] in NO or {"not", "different", "separate"} & set(w):
        return False
    if w[0] in YES or "same" in w:
        return True
    return None


def names(con, now: datetime) -> Dict[str, object]:
    from pflab.agents import questions as qs
    orgs = con.execute("SELECT n.node_id, n.name, (SELECT count(*) FROM kg_edges e WHERE e.dst = n.node_id) FROM kg_nodes n "
                       "WHERE n.kind = 'org'").fetchall()
    comp = con.execute("""SELECT n.node_id, coalesce(i.name, n.name), coalesce(i.symbol, '') FROM kg_nodes n
                          LEFT JOIN instruments i ON i.isin = split_part(n.node_id, ':', 2) WHERE n.kind = 'company'""").fetchall()
    decided = dict(con.execute("SELECT alias, canonical FROM kg_aliases").fetchall())
    company_by_key = {name_key(nm): (cid, nm, sym) for cid, nm, sym in comp if name_key(nm)}
    groups: Dict[str, List[Tuple[str, str, int]]] = defaultdict(list)
    for nid, nm, n in orgs:
        groups[name_key(nm or nid[4:])].append((nid, nm or nid[4:], n))
    merged, to_company, asked = 0, 0, 0
    for key, members in groups.items():
        if not key:
            continue
        if key in company_by_key:                                       # exact: the organisation is the company
            target, how = company_by_key[key][0], "exact: company"
        elif len(members) > 1:                                          # exact: one name, several spellings
            target, how = f"org:{key}", "exact: legal ending"
            con.execute("INSERT INTO kg_nodes VALUES (?, 'org', ?, NULL, ?) ON CONFLICT (node_id) DO NOTHING",
                        [target, max(members, key=lambda m: m[2])[1], now])
        else:
            continue
        for nid, _, _ in members:
            if nid == target or decided.get(nid) == nid:                 # his "no" keeps a name apart
                continue
            _alias(con, nid, target, how, now)
            merge(con, nid, target)
            merged += 1
            to_company += target.startswith("company:")
    # unsure, only about his companies: one extra word after the company's own name
    for key, (cid, nm, sym) in company_by_key.items():
        for okey, members in groups.items():
            extra = okey.split()[len(key.split()):]
            if not okey.startswith(key + " ") or len(extra) != 1 or extra[0] not in UNSURE_WORDS:
                continue
            for nid, onm, _ in members:
                if nid in decided:
                    continue
                if qs.ask(con, "knowledge graph", f"kg-same:{nid}=>{cid}",
                          f"Is \"{onm}\" (named in the news) the same as {nm} ({sym})? Answer yes or no; yes merges them in "
                          "the knowledge graph, no keeps them apart for good.", now) is not None:
                    asked += 1
    # his answers (S58b: read as yes or no from ordinary words; "same" is a yes; one that says neither is asked again)
    for subject, answer, qtext in con.execute("SELECT subject_key, answer, text FROM questions WHERE subject_key LIKE "
                                              "'kg-same:%' AND status = 'answered' ORDER BY answered_at").fetchall():
        nid, cid = subject[len("kg-same:"):].split(":again")[0].split("=>", 1)
        if nid in decided:
            continue
        said = yes_no(answer)
        if said is None:
            if qs.ask(con, "knowledge graph", f"kg-same:{nid}=>{cid}:again:{len(str(answer))}",
                      f"I could not tell yes or no from your answer \"{str(answer)[:60]}\". {qtext.split('?')[0]}? "
                      "Answer yes (they are the same) or no (keep them apart).", now) is not None:
                asked += 1
            continue
        decided[nid] = cid if said else nid
        if said:
            _alias(con, nid, cid, "his yes", now)
            merge(con, nid, cid)
            merged += 1
        else:
            _alias(con, nid, nid, "his no", now)
    return {"names_merged": merged, "into_companies": to_company, "asked": asked}


def title_key(t: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (t or "").lower()))


def copies(con) -> int:
    """Mark syndicated copies: same headline, same day; the earliest (then the smallest id) is the original."""
    rows = con.execute("SELECT doc_id, title, published_at FROM kg_docs WHERE kind = 'article' AND dup_of IS NULL "
                       "AND title IS NOT NULL AND title <> '' ORDER BY published_at, doc_id").fetchall()
    first: Dict[Tuple[str, object], str] = {}
    for did, t, p in con.execute("SELECT doc_id, title, published_at FROM kg_docs WHERE kind = 'article' AND dup_of IS NULL "
                                 "ORDER BY published_at, doc_id").fetchall():
        k = (title_key(t), p.date())
        if k[0] and len(k[0]) >= 20:                                     # a real headline, not a stub
            first.setdefault(k, did)
    n = 0
    for did, t, p in rows:
        orig = first.get((title_key(t), p.date()))
        if orig and orig != did:
            con.execute("UPDATE kg_docs SET dup_of = ? WHERE doc_id = ?", [orig, did])
            n += 1
    return n


def memory(con) -> int:
    """Per subject, the newest analyst note stays current; earlier open ones end on the day the next one began."""
    n = 0
    for subject in [r[0] for r in con.execute("SELECT DISTINCT subject FROM memory WHERE kind='note' AND valid_to IS NULL "
                                              "AND source LIKE 'analyst call #%'").fetchall()]:
        rows = con.execute("SELECT mem_id, valid_from FROM memory WHERE kind='note' AND subject=? AND valid_to IS NULL AND "
                           "source LIKE 'analyst call #%' ORDER BY created_at, mem_id", [subject]).fetchall()
        for (mid, _), (_, nxt_from) in zip(rows, rows[1:]):
            con.execute("UPDATE memory SET valid_to = ? WHERE mem_id = ?", [nxt_from, mid])
            n += 1
    return n


def run(con, now: Optional[datetime] = None) -> Dict[str, object]:
    """One cleanup, in one transaction."""
    from pflab.pm.store import transaction
    now = now or datetime.now()
    with transaction(con):
        out = names(con, now)
        out["copies_marked"] = copies(con)
        out["notes_ended"] = memory(con)
    out["at"] = now.isoformat(timespec="seconds")
    return out


def canonical(con, node_id: str) -> str:
    """The node a name was merged into (itself when never merged or kept apart)."""
    row = con.execute("SELECT canonical FROM kg_aliases WHERE alias = ?", [node_id]).fetchone()
    return row[0] if row else node_id
