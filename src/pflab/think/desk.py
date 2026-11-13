"""T10 the daily desk (S84): the strategist at a desk with an agenda, not a timer.

From this release the strategist works every day the app is open: ONE working session after the Indian close (`india_close`) and ONE in the IST morning after a US session (`us_morning`); a missed
one is caught up in ONE session (`catchup`), never one per missed day. The agenda is built by CODE from what changed since the last desk session, most important first:

    1 case       the open cases whose look is due (a case over the 2% line gets its thinking session through `think.session.think_case`, once a day)
    2 holding    every holding with a thesis-break or high-severity event, a result or a signal of the watch since the last session
    3 scorecards the picks, the decisions, the calibration and the misses, when something was scored since the last session
    4 storyline  the storylines that moved
    5 idea       ONE search for a new idea in each market (`screen_stocks`) while the picks sleeve has room; after a case trimmed or sold a name it looks OUTSIDE that sector first
    then         the plan for the next session, written by code for Today and the reports.

Sonnet (role `read`) works the items; Opus (role `decide`) is called only for a decision: a pick, a withdrawal, a case over the 2% line. Every model call goes through `llm/gateway.py`; the model
reads and names (JSON: a finding, a symbol, a thesis), it never writes a number: a sentence carrying a number that is not in the facts the model was given is dropped (`sourced`). Everything is stored
(`desk_sessions_s84`, `desk_steps_s84`) with the engine, model, thinking level and cost of each step. What the desk finds is written back where `recall` finds it, and what `recall` hands to the
desk is marked used (`knowledge_use_s84`).

Money: a day's desk is stopped by its own budget (`[strategist] daily_budget_rupees`, default 30) and always by his monthly cap (and the governor in the gateway). SPENDING FOLLOWS RESULTS: from the
A55 date (`[strategist] throttle_after`, 2026-12-09), while the decision scorecard has 20 scored decisions and is behind "do nothing", the budget halves (and `think.score.advisory` makes the loop
advisory); ahead, full. A day with nothing changed is a two-line note, not a session, and costs nothing. The weekly allocation review stays weekly (`strategist.due`): the desk never starts it.

Modules of other agents (`llm.gateway`, `think.recall`, `think.watch`, `think.session`, `think.score`) are reached through the small `_x()` functions below, so a test or a not-yet-merged branch
swaps them; each is optional (a missing one narrows the desk, never stops it).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from typing import Callable, Dict, List, Optional

from pflab import think

MODES = ("india_close", "us_morning", "catchup")
SLOTS = ("us_morning", "india_close")
INDIA_CLOSE_AT = time(15, 45)            # the desk sits down after the Indian close (data of the close arrives after 15:30)
US_MORNING_AT = time(7, 0)               # and in the IST morning after a US session
DEFAULTS = {"daily_budget_rupees": 30.0, "desk_max_items": 12, "desk_item_cost_guess": 3.0, "desk_decide_cost_guess": 12.0, "desk_first_since_days": 3, "desk_on": True,
            "desk_case_think": True, "desk_idea_n": 25, "desk_idea_cards": 3}

READ_SYSTEM = ("You are the DESK of a small personal-portfolio system (a paper book of Indian and US shares). You read ONE agenda item at a time and say, in plain words, what it means for the "
               "book. You do not trade and you never write a number: use only the figures in the facts you are given, and if you need a figure that is not there, leave it out. "
               "Answer with JSON only: {\"finding\": at most two sentences, \"needs_decision\": one of none|pick|withdrawal|case, \"next_step\": at most one sentence}. "
               "Say needs_decision=withdrawal only when the facts show an event that breaks the thesis of a pick the book holds; otherwise none.")
def _obj(props: dict, required: list) -> dict:
    """A JSON schema object the vendor's structured output accepts (no extra keys)."""
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


READ_SCHEMA = _obj({"finding": {"type": "string"}, "needs_decision": {"type": "string", "enum": ["none", "pick", "withdrawal", "case"]}, "next_step": {"type": "string"}}, ["finding", "needs_decision", "next_step"])
SHORTLIST_SYSTEM = ("You are the DESK of a small personal-portfolio system. From the screen's rows pick at most {n} symbols worth a closer look for the picks sleeve, using only what the rows say. "
                    "Past returns are a description, not evidence. Answer JSON only: {{\"symbols\": [..], \"why\": one sentence}}. An empty list is a good answer when nothing is worth it.")
SHORTLIST_SCHEMA = _obj({"symbols": {"type": "array", "items": {"type": "string"}}, "why": {"type": "string"}}, ["symbols", "why"])
PICK_SYSTEM = ("You are the DECISION step of the desk of a small personal-portfolio system (paper money). You may name stocks for the picks sleeve with a thesis and what would break it, and skip "
               "ideas you looked at. You never write a size, a price, a weight or any number of your own: code checks the rails, sizes, buys and scores. Each pick needs a thesis of 60+ characters "
               "from the facts, a break condition, and, when the facts show an earlier note or case on the name, what you take from it. Answer JSON only: "
               "{\"picks\": [{\"symbol\", \"thesis\", \"break_condition\", \"storylines\": []}], \"skips\": [{\"symbol\", \"why\"}], \"learned_from\": what the scorecard taught you}. Fewer picks is fine; none is fine.")
PICK_SCHEMA = _obj({"picks": {"type": "array", "items": _obj({"symbol": {"type": "string"}, "thesis": {"type": "string"}, "break_condition": {"type": "string"},
                                                              "storylines": {"type": "array", "items": {"type": "integer"}}}, ["symbol", "thesis", "break_condition", "storylines"])},
                    "skips": {"type": "array", "items": _obj({"symbol": {"type": "string"}, "why": {"type": "string"}}, ["symbol", "why"])}, "learned_from": {"type": "string"}},
                   ["picks", "skips", "learned_from"])
