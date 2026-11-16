"""S89: what the chat can START. The full operator proposes a change (the watchlist, a US holding, an agent's model or thinking, a run of the desk or the weekly look); the proposal is a Yes/No card and NOTHING
changes before his Yes (`cards.post_decision_card` runs `apply` only after Yes). Reading is free and needs no card. The quick road has no tool for this: asking for an action hands over to the full road."""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Dict

KINDS = ("watch_add", "watch_remove", "us_add", "us_set", "us_remove", "agent_set", "run_agent", "standing_set")
APPLY = "pflab.oper.actions:apply"


def describe(kind: str, p: Dict[str, Any]) -> str:
    if kind == "watch_add":
        al = ", ".join(p.get("alerts") or ["moves 3%+", "news"])
        return f"Add {p['symbol']} to the watchlist, alert on {al}?"
    if kind == "watch_remove":
        return f"Stop watching {p['symbol']}?"
    if kind == "us_add":
        return f"Add {p['shares']:g} shares of {p['ticker']} at ${float(p['avg_price']):.2f} to your US holdings (read-only record)?"
    if kind == "us_set":
        return f"Change your {p['ticker']} holding to {p['shares']:g} shares?"
    if kind == "us_remove":
        return f"Remove {p['ticker']} from your US holdings?"
    if kind == "agent_set":
        return f"Set the {p['agent']} agent to {p.get('model') or 'its model'} at {p.get('thinking') or 'its thinking level'} thinking, from the next run?"
    if kind == "standing_set":
        from pflab.oper import standing
        label, _, _, cost = standing.ORDERS[p["order"]]
        return (f"Switch ON '{label}'? It then starts by itself ({cost})." if p["on"] else f"Switch OFF '{label}'? Nothing of that kind starts by itself until you switch it on; the alarm lane and the code go on.")
    return f"Run the {p['agent']} agent now? It draws on your plan's limits."


def check(con, now: datetime, kind: str, p: Dict[str, Any]) -> Dict[str, Any]:
    """Validate WITHOUT changing anything; returns the cleaned payload or raises ValueError."""
    from pflab.app import s89
    s89.ensure(con)
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if kind in ("watch_add", "watch_remove"):
        import re
        s = str(p.get("symbol") or "").strip().upper()
        if not re.match(r"^[A-Z0-9&.\-]{1,20}$", s):
            raise ValueError("Give a name or ticker.")
        if kind == "watch_add" and not con.execute("SELECT count(*) FROM watch_s89 WHERE symbol=?", [s]).fetchone()[0] and con.execute("SELECT count(*) FROM watch_s89").fetchone()[0] >= s89.WATCH_CAP:
            raise ValueError(f"The watchlist holds up to {s89.WATCH_CAP} names.")
        return {"symbol": s, "market": p.get("market") or "India", "why": str(p.get("why") or "")[:200], "alerts": [a for a in (p.get("alerts") or ["moves 3%+", "news"]) if a in s89.ALERTS]}
    if kind in ("us_add", "us_set", "us_remove"):
        if kind == "us_remove":
            t = str(p.get("ticker") or "").strip().upper()
            if not con.execute("SELECT count(*) FROM mine_us_s89 WHERE ticker=?", [t]).fetchone()[0]:
                raise ValueError(f"{t} is not in your US holdings.")
            return {"ticker": t}
        cur = con.execute("SELECT shares, avg_price FROM mine_us_s89 WHERE ticker=?", [str(p.get("ticker") or "").strip().upper()]).fetchone()
        v = s89.validate_us(p.get("ticker"), p.get("shares"), p.get("avg_price") if p.get("avg_price") is not None else (cur[1] if cur else None), p.get("bought_on"), now.date())
        if kind == "us_add" and cur:
            raise ValueError("You already hold it: propose a change of shares instead.")
        if kind == "us_set" and not cur:
            raise ValueError("It is not in your US holdings yet.")
        return {"ticker": v["ticker"], "shares": v["shares"], "avg_price": v["avg_price"], "bought_on": str(v["bought_on"]) if v["bought_on"] else None}
    if kind == "agent_set":
        if str(p.get("agent")) not in {a[0] for a in s89.AGENTS}:
            raise ValueError("unknown agent")
        if p.get("model") is not None and p["model"] not in s89.MODELS:
            raise ValueError("model must be one of " + ", ".join(s89.MODELS))
        if p.get("thinking") is not None and p["thinking"] not in s89.LEVELS:
            raise ValueError("thinking must be one of " + ", ".join(s89.LEVELS))
        return {"agent": str(p["agent"]), "model": p.get("model"), "thinking": p.get("thinking")}
    if kind == "standing_set":
        from pflab.oper import standing
        if str(p.get("order")) not in standing.ORDERS or not isinstance(p.get("on"), bool):
            raise ValueError("standing_set: order is one of " + ", ".join(standing.ORDERS) + "; on is true or false")
        return {"order": str(p["order"]), "on": bool(p["on"])}
    if str(p.get("agent")) not in ("desk", "weekly", "case"):
        raise ValueError("run_agent: desk, weekly or case")
    return {"agent": str(p["agent"])}


def propose(con, now: datetime, kind: str, payload: Dict[str, Any]) -> str:
    """Post the Yes/No card. Nothing is changed here."""
    from pflab.entrance import cards
    try:
        clean = check(con, now, kind, payload or {})
    except ValueError as e:
        return f"Not proposed: {e}"
    cards.post_decision_card(con, now, "chat_action", {"kind": kind, "payload": clean}, describe(kind, clean), APPLY, expires_hours=48)
    return "A Yes/No card is in the chat and on Telegram. Nothing changes until he taps Yes."


def apply(con, now: datetime, payload: Dict[str, Any]) -> str:
    """Runs ONLY after his Yes (the card framework calls it)."""
    from pflab.app import s89
    kind, p = payload["kind"], payload["payload"]
    s89.ensure(con)
    if kind == "watch_add":
        r = s89.watch_add(con, now, p["symbol"], p.get("market") or "India", p.get("why") or "", p.get("alerts"))
        return f"Watching {p['symbol']} now ({r.get('count', 'updated')} on the list)."
    if kind == "watch_remove":
        s89.watch_remove(con, p["symbol"])
        return f"Stopped watching {p['symbol']}."
    if kind in ("us_add", "us_set", "us_remove"):
        s89.us_change(con, now, kind.split("_")[1], p["ticker"], p.get("shares"), p.get("avg_price"), p.get("bought_on"))
        return {"us_add": "Added to", "us_set": "Changed in", "us_remove": "Removed from"}[kind] + f" your US holdings: {p['ticker']}."
    if kind == "agent_set":
        s89.agents_set(con, now, p)
        return f"The {p['agent']} agent will use the new setting from its next run."
    if kind == "standing_set":
        from pflab.oper import standing
        r = standing.set_on(con, now, p["order"], p["on"], by="him (chat)")
        return f"'{r['label']}' is now {'ON' if r['on'] else 'OFF'}."
    agent = p["agent"]

    def go():
        c = con.cursor()
        try:
            if agent == "weekly":
                from pflab.oper import introspect
                introspect.run(c, datetime.now())
            elif agent == "desk":
                from pflab.think import desk
                desk.run_desk(c, datetime.now(), "india_close")
            elif agent == "case":                                      # S93: his own "think the cases through" (before S93 this branch was missing and the card did nothing)
                from pflab.think import wire
                wire.sweep(c, datetime.now(), asked=True)
        except Exception:
            pass
    threading.Thread(target=go, name=f"run-{agent}", daemon=True).start()
    return f"Started the {agent} run."
