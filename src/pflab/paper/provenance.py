"""Decision provenance (S79b item 18C): which sources stood behind every paper decision, and whether they were right.

At the moment a paper decision is recorded (`paper/manager.decide`) this module stores one row per SOURCE in `decision_provenance_s79`:
    tool:<name>           a tool call the decision cited ([call N] in its reason; role 'cited', weight 1) or, when it cited none, the evidence tools run in the
                          mission for this name (role 'consulted', weight 0.5). With cites, the uncited calls are listed with weight 0 (the record, no credit).
    agent:<role>          the team members who worked on the mission (the deciding role weight 1, the others 0.5); the reviewer joins at `execute`
    model:<name>          the model that spoke the decision (weight 1)
    forecaster:<name>     the forecasts in force that day for the name (or for the index, for cash decisions): one row per forecaster of `forecasts_s79`
                          (horizon nearest `forecast_horizon_sessions`), weight = its Hedge weight that day ('forecaster:hedge' = the combination, weight 1)
    bear_warning          a bear warning on the name made in the last `warning_days` days (`bear_warnings_s79`; direction -1)
    debate                the debate behind it (weight 0: listed)
    transmission / chain:<type>   causal chains of the latest situation report that mention the name (direction read from the chain's links when it states one)
    claim:<kind>          live situation claims about the name; direction = sign of `value` for the kinds sentiment, forecast and move, otherwise unknown (weight 0)
    situation_report, allocation_target   listed with weight 0 (the report and the allocation target in force)

`direction` is the source's own call on the stock (+1 up, -1 down; NULL for a tool or agent that simply backed the decision). `supports` is derived once, by code:
the source stood WITH the decision when its direction agrees with it (a BUY/ADD wants up, a REDUCE/SELL down, a HOLD up, a WAIT down); NULL direction = backed it;
direction 0 = cannot tell, not credited.

When `paper/manager.score_due` scores a decision's claim (good/bad at 7/28/84/182 days) `credit_scored` credits every source with weight >= `min_weight`:
    hit            the source was RIGHT: it supported the decision and the decision was good, or it opposed it and the decision was bad
    contribution   the decision's gain in percentage points (add/hold: market-adjusted return; trim: minus it; wait: minus the stock return; cash: cash less the
                   Nifty 500) with the source's sign: + when it supported, - when it opposed. It describes; it never raises a limit.
and the scorecard `source_scorecard_s79` per (market, source_kind, decision_kind, horizon) is rebuilt. Under `min_n` (20) credited decisions a row shows its count only.
Everything is by code; no model makes a number or a verdict. Every entry point is wrapped: provenance never blocks a decision. Switch: configs/s79b.toml [provenance] on.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "s79b.toml"
DEFAULTS = {"on": True, "forecast_horizon_sessions": 20, "headline_horizon_days": 28, "warning_days": 14, "min_weight": 0.05, "min_n": 20, "kg": True,
            "max_lines": 8}
EVIDENCE_ACTION_TOOLS = ("case_calculate", "web_search", "fetch_cited", "reproduce_calc")      # action-kind tools that still produce evidence
NOT_EVIDENCE = ("paper_book", "paper_decide", "provenance", "proposals", "system_allocation", "work_status", "case_evidence", "bear_scorecard", "forecast_scorecard")
DIRECTION_KINDS = ("sentiment", "forecast", "move")          # situation claims whose sign of `value` is a call on the stock
_TAG = re.compile(r"\[calls?\s*([\d,\s]+)\]", re.I)
_UP = ("up", "rise", "rises", "positive", "bull", "bullish", "higher", "gain", "+", "+1", "1")
_DOWN = ("down", "fall", "falls", "negative", "bear", "bearish", "lower", "loss", "-", "-1")


# --- switch and settings -----------------------------------------------------------------------------------------------------------------

def settings() -> dict:
    out = dict(DEFAULTS)
    try:
        from pflab import _toml
        out.update({k: v for k, v in (_toml.load(CONFIG).get("provenance") or {}).items() if k in DEFAULTS})
    except Exception:
        pass
    return out


def on() -> bool:
    return bool(settings()["on"])


def _has(con, table: str) -> bool:
    try:
        return con.execute("SELECT 1 FROM information_schema.tables WHERE table_name=?", [table]).fetchone() is not None
    except Exception:
        return False


def _market_of(isin: Optional[str], given: Optional[str] = None) -> str:
    if given and str(given).upper() in ("IN", "US"):
        return str(given).upper()
    return "US" if isin and str(isin).startswith("ZZ") else "IN"


def _sign(x: Optional[float], dead: float = 0.0005) -> int:
    if x is None:
        return 0
    return 1 if x > dead else -1 if x < -dead else 0


def supports(kind: str, direction: Optional[int]) -> Optional[bool]:
    """Did a source with this call on the stock stand with a decision of this kind? NULL direction: it backed the decision; 0: cannot tell (None)."""
    if direction is None:
        return True
    if direction == 0:
        return None
    return direction < 0 if kind in ("trim", "wait") else direction > 0


def _dir_word(v) -> int:
    s = str(v).strip().lower()
    return 1 if s in _UP else -1 if s in _DOWN else 0


def _chain_direction(links) -> int:
    """The direction a causal chain states for its last link ('direction', 'sign' or 'effect'); 0 when it states none."""
    try:
        obj = json.loads(links) if isinstance(links, str) else links
    except Exception:
        return 0
    seq = obj if isinstance(obj, list) else (obj.get("links") if isinstance(obj, dict) else None)
    if not seq:
        return 0
    last = seq[-1]
    if isinstance(last, dict):
        for k in ("direction", "sign", "effect"):
            if k in last:
                return _dir_word(last[k])
    return 0


def _ins(con, did: int, market: str, kind: str, sid, role: str, weight: float, now: datetime, direction: Optional[int] = None, kind_of_decision: Optional[str] = None,
         detail: Optional[dict] = None) -> int:
    """One provenance row (idempotent on decision, kind, id). `supports` is derived from the decision's kind when known."""
    sup = supports(kind_of_decision, direction) if kind_of_decision else None
    n0 = con.execute("SELECT count(*) FROM decision_provenance_s79 WHERE decision_id=?", [did]).fetchone()[0]
    con.execute("INSERT INTO decision_provenance_s79 VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                [did, market, kind, str(sid), role, float(weight), direction, sup, json.dumps(detail, default=str)[:600] if detail else None, now])
    return con.execute("SELECT count(*) FROM decision_provenance_s79 WHERE decision_id=?", [did]).fetchone()[0] - n0


# --- recording, at decide time ----------------------------------------------------------------------------------------------------------

def record(con, now: datetime, did: int, cid: Optional[int], inputs: Optional[dict] = None, market: Optional[str] = None) -> int:
    """Store the provenance of one decision. Returns the rows added. NEVER raises (a failure is logged and the decision stands)."""
    try:
        if not on() or not _has(con, "decision_provenance_s79"):
            return 0
        return _record(con, now, did, cid, inputs or {}, market)
    except Exception as e:
        log.warning("provenance: decision %s not recorded (%s: %s)", did, type(e).__name__, str(e)[:200])
        return 0


def _record(con, now: datetime, did: int, cid: Optional[int], inputs: dict, market: Optional[str]) -> int:
    from pflab.paper import manager
    action, isin, symbol, made_at = con.execute("SELECT action, isin, symbol, made_at FROM paper_decisions WHERE decision_id=?", [did]).fetchone()
    kind = manager.KIND[action]
    mk = _market_of(isin, market or inputs.get("market"))
    st = settings()
    n = 0
    n += _tools(con, now, did, cid, inputs, mk, kind, symbol, st)
    n += _agents(con, now, did, cid, inputs, mk, st)
    n += _forecasts(con, now, did, mk, kind, isin, st)
    n += _bear(con, now, did, mk, kind, isin, symbol, st)
    n += _situation(con, now, did, mk, kind, isin, symbol, st)
    n += _allocation(con, now, did, mk)
    return n


def _tools(con, now, did, cid, inputs, mk, kind, symbol, st) -> int:
    prov = inputs.get("_prov") or {}
    text = " ".join(str(x) for x in (inputs.get("reason"), inputs.get("alternatives"), prov.get("cited_text")) if x)
    cited = {int(x) for t in _TAG.findall(text) for x in re.findall(r"\d+", t)} | {int(x) for x in (prov.get("cited") or [])}
    passes = set(int(p) for p in (prov.get("pass_id"),) if p)
    if cid and _has(con, "hq_tasks") and _has(con, "hq_passes"):
        for (t,) in con.execute("SELECT task_id FROM hq_tasks WHERE case_id=?", [cid]).fetchall():
            passes |= {int(r[0]) for r in con.execute("SELECT pass_id FROM hq_passes WHERE trigger=?", [f"task:{t}"]).fetchall()}
    rows: Dict[int, tuple] = {}
    if _has(con, "hq_tool_calls"):
        if passes:
            for r in con.execute(f"SELECT call_no, tool, kind, args_json, status FROM hq_tool_calls WHERE pass_id IN ({','.join(str(p) for p in passes)}) "
                                 "AND status='ran' ORDER BY call_no").fetchall():
                rows[int(r[0])] = r
        if cited:
            for r in con.execute(f"SELECT call_no, tool, kind, args_json, status FROM hq_tool_calls WHERE call_no IN ({','.join(str(c) for c in cited)})").fetchall():
                rows[int(r[0])] = r
    n = 0
    for no, r in sorted(rows.items()):
        tool, tkind, args = r[1], r[2], r[3]
        if no not in cited:
            if tool in NOT_EVIDENCE or not (tkind == "read" or tool in EVIDENCE_ACTION_TOOLS):
                continue
            try:                                                          # a call about another name is not this decision's evidence
                sym = str((json.loads(args or "{}") or {}).get("symbol") or "").upper()
            except Exception:
                sym = ""
            if sym and symbol and sym != str(symbol).upper():
                continue
        if no in cited:
            role, w = "cited", 1.0
        else:
            role, w = "consulted", (0.0 if cited else 0.5)
        n += _ins(con, did, mk, f"tool:{tool}", no, role, w, now, None, kind)
    return n


def _agents(con, now, did, cid, inputs, mk, st) -> int:
    prov = inputs.get("_prov") or {}
    n = 0
    deciding_role, deciding_model, deciding_pass = prov.get("role"), prov.get("model"), prov.get("pass_id")
    if cid and _has(con, "hq_tasks") and _has(con, "hq_passes"):
        seen = {}
        for tid, role in con.execute("SELECT task_id, role FROM hq_tasks WHERE case_id=? ORDER BY task_id", [cid]).fetchall():
            for pid, model, prole in con.execute("SELECT pass_id, model, role FROM hq_passes WHERE trigger=? ORDER BY pass_id", [f"task:{tid}"]).fetchall():
                seen[(role or prole, tid)] = (pid, model)
                if deciding_pass is None and (role or prole) in ("quant", "coordinator"):
                    deciding_role, deciding_model, deciding_pass = (role or prole), model, pid
        for (role, tid), (pid, model) in seen.items():
            if role in (None, "review"):
                continue
            n += _ins(con, did, mk, f"agent:{role}", tid, "deciding" if role == deciding_role else "worked", 1.0 if role == deciding_role else 0.5, now, None, None)
    if deciding_role and not n:
        n += _ins(con, did, mk, f"agent:{deciding_role}", prov.get("task_id") or deciding_pass or 0, "deciding", 1.0, now)
    if deciding_model:
        n += _ins(con, did, mk, f"model:{deciding_model}", deciding_pass or 0, "speaker", 1.0, now)
    # agents/models back the decision: supports = True (credited by the kind of decision)
    con.execute("UPDATE decision_provenance_s79 SET supports=true WHERE decision_id=? AND (source_kind LIKE 'agent:%' OR source_kind LIKE 'model:%') AND supports IS NULL", [did])
    return n


def _forecasts(con, now, did, mk, kind, isin, st) -> int:
    if not _has(con, "forecasts_s79"):
        return 0
    from pflab import markets
    subject = isin
    if not subject:
        try:
            subject = markets.get(mk).index
        except Exception:
            return 0
    day = now.date()
    r = con.execute("SELECT max(as_of) FROM forecasts_s79 WHERE market=? AND source='live' AND subject=? AND as_of<=?", [mk, subject, day]).fetchone()
    if not r or r[0] is None:
        return 0
    as_of = r[0]
    hs = [int(x[0]) for x in con.execute("SELECT DISTINCT horizon_sessions FROM forecasts_s79 WHERE market=? AND source='live' AND subject=? AND as_of=?", [mk, subject, as_of]).fetchall()]
    if not hs:
        return 0
    h = min(hs, key=lambda x: (abs(x - int(st["forecast_horizon_sessions"])), x))
    rows = con.execute("SELECT forecast_id, forecaster, quantiles_json, meta_json FROM forecasts_s79 WHERE market=? AND source='live' AND subject=? AND as_of=? AND horizon_sessions=? "
                       "ORDER BY forecast_id", [mk, subject, as_of, h]).fetchall()
    weights: Dict[str, float] = {}
    for _, name, _, meta in rows:
        if name == "hedge" and meta:
            try:
                weights = {k: float(v) for k, v in (json.loads(meta).get("weights") or {}).items()}
            except Exception:
                pass
    n = 0
    for fid, name, qj, _meta in rows:
        try:
            q50 = float(json.loads(qj).get("0.5"))
        except Exception:
            continue
        d = _sign(q50)
        w = 1.0 if name == "hedge" else weights.get(name, 0.0)
        n += _ins(con, did, mk, f"forecaster:{name}", fid, "in_force", w, now, d, kind, {"q50": round(q50, 5), "horizon_sessions": h, "as_of": str(as_of), "subject": subject})
    return n


def _bear(con, now, did, mk, kind, isin, symbol, st) -> int:
    if not isin:
        return 0
    n = 0
    since = now - timedelta(days=int(st["warning_days"]))
    if _has(con, "bear_warnings_s79"):
        for wid, claim, hz in con.execute("SELECT warning_id, claim, horizon_sessions FROM bear_warnings_s79 WHERE market=? AND isin=? AND made_at<=? AND made_at>=? ORDER BY warning_id",
                                          [mk, isin, now, since]).fetchall():
            n += _ins(con, did, mk, "bear_warning", wid, "warning", 1.0, now, -1, kind, {"claim": str(claim)[:200], "horizon_sessions": hz})
    if _has(con, "debates_s79"):
        for (dbid,) in con.execute("SELECT debate_id FROM debates_s79 WHERE market=? AND symbol=? AND created_at<=? AND created_at>=? ORDER BY debate_id",
                                   [mk, symbol, now, since]).fetchall():
            n += _ins(con, did, mk, "debate", dbid, "debate", 0.0, now)
    return n


def _situation(con, now, did, mk, kind, isin, symbol, st) -> int:
    n = 0
    day = now.date()
    names = [x for x in (symbol, isin) if x]
    if not names:
        return 0
    if _has(con, "situation_report"):
        r = con.execute("SELECT report_id, as_of FROM situation_report WHERE market=? AND as_of<=? AND created_at<=? ORDER BY as_of DESC, report_id DESC LIMIT 1", [mk, day, now]).fetchone()
        if r:
            n += _ins(con, did, mk, "situation_report", r[0], "report", 0.0, now, None, None, {"as_of": str(r[1])})
            if _has(con, "situation_chain"):
                for cidn, ctype, links, ok in con.execute("SELECT chain_id, chain_type, links, ok FROM situation_chain WHERE report_id=? ORDER BY chain_id", [r[0]]).fetchall():
                    txt = f"{links or ''}"
                    if not any(x.lower() in txt.lower() for x in names):
                        continue
                    ct = str(ctype or "chain").lower()
                    k = "transmission" if "transmission" in ct else f"chain:{ct}"
                    d = _chain_direction(links)
                    n += _ins(con, did, mk, k, cidn, "chain", 1.0, now, d, kind, {"chain_type": ctype, "ok": ok})
    if _has(con, "situation_claim"):
        for clid, ckind, val, ents, subj in con.execute(
                "SELECT claim_id, kind, value, entities, subject FROM situation_claim WHERE market=? AND as_of<=? AND created_at<=? AND (expires_on IS NULL OR expires_on>=?) "
                "ORDER BY claim_id DESC LIMIT 200", [mk, day, now, day]).fetchall():
            txt = f"{subj or ''} {ents or ''}".lower()
            if not any(x.lower() in txt for x in names):
                continue
            d = _sign(float(val), 1e-9) if (ckind in DIRECTION_KINDS and val is not None) else 0
            n += _ins(con, did, mk, f"claim:{ckind}", clid, "claim", 1.0 if d else 0.0, now, d, kind, {"subject": subj})
    return n


def _allocation(con, now, did, mk) -> int:
    if not _has(con, "system_allocation_s79"):
        return 0
    r = con.execute("SELECT target_id, status FROM system_allocation_s79 WHERE market=? AND activated_at IS NOT NULL AND activated_at<=? ORDER BY activated_at DESC, target_id DESC LIMIT 1",
                    [mk, now]).fetchone()
    return _ins(con, did, mk, "allocation_target", r[0], "target", 0.0, now, None, None, {"status": r[1]}) if r else 0


def on_review(con, now: datetime, did: int, verdict: str, status: str) -> int:
    """At `execute`: the independent review's verdict joins the sources. It supports the decision when it approved; otherwise it stood against it, and it is
    credited as right when the (scored anyway) decision turns out bad. NEVER raises."""
    try:
        if not on() or not _has(con, "decision_provenance_s79") or verdict not in ("approve", "revise", "reject"):
            return 0
        isin = con.execute("SELECT isin FROM paper_decisions WHERE decision_id=?", [did]).fetchone()
        mk = _market_of(isin[0] if isin else None)
        n = _ins(con, did, mk, "agent:review", verdict, "verdict", 1.0, now, None, None, {"verdict": verdict, "status": status})
        con.execute("UPDATE decision_provenance_s79 SET supports=? WHERE decision_id=? AND source_kind='agent:review'", [verdict == "approve", did])
        return n
    except Exception as e:
        log.warning("provenance: review of decision %s not recorded (%s: %s)", did, type(e).__name__, str(e)[:200])
        return 0


# --- crediting, at score time ------------------------------------------------------------------------------------------------------------

def _gain(kind: str, isin: Optional[str], detail: dict) -> Optional[float]:
    """The decision's gain in percentage points from its scored claim."""
    try:
        if isin == "CASH" or "cash_pct" in detail:
            return float(detail["cash_pct"]) - float(detail["nifty500_pct"])
        adj, sp = detail.get("market_adjusted_pct"), detail.get("stock_pct")
        if kind == "trim":
            return -float(adj) if adj is not None else None
        if kind == "wait":
            return -float(sp) if sp is not None else None
        return float(adj) if adj is not None else None
    except Exception:
        return None


def credit_scored(con, now: datetime) -> dict:
    """Credit every scored (good/bad) claim of a decision with provenance to its sources; idempotent (a source is credited once per decision and horizon).
    Rebuilds the scorecard and writes the credit to the knowledge graph. NEVER raises."""
    out = {"credited": 0, "decisions": 0}
    try:
        if not on() or not _has(con, "source_credit_s79") or not _has(con, "paper_claims"):
            return out
        st = settings()
        done_dec, markets_touched = set(), set()
        claims = con.execute(
            "SELECT c.decision_id, c.horizon_days, c.kind, c.isin, c.outcome, c.outcome_json, c.due_on FROM paper_claims c WHERE c.outcome IN ('good','bad') "
            "AND c.decision_id IN (SELECT DISTINCT decision_id FROM decision_provenance_s79) ORDER BY c.decision_id, c.horizon_days").fetchall()
        for did, hd, ckind, isin, outcome, ojson, due in claims:
            srcs = con.execute("SELECT source_kind, source_id, market, supports, weight FROM decision_provenance_s79 WHERE decision_id=? AND weight>=? AND supports IS NOT NULL "
                               "ORDER BY weight DESC, source_id", [did, float(st["min_weight"])]).fetchall()
            have = {r[0] for r in con.execute("SELECT source_kind FROM source_credit_s79 WHERE decision_id=? AND horizon_days=?", [did, hd]).fetchall()}
            try:
                detail = json.loads(ojson) if ojson else {}
            except ValueError:
                detail = {}
            gain = _gain(ckind, isin, detail)
            seen = set()
            for skind, sid, mk, sup, w in srcs:
                if skind in have or skind in seen:
                    continue
                seen.add(skind)
                hit = (outcome == "good") if sup else (outcome == "bad")
                contrib = None if gain is None else (gain if sup else -gain)
                con.execute("INSERT INTO source_credit_s79 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                            [did, mk, skind, sid, hd, ckind, outcome, bool(sup), bool(hit), gain, contrib, due, now])
                out["credited"] += 1
                done_dec.add(did)
                markets_touched.add(mk)
                if st["kg"]:
                    _kg(con, now, did, hd, skind, hit, outcome, contrib, sup, due)
        out["decisions"] = len(done_dec)
        for mk in markets_touched:
            rebuild_scorecard(con, mk, now)
    except Exception as e:
        log.warning("provenance: crediting failed (%s: %s)", type(e).__name__, str(e)[:200])
    return out


def _kg(con, now, did, hd, skind, hit, outcome, contrib, sup, due) -> None:
    """The credit as a graph edge: source:<kind> -was_right_on / misled_on-> paper_decision:<id>, with the evidence on the edge. Additive; never raises."""
    try:
        if not _has(con, "kg_edges"):
            return
        from pflab.kg import graph
        action, isin, symbol = con.execute("SELECT action, isin, symbol FROM paper_decisions WHERE decision_id=?", [did]).fetchone()
        sn, dn = f"source:{skind}", f"paper_decision:{did}"
        graph.node(con, sn, "source", skind, now=now)
        graph.node(con, dn, "paper_decision", f"{action} {symbol or 'cash'} (decision {did})", {"action": action, "symbol": symbol, "isin": isin}, now=now)
        if isin:
            graph.edge(con, dn, "about", f"company:{isin}", due, "provenance", f"paper_decision:{did}", now=now)
        graph.edge(con, sn, "was_right_on" if hit else "misled_on", dn, due, "provenance", f"paper_decision:{did}:h{hd}",
                   {"horizon_days": hd, "outcome": outcome, "contribution_pct": None if contrib is None else round(contrib, 2), "supported": bool(sup)}, now=now)
    except Exception as e:
        log.debug("provenance: kg write skipped (%s)", e)


def rebuild_scorecard(con, market: str, now: Optional[datetime] = None) -> int:
    """Recompute `source_scorecard_s79` for a market from `source_credit_s79` (per decision kind and for 'all'); idempotent."""
    now = now or datetime.now()
    con.execute("DELETE FROM source_scorecard_s79 WHERE market=?", [market])
    con.execute("INSERT INTO source_scorecard_s79 SELECT market, source_kind, decision_kind, horizon_days, count(*), count(*) FILTER (WHERE hit), avg(contribution), ? "
                "FROM source_credit_s79 WHERE market=? GROUP BY market, source_kind, decision_kind, horizon_days", [now, market])
    con.execute("INSERT INTO source_scorecard_s79 SELECT market, source_kind, 'all', horizon_days, count(*), count(*) FILTER (WHERE hit), avg(contribution), ? "
                "FROM source_credit_s79 WHERE market=? GROUP BY market, source_kind, horizon_days", [now, market])
    return int(con.execute("SELECT count(*) FROM source_scorecard_s79 WHERE market=?", [market]).fetchone()[0])


# --- reading ----------------------------------------------------------------------------------------------------------------------------

def chain(con, did: int) -> dict:
    """The chain of sources behind one decision, with the credit each has earned so far."""
    d = con.execute("SELECT decision_id, action, symbol, status, made_at, ref_date FROM paper_decisions WHERE decision_id=?", [did]).fetchone() if _has(con, "paper_decisions") else None
    if d is None:
        return {"decision_id": did, "found": False, "note": "no such paper decision"}
    rows = con.execute("SELECT source_kind, source_id, role, weight, direction, supports, detail FROM decision_provenance_s79 WHERE decision_id=? ORDER BY weight DESC, source_kind, source_id", [did]).fetchall()
    credit: Dict[str, list] = {}
    for sk, hd, outcome, hit, contrib in con.execute("SELECT source_kind, horizon_days, outcome, hit, contribution FROM source_credit_s79 WHERE decision_id=? ORDER BY horizon_days", [did]).fetchall():
        credit.setdefault(sk, []).append({"horizon_days": hd, "decision_outcome": outcome, "source_was_right": bool(hit), "contribution_pct": None if contrib is None else round(contrib, 2)})
    srcs = []
    for sk, sid, role, w, dr, sup, det in rows:
        s = {"source_kind": sk, "source_id": sid, "role": role, "weight": round(w, 3), "direction": dr, "supports_decision": sup, "credit": credit.get(sk, [])}
        if det:
            try:
                s["detail"] = json.loads(det)
            except ValueError:
                s["detail"] = det
        srcs.append(s)
    return {"decision_id": did, "found": True, "action": d[1], "symbol": d[2], "status": d[3], "made_at": str(d[4])[:16], "n_sources": len(srcs), "sources": srcs}


def scorecard(con, market: str = "IN", horizon_days: Optional[int] = None) -> dict:
    """The source scorecard at a horizon: rows with n, and (from `min_n` credited decisions) hits, the plain and skeptical hit rate and the mean contribution."""
    from pflab.hq import scorecard as sc
    st = settings()
    h = int(horizon_days or st["headline_horizon_days"])
    min_n = int(st["min_n"])
    rows = []
    for sk, dk, n, hits, mean in con.execute("SELECT source_kind, decision_kind, n, hits, mean_outcome FROM source_scorecard_s79 WHERE market=? AND horizon_days=? "
                                             "ORDER BY (decision_kind='all') DESC, n DESC, source_kind, decision_kind", [market, h]).fetchall():
        r = {"source_kind": sk, "decision_kind": dk, "n": int(n)}
        if n >= min_n:
            r.update({"hits": int(hits), "hit_rate": round(hits / n, 3), "skeptical_rate": sc.skeptical(int(hits), int(n - hits)), "mean_outcome_pct": None if mean is None else round(float(mean), 2)})
        else:
            r["note"] = f"only {int(n)} credited decision(s): a count, not a conclusion (under {min_n})"
        rows.append(r)
    return {"market": market, "horizon_days": h, "min_n": min_n, "rows": rows}


_KIND_WORDS = {"trim": "sells", "add": "buys", "hold": "holds", "wait": "waits"}


def _who(sk: str) -> str:
    if sk == "bear_warning":
        return "the bear"
    if sk == "transmission":
        return "transmission"
    if sk.startswith("forecaster:"):
        return f"the {sk[11:]} forecast"
    if sk.startswith("tool:"):
        return f"the {sk[5:]} tool"
    if sk.startswith("agent:"):
        return f"the {sk[6:]}"
    if sk.startswith("model:"):
        return f"model {sk[6:]}"
    if sk.startswith("claim:"):
        return f"{sk[6:]} claims"
    if sk.startswith("chain:"):
        return f"{sk[6:]} chains"
    return sk.replace("_", " ")


def line_for(sk: str, dk: str, n: int, hits: int, min_n: int) -> str:
    """One plain-word line from the numbers (no model). Under `min_n` it states the count only."""
    who = _who(sk)
    when = f" before {_KIND_WORDS[dk]}" if dk in _KIND_WORDS else ""
    if n < min_n:
        return f"{who[0].upper() + who[1:]} stood behind {n} scored decision(s){when}: too few to say if it was right (under {min_n})."
    if sk == "transmission":
        return f"Transmission misled on {n - hits} of {n} decisions{when} and was right on {hits}."
    noun = "warnings" if sk == "bear_warning" else "decisions"
    return f"{who[0].upper() + who[1:]} was right on {hits} of {n} {noun}{when}."


def lines(con, market: str = "IN", horizon_days: Optional[int] = None, limit: Optional[int] = None) -> List[str]:
    """Plain-word lines, strongest evidence first: sources with enough credited decisions, then counts. Generated by code from the scorecard."""
    st = settings()
    h = int(horizon_days or st["headline_horizon_days"])
    min_n = int(st["min_n"])
    rows = con.execute("SELECT source_kind, decision_kind, n, hits FROM source_scorecard_s79 WHERE market=? AND horizon_days=? AND decision_kind <> 'all' "
                       "ORDER BY (n >= ?) DESC, n DESC, source_kind, decision_kind", [market, h, min_n]).fetchall()
    out = [line_for(sk, dk, int(n), int(hits), min_n) for sk, dk, n, hits in rows]
    return out[: int(limit or st["max_lines"])]


def dossier_text(con, market: str = "IN") -> str:
    """The block of the weekly review dossier: which sources were right. Empty when nothing has been credited. NEVER raises."""
    try:
        if not on() or not _has(con, "source_scorecard_s79"):
            return ""
        ls = lines(con, market)
        if not ls:
            return ""
        return ("WHICH SOURCES WERE RIGHT (by code, from this book's scored decisions at " + str(settings()["headline_horizon_days"]) + " days; a count under "
                + str(settings()["min_n"]) + " is not a conclusion): " + " ".join(ls))
    except Exception:
        return ""
