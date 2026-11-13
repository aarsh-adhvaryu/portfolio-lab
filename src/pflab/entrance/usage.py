"""Usage logging (S85 E8): what the model calls cost, by purpose, model and chat. Every API call is a row in `api_calls` (model, tokens in and out, rupees, purpose, the chat and the reply it served);
this module only READS them, for Today and the morning report. Plain functions returning JSON-able dicts; `/api/usage` serves the same.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

COUNTED = ("done", "sending", "queued", "submitted", "refused")
PURPOSE_OF_AGENT = {"w_assistant": "chat", "chat": "chat", "assistant": "chat", "think": "cases", "desk": "desk", "strategist": "strategist", "checker": "checker", "reader": "reading",
                    "reading": "reading", "gatekeeper": "reading", "wording": "chat", "router": "chat", "worker": "lab", "fetch": "reading", "brain": "strategist", "escalation": "chat"}
_PURPOSE_SQL = "coalesce(nullif(purpose, ''), agent, 'other')"
_STATUS = "status IN (" + ",".join(f"'{s}'" for s in COUNTED) + ")"


def _bounds(day: date):
    d0 = datetime(day.year, day.month, day.day)
    return d0, d0 + timedelta(days=1)


def _purpose(raw: str) -> str:
    return PURPOSE_OF_AGENT.get(raw, raw)


def today(con, day: date) -> dict:
    """{"day", "calls", "cost_inr", "tokens_in", "tokens_out", "cached_tokens", "by_model": [{"model","calls","cost_inr"}]} for the calendar day."""
    d0, d1 = _bounds(day)
    r = con.execute(f"SELECT count(*), coalesce(sum(cost_inr),0), coalesce(sum(input_tokens),0), coalesce(sum(output_tokens),0), coalesce(sum(cached_tokens),0) FROM api_calls "
                    f"WHERE created_at >= ? AND created_at < ? AND {_STATUS}", [d0, d1]).fetchone()
    models = con.execute(f"SELECT model, count(*), coalesce(sum(cost_inr),0) FROM api_calls WHERE created_at >= ? AND created_at < ? AND {_STATUS} GROUP BY model ORDER BY 3 DESC", [d0, d1]).fetchall()
    return {"day": str(day), "calls": int(r[0]), "cost_inr": float(r[1]), "tokens_in": int(r[2]), "tokens_out": int(r[3]), "cached_tokens": int(r[4]),
            "by_model": [{"model": m, "calls": int(n), "cost_inr": float(c)} for m, n, c in models]}


def by_purpose(con, day: date) -> List[dict]:
    """One row per purpose (chat, strategist, checker, cases, desk, reading, lab...): [{"purpose","calls","cost_inr","tokens_in","tokens_out"}], dearest first."""
    d0, d1 = _bounds(day)
    rows = con.execute(f"SELECT {_PURPOSE_SQL}, count(*), coalesce(sum(cost_inr),0), coalesce(sum(input_tokens),0), coalesce(sum(output_tokens),0) FROM api_calls "
                       f"WHERE created_at >= ? AND created_at < ? AND {_STATUS} GROUP BY 1", [d0, d1]).fetchall()
    merged: Dict[str, dict] = {}
    for p, n, c, ti, to in rows:
        k = _purpose(str(p))
        m = merged.setdefault(k, {"purpose": k, "calls": 0, "cost_inr": 0.0, "tokens_in": 0, "tokens_out": 0})
        m["calls"] += int(n)
        m["cost_inr"] += float(c)
        m["tokens_in"] += int(ti)
        m["tokens_out"] += int(to)
    return sorted(merged.values(), key=lambda m: -m["cost_inr"])


def by_chat(con, chat_id: int) -> List[dict]:
    """The calls that served one chat: [{"call_id","at","model","thinking","cost_inr","tokens_in","tokens_out","reply_msg_id","purpose"}]."""
    rows = con.execute("SELECT call_id, created_at, model, thinking, cost_inr, input_tokens, output_tokens, reply_msg_id, purpose FROM api_calls WHERE chat_id=? ORDER BY call_id", [chat_id]).fetchall()
    return [{"call_id": r[0], "at": str(r[1])[:19], "model": r[2], "thinking": r[3], "cost_inr": float(r[4] or 0), "tokens_in": r[5], "tokens_out": r[6], "reply_msg_id": r[7], "purpose": r[8]} for r in rows]


def by_reply(con, msg_id: int) -> dict:
    """What one reply cost: {"calls", "cost_inr", "models": [...]}."""
    rows = con.execute("SELECT model, coalesce(cost_inr,0) FROM api_calls WHERE reply_msg_id=?", [msg_id]).fetchall()
    return {"calls": len(rows), "cost_inr": float(sum(r[1] for r in rows)), "models": sorted({r[0] for r in rows})}


def month_to_date(con, day: date) -> float:
    d0 = datetime(day.year, day.month, 1)
    return float(con.execute(f"SELECT coalesce(sum(cost_inr),0) FROM api_calls WHERE created_at >= ? AND {_STATUS}", [d0]).fetchone()[0])


def line(con, day: date) -> str:
    """A text block for Today and the morning report: what the AI cost today, by purpose, and the month so far."""
    t = today(con, day)
    if not t["calls"]:
        return f"AI use today: no calls. This month so far Rs {month_to_date(con, day):,.0f}."
    parts = [f"{p['purpose']} Rs {p['cost_inr']:,.2f} ({p['calls']})" for p in by_purpose(con, day)[:6]]
    return (f"AI use today: Rs {t['cost_inr']:,.2f} in {t['calls']} call{'s' if t['calls'] != 1 else ''} ({'; '.join(parts)}). This month so far Rs {month_to_date(con, day):,.0f}.")


def view(con, day: date) -> dict:
    """Everything the usage screens need in one JSON-able dict (the `/api/usage` route)."""
    return {"today": today(con, day), "by_purpose": by_purpose(con, day), "text": line(con, day), "month_inr": month_to_date(con, day)}
