"""The daily review (S73, trimmed in S80 phase 4): every evening the system looks at what it has told him or promised, by code, and says what needs him. It costs nothing.

    envelope     what is available this month, whether the market is far enough below its high for the dip tranche (plan/envelope.py)
    rules        money rules and limits that wait for his yes
    scans, forward tests   hits on what he holds or watches, with the learner's label; the months recorded of each forward test

The proposal, claim and memory-flag parts are gone with the layers they read (proposals, readers, investigation scans). One note per day goes into the conversation
(a state is told once). Nothing is bought, sold, moved or changed. Exact numbers come from code; no model writes any of it.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional


def _index(rt):
    try:
        from pflab.hq import stocks
        return stocks.index_series(rt.data_root)
    except Exception:
        return None


def _scans(rt) -> List[str]:
    p = rt.pm_dir / "app" / "cache" / "scans.json"
    try:
        res = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        return []
    L = []
    for sid, r in (res.get("scans") or {}).items():
        hits = r.get("hits") or []
        if hits:
            L.append(f"Scan #{sid} has {len(hits)} hit(s) on what you hold or watch, e.g. {hits[0].get('symbol')}: {'; '.join(hits[0].get('why', []))[:100]} (information; see what the learner tested).")
    return L[:3]


def _forward(con) -> List[str]:
    rows = con.execute("SELECT claim, count(*), count(*) FILTER (WHERE status = 'settled') FROM forward_months GROUP BY 1 ORDER BY 1").fetchall()
    return ["Forward tests, months formed / settled: " + ", ".join(f"{c} {n}/{s}" for c, n, s in rows) + " (decided once at 24 months)."] if rows else []


def _waiting(con) -> List[str]:
    from pflab.hq import rules
    L = [f"Waiting for your yes (about money): {r['text'][:120]} [rule #{r['rule_id']}]" for r in rules.pending(con)]
    for q_id, text in con.execute("SELECT q_id, text FROM questions WHERE status = 'open' AND agent = 'limits' ORDER BY q_id LIMIT 6").fetchall():
        L.append(f"Waiting for your yes [Q#{q_id}]: {str(text)[:220]} (say yes or no here and I will apply it)")
    return L


def review(rt, now: Optional[datetime] = None) -> dict:
    from pflab.app import assistant
    from pflab.plan import envelope
    con, now = rt.cursor(), now or rt.clock()
    index = _index(rt)
    out: dict = {}
    L: List[str] = []
    for part in (lambda: [envelope.explain(envelope.status(con, now.date(), index))] if envelope.status(con, now.date(), index).get("active") else [],
                 lambda: _waiting(con), lambda: _scans(rt), lambda: _forward(con)):
        try:
            L += part()
        except Exception as e:                                # one part failing is said, never hidden, and never stops the others
            L.append(f"(a part of the review failed: {type(e).__name__}: {str(e)[:100]})")
            out.setdefault("failed", []).append(type(e).__name__)
    text = f"Daily review, {now:%a %d %b}:\n" + ("\n".join(f"- {x}" for x in L) if L else "- Nothing needs you today. Everything standing is where it was.")
    out["lines"] = len(L)
    out["told"] = assistant.notify(con, now, text, f"review:{now.date()}")
    return out