WITHDRAW_SYSTEM = ("You are the DECISION step of the desk of a small personal-portfolio system (paper money). A pick the book holds may have lost its thesis. Withdraw it only if the facts show the "
                   "thesis no longer holds; the sale is then made by code (the 12-month tax guard may make it wait). Never write a number. Answer JSON only: "
                   "{\"action\": \"withdraw\" or \"keep\", \"reason\": one or two sentences using only the facts}.")
WITHDRAW_SCHEMA = _obj({"action": {"type": "string", "enum": ["withdraw", "keep"]}, "reason": {"type": "string"}}, ["action", "reason"])

_NUM = re.compile(r"\d[\d,]*\.?\d*")
_TAGS = re.compile(r"[#@][\w-]+")


# --- settings and the optional modules --------------------------------------------------------------------------------------------------------------------------------------------

def settings() -> dict:
    out = dict(DEFAULTS)
    try:
        from pflab import core
        st = core.settings()["strategist"]
        out.update({k: v for k, v in st.items() if k in DEFAULTS})
        if "daily_budget_rupees" in st:
            out["daily_budget_rupees"] = float(st["daily_budget_rupees"])
    except Exception:
        pass
    return out


call_fn: Optional[Callable] = None            # a test injects a scripted `call(con, role, system, messages, **kw)`; else `llm.gateway.call`
modules: Dict[str, object] = {}                # a test injects fakes: "recall", "watch", "session", "score"


def _x(name: str):
    if name in modules:
        return modules[name]
    try:
        import importlib
        return importlib.import_module({"gateway": "pflab.llm.gateway"}.get(name, f"pflab.think.{name}"))
    except Exception:
        return None


def _call(con, role: str, system: str, messages: list, **kw) -> dict:
    fn = call_fn
    if fn is None:
        from pflab.llm import gateway
        fn = gateway.call
    from pflab.think.session import scrub                               # a US pseudo-ISIN in the facts is an "account-like number" to the egress gate: names go by symbol
    return fn(con, role, system, scrub(con, messages), agent="desk", **kw)         # the door's governor knows the agent `desk` (its own layer); the first user message is what the egress gate reads


def _refusal(e: BaseException) -> Optional[str]:
    """Plain words when the governor, the cap or the egress gate refused (the desk stops for the day), else None (an ordinary failure of one item)."""
    try:
        from pflab.llm import gateway
        return gateway.refusal_reason(e)
    except Exception:
        return None


def on() -> bool:
    return bool(settings()["desk_on"]) and think.on()


# --- helpers ------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _id(con, table: str, col: str) -> int:
    from pflab.pm.store import next_id
    return next_id(con, table, col)


def sourced(text: str, facts: str) -> bool:
    """Rule 8 for a model's sentence: every number in it is in the facts the model was given."""
    known = {n.replace(",", "").rstrip(".") for n in _NUM.findall(_TAGS.sub(" ", facts))}
    return all(n.replace(",", "").rstrip(".") in known for n in _NUM.findall(_TAGS.sub(" ", text or "")))


def _clean(text: str, facts: str, fallback: str) -> str:
    t = " ".join(str(text or "").split())
    return t if t and sourced(t, facts) else fallback


def _cut(s, n: int = 160) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "..."


def _market_open_day(market: str, d: date) -> bool:
    try:
        from pflab import markets
        return bool(markets.get(market).is_session(d))
    except Exception:
        return d.weekday() < 5


# --- the sessions and the slots ------------------------------------------------------------------------------------------------------------------------------------------------

def _last_session(con) -> Optional[dict]:
    r = con.execute("SELECT session_id, day, mode, covers, started_at, status FROM desk_sessions_s84 WHERE status IN ('done','quiet','budget') ORDER BY started_at DESC, session_id DESC LIMIT 1").fetchone()
    return dict(zip(("session_id", "day", "mode", "covers", "started_at", "status"), r)) if r else None


def since(con, now: datetime) -> datetime:
    """What changed is measured from the last finished desk session (a quiet one counts); with none yet, from a few days back."""
    last = _last_session(con)
    return last["started_at"] if last else now - timedelta(days=int(settings()["desk_first_since_days"]))


def _slot_done(con, day: date, slot: str) -> bool:
    for (cov,) in con.execute("SELECT covers FROM desk_sessions_s84 WHERE day=? AND status IN ('done','quiet','budget')", [day]).fetchall():
        if slot in (cov or "").split(","):
            return True
    return False


def _failed_today(con, day: date, slot: str) -> int:
    return sum(1 for (cov,) in con.execute("SELECT covers FROM desk_sessions_s84 WHERE day=? AND status='failed'", [day]).fetchall() if slot in (cov or "").split(","))


def pending_slots(con, now: datetime) -> List[str]:
    """The slots (us_morning, india_close) that are open now and not yet worked today."""
    day, t = now.date(), now.time()
    out = []
    if t >= US_MORNING_AT and _market_open_day("US", day - timedelta(days=1)) and not _slot_done(con, day, "us_morning") and _failed_today(con, day, "us_morning") < 2:
        out.append("us_morning")
    if t >= INDIA_CLOSE_AT and _market_open_day("IN", day) and not _slot_done(con, day, "india_close") and _failed_today(con, day, "india_close") < 2:
        out.append("india_close")
    return out


def mode_for(con, now: datetime) -> Optional[tuple]:
    """(mode, covers) for the session to run now, or None. Two slots open at once, or a day off since the last session, is ONE catch-up session covering what is open."""
    slots = pending_slots(con, now)
    if not slots:
        return None
    last = _last_session(con)
    gap = last is not None and (now.date() - last["day"]).days >= 2
    if len(slots) > 1 or gap:
        return "catchup", ",".join(slots)
    return slots[0], slots[0]


# --- the agenda (code) ----------------------------------------------------------------------------------------------------------------------------------------------------------------

