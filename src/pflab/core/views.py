"""The tactical lane (S80 phase 3): how the AI acts on news the same day. A policy change needs lab tests and weeks of shadow; a VIEW does not. The strategist issues one: a direction, the
names, a size as a share of the TACTICAL BUDGET, a horizon, exit conditions and the storyline it rests on. Code checks it, sizes it and carries it out at the close, inside the
tactical budget, through the same rails as every other order. No conversation and no approval.

    budget      a share of the book: 10% to start, 20% once its views have beaten the index over `views_to_judge` scored views, 5% after a poor record
    sizing      code: each active view adds `share_of_budget x budget share x book value` to its names' target weights (split equally); a DOWN view lowers them (no short selling: it can
                take a holding to zero, never below); the sum of the shares of all active views cannot pass 1.0
    life        a view is active from the close after it is issued until its horizon, or until its stop (a fall of `stop_pct` from its reference close) fires
    scoring     at the horizon: the names' equal-weighted return against the Nifty 500's over the same sessions, times the direction; positive is good
The strategist sees its own record in the book card. Views merge into the policy's target weights BEFORE the rails, so every cap, the circuit breaker and the turnover limits apply.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Dict, List, Optional

from pflab import core

MAX_NAMES = 6
MAX_HORIZON = 60
MIN_HORIZON = 3


def settings() -> dict:
    return core.settings()["tactical"]


def budget_share(con) -> dict:
    """The tactical budget as a share of the book: start, or high after a good record of `views_to_judge` scored views, or low after a poor one."""
    st = settings()
    rows = con.execute("SELECT outcome_json FROM core_views_s80 WHERE outcome IN ('good','bad') ORDER BY view_id DESC LIMIT ?", [int(st["views_to_judge"])]).fetchall()
    if len(rows) < int(st["views_to_judge"]):
        return {"share": float(st["start_share"]), "why": f"{len(rows)} of {st['views_to_judge']} views scored: the starting budget"}
    ex = [json.loads(r[0]).get("excess_signed", 0.0) for r in rows]
    mean, hit = sum(ex) / len(ex), sum(1 for x in ex if x > 0) / len(ex)
    if mean > 0 and hit >= 0.55:
        return {"share": float(st["high_share"]), "why": f"its last {len(ex)} views beat the index on average ({mean:+.2%}, {hit:.0%} right): the larger budget"}
    if mean < -0.005 or hit < 0.40:
        return {"share": float(st["low_share"]), "why": f"a poor record over its last {len(ex)} views ({mean:+.2%}, {hit:.0%} right): the smaller budget"}
    return {"share": float(st["start_share"]), "why": f"a middling record over its last {len(ex)} views: the starting budget"}


def active(con, day: date) -> List[dict]:
    out = []
    for r in con.execute("SELECT view_id, direction, names_json, share_of_budget, horizon_sessions, exit_json, due_on, ref_level, storyline_id FROM core_views_s80 "
                         "WHERE status='active' AND made_on < ? AND due_on >= ? ORDER BY view_id", [day, day]).fetchall():
        out.append({"view_id": r[0], "direction": r[1], "names": json.loads(r[2]), "share": r[3], "horizon": r[4], "exit": json.loads(r[5] or "{}"), "due_on": r[6], "storyline_id": r[8]})
    return out


def issue(con, now: datetime, day: date, *, direction: int, names: List[str], share_of_budget: float, horizon_sessions: int, stop_pct: float = 8.0, storyline_id: Optional[int] = None,
          reason: str = "", session_id: Optional[int] = None, isin_of=None) -> dict:
    """Validate and store a view (status 'active' from the next close). `names`: symbols the record knows. Returns the view's id and what code will do with it."""
    from pflab.paper import book
    from pflab.pm.store import next_id
    from pflab import markets
    if not settings()["on"]:
        return {"ok": False, "problem": "the tactical lane is switched off (configs/core.toml [tactical])"}
    if direction not in (-1, 1):
        return {"ok": False, "problem": "direction is 1 (up: buy) or -1 (down: reduce what is held; nothing is ever shorted)"}
    if not 0 < share_of_budget <= 1:
        return {"ok": False, "problem": "share_of_budget is a fraction of the tactical budget, above 0 and at most 1"}
    if not MIN_HORIZON <= int(horizon_sessions) <= MAX_HORIZON:
        return {"ok": False, "problem": f"horizon_sessions must be {MIN_HORIZON} to {MAX_HORIZON}"}
    if not 1 <= float(stop_pct) <= 30:
        return {"ok": False, "problem": "stop_pct (the fall from the reference close that ends the view) is 1 to 30"}
    reason = " ".join((reason or "").split())
    if len(reason) < 25:
        return {"ok": False, "problem": "say why in a sentence or two, and what it rests on"}
    if storyline_id is not None:
        from pflab.story import store as sstore
        if not sstore.get(con, int(storyline_id)):
            return {"ok": False, "problem": f"storyline {storyline_id} does not exist"}
    isins = []
    for n in list(dict.fromkeys(names))[:MAX_NAMES + 1]:
        i = (isin_of or (lambda sym: book.isin_of(con, sym)))(str(n).upper())
        px = book.close_on(con, i, day) if i else None
        meta = book.inst(con, i) if i else {}
        if not i or px is None or (meta.get("asset_class") or "") not in book.BUYABLE:
            return {"ok": False, "problem": f"{n} is not a listed share or ETF with a stored close"}
        isins.append(i)
    if not isins or len(isins) > MAX_NAMES:
        return {"ok": False, "problem": f"name 1 to {MAX_NAMES} securities"}
    used = sum(v["share"] for v in active(con, day.fromordinal(day.toordinal() + 1)) if v["view_id"])
    if used + share_of_budget > 1.0 + 1e-9:
        return {"ok": False, "problem": f"the active views already use {used:.0%} of the tactical budget; this one would pass 100%"}
    ref = sum(book.close_on(con, i, day)[1] for i in isins) / len(isins)
    due = markets.get("IN").session_after(day, int(horizon_sessions))
    vid = next_id(con, "core_views_s80", "view_id")
    con.execute("INSERT INTO core_views_s80 (view_id, made_on, made_at, session_id, storyline_id, direction, names_json, share_of_budget, horizon_sessions, exit_json, reason, status, due_on, ref_level) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [vid, day, now, session_id, storyline_id, direction, json.dumps(isins), float(share_of_budget), int(horizon_sessions),
                                                         json.dumps({"stop_pct": float(stop_pct)}), reason[:600], "active", due, ref])
    b = budget_share(con)
    return {"ok": True, "view_id": vid, "starts": "the next close", "ends": str(due), "tactical_budget_share_of_book": b["share"], "worth_of_budget_used": round(used + share_of_budget, 3),
            "code_will": f"{'buy' if direction > 0 else 'reduce'} {len(isins)} name(s) by about {share_of_budget * b['share']:.1%} of the book in all, through the rails"}


