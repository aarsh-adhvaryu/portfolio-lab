"""The picks sleeve's share follows its live record (S83 L5, A61; the registered rule, code and no model).

Protocol: `docs/protocols/s83_picks_live_protocol.md` (committed before the first pick; `tests/test_s83_picks.py` pins `RULE` below to the protocol's JSON block and to `configs/core.toml`).

    India   the `longterm` sleeve starts at 40% of the India part (the rupee book); every 60 sessions, once 60 sessions of record exist: its return after estimated tax against the Nifty 500
            over the last 120 sessions (or all there is): ahead -> +5 points (at most 60), behind by more than 2 points a year -> -5 points (at least 20), otherwise unchanged.
    US      the picks' share of the sub-book starts at 50%, the same steps between 30% and 70% (SPY keeps at least 30%), against SPY in rupees.
    a shrink means no new picks until the next judgment and the money from sales goes to the core; nothing is ever sold to reach a share.

Every judgment is one dated row in `sleeve_share_s83` with its figures (a "level" judgment has old = new). The record comes from `core/pick_score.sleeve_record(con, market, day)`
(the score agent's module: absent or failing = no change, "not enough record").

    settings(market)               the picks settings for a market (the nested `[picks.in]` / `[picks.us]` tables over `[picks]`), `on` = both switches
    share(con, market)             {"share", "start", "source", "min", "max", "shrinking", "judged_on"}
    judge(con, now, market, day)   apply the rule once if it is due; returns what it did (never raises for a missing input)
    status(con, market)            the share, the last judgment, how many sessions to the next one, the record's figures
    report_line(con, day)          a plain sentence for the 15:45 report when a judgment MOVED a share that day, else None
"""
from __future__ import annotations

import copy
import inspect
import json
from datetime import date, datetime
from typing import Callable, Optional

MARKETS = ("IN", "US")
RULE = {
    "IN": {"start_share": 0.40, "min_share": 0.20, "max_share": 0.60, "step": 0.05},
    "US": {"start_share": 0.50, "min_share": 0.30, "max_share": 0.70, "step": 0.05, "spy_floor": 0.30},
    "judge_every_sessions": 60,
    "min_sessions_of_record": 60,
    "window_sessions": 120,
    "behind_points_a_year": 2.0,
    "min_system_picks_bought": 1,
}
# Amendment A1 (his decision 2026-11-12, F1/A64): once, at the S84 release, India's share becomes his Kite stocks' weight plus `extra_points` (at most the maximum, never lower than it was):
# `extra_points` = `ordinary_points` for the system's ordinary picks + `reserve_points` for the opportunity reserve. The range, the steps and the judgment rule above stay.
# Pinned to the protocol's second JSON block (`json amendment_a1`) by tests/test_s84_fixa.py.
RULE_A1 = {"decided": "2026-11-12", "market": "IN", "extra_points": 20.0, "ordinary_points": 10.0, "reserve_points": 10.0, "max_share": 0.60}
DECISION_REASON = "his decision 2026-11-12"
NAMES = {"IN": "India", "US": "US"}
AGAINST = {"IN": "the Nifty 500", "US": "SPY in rupees"}
BOUGHT_STATES = ("buying", "held", "withdrawn", "stopped", "broken")


# --- settings ------------------------------------------------------------------------------------------------------------------------

def settings(market: Optional[str] = None) -> dict:
    """`[picks]` of configs/core.toml over the defaults in `core/__init__.py` (the nested market tables are merged key by key). With a market: the flat dict for it (`on` is true only when
    the market's own switch and `[picks] on` are both true)."""
    from pflab import core
    out = copy.deepcopy(core.DEFAULTS["picks"])
    try:
        from pflab import _toml
        raw = _toml.load(core.CONFIG).get("picks") or {}
        for k, v in raw.items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k].update(v)
            else:
                out[k] = v
    except Exception:
        pass
    if market is None:
        return out
    mk = {"IN": "in", "US": "us"}[market]
    flat = {k: v for k, v in out.items() if not isinstance(v, dict)}
    flat.update(out.get(mk) or {})
    flat["on"] = bool(out.get("on", True)) and bool((out.get(mk) or {}).get("on", True)) and core.on()
    return flat


def on(market: str) -> bool:
    return bool(settings(market)["on"])


# --- the share ------------------------------------------------------------------------------------------------------------------------

def _last_row(con, market: str) -> Optional[tuple]:
    return con.execute("SELECT change_id, decided_on, old_share, new_share, reason, figures_json FROM sleeve_share_s83 WHERE market=? ORDER BY decided_on DESC, change_id DESC LIMIT 1",
                       [market]).fetchone()


def share(con, market: str = "IN") -> dict:
    """The picks sleeve's share now: the starting share until a judgment has moved it, then the last judgment's. `shrinking`: the last judgment lowered it (no new picks until the next)."""
    c = settings(market)
    start = float(c["start_share"])
    r = _last_row(con, market)
    if r is None:
        return {"share": start, "start": start, "source": "the starting share (no judgment yet)", "min": float(c["min_share"]), "max": float(c["max_share"]), "shrinking": False, "judged_on": None}
    return {"share": float(r[3]), "start": start, "source": f"judged on {r[1]}: {r[4]}", "min": float(c["min_share"]), "max": float(c["max_share"]),
            "shrinking": float(r[3]) < float(r[2]) - 1e-9, "judged_on": str(r[1])}