def _scope(con, day: date, market: Optional[str] = None) -> List[dict]:
    """Holdings the desk watches: the watch's scope when it exists, else the paper book's positions."""
    rows: List[dict] = []
    w = _x("watch")
    try:
        if w is not None and hasattr(w, "scope"):
            rows = [dict(r) for r in w.scope(con, day)]
    except Exception:
        rows = []
    if not rows:
        try:
            from pflab.paper import book
            rows = [{"name": i, "isin": i, "symbol": i, "market": "IN", "exposure_inr": 0.0, "exposure_pct": 0.0, "why": "held"} for i, q in book.positions(con).items() if q > 1e-9]
        except Exception:
            rows = []
    return [r for r in rows if market is None or r.get("market", "IN") == market]


def _picks_by_isin(con, day: date) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    try:
        from pflab.core import picks
        for m in ("IN", "US"):
            for p in picks.status(con, m, day)["picks"]:
                if p["state"] in ("held", "buying", "proposed") and p.get("isin"):
                    out[p["isin"]] = {**p, "market": m}
    except Exception:
        pass
    return out


def _events_since(con, isins: List[str], t0: datetime, now: datetime) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    try:
        from pflab.kg.events import material_events
        for e in material_events(con, isins, t0, now):
            out.setdefault(e["isin"], []).append(e)
    except Exception:
        pass
    return out


def _case_item(c: dict, why: str, due: bool) -> dict:
    pend = f" Waiting for: {c['pending']}." if c.get("pending") else ""
    kl = f" Class: {str(c['klass']).replace('_', ' ')}." if c.get("klass") else ""
    facts = (f"Case #{c['case_id']} on {c.get('symbol') or c['title']}: {c['title']}.{kl}{pend} State: {c['state']}. "
             f"Exposure about {float(c.get('exposure_pct') or 0) * 100:.1f}% of the book. "
             + (f"Its look was due {c.get('next_look_on_s') or c.get('next_look_on')}." if due else "Open."))
    over = float(c.get("exposure_pct") or 0) >= float(think.settings()["opus_exposure_share"])
    return {"kind": "case", "ref": f"case:{c['case_id']}", "market": c.get("market"), "isin": c.get("isin"), "symbol": c.get("symbol"), "title": f"case #{c['case_id']}: {c['title']}", "why": why,
            "facts": facts, "model": "read", "score": float(c.get("score") or 0.0), "case_id": c["case_id"], "over_2pct": bool(over and due)}


def agenda(con, now: datetime, mode: str) -> List[dict]:
    """The agenda for a session of `mode`, most important first, from what changed since the last desk session. Code only; no model, no cost."""
    day = now.date()
    t0 = since(con, now)
    st = settings()
    want = {"india_close": {"IN"}, "us_morning": {"US"}, "catchup": {"IN", "US"}}.get(mode, {"IN", "US"})
    items: List[dict] = []
    # 1 the open cases and their looks due
    try:
        from pflab.think import cases
        due_ids = {c["case_id"] for c in cases.looks_due(con, day)}
        for c in cases.open_cases(con):
            if c.get("market") not in want and c.get("market") is not None:
                continue
            new_sig = bool(con.execute("SELECT 1 FROM think_signals_s84 WHERE case_id=? AND ts > ? LIMIT 1", [c["case_id"], t0]).fetchone())
            if c["case_id"] in due_ids or new_sig:
                items.append(_case_item(c, "its look is due" if c["case_id"] in due_ids else "a new signal joined it", c["case_id"] in due_ids))
    except Exception:
        pass
    # 2 holdings with news, a result or a move since the last session
    try:
        scope = [r for r in _scope(con, day) if r.get("market", "IN") in want]
        by_isin = {r["isin"]: r for r in scope if r.get("isin")}
        ev = _events_since(con, list(by_isin), t0, now)
        sigs: Dict[str, List[dict]] = {}
        for s in con.execute("SELECT isin, signal, value, threshold, surprise, status FROM think_signals_s84 WHERE ts > ? AND status <> 'examined'", [t0]).fetchall():
            sigs.setdefault(s[0], []).append({"signal": s[1], "value": s[2], "threshold": s[3], "surprise": s[4], "status": s[5]})
        pk = _picks_by_isin(con, day)
        in_case = {i["isin"] for i in items if i["kind"] == "case"}
        for isin, r in by_isin.items():
            if isin in in_case or (not ev.get(isin) and not sigs.get(isin)):
                continue
            lines = [f"{e['ts']:%Y-%m-%d}: {e['kind'].replace('_', ' ')} ({e['severity']}): {_cut(e['text'], 110)}" for e in ev.get(isin, [])[:4]]
            lines += [f"signal {s['signal'].replace('_', ' ')}: {s['value']:+.3g} against a threshold of {s['threshold']:.3g}" for s in sigs.get(isin, [])[:3]]
            sym = r.get("symbol") or isin
            pick = pk.get(isin)
            facts = f"{sym} ({r.get('market', 'IN')}), about {float(r.get('exposure_pct') or 0) * 100:.1f}% of the book. Since the last session: " + " | ".join(lines)
            if pick:
                facts += f" | It is a pick. Thesis: {_cut(pick.get('thesis'), 200)} Breaks if: {_cut(pick.get('break_condition'), 140)}"
            items.append({"kind": "holding", "ref": f"holding:{isin}", "market": r.get("market", "IN"), "isin": isin, "symbol": sym, "title": f"{sym}: news or a move since the last session",
                          "why": "an event or a signal since the last session", "facts": facts, "model": "read", "score": float(r.get("exposure_inr") or 0.0),
                          "has_events": bool(ev.get(isin)), "pick": pick})
    except Exception:
        pass
    # 3 the scorecards, when something was scored since the last session
    try:
        n_new = con.execute("SELECT count(*) FROM think_scores_s84 WHERE scored_on >= ?", [t0.date()]).fetchone()[0]
        n_new += con.execute("SELECT count(*) FROM pick_scores_s83 WHERE scored_on >= ?", [t0.date()]).fetchone()[0]
        if n_new:
            items.append({"kind": "scorecards", "ref": "scorecards", "market": None, "title": "the scorecards moved", "why": f"{n_new} new score(s) since the last session", "facts": scorecard_text(con, day),
                          "model": "read", "score": 0.0})
    except Exception:
        pass
    # 4 the storylines that moved
    try:
        rows = con.execute("SELECT storyline_id, claim, probability, market FROM storylines_s80 WHERE status='open' AND updated_at >= ? ORDER BY storyline_id", [t0]).fetchall()
        rows = [r for r in rows if r[3] in want or r[3] is None]
        if rows:
            facts = "Storylines that moved since the last session: " + " | ".join(f"#{a} {_cut(b, 90)} (now {float(p or 0):.0%})" for a, b, p, _ in rows[:6])
            items.append({"kind": "storyline", "ref": "storylines", "market": None, "title": f"{len(rows)} storyline(s) moved", "why": "updated since the last session", "facts": facts, "model": "read", "score": 0.0})
    except Exception:
        pass
    # 5 one search for a new idea in each market, while the picks sleeve has room
    for m in ("IN", "US"):
        if m not in want or _idea_done_today(con, day, m):
            continue
        room = _sleeve_room(con, m, day)
        if room is None or room < 0.005:
            continue
        away = _sector_to_avoid(con, m, day)
        items.append({"kind": "idea", "ref": f"idea:{m}", "market": m, "title": f"a search for a new idea ({'India' if m == 'IN' else 'US'})",
                      "why": f"the picks sleeve has room ({room:.0%} of the book)" + (f"; a case just reduced a name in {away}, so look outside it first" if away else ""),
                      "facts": f"Market {m}. Room under the sleeve's share: {room:.0%}." + (f" Sector to look outside first: {away}." if away else ""), "model": "decide", "score": 0.0,
                      "outside_sector": away})
    order = {"case": 0, "holding": 1, "scorecards": 2, "storyline": 3, "idea": 4}
    items.sort(key=lambda i: (order.get(i["kind"], 9), -float(i.get("score") or 0.0)))
    for n, it in enumerate(items[: int(st["desk_max_items"])], 1):
        it["rank"] = n
    return items[: int(st["desk_max_items"])]


