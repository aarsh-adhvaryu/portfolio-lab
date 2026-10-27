"""The rule tests registered and read back (S64; docs/research/s64_rules_protocol.md).

`register_all` turns each rule of thumb the system shows into a pre-registered claim for the learner (origin `study`) and links
the starter scans to their claim. The learner's cycle then tests them like any claim (templates.rule_filter), and everything
that shows a rule asks `status` for its label: not tested, passed or failed, with the claim's own words. A passed rule is wired
live (claims.wire) and `today` says which of his names meet it; a failed one has no live feature.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from pflab.learner import claims
from pflab.learner import templates as tp

PROTOCOL = "docs/research/s64_rules_protocol.md"
# (rule, direction, the claim in words that name what the test measures, the protocol's description of the test)
RULE_CLAIMS = [
    ("pe_above_50", "under", "Stocks priced above 50 times their trailing earnings earn less over the next month than the other "
     "Nifty 500 stocks.", "Month-end Nifty 500 members with a P/E above 50 against all members, one month ahead."),
    ("pe_below_15", "out", "Cheap stocks, priced below 15 times their trailing earnings, earn more over the next month than the "
     "other Nifty 500 stocks.", "Members with a P/E between 0 and 15 against all members, one month ahead."),
    ("near_52w_low_5", "out", "Stocks within 5% of their 52-week low earn more over the next month than the other Nifty 500 "
     "stocks.", "Members within 5% above their 250-session low against all members, one month ahead."),
    ("below_sma200", "under", "Stocks trading below their 200-day average earn less over the next month than the other Nifty 500 "
     "stocks.", "Members below their 200-session average against all members, one month ahead."),
    ("volume_spike_2", "out", "Stocks with a volume spike, traded value over twice the 20-day average, earn more over the next "
     "month than the other Nifty 500 stocks.", "Members whose month-end traded value is over twice the prior 20 sessions' average."),
    ("ath_fall_40", "out", "Stocks 40% or more below their all-time high rebound: they earn more over the next month than the "
     "other Nifty 500 stocks.", "Members at least 40% below their highest close since 2008-06, against all members."),
    ("rsi_below_30", "out", "Oversold stocks, with an RSI below 30, bounce: they earn more over the next month than the other "
     "Nifty 500 stocks.", "Members with Wilder RSI(14) below 30 against all members, one month ahead."),
]
SCAN_OF_RULE = {r: c for r, c in tp.RULE_SCAN.items()}


def register_all(con, proto_dir: Path, now: datetime) -> Dict[str, str]:
    """Register the seven claims (once: an existing one is reused) and link the starter scans. Returns rule -> claim #id: state."""
    out = {}
    for rule, direction, claim, quote in RULE_CLAIMS:
        cid = claims.register_study(con, "rule_filter", {"rule": rule, "direction": direction, "months": 1}, claim, quote,
                                    f"S64 pre-registered study: rule {rule}", PROTOCOL, now)
        status = con.execute("SELECT status FROM learn_claims WHERE claim_id=?", [cid]).fetchone()[0]
        out[rule] = f"claim #{cid}: " + (claims.register(con, cid, proto_dir, now) if status == "proposed" else status)
    link_scans(con)
    return out


def claim_of(con, rule: str) -> Optional[dict]:
    r = con.execute("SELECT claim_id, claim, status, decision, why, params_json FROM learn_claims WHERE template='rule_filter' "
                    "AND model='study' AND json_extract_string(params_json, '$.rule') = ? ORDER BY claim_id LIMIT 1", [rule]).fetchone()
    if not r:
        return None
    return {"claim_id": r[0], "claim": r[1], "status": r[2], "decision": r[3], "why": r[4], "params": json.loads(r[5])}


def status(con, rule: str) -> dict:
    """{'label': 'not tested' | 'passed' | 'failed' | 'registered, test pending', 'claim_id', 'why'} for a rule."""
    c = claim_of(con, rule)
    if c is None:
        return {"label": "not tested", "claim_id": None, "why": None}
    same = con.execute("SELECT decision, why FROM learn_claims WHERE claim_id = (SELECT same_as FROM learn_claims WHERE claim_id=?)",
                       [c["claim_id"]]).fetchone() if c["status"] == "same" else None
    d, why = (same if same else (c["decision"], c["why"]))
    label = {"pass": "passed", "fail": "failed"}.get(d)
    if label is None:
        label = "registered, test pending" if c["status"] in ("registered", "proposed", "same") else "not tested"
    return {"label": label, "claim_id": c["claim_id"], "why": (why or "")[:300], "direction": c["params"]["direction"]}


def link_scans(con) -> int:
    """A scan whose only condition is a rule's (the starters, or one made later) carries that rule's claim."""
    n = 0
    for sid, cj in con.execute("SELECT scan_id, conditions_json FROM scans WHERE claim_id IS NULL").fetchall():
        conds = json.loads(cj)
        if len(conds) != 1:
            continue
        text = conds[0]["name"] + (f":{conds[0]['value']}" if conds[0]["value"] else "")
        for rule, scan_text in SCAN_OF_RULE.items():
            if text == scan_text:
                c = claim_of(con, rule)
                if c:
                    con.execute("UPDATE scans SET claim_id=? WHERE scan_id=?", [c["claim_id"], sid])
                    n += 1
    return n


def today(con, root, rule: str, asof: date) -> Dict[str, str]:
    """Which of his names meet a rule right now (price rules by the scan engine, P/E rules by the valuation facts)."""
    from pflab.quant import scan
    if rule in SCAN_OF_RULE:
        r = scan.evaluate(con, root, scan.parse(SCAN_OF_RULE[rule]), "list", asof)
        return {h["symbol"]: "; ".join(h["why"]) for h in r["hits"]}
    from pflab.app import research
    from pflab.hq import valuation
    out = {}
    for isin, sym in scan.universe_isins(con, root, "list", asof).items():
        try:
            pe = valuation.facts(con, root, isin, sym, research.closes(con, root, isin, asof, years=6), asof).get("pe_ttm")
        except Exception:
            continue
        if pe and ((rule == "pe_above_50" and pe > 50) or (rule == "pe_below_15" and 0 < pe < 15)):
            out[sym] = f"P/E {pe:.1f}"
    return out