def decision_done(con, market: str = "IN") -> bool:
    """Has the one-time start of 2026-11-12 (F1) been written for the market?"""
    try:
        return bool(con.execute("SELECT 1 FROM sleeve_share_s83 WHERE market=? AND reason LIKE ?", [market, DECISION_REASON + "%"]).fetchone())
    except Exception:
        return False


def set_start_by_decision(con, now: datetime) -> dict:
    """F1 (his decision 2026-11-12), once: India's share = his Kite stocks' weight in the India part + 20 points, at most the 60% maximum and never lower than it is now; written as one dated
    row in `sleeve_share_s83` whose reason starts "his decision 2026-11-12". Idempotent by that reason. His Kite stocks are adopted first; with none held yet (nothing to weigh) it writes
    nothing and says "waiting". Never raises; the range, the steps and the judgment rule are untouched. Called at the app's start (`app/runtime.py`)."""
    try:
        from pflab.core import picks
        from pflab.pm.store import next_id
        market = "IN"
        if not on(market):
            return {"done": False, "why": "the India picks are switched off"}
        if decision_done(con, market):
            return {"done": False, "why": "already done"}
        picks.adopt_kite_holdings(con, now)
        day = now.date()
        wts, _sectors = picks._weights(con, market, day)
        kite = [p for p in picks.managed(con, market) if p["source"] == "kite"]
        kite_w = sum(max(0.0, wts.get(p["isin"], 0.0)) for p in kite)
        if kite_w <= 1e-9:
            return {"done": False, "why": "waiting: no Kite stock of his is held in the book yet, so there is nothing to weigh"}
        c = settings(market)
        cur = share(con, market)["share"]
        extra = float(RULE_A1["extra_points"]) / 100.0
        new = round(max(cur, min(float(c["max_share"]), kite_w + extra)), 4)
        why = (f"{DECISION_REASON}: his Kite stocks hold {kite_w:.1%} of the India part; room for the system's own picks worth {RULE_A1['extra_points']:g} points on top "
               f"({RULE_A1['ordinary_points']:g} for ordinary picks, {RULE_A1['reserve_points']:g} an opportunity reserve in cash), at most {float(c['max_share']):.0%}: the share is {new:.1%} (was {cur:.0%})")
        figs = {"kind": "decision", "kite_weight": round(kite_w, 5), "extra_points": RULE_A1["extra_points"], "reserve_points": RULE_A1["reserve_points"], "max_share": float(c["max_share"])}
        cid = next_id(con, "sleeve_share_s83", "change_id")
        con.execute("INSERT INTO sleeve_share_s83 (change_id, market, decided_on, old_share, new_share, reason, figures_json) VALUES (?,?,?,?,?,?,?)",
                    [cid, market, day, float(cur), float(new), why, json.dumps(figs)])
        return {"done": True, "change_id": cid, "old": cur, "new": new, "kite_weight": kite_w, "reason": why}
    except Exception as e:
        return {"done": False, "why": f"{type(e).__name__}: {str(e)[:160]}"}


def system_picks_bought(con, market: str) -> int:
    try:
        return int(con.execute("SELECT count(*) FROM picks_s83 WHERE market=? AND source='system' AND state IN (%s)" % ",".join("?" for _ in BOUGHT_STATES), [market, *BOUGHT_STATES]).fetchone()[0])
    except Exception:
        return 0


def _record(con, market: str, day: date, window: int, record_fn: Optional[Callable]) -> Optional[dict]:
    """The sleeve's record from the score agent's module (asked for `window` sessions when it takes the argument); None when it is absent or fails."""
    fn = record_fn
    if fn is None:
        try:
            from pflab.core import pick_score
            fn = pick_score.sleeve_record
        except Exception:
            return None
    try:
        kw = {"window": window} if "window" in inspect.signature(fn).parameters else {}
        r = fn(con, market, day, **kw)
    except Exception:
        return None
    if not isinstance(r, dict) or not r.get("sessions"):
        return None
    out = dict(r)
    if out.get("points_a_year") is None and out.get("sleeve_return_after_tax") is not None and out.get("index_return") is not None:
        n = max(1, min(int(out["sessions"]), int(window)))
        out["points_a_year"] = (float(out["sleeve_return_after_tax"]) - float(out["index_return"])) * 100.0 * 252.0 / n
    return out


def _decide(cur: float, pts: float, c: dict) -> tuple:
    """The rule: ahead (above zero) +step, behind by more than `behind_points` -step, else level. -> (new share, word)."""
    step, lo, hi = float(c["step"]), float(c["min_share"]), float(c["max_share"])
    if pts > 0:
        return round(min(hi, cur + step), 4), "ahead"
    if pts < -float(c["behind_points"]):
        return round(max(lo, cur - step), 4), "behind"
    return cur, "level"