def _idea_done_today(con, day: date, market: str) -> bool:
    r = con.execute("SELECT 1 FROM desk_steps_s84 s JOIN desk_sessions_s84 d ON d.session_id=s.session_id WHERE d.day=? AND s.kind='idea' AND s.market=? AND s.status IN ('done','noted')", [day, market]).fetchone()
    return bool(r)


def _sleeve_room(con, market: str, day: date) -> Optional[float]:
    """Room left under the picks sleeve's share (a share of the market's book), or None when the sleeve cannot be read or is off or just lowered."""
    try:
        from pflab.core import picks_card
        b = picks_card.market_block(con, market, day)
        if not b["on"] or b.get("no_new_picks"):
            return None
        return float(b["room"])
    except Exception:
        return None


def _sector_to_avoid(con, market: str, day: date) -> Optional[str]:
    """The sector of a name a case trimmed or sold in the last 3 days (the search for a new idea looks OUTSIDE it first)."""
    try:
        rows = con.execute("SELECT symbol, isin FROM think_decisions_s84 WHERE decided_on >= ? AND acted_option IN ('sell','trim')", [day - timedelta(days=3)]).fetchall()
        if not rows:
            return None
        from pflab.lab import screen
        sec = screen.sectors(con, screen._root(None), [r[1] for r in rows if r[1]], day) if market == "IN" else {}
        for v in sec.values():
            if v:
                return str(v)
    except Exception:
        pass
    return None


def scorecard_text(con, day: date) -> str:
    parts = []
    try:
        from pflab.core import pick_score
        parts += [pick_score.scorecard_text(con, m) for m in ("IN", "US")]
    except Exception:
        pass
    s = _x("score")
    try:
        if s is not None:
            sc = s.scorecard(con)
            parts.append(f"Decisions: {sc.get('scored', 0)} scored; against doing nothing {float(sc.get('vs_nothing_inr') or 0):+,.0f} rupees after tax. "
                         f"Skips that ran: {sc.get('skips_ran', 0)}, skips that fell: {sc.get('skips_fell', 0)}.")
    except Exception:
        pass
    return "\n".join(parts) or "No scorecard yet."


# --- the budget ------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _decisions_scored(con) -> Optional[dict]:
    s = _x("score")
    try:
        if s is not None:
            return s.scorecard(con)
    except Exception:
        pass
    return None


def cap_left(con, now: datetime) -> Optional[float]:
    """Rupees left under his cap (the window's in an acceptance window, else the month's); None when it cannot be read (the governor in the gateway still checks every call)."""
    try:
        from pflab.agents import analyst as an
        cfg = an.config()
        acc = an.acceptance(cfg, now)
        if acc:
            return float(acc["cap"]) - an.window_spend(con, acc["since"])
        return float(cfg["cap"]) - an.month_spend_inr(con, now)
    except Exception:
        return None


def spent_today(con, day: date) -> float:
    """What the day's desk sessions spent (their own model calls and the case sessions they started); a session adds its total when it finishes."""
    own = float(con.execute("SELECT coalesce(sum(cost_rupees),0) FROM desk_sessions_s84 WHERE day=?", [day]).fetchone()[0])
    try:                                                                    # the door's own ledger counts what the governor counts (refused and failed calls too)
        from pflab.llm import gateway
        return max(own, gateway.spent(con, datetime.combine(day, time.min), agent="desk"))
    except Exception:
        return own


