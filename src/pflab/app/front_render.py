"""Exact renderings of what the tools returned (S71): the numbers of a local reply come from here, not from a language model.

The first real run of the chat front showed why. The local model worded a portfolio answer fluently and every number in it was in the data, so the number guard
passed it, yet it said a holding was "4.62% of your equity" when 4.62% is its share of the whole portfolio: the guard proves a number EXISTS, not that it sits next to
the right label. So the facts are rendered by code, label and value together, and the model only adds a short plain-words paragraph afterwards that must itself pass the
guard; if it does not, the exact facts stand alone. Every function takes the parsed tool result and returns text, and tolerates a missing key (it says less, never a wrong thing).
"""
from __future__ import annotations

from typing import Dict, List, Optional


def inr(x) -> str:
    """Rupees with Indian digit grouping: 172760.8 -> 'Rs 1,72,761'; negatives as '-Rs 2,64,000'."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    sign = "-" if v < 0 else ""
    n = f"{abs(round(v)):d}"
    if len(n) > 3:
        head, tail = n[:-3], n[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        n = ",".join(parts) + "," + tail
    return f"{sign}Rs {n}"


def _pct(x, digits: int = 1) -> str:
    try:
        return f"{float(x):.{digits}f}%"
    except (TypeError, ValueError):
        return str(x)


def status(work: Optional[dict], system: Optional[dict]) -> str:
    lines: List[str] = []
    inv = (work or {}).get("investigations") or []
    if not inv:
        lines.append("Nothing is being investigated right now.")
    for i in inv[:5]:
        doing = i.get("current_action") or ("finished" if i.get("state") == "done" else "")
        lines.append(f"Investigation #{i.get('case_id')} ({i.get('state')}): {str(i.get('goal', ''))[:110]}" + (f". {doing}" if doing else "")
                     + (f". Stuck: {i['blocker']}" if i.get("blocker") else ""))
    need = (work or {}).get("needs_from_him") or []
    if need:
        lines.append("Waiting for you: " + "; ".join(str(n.get("text", n) if isinstance(n, dict) else n)[:120] for n in need[:4]))
    if system:
        bad = [c for c in (system.get("connectors") or []) if c.get("state") not in ("ok", None)]
        lines.append("System: " + str(system.get("verdict", ""))[:160])
        for c in bad[:5]:
            lines.append(f"  {c.get('name')}: {str(c.get('line', ''))[:120]}")
    return "\n".join(lines)


def portfolio(p: Optional[dict]) -> str:
    if not p:
        return ""
    lines = [f"Net worth {p.get('net_worth')} (record as of {p.get('asof')}, statements to {p.get('statements_to')})."]
    b = p.get("buckets") or []
    if b:
        lines.append("Split: " + ", ".join(f"{x.get('bucket')} {x.get('value')} ({_pct(x.get('weight_pct'))} of the portfolio)" for x in b))
    h = p.get("holdings") or []
    if h:
        lines.append("Largest holdings (share of the whole portfolio, gain on cost):")
        for x in h[:6]:
            lines.append(f"  {x.get('symbol')}: {x.get('value')}, {_pct(x.get('weight_pct'), 2)} of the portfolio, {_pct(x.get('gain_pct'))} gain")
    d = p.get("direct_stocks")
    if d:
        lines.append(f"Direct stocks together: {d.get('names')} names, worth {d.get('value')} on a cost of {d.get('cost')} ({d.get('unrealised_gain')}, {_pct(d.get('gain_pct'))}).")
    if p.get("kite_vs_statements"):
        lines.append("Kite and the statements differ on: " + "; ".join(str(x)[:80] for x in p["kite_vs_statements"][:3]))
    if p.get("fall_limit"):
        lines.append(str(p["fall_limit"])[:160])
    return "\n".join(lines)


def fall(r: Optional[dict]) -> str:
    t = (r or {}).get("table") or []
    if not t:
        return ""
    lines = [f"Your portfolio today is {inr(r.get('total_rupees'))}, of which {inr(r.get('equity_rupees'))} is in shares and {inr(r.get('cash_and_debt_rupees'))} in cash and debt."]
    for row in t:
        lines.append(f"  If the index falls {row.get('index_fall_pct'):g}%: you lose about {inr(abs(float(row.get('loss_rupees', 0))))}, which is {_pct(abs(float(row.get('loss_pct_of_total', 0))))} of the portfolio.")
    lines.append(str((r.get("assumptions") or {}).get("note", "The falls are stated assumptions, not forecasts."))[:200])
    return "\n".join(lines)


def deploy(r: Optional[dict]) -> str:
    if not r or not r.get("table"):
        return ""
    a = r.get("assumptions") or {}
    lines = [f"Putting {inr(a.get('amount_rupees'))} to work, four ways, over made-up price paths (a {a.get('fall_pct'):g}% sharp fall, a {a.get('decline_pct'):g}% decline, a fall and recovery, no crash):"]
    for k, v in (r.get("policies") or {}).items():
        lines.append(f"  {k}: {str(v)[:110]}")
    by_path: Dict[str, list] = {}
    for row in r["table"]:
        by_path.setdefault(row.get("path"), []).append(row)
    for path, rows in by_path.items():
        lines.append(f"  {path}: " + "; ".join(f"{x.get('policy')} {_pct(x.get('return_pct'))} (worst {_pct(x.get('worst_value_vs_amount_pct'))})" for x in rows))
    best = r.get("best_terminal_by_path") or {}
    if best:
        lines.append("  Best at the end, by path: " + ", ".join(f"{k} -> {v}" for k, v in best.items()))
    lines.append(str(r.get("note", "A hypothetical scenario study, not a forecast."))[:200])
    return "\n".join(lines)
