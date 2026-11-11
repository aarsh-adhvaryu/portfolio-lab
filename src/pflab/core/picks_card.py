"""The PICKS section of the book card and of the strategist's first message (S83 L3). Plain text and a JSON-able dict, both from code; nothing here calls a model and nothing writes.

    build(con, day)  -> {"IN": market, "US": market, "learned": {...} | None, "text": str}
    market           {"market", "on", "share", "share_why", "room", "no_new_picks", "picks": [{pick_id, symbol, source, state, thesis (one line), break_condition, days_held, weight,
                      vs_index: {horizon_months, return_pct, index_return_pct, excess_pct} | None}], "needs_learned"}

The share and its reason come from `pick_share.status`, the picks from `picks.status`, each pick's result against the index from the scorecard table `pick_scores_s83` (its longest scored horizon;
"not scored yet" before the first month). `learned` is the newest strategist note's `learned` part.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

NAMES = {"IN": "India", "US": "US"}
LIVE = ("proposed", "buying", "held", "withdrawn")        # the states that still hold or wait to hold shares (the sizing's `managed`)


def _one_line(s: Optional[str], n: int = 140) -> str:
    t = " ".join(str(s or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _vs_index(con, market: str) -> dict:
    """{pick_id: longest scored horizon against the index} from `pick_scores_s83` (empty when the table is absent or nothing is scored)."""
    try:
        rows = con.execute("SELECT ref_id, horizon_months, return_pct, index_return_pct, excess_pct FROM pick_scores_s83 WHERE market=? AND kind='pick' ORDER BY ref_id, horizon_months", [market]).fetchall()
    except Exception:
        return {}
    out = {}
    for ref, h, ret, idx, ex in rows:
        out[int(ref)] = {"horizon_months": int(h), "return_pct": ret, "index_return_pct": idx, "excess_pct": ex}
    return out


def market_block(con, market: str, day: date) -> dict:
    from pflab.core import picks
    st = picks.status(con, market, day)
    sh = st["share"]
    scored = _vs_index(con, market)
    plist, occupied = [], 0.0
    for p in st["picks"]:
        if p["state"] not in LIVE:
            continue
        occupied += float(p["weight"] or 0.0)
        plist.append({"pick_id": p["pick_id"], "symbol": p["symbol"], "source": p["source"], "state": p["state"], "thesis": _one_line(p["thesis"]), "break_condition": _one_line(p["break_condition"], 120),
                      "days_held": p["days_held"], "weight": p["weight"], "vs_index": scored.get(int(p["pick_id"]))})
    ceiling = share_ceiling(market, float(sh["share"]))
    room = max(0.0, ceiling - occupied)
    return {"market": market, "on": bool(st["on"]), "share": float(sh["share"]), "share_why": sh.get("source"), "room": round(room, 4), "no_new_picks": bool(sh.get("no_new_picks")),
            "system_picks_bought": sh.get("system_picks_bought"), "next_judgment_at_sessions": sh.get("next_judgment_at_sessions"), "picks": plist, "needs_learned": bool(st["needs_learned"])}


def share_ceiling(market: str, share: float) -> float:
    """The most the picks may hold of the market's book: the sleeve's share (US: also under 1 minus the SPY floor)."""
    if market != "US":
        return share
    try:
        from pflab.core import pick_share
        return min(share, 1.0 - float(pick_share.settings("US")["us_spy_floor"]))
    except Exception:
        return share


def _market_text(m: dict) -> str:
    nm = NAMES[m["market"]]
    if not m["on"]:
        return f"PICKS, {nm}: switched off for now (the book holds its core and what it holds)."
    head = (f"PICKS, {nm}: the sleeve's share is {m['share']:.0%} ({m['share_why']}); the picks hold {m['share'] - m['room']:.0%}"
            + (", room left under the share " + f"{m['room']:.0%}" if m["room"] > 0.005 else ", no room left under the share") + "."
            + (" The share was just lowered: no new picks until the next judgment." if m["no_new_picks"] else ""))
    if not m["picks"]:
        return head + " No picks yet."
    lines = [head]
    for p in m["picks"]:
        v = p["vs_index"]
        vs = (f"{v['excess_pct']:+.1f} points against the index at {v['horizon_months']} month(s)" if v and v.get("excess_pct") is not None else "not scored yet (first score at 1 month)")
        who = "his Kite stock" if p["source"] == "kite" else "system pick"
        lines.append(f"  - {p['symbol']} ({who}, {p['state']}, {p['days_held']} days in the book, {float(p['weight'] or 0) * 100:.1f}% of the book): {vs}. Thesis: {p['thesis']} Breaks if: {p['break_condition']}")
    return "\n".join(lines)


def build(con, day: date) -> dict:
    """The PICKS section for both markets and the last 'what I learned'. A market that cannot be read is left out with its reason (the card never fails for it)."""
    from pflab.lab import service
    out: dict = {}
    parts = []
    for m in ("IN", "US"):
        try:
            out[m] = market_block(con, m, day)
            parts.append(_market_text(out[m]))
        except Exception as e:
            out[m] = None
            parts.append(f"PICKS, {NAMES[m]}: unreadable ({type(e).__name__})")
    out["learned"] = service.last_learned(con)
    parts.append("WHAT I LEARNED (last note): " + (f"({out['learned']['when']}) {_one_line(out['learned']['learned'], 400)}" if out["learned"] else "nothing written yet"))
    out["text"] = "\n".join(parts)
    return out