def budget_status(con, day: date, now: Optional[datetime] = None) -> dict:
    """{base, budget, spent, left, halved, why, month_cap_left}: spending follows results. From `throttle_after` while the decision scorecard has `advisory_after_scored` scored decisions and is
    behind 'do nothing', the budget halves; ahead, it is full."""
    st = settings()
    base = float(st["daily_budget_rupees"])
    budget, halved, why = base, False, "the full daily budget"
    sc = _decisions_scored(con)
    need = int(think.settings()["advisory_after_scored"])
    behind = bool(sc and int(sc.get("scored") or 0) >= need and float(sc.get("vs_nothing_inr") or 0.0) < 0)
    if behind:
        try:
            from pflab import core
            applied = core.throttle_active(day)
        except Exception:
            applied = True
        if applied:
            budget, halved, why = base / 2.0, True, f"halved: {sc['scored']} scored decisions and behind doing nothing after tax (spending follows results)"
        else:
            why = "the decisions are behind doing nothing, but the halving is recorded, not applied before the A55 date"
    spent = spent_today(con, day)
    return {"base": base, "budget": budget, "spent": round(spent, 2), "left": round(max(0.0, budget - spent), 2), "halved": halved, "behind": behind, "why": why,
            "month_cap_left": None if now is None else cap_left(con, now)}


def due(con, now: datetime) -> List[str]:
    """Reasons for a desk session now (read by `lab/strategist.tick`): a slot is open and the agenda for it is not empty. A quiet day gives none."""
    if not on():
        return []
    try:
        m = mode_for(con, now)
        if not m:
            return []
        items = agenda(con, now, m[0])
        if not items:
            return []
        return [f"the daily desk ({m[0].replace('_', ' ')}): {len(items)} item(s) on the agenda, first: {items[0]['title']}"]
    except Exception:
        return []


# --- working the agenda ---------------------------------------------------------------------------------------------------------------------------------------------------------------

def _recall_text(con, now: datetime, it: dict) -> tuple:
    r = _x("recall")
    if r is None or not (it.get("isin") or it.get("symbol")):
        return "", []
    try:
        res = r.recall(con, now, isin=it.get("isin"), symbol=it.get("symbol"), asof=now.date(), limit_chars=2500)
        return res.get("text") or "", res.get("items") or []
    except Exception:
        return "", []


def _model_row(res: dict) -> dict:
    return {"engine": str(res.get("engine") or ""), "model": str(res.get("model") or ""), "thinking": str(res.get("thinking") or ""), "cost": float(res.get("cost_rupees") or 0.0),
            "cached": int(res.get("cached_tokens") or 0)}


def _json(res: dict) -> dict:
    j = res.get("json")
    if isinstance(j, dict):
        return j
    try:
        t = str(res.get("text") or "")
        m = re.search(r"\{.*\}", t, re.S)
        return json.loads(m.group(0)) if m else {}
    except Exception:
        return {}


def _step(con, sid: int, it: dict, now: datetime, status: str, finding: str, row: Optional[dict] = None) -> int:
    stid = _id(con, "desk_steps_s84", "step_id")
    row = row or {}
    con.execute("INSERT INTO desk_steps_s84 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [stid, sid, it.get("rank"), it["kind"], it["ref"], it.get("market"), it.get("symbol"), now, row.get("engine", ""),
                row.get("model", ""), row.get("thinking", ""), float(row.get("cost", 0.0)), int(row.get("cached", 0)), status, _cut(finding, 600)])
    return stid


class _Stop(Exception):
    """The day's budget or his cap ended the desk's work."""


def _guard_budget(con, now: datetime, spent: float, budget: float, est: float) -> None:
    if spent >= budget:
        raise _Stop("the day's desk budget is used")
    left = cap_left(con, now)
    if left is not None and left <= 0:
        raise _Stop("his monthly cap has no room")


def _read(con, now: datetime, it: dict, recall_text: str, case_id: Optional[int] = None) -> tuple:
    """One Sonnet read of an agenda item -> (answer dict, model row, facts given)."""
    facts = it["facts"] + ("\n\nWHAT WE ALREADY KNOW:\n" + recall_text if recall_text else "")
    res = _call(con, "read", READ_SYSTEM, [{"role": "user", "content": f"AGENDA ITEM ({it['kind']}): {it['title']}\nWhy it is here: {it['why']}\n\n{facts}"}],
                case_id=case_id, purpose=f"desk {it['kind']}", now=now, max_tokens=700, schema=READ_SCHEMA)
    return _json(res), _model_row(res), facts


def _work_case(con, now, it, sid, root) -> tuple:
    from pflab.think import cases
    cid = it["case_id"]
    done_today = any(str(s["step_at"])[:10] == str(now.date()) for s in cases.steps(con, cid))
    extra = ""
    cost_before = sum(float(s["cost_rupees"] or 0) for s in cases.steps(con, cid))
    if it.get("over_2pct") and settings()["desk_case_think"] and not done_today:
        s = _x("session")
        if s is not None and hasattr(s, "think_case"):
            try:
                r = s.think_case(con, now, cid, root=root)
                extra = (f" The case was thought through again by the desk: it is {str(r.get('class') or 'unclear').replace('_', ' ')}, now {r.get('state')}." if r.get("ok")
                         else f" The case's own session did not finish ({str(r.get('failed') or r.get('skipped') or 'no answer')[:120]}).")
            except Exception as e:
                extra = f" (the case's own session failed: {type(e).__name__})"
    spent = sum(float(s["cost_rupees"] or 0) for s in cases.steps(con, cid)) - cost_before
    c = cases.get_case(con, cid) or {}
    it = {**it, "facts": it["facts"] + extra + (f" Latest class: {c.get('klass')}." if c.get("klass") else "")}
    return it, max(0.0, spent)


