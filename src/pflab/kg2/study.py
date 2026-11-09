"""The "graph earns its place" study: the code that measures it (S81 B7). Protocol: `docs/protocols/s81_kg_study_protocol.md` (committed before any run).

It only measures: nothing here changes the graph, a storyline or a switch. Judged later on live data; before the sample is complete it returns the counts and no
verdict (`verdict: "pending"`).
"""
from __future__ import annotations

import math
import re
from datetime import date
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

MIN_ARM = 30
MIN_DIFF = 0.05
Z_CRIT = 1.96
MIN_STRATUM = 10
NOT_BEFORE = date(2027, 5, 1)
MIN_ROWS = 100
CORRECT_MIN = 0.95


def _exists(con, table: str) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]).fetchone()[0])


def _proof_ok(row, root: Path, m: pd.DataFrame) -> bool:
    """A second, independent implementation of the two linking rules, applied to one sampled link."""
    rule = str(row["link_rule"])
    if rule.startswith("filing:"):
        mt = re.search(r"scrip (\w+) -> (\w+) valid on (\d{4}-\d{2}-\d{2})", str(row["link_proof"]))
        if not mt:
            return False
        scrip, isin, d = mt.group(1), mt.group(2), mt.group(3)
        sub = m[(m["scrip_code"] == scrip) & (m["isin"] == isin) & (m["valid_from"].astype(str).str[:10] <= d) & (m["valid_to"].astype(str).str[:10] >= d)]
        return bool(len(sub)) and isin == row["isin"]
    if rule.startswith("news:"):
        from pflab.kg2 import news, scope as sc
        s = sc.load(root)
        al = next((n["aliases"] for n in s["names"] if n["isin"] == row["isin"]), [])
        mt = re.search(r"org token '([^']+)'", str(row["link_proof"]))
        if not mt or mt.group(1) not in al:
            return False
        tp = news.text_path(root, news.url_hash(str(row["ref"])))
        if tp.exists():
            import json
            t = json.loads(tp.read_text(encoding="utf-8"))
            hay = " " + re.sub(r"[^a-z0-9&+ ]", " ", (t.get("title", "") + " " + t.get("text", "")).lower()) + " "
            return any(f" {a} " in hay for a in al)
        slug = " " + re.sub(r"[^a-z0-9]+", " ", str(row["ref"]).lower()) + " "
        return any(f" {a} " in slug or f" {a.split()[0]} " in slug for a in al)
    return False


def attachment_check(con, root: Path, day: date) -> dict:
    """Measure 1: (a) the hand-check sample re-derived independently; (b) graph evidence attached to storylines the company is exposed to."""
    root = Path(root)
    a_n = a_ok = 0
    sample = root / "kg" / "audit_sample.csv"
    if sample.exists():
        from pflab.kg2 import build as kb
        m = kb.scrip_map(root)
        m["valid_from"], m["valid_to"] = m["valid_from"].astype(str), m["valid_to"].astype(str)
        s = pd.read_csv(sample, dtype=str).fillna("")
        a_n = int(len(s))
        a_ok = int(sum(_proof_ok(r, root, m) for _, r in s.iterrows()))
    b_n = b_ok = 0
    if _exists(con, "storyline_evidence_s80") and _exists(con, "storyline_exposure_s80") and _exists(con, "kg2_event"):
        rows = con.execute("""SELECT e.evidence_id, x.isin,
                                     EXISTS (SELECT 1 FROM storyline_exposure_s80 p WHERE p.storyline_id = e.storyline_id AND p.isin = x.isin)
                              FROM storyline_evidence_s80 e JOIN kg2_event x ON x.event_id = e.source_ref
                              WHERE e.source_kind = 'kg2_event' AND e.evidence_date <= ?""", [day]).fetchall()
        b_n, b_ok = len(rows), sum(1 for r in rows if r[2])
    n = a_n + b_n
    ra = (a_ok / a_n) if a_n else None
    rb = (b_ok / b_n) if b_n else None
    if n < MIN_ROWS:
        verdict = "pending"
    else:
        verdict = "pass" if all(r is None or r >= CORRECT_MIN for r in (ra, rb)) else "fail"
    return {"sample_n": a_n, "sample_correct": a_ok, "sample_rate": ra, "evidence_n": b_n, "evidence_correct": b_ok, "evidence_rate": rb, "rows": n, "verdict": verdict}


def _z(h1: int, n1: int, h0: int, n0: int) -> float:
    p = (h1 + h0) / (n1 + n0)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n0))
    return 0.0 if se == 0 else (h1 / n1 - h0 / n0) / se


def prediction_comparison(con, day: date) -> dict:
    """Measure 2: the hit rate of scored storyline predictions with and without graph evidence on the storyline when the prediction was made."""
    if not (_exists(con, "storyline_predictions_s80") and _exists(con, "storyline_evidence_s80")):
        return {"verdict": "pending", "graph": {"n": 0, "hits": 0}, "plain": {"n": 0, "hits": 0}}
    rows = con.execute("""SELECT p.pred_id, s.kind, p.outcome,
                                 EXISTS (SELECT 1 FROM storyline_evidence_s80 e WHERE e.storyline_id = p.storyline_id AND e.source_kind = 'kg2_event'
                                         AND e.evidence_date <= p.made_on) AS has_graph
                          FROM storyline_predictions_s80 p JOIN storylines_s80 s USING (storyline_id)
                          WHERE p.outcome IN ('good', 'bad') AND p.due_on <= ?""", [day]).fetchall()
    arms: Dict[bool, list] = {True: [0, 0], False: [0, 0]}
    strata: Dict[str, Dict[bool, list]] = {}
    for _, kind, outcome, g in rows:
        hit = 1 if outcome == "good" else 0
        arms[bool(g)][0] += 1
        arms[bool(g)][1] += hit
        st = strata.setdefault(kind or "?", {True: [0, 0], False: [0, 0]})
        st[bool(g)][0] += 1
        st[bool(g)][1] += hit
    (ng, hg), (npl, hp) = arms[True], arms[False]
    out = {"graph": {"n": ng, "hits": hg, "rate": (hg / ng) if ng else None}, "plain": {"n": npl, "hits": hp, "rate": (hp / npl) if npl else None}}
    if ng < MIN_ARM or npl < MIN_ARM or day < NOT_BEFORE:
        out.update(verdict="pending", note=f"needs {MIN_ARM} scored predictions in each arm and a date on or after {NOT_BEFORE.isoformat()}")
        return out
    diff = hg / ng - hp / npl
    z = _z(hg, ng, hp, npl)
    ok_strata = True
    for kind, st in strata.items():
        if st[True][0] >= MIN_STRATUM and st[False][0] >= MIN_STRATUM and (st[True][1] / st[True][0] - st[False][1] / st[False][0]) <= 0:
            ok_strata = False
    out.update(diff=diff, z=z, strata_hold=ok_strata, verdict="pass" if (diff >= MIN_DIFF and z >= Z_CRIT and ok_strata) else "fail")
    return out