def merge(con, day: date, weights: Dict[str, float], holdings: Dict[str, float]) -> Dict[str, float]:
    """The policy's target weights plus every active view's adjustment (before the rails). Also ends views whose stop fired. `holdings`: current weights by ISIN."""
    from pflab.paper import book
    out = dict(weights)
    share = budget_share(con)["share"]
    for v in active(con, day):
        px = [book.close_on(con, i, day) for i in v["names"]]
        ref = con.execute("SELECT ref_level FROM core_views_s80 WHERE view_id=?", [v["view_id"]]).fetchone()[0]
        now_lvl = sum(p[1] for p in px if p) / max(1, sum(1 for p in px if p))
        if v["direction"] > 0 and ref and now_lvl / ref - 1 <= -v["exit"].get("stop_pct", 8.0) / 100.0:
            con.execute("UPDATE core_views_s80 SET status='stopped' WHERE view_id=?", [v["view_id"]])
            continue
        each = v["share"] * share / len(v["names"])
        done = json.loads(con.execute("SELECT executed_json FROM core_views_s80 WHERE view_id=?", [v["view_id"]]).fetchone()[0] or "{}")
        for i in v["names"]:
            if i not in out and (done.get(i) or {}).get("qty"):        # S81: carried out in session (core/session.py): the book holds it already, the close does not add it a second time
                continue
            cur = holdings.get(i, 0.0)
            base = out.get(i, cur)
            out[i] = base + each if v["direction"] > 0 else max(0.0, base - each)
    return out


def score_due(con, now: datetime, day: date, root=None) -> int:
    """At each view's horizon (or when stopped): its names' return against the Nifty 500's over the same days, signed by the direction."""
    from pflab.paper import book
    from pflab.story import series
    n = 0
    for vid, direction, names_json, ref, made_on, due, status in con.execute(
            "SELECT view_id, direction, names_json, ref_level, made_on, due_on, status FROM core_views_s80 WHERE scored_at IS NULL AND (due_on <= ? OR status='stopped') AND status <> 'void'", [day]).fetchall():
        names = json.loads(names_json)
        end = date.min if False else (due if due <= day else day)
        px = [book.close_on(con, i, end) for i in names]
        if not ref or any(p is None for p in px):
            continue
        ret = sum(p[1] for p in px) / len(px) / ref - 1.0
        i0, i1 = series.level_on("NIFTY500_TRI", made_on, root), series.level_on("NIFTY500_TRI", end, root)
        idx = (i1 / i0 - 1.0) if i0 and i1 else 0.0
        signed = direction * (ret - idx)
        con.execute("UPDATE core_views_s80 SET scored_at=?, outcome=?, outcome_json=?, status=CASE WHEN status='stopped' THEN 'stopped' ELSE 'done' END WHERE view_id=?",
                    [now, "good" if signed > 0 else "bad", json.dumps({"names_return": round(ret, 5), "index_return": round(idx, 5), "excess_signed": round(signed, 5), "to": str(end)}), vid])
        n += 1
    return n


def record_text(con) -> str:
    rows = con.execute("SELECT count(*) FILTER (WHERE outcome='good'), count(*) FILTER (WHERE outcome='bad'), count(*) FILTER (WHERE scored_at IS NULL) FROM core_views_s80").fetchone()
    b = budget_share(con)
    return f"{rows[0]} good and {rows[1]} bad of the scored views, {rows[2]} open; budget {b['share']:.0%} of the book ({b['why']})"