def _find_idea(con, now, it, sid, root, spent, budget) -> tuple:
    """The idea search of one market: code screens, Sonnet shortlists, code makes the cards, Opus names picks or skips, code validates and records. -> (finding, [model rows])."""
    from pflab.lab import screen, tools
    st = settings()
    m = it["market"]
    rows_out: List[dict] = []
    flt = {"exclude_held": True, "exclude_flagged": True}
    res = screen.screen_stocks(con, now, m, flt, "momentum_126", int(st["desk_idea_n"]), root=root, detail="brief")
    rows = res.get("rows") or []
    if it.get("outside_sector"):
        outside = [r for r in rows if str(r.get("sector") or "") != it["outside_sector"]]
        rows = outside + [r for r in rows if r not in outside]
    if not rows:
        return "The screen returned nothing to look at today.", rows_out
    table = json.dumps(rows[: int(st["desk_idea_n"])], default=str)
    n = int(st["desk_idea_cards"])
    _guard_budget(con, now, spent, budget, st["desk_item_cost_guess"])
    r1 = _call(con, "read", SHORTLIST_SYSTEM.format(n=n), [{"role": "user", "content": it["facts"] + "\n\nSCREEN ROWS:\n" + table}], purpose="desk idea shortlist", now=now, max_tokens=500, schema=SHORTLIST_SCHEMA)
    rows_out.append(_model_row(r1))
    j1 = _json(r1)
    wanted = [str(s).upper() for s in (j1.get("symbols") or [])][:n]
    known = {str(r.get("symbol")).upper() for r in rows}
    wanted = [s for s in wanted if s in known]
    if not wanted:
        return "Nothing on the screen was worth a closer look: " + _clean(j1.get("why"), table, "no reason given") , rows_out
    cards, rtexts = [], []
    ctx = tools.make_ctx(con, None, root, now, 0)
    for sym in wanted:
        try:
            cards.append(json.dumps(screen.fit_card(screen.company_card(con, now, m, sym, root=root), 3500), default=str))
        except Exception as e:
            cards.append(f"{sym}: card unavailable ({type(e).__name__})")
        rt, items = _recall_text(con, now, {"symbol": sym})
        rtexts.append(f"{sym}: {rt}" if rt else "")
    facts = it["facts"] + "\n\nCOMPANY CARDS:\n" + "\n".join(cards) + ("\n\nWHAT WE ALREADY KNOW:\n" + "\n".join(t for t in rtexts if t) if any(rtexts) else "")
    facts += "\n\nPICKS SCORE:\n" + scorecard_text(con, now.date())
    _guard_budget(con, now, spent + sum(r["cost"] for r in rows_out), budget, st["desk_decide_cost_guess"])
    r2 = _call(con, "decide", PICK_SYSTEM, [{"role": "user", "content": facts}], purpose="desk idea decision", now=now, max_tokens=1500, schema=PICK_SCHEMA)
    rows_out.append(_model_row(r2))
    j2 = _json(r2)
    ctx.session_id = f"desk {now:%Y-%m-%d}"
    done = []
    picks_in = [p for p in (j2.get("picks") or []) if isinstance(p, dict) and str(p.get("symbol") or "").upper() in {w for w in wanted}]
    if picks_in:
        out, err = tools.run(ctx, "propose_picks", {"market": m, "items": [{"symbol": str(p["symbol"]), "thesis": str(p.get("thesis") or ""), "break_condition": str(p.get("break_condition") or ""),
                                                                           "storylines": [x for x in (p.get("storylines") or []) if isinstance(x, int)]} for p in picks_in],
                                                     "learned_from": str(j2.get("learned_from") or "")})
        o = json.loads(out)
        acc = [a.get("symbol") for a in (o.get("accepted") or [])]
        done.append(f"named {', '.join(acc)}" if acc else "no pick accepted: " + _cut(o.get("problem") or "", 200))
    for s in (j2.get("skips") or []):
        if isinstance(s, dict) and str(s.get("symbol") or "").upper() in set(wanted):
            out, err = tools.run(ctx, "skip_idea", {"market": m, "symbol": str(s["symbol"]), "why": str(s.get("why") or "")})
            if not err:
                done.append(f"skipped {s['symbol']}")
    return ("Looked at " + ", ".join(wanted) + ". " + ("; ".join(done) if done else "named nobody and skipped nobody.")), rows_out


def _withdrawal(con, now, it, recall_text, root) -> tuple:
    from pflab.lab import tools
    pick = it.get("pick") or {}
    facts = it["facts"] + ("\n\nWHAT WE ALREADY KNOW:\n" + recall_text if recall_text else "")
    res = _call(con, "decide", WITHDRAW_SYSTEM, [{"role": "user", "content": facts}], purpose="desk withdrawal", now=now, max_tokens=600, schema=WITHDRAW_SCHEMA)
    row = _model_row(res)
    j = _json(res)
    if str(j.get("action")) == "withdraw" and pick.get("symbol"):
        ctx = tools.make_ctx(con, None, root, now, 0)
        ctx.session_id = f"desk {now:%Y-%m-%d}"
        reason = _clean(j.get("reason"), facts, "the thesis is broken by an event the desk read")
        out, err = tools.run(ctx, "withdraw_pick", {"market": pick.get("market") or it.get("market"), "symbol": pick["symbol"], "reason": reason if len(reason) >= 20 else reason + " (the desk read the event)"})
        o = json.loads(out)
        return ("withdrew " + str(pick["symbol"]) if o.get("ok") else "withdrawal refused: " + _cut(o.get("problem") or "", 200)), row
    return "kept the pick: " + _clean(j.get("reason"), facts, "the event does not break the thesis"), row