def judge(con, now: datetime, market: str, day: date, record_fn: Optional[Callable] = None) -> dict:
    """Apply the rule once if it is due (60 sessions of record and at least one system pick bought, then every `judge_every_sessions` further sessions). One dated row is written for each
    judgment, the share moved or not. Idempotent: a second call on the same record writes nothing."""
    from pflab.pm.store import next_id
    c = settings(market)
    if not c["on"]:
        return {"judged": False, "why": f"the {NAMES[market]} picks are switched off"}
    rec = _record(con, market, day, int(c["window_sessions"]), record_fn)
    if rec is None:
        return {"judged": False, "why": "not enough record: the sleeve's record is not available yet"}
    sessions = int(rec["sessions"])
    if sessions < int(RULE["min_sessions_of_record"]):
        return {"judged": False, "why": f"not enough record: {sessions} of {RULE['min_sessions_of_record']} sessions"}
    if system_picks_bought(con, market) < int(RULE["min_system_picks_bought"]):
        return {"judged": False, "why": "no pick of the system has been bought yet: the record is his Kite stocks alone"}
    last = _last_row(con, market)
    if last is not None:
        seen = int((json.loads(last[5] or "{}")).get("sessions") or 0)
        if sessions < seen + int(c["judge_every_sessions"]):
            return {"judged": False, "why": f"next judgment at {seen + int(c['judge_every_sessions'])} sessions of record ({sessions} now)"}
    cur = share(con, market)["share"]
    pts = rec.get("points_a_year")
    if pts is None:
        return {"judged": False, "why": "not enough record: the record has no figure against the index"}
    pts = float(pts)
    new, word = _decide(cur, pts, c)
    against = AGAINST[market]
    figs = {"sessions": sessions, "window_sessions": int(c["window_sessions"]), "points_a_year": round(pts, 3), "sleeve_return_after_tax": rec.get("sleeve_return_after_tax"),
            "index_return": rec.get("index_return"), "worst_fall_sleeve": rec.get("worst_fall_sleeve"), "worst_fall_index": rec.get("worst_fall_index"), "result": word,
            "behind_points": float(c["behind_points"]), "step": float(c["step"])}
    if word == "level":
        why = f"level with {against} ({pts:+.1f} points a year over the last {min(sessions, int(c['window_sessions']))} sessions): the share stays at {cur:.0%}"
    elif new == cur:
        why = f"{word} {against} ({pts:+.1f} points a year) but the share is already at its {'maximum' if word == 'ahead' else 'minimum'} of {cur:.0%}"
    elif word == "ahead":
        why = f"ahead of {against} ({pts:+.1f} points a year over the last {min(sessions, int(c['window_sessions']))} sessions): the share rises from {cur:.0%} to {new:.0%}"
    else:
        why = (f"behind {against} ({pts:+.1f} points a year over the last {min(sessions, int(c['window_sessions']))} sessions): the share falls from {cur:.0%} to {new:.0%}; "
               f"no new picks until the next judgment, nothing is sold to reach it, sale money goes to the core")
    cid = next_id(con, "sleeve_share_s83", "change_id")
    con.execute("INSERT INTO sleeve_share_s83 (change_id, market, decided_on, old_share, new_share, reason, figures_json) VALUES (?,?,?,?,?,?,?)",
                [cid, market, day, float(cur), float(new), why, json.dumps(figs, default=str)])
    return {"judged": True, "change_id": cid, "old": cur, "new": new, "result": word, "reason": why}


def status(con, market: str = "IN") -> dict:
    """Everything a screen or the card needs about the share (JSON-able)."""
    c = settings(market)
    s = share(con, market)
    r = _last_row(con, market)
    last = None if r is None else {"decided_on": str(r[1]), "old": float(r[2]), "new": float(r[3]), "reason": r[4], "figures": json.loads(r[5] or "{}")}
    seen = int((last or {}).get("figures", {}).get("sessions") or 0) if last else 0
    nxt = (seen + int(c["judge_every_sessions"])) if last else int(RULE["min_sessions_of_record"])
    return {"market": market, "on": bool(c["on"]), **s, "last_judgment": last, "next_judgment_at_sessions": nxt, "judged_every_sessions": int(c["judge_every_sessions"]),
            "system_picks_bought": system_picks_bought(con, market), "no_new_picks": bool(s["shrinking"])}


def report_line(con, day: date) -> Optional[str]:
    """A plain sentence for the 15:45 report of session `day` when a judgment moved a share at that close or at the one before it (the judgment is made by the evening close loop, so the
    next day's report tells it), both markets joined; None when nothing moved."""
    try:
        from pflab import markets
        since = markets.get("IN").previous_session(day)
    except Exception:
        since = day
    out = []
    for r in con.execute("SELECT market, old_share, new_share, reason FROM sleeve_share_s83 WHERE decided_on >= ? AND decided_on <= ? AND abs(new_share - old_share) > 1e-9 ORDER BY change_id", [since, day]).fetchall():
        name = NAMES.get(r[0], r[0])
        out.append(f"{name} picks share {'raised' if r[2] > r[1] else 'lowered'} from {r[1]:.0%} to {r[2]:.0%}: {r[3]}.")
    return " ".join(out) if out else None
