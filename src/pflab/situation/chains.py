"""Causal chains (S79b item 16): WHY is a list of links cause -> effect, each link citing claims, and a cause must be dated BEFORE its effect.

The rule is in code, not in the prompt: `validate_link` refuses a link whose cause is dated on or after its effect (a same-day pair is a co-movement, not a cause),
or whose cause or effect is unknown, or whose cause has no evidence (no tool-call id). A chain with a refused link is stored as not ok with the reason and is never
shown as an explanation. Chains go to the knowledge graph with their evidence; each chain TYPE (cause kind > effect kind) accumulates a hit rate from the predictions
made while it was in the report (`score.py`), shown only from 20 outcomes.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from pflab.pm.store import next_id

MIN_OUTCOMES = 20


def _date(x) -> Optional[date]:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    try:
        return date.fromisoformat(str(x)[:10])
    except (TypeError, ValueError):
        return None


def chain_type(cause: dict, effect: dict) -> str:
    return f"{cause['kind']}>{effect['kind']}"


def validate_link(cause: Optional[dict], effect: Optional[dict]) -> Tuple[bool, str]:
    """(ok, reason). The cause's evidence must be dated strictly before the effect's, and the cause must rest on a tool call (or be a stated state claim)."""
    if not cause or not effect:
        return False, "a link names a claim that is not in the situation"
    if cause["claim_id"] == effect["claim_id"]:
        return False, "a claim cannot cause itself"
    cd, ed = _date(cause["as_of"]), _date(effect["as_of"])
    if cd is None or ed is None:
        return False, "a claim has no date"
    state_effect = effect["kind"] in STATE_KINDS or effect["subject"].startswith(STATE_SUBJECTS)
    if cd > ed or (cd == ed and not state_effect):
        return False, (f"the cause ({cause['kind']} {cause['subject']}, dated {cd}) is not dated before its effect ({effect['kind']} {effect['subject']}, dated {ed}): "
                       f"{'a same-day pair is a co-movement, not a cause' if cd == ed else 'a later event cannot explain an earlier one'}")
    if not cause.get("call_ids") and (cause.get("source") or "") not in DATA_SOURCES:
        return False, "the cause rests on no tool call"
    return True, ""


# Only these cause -> effect types may appear as an explanation (WHY). A link between claims of any other kind is not a causal link, whatever the model says (the first real report linked
# "US VIX contribution" to "the unexplained part of the index move"). A state effect (the book's exposure, a standing relative position) has no event time, so a cause dated the same day is
# allowed there; every event effect needs a cause dated strictly before it. The flows type uses the PREVIOUS session's foreign buying: the same session's flows are a NOW fact (a part of
# the day's move), not a cause of it.
STATE_KINDS = ("exposure", "book", "allocation")
STATE_SUBJECTS = ("relative_",)
DATA_SOURCES = ("week", "levels", "book")                 # claims read from the collected files by code, no tool call: valid evidence for a cause
CRUDE = ("week_BRENT_FUT",)


def _is(c: dict, kind: str, *subjects: str, prefix: bool = False) -> bool:
    return c["kind"] == kind and (not subjects or (c["subject"].startswith(subjects) if prefix else c["subject"] in subjects))


WHITELIST = (
    ("us_close>nse_gap", lambda c, e: _is(c, "macro", "leg_", prefix=True) and _is(e, "transmission", "open_gap"),
     "a leg of the one-factor gap regression (quant/transmission.py)"),
    ("foreign_flows>index_move", lambda c, e: _is(c, "macro", "flow_prev") and _is(e, "macro", "macro_attribution"),
     "the previous session's foreign buying as a candidate driver of the day's move; an association, not a proof"),
    ("crude>oil_theme_exposure", lambda c, e: _is(c, "macro", *CRUDE) and e["kind"] == "exposure" and "primary_proxy crude" in e["text"],
     "crude is this theme's primary proxy, so its move reaches the book through the holdings that carry the theme"),
    ("asia>relative_performance", lambda c, e: _is(c, "macro", "week_ASIA") and _is(e, "move", "relative_vs_asia_week"),
     "the Asian peers' week against India's week; an association, not a proof"),
)
ALLOWED = ", ".join(t for t, _, _ in WHITELIST)


def whitelisted(cause: dict, effect: dict) -> Optional[str]:
    """The whitelisted type name of a cause -> effect pair, or None."""
    for name, test, _ in WHITELIST:
        if test(cause, effect):
            return name
    return None


def make_chain(links: List[dict], by_id: Dict[int, dict], strict_types: bool = False) -> dict:
    """links: [{cause, effect, mechanism}] with claim ids. Returns {links: [...checked], ok, types, reason}. With strict_types the pair must also be a whitelisted type."""
    out, ok, reasons, types = [], True, [], []
    for lk in links:
        try:
            c, e = by_id.get(int(lk["cause"])), by_id.get(int(lk["effect"]))
        except (KeyError, TypeError, ValueError):
            c = e = None
        good, why = validate_link(c, e)
        wl = whitelisted(c, e) if (good and strict_types) else None
        if good and strict_types and wl is None:
            good, why = False, f"{c['kind']} {c['subject']} -> {e['kind']} {e['subject']} is not a causal link the system accepts (allowed types: {ALLOWED})"
        row = {"cause": lk.get("cause"), "effect": lk.get("effect"), "mechanism": str(lk.get("mechanism") or "")[:240], "ok": good, "reason": why}
        if good:
            row.update(cause_date=str(_date(c["as_of"])), effect_date=str(_date(e["as_of"])), type=wl or chain_type(c, e), cause_calls=list(c.get("call_ids") or []),
                       effect_calls=list(e.get("call_ids") or []))
            types.append(row["type"])
        else:
            ok = False
            reasons.append(why)
        out.append(row)
    return {"links": out, "ok": ok and bool(out), "types": sorted(set(types)), "reason": "; ".join(reasons)[:400]}


def code_links(by_id: Dict[int, dict]) -> List[dict]:
    """Links the code can state without a model: a macro leg of the other side's session (dated then) -> the opening gap it implies (dated the target session), and a sector
    leg's driver -> the sector gap. These are the transmission study's own relations (quant/transmission.py), not new claims."""
    gaps = [c for c in by_id.values() if c["kind"] == "transmission" and c["subject"] == "open_gap" and c.get("value") is not None]
    legs = [c for c in by_id.values() if c["kind"] == "macro" and c["subject"].startswith("leg_")]
    links = []
    for g in gaps:
        for lg in sorted(legs, key=lambda c: -abs(c.get("value") or 0.0))[:3]:
            links.append({"cause": lg["claim_id"], "effect": g["claim_id"], "mechanism": f"{lg['subject'][4:]} is a leg of the one-factor gap regression (quant/transmission.py)"})
    # the other whitelisted types, every pair that exists among the claims (the check in make_chain decides)
    for e in by_id.values():
        for c in by_id.values():
            name = whitelisted(c, e) if c is not e else None
            if name and name != "us_close>nse_gap":
                links.append({"cause": c["claim_id"], "effect": e["claim_id"], "mechanism": next(m for n, _, m in WHITELIST if n == name)})
    return links


# --- persistence and the knowledge graph ------------------------------------------------------------------------------------------------------

def store(con, report_id: Optional[int], market: str, as_of: date, chain: dict, now: datetime) -> int:
    cid = next_id(con, "situation_chain", "chain_id")
    ctype = ",".join(chain.get("types") or []) or "none"
    con.execute("INSERT INTO situation_chain VALUES (?,?,?,?,?,?,?,?,?)", [cid, report_id, market, as_of, ctype, json.dumps(chain["links"], default=str), bool(chain["ok"]), chain.get("reason") or "", now])
    return cid


def to_kg(con, chain_id: int, chain: dict, by_id: Dict[int, dict], market: str, now: datetime) -> int:
    """Write the OK links of a chain to the knowledge graph: a node per claim, an edge cause -[leads_to]-> effect valid from the effect's date, evidence in its attributes."""
    from pflab.kg import graph
    n = 0
    for lk in chain["links"]:
        if not lk["ok"]:
            continue
        c, e = by_id[int(lk["cause"])], by_id[int(lk["effect"])]
        cn, en = f"sit:{market}:{c['kind']}:{c['subject']}", f"sit:{market}:{e['kind']}:{e['subject']}"
        graph.node(con, cn, "situation", f"{c['kind']} {c['subject']}", {"text": c["text"][:200]}, now=now)
        graph.node(con, en, "situation", f"{e['kind']} {e['subject']}", {"text": e["text"][:200]}, now=now)
        if graph.edge(con, cn, "leads_to", en, _date(e["as_of"]), "situation", f"chain:{chain_id}",
                      {"mechanism": lk["mechanism"], "cause_date": lk["cause_date"], "effect_date": lk["effect_date"], "type": lk["type"], "calls": lk["cause_calls"] + lk["effect_calls"]},
                      now=now):
            n += 1
        graph.node(con, f"chaintype:{lk['type']}", "chaintype", lk["type"], None, now=now)
    return n