def run_desk(con, now: datetime, mode: str, *, root=None, covers: Optional[str] = None) -> dict:
    """One desk session. -> {session_id, mode, status (done | quiet | budget | failed | skipped), cost_rupees, items, plan, ...}. Never raises."""
    if mode not in MODES:
        return {"skipped": f"unknown mode {mode!r}"}
    if not on():
        return {"skipped": "the desk is switched off (the kill switch, [think] on or the desk's own switch)"}
    day = now.date()
    covers = covers or ("us_morning,india_close" if mode == "catchup" else mode)
    if all(_slot_done(con, day, s) for s in covers.split(",")):
        return {"skipped": f"the {mode} session of {day} already ran"}
    t0 = since(con, now)
    sid = _id(con, "desk_sessions_s84", "session_id")
    bs = budget_status(con, day, now)
    con.execute("INSERT INTO desk_sessions_s84 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [sid, day, mode, covers, now, None, t0, "running", 0.0, bs["budget"], "[]", "", ""])
    try:
        items = agenda(con, now, mode)
    except Exception as e:
        con.execute("UPDATE desk_sessions_s84 SET status='failed', finished_at=?, note=? WHERE session_id=?", [now, f"agenda failed: {type(e).__name__}: {str(e)[:200]}", sid])
        return {"session_id": sid, "mode": mode, "status": "failed", "error": str(e)[:200]}
    if not items:                                                                    # a day with nothing changed: a two-line note, not a session, no cost
        plan = (f"A quiet day: nothing changed since {t0:%d %b %H:%M} (no case look due, no news or move on a holding, nothing scored, no storyline moved, no room for a new idea).\n"
                "The desk sits down again after the next close.")
        con.execute("UPDATE desk_sessions_s84 SET status='quiet', finished_at=?, plan_text=?, note='nothing changed' WHERE session_id=?", [now, plan, sid])
        return {"session_id": sid, "mode": mode, "status": "quiet", "cost_rupees": 0.0, "items": 0, "plan": plan}
    con.execute("UPDATE desk_sessions_s84 SET agenda_json=? WHERE session_id=?", [json.dumps([{k: v for k, v in i.items() if k in ("rank", "kind", "ref", "title", "why")} for i in items]), sid])
    spent, status, results, stopped, halt = 0.0, "done", [], None, False
    for it in items:
        if halt:
            _step(con, sid, it, now, "not_reached", f"not reached: {stopped}")
            results.append((it, "not_reached", ""))
            continue
        try:
            _guard_budget(con, now, spent, bs["budget"], 0.0)
        except _Stop as s:
            status, stopped = "budget", str(s)
            _step(con, sid, it, now, "not_reached", f"not reached: {s}")
            results.append((it, "not_reached", ""))
            continue
        try:
            fin, st_name, cost = _work_item(con, now, sid, it, spent, bs["budget"], root)
            spent += cost
            results.append((it, st_name, fin))
        except _Stop as s:
            status, stopped = "budget", str(s)
            _step(con, sid, it, now, "not_reached", f"not reached: {s}")
            results.append((it, "not_reached", ""))
        except Exception as e:                                                       # a failed model call is recorded; the rest of the agenda goes on
            why = _refusal(e)
            _step(con, sid, it, now, "failed", why or f"{type(e).__name__}: {str(e)[:200]}")
            results.append((it, "failed", f"could not be worked: {why or type(e).__name__}"))
            if why:                                                                  # the cap, the governor or the egress gate said no: the rest waits for the next session
                status, stopped = "budget", why
                halt = True
    if status == "done" and spent >= bs["budget"] > 0:
        status, stopped = "budget", "the day's desk budget is used"
    plan = _plan(con, now, items, results, stopped)
    con.execute("UPDATE desk_sessions_s84 SET status=?, finished_at=?, cost_rupees=?, plan_text=?, note=? WHERE session_id=?", [status, now, spent, plan, stopped or "", sid])
    return {"session_id": sid, "mode": mode, "status": status, "cost_rupees": round(spent, 2), "items": len(items), "worked": sum(1 for r in results if r[1] in ("done", "noted", "used")),
            "plan": plan, "stopped": stopped}


def _work_item(con, now, sid, it, spent: float, budget: float, root) -> tuple:
    """-> (finding, status, cost). Raises _Stop when the budget or the cap ends the work."""
    st = settings()
    rt, ritems = _recall_text(con, now, it) if it["kind"] in ("holding", "case") else ("", [])
    cost, rows, finding, status = 0.0, [], "", "done"
    fresh = None
    rc = _x("recall")
    if it["kind"] == "holding" and not it.get("has_events") and rc is not None:
        try:
            fresh = rc.same_subject_fresh(con, now, isin=it.get("isin"))      # never pay twice: a fresh note on an unchanged subject is USED
        except Exception:
            fresh = None
    if fresh:
        finding, status = f"used the note already held ({fresh.get('title') or fresh.get('id')}, {fresh.get('day')}): nothing new since it was written.", "used"
        stid = _step(con, sid, it, now, status, finding)
        _mark(con, now, [fresh], stid)
        return finding, status, 0.0
    if it["kind"] == "idea":
        finding, rows = _find_idea(con, now, it, sid, root, spent, budget)
        cost = sum(r["cost"] for r in rows)
        stid = _step(con, sid, it, now, "done", finding, {**rows[-1], "cost": cost} if rows else None)
        _write_back(con, now, it, finding, cost)
        return finding, "done", cost
    if it["kind"] == "case":
        it, case_cost = _work_case(con, now, it, sid, root)
        cost += case_cost
    if it["model"] == "read":
        _guard_budget(con, now, spent + cost, budget, st["desk_item_cost_guess"])
        ans, row, facts = _read(con, now, it, rt, case_id=it.get("case_id"))
        cost += row["cost"]
        finding = _clean(ans.get("finding"), facts, _cut(it["facts"], 220))
        nxt = _clean(ans.get("next_step"), facts, "")
        it["next_step"] = nxt
        nd = str(ans.get("needs_decision") or "none")
        stid = _step(con, sid, it, now, "done", finding + (f" Next: {nxt}" if nxt else ""), row)
        _mark(con, now, ritems, stid)
        if it["kind"] == "holding" and nd == "withdrawal" and it.get("pick") and it.get("has_events"):
            _guard_budget(con, now, spent + cost, budget, st["desk_decide_cost_guess"])
            res, row2 = _withdrawal(con, now, it, rt, root)
            cost += row2["cost"]
            finding += " Decision: " + res
            _step(con, sid, {**it, "kind": "withdrawal", "ref": it["ref"] + ":w"}, now, "done", res, row2)
        _write_back(con, now, it, finding, cost)
    return finding, status, cost


def _mark(con, now: datetime, items: list, stid: int) -> None:
    r = _x("recall")
    try:
        if r is not None and items:
            r.mark_used(con, items, by_kind="desk", by_ref=str(stid), day=now.date())
    except Exception:
        pass


def _write_back(con, now: datetime, it: dict, finding: str, cost: float) -> None:
    r = _x("recall")
    if r is None or not finding or it["kind"] not in ("holding", "idea", "case"):
        return
    try:
        r.write_back(con, now, isin=it.get("isin"), symbol=it.get("symbol"), topic=None if it.get("isin") or it.get("symbol") else it["kind"], title=f"desk {now:%Y-%m-%d}: {it['title']}"[:200],
                     text=finding, source="desk", cost_rupees=cost, case_id=it.get("case_id"))
    except Exception:
        pass


# --- the plan, the lines the reports show -------------------------------------------------------------------------------------------------------------------------------------------

def _plan(con, now: datetime, items: list, results: list, stopped: Optional[str]) -> str:
    lines = [f"Desk, {now:%d %b}: {sum(1 for r in results if r[1] in ('done', 'noted', 'used'))} of {len(items)} agenda item(s) worked."]
    for it, stt, fin in results[:6]:
        lines.append(f"- {it['title']}: {_cut(fin, 170) if stt != 'not_reached' else 'not reached (the budget)'}")
    nexts = [it.get("next_step") for it, _, _ in results if it.get("next_step")]
    nxt = ["Next session: " + (" ".join(nexts[:2]) if nexts else "the same agenda, from what changes.")]
    try:
        from pflab.think import cases
        due = [c for c in cases.open_cases(con) if c.get("next_look_on")]
        if due:
            nxt.append("Looks due: " + ", ".join(f"{c.get('symbol') or c['title']} on {c.get('next_look_on_s') or c['next_look_on']}" for c in due[:4]) + ".")
    except Exception:
        pass
    if stopped:
        nxt.append(f"(Stopped early: {stopped}; the rest waits for the next session.)")
    return "\n".join(lines + nxt)


def plan_text(con, day: Optional[date] = None) -> str:
    """The desk's latest note for Today and the 15:45 report: the plan of the last session on or before `day`."""
    day = day or date.today()
    r = con.execute("SELECT plan_text, mode, status FROM desk_sessions_s84 WHERE day <= ? AND status IN ('done','quiet','budget') ORDER BY started_at DESC, session_id DESC LIMIT 1", [day]).fetchone()
    text = r[0] if r and r[0] else "The desk has not sat down yet."
    try:                                                                      # S85 E7: notes he sent about the whole market or a sector go into the pre-open plan
        from pflab.think import chat_hooks
        extra = chat_hooks.preopen_text(con, day)
        if extra:
            text = f"{text}\n{extra}"
    except Exception:
        pass
    return text


def cost_line(con, now: Optional[datetime] = None) -> str:
    """Rupees spent on thinking this month per decision that beat doing nothing (desk + cases), in plain words."""
    now = now or datetime.now()
    start = datetime(now.year, now.month, 1)
    spent = float(con.execute("SELECT coalesce(sum(cost_rupees),0) FROM desk_steps_s84 WHERE step_at >= ?", [start]).fetchone()[0])
    try:
        spent += float(con.execute("SELECT coalesce(sum(cost_rupees),0) FROM think_steps_s84 WHERE step_at >= ?", [start]).fetchone()[0])
    except Exception:
        pass
    scored = con.execute("SELECT count(DISTINCT decision_id) FROM think_scores_s84").fetchone()[0]
    beat = con.execute("SELECT count(DISTINCT decision_id) FROM think_scores_s84 WHERE track='rule' AND vs_nothing_inr > 0").fetchone()[0]
    if not scored:
        return f"Thinking cost Rs {spent:,.0f} this month; no decision has been scored yet, so there is no cost per good decision yet."
    if not beat:
        return f"Thinking cost Rs {spent:,.0f} this month; none of {scored} scored decision(s) has beaten doing nothing yet."
    return f"Thinking cost Rs {spent:,.0f} this month: about Rs {spent / beat:,.0f} for each of the {beat} decision(s) that beat doing nothing (of {scored} scored)."


def sessions(con, limit: int = 10) -> List[dict]:
    """The desk's recent sessions, JSON-able (for a screen)."""
    cols = ("session_id", "day", "mode", "covers", "status", "cost_rupees", "budget_rupees", "plan_text", "note")
    return [{**dict(zip(cols, r)), "day": str(r[1])} for r in con.execute(f"SELECT {', '.join(cols)} FROM desk_sessions_s84 ORDER BY session_id DESC LIMIT ?", [limit]).fetchall()]


def steps(con, session_id: int) -> List[dict]:
    cols = ("step_id", "ord", "kind", "ref", "market", "symbol", "engine", "model", "thinking", "cost_rupees", "cached_tokens", "status", "finding")
    return [dict(zip(cols, r)) for r in con.execute(f"SELECT {', '.join(cols)} FROM desk_steps_s84 WHERE session_id=? ORDER BY step_id", [session_id]).fetchall()]


def tick_hook(con, now: datetime, root=None) -> dict:
    """What `strategist.tick` calls: the desk sits down when a slot is open (the agenda decides whether it is a session or a two-line note). Never raises; costs nothing when off or quiet."""
    try:
        if not on():
            return {"off": True}
        try:                                                                  # S85 E7: names he suggested beyond the day's 5 are taken up by the next desk
            from pflab.think import chat_hooks
            chat_hooks.run_queued_suggestions(con, now, root=root)
        except Exception:
            pass
        m = mode_for(con, now)
        if not m:
            return {"nothing_open": True}
        return run_desk(con, now, m[0], root=root, covers=m[1])
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:200]}"}
