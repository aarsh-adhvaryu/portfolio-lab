"""The "while you were away" digest (S79 item 3): ONE local, free message written by code from stored facts. No model, no cloud money: stale days are not
re-explained, they are summarised once. Every figure is read from the store (`facts_json` keeps them), so nothing in the text is model-made.

    build(con, off_from, off_to, now) -> {"text", "facts"}       compose
    maybe_send(con, now)                                           once per gap: store in away_digest_s79 and queue it on Telegram (kind "summary")
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import List, Optional

from pflab import markets
from pflab.service import presence

MIN_GAP = timedelta(hours=3)


def sessions_missed(market: str, off_from: datetime, off_to: datetime) -> List[date]:
    """Sessions whose close fell inside the gap (the session in progress when the app went off counts when its close passed while it was off)."""
    m = markets.get(market)
    out = []
    d = off_from.date() - timedelta(days=1)
    while d <= off_to.date():
        w = m.window_ist(d)
        if w is not None and off_from < w[1] <= off_to:
            out.append(d)
        d += timedelta(days=1)
    return out


def _movers(con, off_from: datetime, k: int = 3) -> list:
    """The system's holdings that moved most since the close before the gap (point-in-time: closes on or before each date)."""
    try:
        from pflab.paper import book
        day = (con.execute("SELECT max(day) FROM paper_days").fetchone() or [None])[0]
        if day is None:
            return []
        h = book.holdings(con, day)
        out = []
        for r in h["rows"]:
            p0 = con.execute("SELECT close FROM prices WHERE isin=? AND date <= ? ORDER BY date DESC LIMIT 1", [r["isin"], off_from.date()]).fetchone()
            if p0 and p0[0] and r.get("price"):
                out.append((r["symbol"], float(r["price"]) / float(p0[0]) - 1.0, float(r.get("weight") or 0.0)))
        out.sort(key=lambda x: -abs(x[1]))
        return [{"symbol": s, "change_pct": round(100 * c, 1), "weight_pct": round(100 * w, 1)} for s, c, w in out[:k]]
    except Exception:
        return []


def _value_change(con, off_from: datetime) -> Optional[dict]:
    try:
        a = con.execute("SELECT value, flows FROM paper_days WHERE day <= ? ORDER BY day DESC LIMIT 1", [off_from.date()]).fetchone()
        b = con.execute("SELECT day, value FROM paper_days ORDER BY day DESC LIMIT 1").fetchone()
        flows = con.execute("SELECT coalesce(sum(flows), 0) FROM paper_days WHERE day > ?", [off_from.date()]).fetchone()[0]
        if a and b and a[0]:
            return {"as_of": str(b[0]), "from": round(float(a[0])), "to": round(float(b[1])), "change_pct": round(100 * ((float(b[1]) - float(flows)) / float(a[0]) - 1), 2)}
    except Exception:
        pass
    return None


def build(con, off_from: datetime, off_to: datetime, now: datetime) -> dict:
    facts: dict = {"gap": presence.describe(off_from, off_to)}
    missed = {c: [str(d) for d in sessions_missed(c, off_from, off_to)] for c in markets.codes()}
    facts["sessions_missed"] = missed
    try:
        facts["filings_since"] = int(con.execute("SELECT count(*) FROM kg_docs WHERE kind='filing' AND ingested_at >= ?", [off_from]).fetchone()[0])
    except Exception:
        facts["filings_since"] = None
    facts["book"] = _value_change(con, off_from)
    facts["movers"] = _movers(con, off_from)
    try:
        facts["forecasts_scored"] = int(con.execute("SELECT count(*) FROM forecast_scores_s79 WHERE scored_at >= ?", [off_from]).fetchone()[0])
    except Exception:
        facts["forecasts_scored"] = None
    lines = [f"While you were away: {facts['gap']}."]
    for c, ds in missed.items():
        if ds:
            lines.append(f"{markets.get(c).name}: {len(ds)} session(s) closed while it was off ({', '.join(ds[-3:])}{' ...' if len(ds) > 3 else ''}); caught up in order.")
    b = facts["book"]
    if b:
        lines.append(f"The system's own book moved {b['change_pct']:+.2f}% (as of {b['as_of']}), money in and out taken out.")
    if facts["movers"]:
        lines.append("Biggest moves among what it holds: " + "; ".join(f"{m['symbol']} {m['change_pct']:+.1f}% ({m['weight_pct']:.0f}% of the book)" for m in facts["movers"]) + ".")
    if facts["filings_since"]:
        lines.append(f"{facts['filings_since']} new filing(s) were read.")
    if facts["forecasts_scored"]:
        lines.append(f"{facts['forecasts_scored']} forecast(s) were scored against what happened.")
    lines.append("The explanations of the biggest moves and fresh forecasts follow as their data arrives.")
    return {"text": "\n".join(lines), "facts": facts}


def maybe_send(con, now: datetime) -> Optional[int]:
    """Once per gap longer than MIN_GAP, after the catch-up has settled (the caller decides when). Returns the digest id, or None."""
    gaps = [g for g in presence.gaps(con) if g[1] - g[0] >= MIN_GAP]
    if not gaps:
        return None
    off_from, off_to = gaps[-1]
    if con.execute("SELECT 1 FROM away_digest_s79 WHERE off_from=? AND off_to=?", [off_from, off_to]).fetchone():
        return None
    from pflab.pm.store import next_id
    from pflab.service import telegram as tgm
    d = build(con, off_from, off_to, now)
    did = next_id(con, "away_digest_s79", "digest_id")
    con.execute("INSERT INTO away_digest_s79 VALUES (?,?,?,?,?,?,?)", [did, now, off_from, off_to, d["text"], json.dumps(d["facts"], default=str), False])
    tgm.enqueue(con, d["text"], "summary", dedup_key=f"away:{off_from:%Y%m%d%H%M}", now=now)
    return did


def latest(con) -> Optional[dict]:
    r = con.execute("SELECT digest_id, created_at, text, seen FROM away_digest_s79 ORDER BY digest_id DESC LIMIT 1").fetchone()
    return None if r is None else {"id": r[0], "at": str(r[1])[:16], "text": r[2], "seen": bool(r[3])}