def type_stats(con, market: Optional[str] = None) -> Dict[str, dict]:
    """Hit rate per chain type from the scored predictions made while the type was in the report: {type: {n, hits, hit_rate (None under 20 outcomes)}}.
    A hit is a scored prediction whose probability was on the right side of one half."""
    q = ("SELECT p.chain_type, o.outcome, p.horizons, o.horizon FROM situation_prediction p JOIN situation_outcome o ON o.pred_id = p.pred_id "
         "WHERE o.outcome IS NOT NULL AND p.chain_type IS NOT NULL AND p.chain_type <> 'none'" + (" AND p.market=?" if market else ""))
    rows = con.execute(q, [market] if market else []).fetchall()
    acc: Dict[str, List[int]] = {}
    for ct, outcome, hz, h in rows:
        try:
            p = float(json.loads(hz)[str(h)])
        except (ValueError, KeyError, TypeError):
            continue
        hit = int((p >= 0.5) == bool(outcome))
        for t in str(ct).split(","):
            acc.setdefault(t, []).append(hit)
    return {t: {"n": len(v), "hits": sum(v), "hit_rate": round(sum(v) / len(v), 3) if len(v) >= MIN_OUTCOMES else None} for t, v in acc.items()}


def update_kg_stats(con, market: Optional[str], now: datetime) -> int:
    """Write each chain type's n and hit rate onto its graph node (code only)."""
    from pflab.kg import graph
    st = type_stats(con, market)
    for t, s in st.items():
        graph.node(con, f"chaintype:{t}", "chaintype", t, s, now=now)
    return len(st)
