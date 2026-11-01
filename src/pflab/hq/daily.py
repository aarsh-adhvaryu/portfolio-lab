"""The daily review (S73): every evening the system looks at everything it has told him or promised, by code, and says what needs him. It costs nothing.

The brain's morning pass (Opus, about Rs 5 a day for a look that mostly found nothing) is replaced by this. Code reads what stands:

    claims       every proposal states its claim the day it is made; those past 5, 20 or 60 sessions are scored (hq/scorecard.py)
    proposals    an open one whose price, record or lot data no longer match is said to be stale; a WAIT or HOLD names what reopens it
    envelope     what is available this month, whether the market is far enough below its high for the dip tranche (plan/envelope.py)
    rules        money rules and limits that wait for his yes; the learner's and the companion's proposals that wait too
    memory       a standing conclusion that new evidence now goes against (a material document, evidence against in another investigation, a review that is due): it is named, and
                 when it concerns a holding that matters a QUICK investigation is queued through the same guards as any the system starts itself (hq/missions.adopt)
    scans, forward tests   hits on what he holds or watches, with the learner's label; the months recorded of each forward test

One note per day goes into the conversation (a state is told once). Nothing is bought, sold, moved or changed. Exact numbers come from code; no model writes any of it.
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


def _proposals(con, rt, now) -> List[str]:
    from pflab.hq import proposals, scorecard
    L = []
    for p in proposals.listing(con, limit=40):
        if p["status"] not in ("proposed", "accepted"):
            continue
        why = proposals.stale_reason(con, p, rt.pm_dir)
        if why:
            L.append(f"Proposal #{p['proposal_id']} {p['action']} {p['symbol'] or ''} is stale: {why}")
    for (pid, act, sym) in con.execute("SELECT DISTINCT p.proposal_id, p.action, p.symbol FROM hq_claims c JOIN hq_proposals p ON p.proposal_id = c.proposal_id "
                                       "WHERE cast(c.scored_at AS DATE) = ? AND c.outcome IN ('good', 'bad')", [now.date()]).fetchall():
        v = scorecard.proposal_view(con, pid)
        L.append(f"Proposal #{pid} {act} {sym or ''} was scored: {v['verdict']} (" + ", ".join(f"{h['days']} days {h['outcome']}" for h in v["horizons"]) + ").")
    return L


def _memory(con, rt, now) -> List[str]:
    """Standing conclusions that new evidence now goes against; at most one quick investigation is queued."""
    from pflab.hq import cases
    from pflab.kg import memory
    from pflab.pm.store import next_id
    L, queued = [], 0
    for c in memory._concluded(con, None)[:8]:
        if not c["at"] or (now - c["at"]).days > 120:
            continue
        isins = [s.split(":", 1)[1] for s in c["subjects"] if s.startswith("company:")]
        new = []
        for doc, read_at, summary, js in con.execute("SELECT doc_id, read_at, summary, isins_json FROM hq_readings WHERE material = 'yes' AND read_at > ? ORDER BY read_at", [c["at"]]).fetchall():
            try:
                if set(json.loads(js or "[]")) & set(isins):
                    new.append((doc, str(summary or "")[:140]))
            except ValueError:
                pass
        fresh = [(d, s) for d, s in new if not con.execute("SELECT 1 FROM hq_memory_effects WHERE case_id = ? AND kind = 'flagged' AND ref = ?", [c["case_id"], d]).fetchone()]
        due = bool(c["next_review"] and c["next_review"] <= now)
        if not fresh and not due:
            continue
        for d, _s in fresh:
            con.execute("INSERT INTO hq_memory_effects VALUES (?,?,?,?,?,?)", [next_id(con, "hq_memory_effects", "effect_id"), c["case_id"], "flagged", d, "new evidence after the conclusion", now])
        L.append(f"Conclusion of investigation #{c['case_id']} ('{c['decision']}', {str(c['at'])[:10]}) "
                 + (f"has {len(fresh)} new document(s) since: {fresh[0][1]}" if fresh else "is due for its review")
                 + ("; a quick re-check is queued." if (fresh and queued < 1 and isins) else "."))
        if fresh and isins and queued < 1:
            cid, new_case = cases.open_case(con, now, f"Re-check the earlier conclusion of investigation #{c['case_id']} ({c['question'][:200]}): new evidence since: {fresh[0][1]}",
                                            origin="code", subject=None, isin=isins[0], key=f"discover:reading:daily:{c['case_id']}:{fresh[0][0]}")
            queued += int(bool(new_case))
    return L


def pot_to_proposals(rt, now: datetime) -> List[str]:
    """The opportunity pot's open ideas become proposals in the one ledger (so they are scored like the rest and obey the house rules): a BUY with the buy price, the exit and
    the stop that code worked out, and an amount that cannot pass what is left in the pot. An idea exists only after the pot's limit has his yes; nothing is bought."""
    from pflab.hq import proposals
    con = rt.cursor()
    have = set()
    for (pj,) in con.execute("SELECT payload_json FROM hq_proposals WHERE payload_json LIKE '%pot_idea%'").fetchall():
        try:
            have.add(int(json.loads(pj).get("pot_idea")))
        except (ValueError, TypeError):
            pass
    L = []
    for iid, isin, sym, reason, bb, ea, sb, amount in con.execute(
            "SELECT idea_id, isin, symbol, reason, buy_below, exit_above, stop_below, amount FROM pot_ideas WHERE status = 'open' ORDER BY idea_id").fetchall():
        if int(iid) in have:
            continue
        out = proposals.create(con, now, {"action": "BUY", "isin": isin, "symbol": sym, "amount_rupees": amount,
                                          "reason": f"Opportunity pot idea: {reason} Worked out by code: buy at or below {bb}, exit above {ea}, stop below {sb}.",
                                          "alternatives": "Waiting for the buy-below price, or leaving the pot unspent."}, by="the opportunity pot")
        if out.get("stored"):
            pj = json.loads(con.execute("SELECT payload_json FROM hq_proposals WHERE proposal_id = ?", [out["proposal_id"]]).fetchone()[0])
            pj["pot_idea"], pj["pot"] = int(iid), {"buy_below": bb, "exit_above": ea, "stop_below": sb}
            con.execute("UPDATE hq_proposals SET payload_json = ? WHERE proposal_id = ?", [json.dumps(pj, default=str), out["proposal_id"]])
            L.append(f"Opportunity pot idea {sym} became proposal #{out['proposal_id']} (buy at or below {bb}); it is advice, nothing is bought.")
        else:
            L.append(f"Opportunity pot idea {sym} was not proposed: {str(out.get('problem'))[:140]}")
    return L


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
    from pflab.hq import scorecard
    from pflab.plan import envelope
    con, now = rt.cursor(), now or rt.clock()
    index = _index(rt)
    out = {"claims_stated": scorecard.register_missing(con, now, index), "claims_scored": scorecard.score_due(con, now, index)}
    L: List[str] = []
    for part in (lambda: _proposals(con, rt, now), lambda: [envelope.explain(envelope.status(con, now.date(), index))] if envelope.status(con, now.date(), index).get("active") else [],
                 lambda: _waiting(con), lambda: pot_to_proposals(rt, now), lambda: _memory(con, rt, now), lambda: _scans(rt), lambda: _forward(con)):
        try:
            L += part()
        except Exception as e:                                # one part failing is said, never hidden, and never stops the others
            L.append(f"(a part of the review failed: {type(e).__name__}: {str(e)[:100]})")
            out.setdefault("failed", []).append(type(e).__name__)
    text = f"Daily review, {now:%a %d %b}:\n" + ("\n".join(f"- {x}" for x in L) if L else "- Nothing needs you today. Everything standing is where it was.")
    out["lines"] = len(L)
    out["told"] = assistant.notify(con, now, text, f"review:{now.date()}")
    return out


def reconcile_and_tell(rt) -> int:
    """A trade he made arrives (a confirmation, a statement, Kite): it is matched to the proposal he accepted (hq/proposals.reconcile, which tells him and reopens the investigation),
    and now also: the investigation is linked into the graph again with its new position, and where he has an envelope he is told what is left of it. Free, code only."""
    from pflab.app import assistant
    from pflab.hq import proposals
    from pflab.kg import memory
    from pflab.plan import envelope
    con, now = rt.cursor(), rt.clock()
    done = proposals.reconcile(con, now)
    for d in done:
        row = con.execute("SELECT case_id, symbol FROM hq_proposals WHERE proposal_id = ?", [d["proposal_id"]]).fetchone()
        if row and row[0]:
            try:
                memory.record_case(con, int(row[0]), now)
            except Exception:
                pass
        env = envelope.status(con, now.date(), _index(rt))
        if env.get("active"):
            assistant.notify(con, now, "After that trade: " + envelope.explain(env), f"envelope-after:{d['proposal_id']}:{d['status']}")
    return len(done)
