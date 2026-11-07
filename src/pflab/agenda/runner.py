"""Doing the agenda: `tick(rt, now)` is what the app's idle loop calls. It refills the agenda when it is empty, and does one item unless something urgent is open.

Every act is recorded (start, outcome, useful, effect), the kind's yield is recomputed, and `paper.cadence.act` is told (loop "agenda") so silence detection sees it.
Nothing here raises: a worker that fails leaves a 'failed' row.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Optional

from pflab.agenda import items, kinds, picker

REFILL_EVERY = timedelta(minutes=15)
_LOCK = threading.Lock()
_LAST_REFILL: Dict[tuple, datetime] = {}


def _markets(now: datetime, mode: Optional[str]) -> Dict[str, str]:
    """{market: mode} for every market; a given `mode` applies to all (the primary market alone when markets cannot be read)."""
    try:
        from pflab import markets
        ms = markets.modes(now)
        return {m: (mode or md) for m, md in ms.items()}
    except Exception:
        return {"IN": mode or "deep"}


def refill(con, market: str, now: datetime) -> Dict[str, int]:
    """Ask every kind's producer for candidates and queue them (deduplicated by kind + subject + day); {kind: added}."""
    return kinds.produce(con, market, now)


def _needs_refill(rt, con, market: str, now: datetime) -> bool:
    if items.queued(con, market):
        return False
    key = (str(getattr(rt, "pm_dir", "")), market)
    last = _LAST_REFILL.get(key)
    return last is None or now - last >= REFILL_EVERY


def _cadence(con, now: datetime, what: str, useful: bool, detail: dict) -> None:
    try:
        from pflab.paper import cadence
        cadence.act(con, now, "agenda", what, useful, detail)
    except Exception:
        pass                                     # the paper tables may not exist yet; the agenda never depends on them


def _valid_effect(effect: str) -> bool:
    return effect.split(":", 1)[0].strip() in items.EFFECTS


def work_one(rt, now: datetime, mode: Optional[str] = None) -> dict:
    """Do the best eligible item of any market, unless urgent work is open. Never raises."""
    con = rt.cursor()
    try:
        if picker.urgent_pending(con):
            return {"state": "urgent", "why": "urgent work (a mission's task or an order of his) is open: the agenda waits"}
        items.sweep_interrupted(con, now)
        best = None
        for market, md in _markets(now, mode).items():
            it = picker.next_item(con, market, md, now)
            if it and (best is None or it["score"] > best["score"]):
                best = {**it, "mode": md}
        if best is None:
            return {"state": "idle", "why": "nothing eligible on the agenda in this mode"}
        iid, kind, market = best["item_id"], best["kind"], best["market"]
        items.start(con, iid, now)
        t0 = time.monotonic()
        res: dict = {}
        try:
            k = kinds.REGISTRY.get(kind)
            if k is None:
                raise LookupError(f"kind {kind!r} is not registered")
            res = k.worker(rt, best, now) or {}
        except Exception as e:
            msg = f"{type(e).__name__}: {str(e)[:300]}"
            items.fail(con, iid, now, msg)
            items.refresh_stats(con, market, kind, now)
            _cadence(con, now, f"agenda: {kind} {best['subject']} failed", False, {"item": iid, "error": msg})
            return {"state": "failed", "item_id": iid, "kind": kind, "subject": best["subject"], "error": msg, "seconds": round(time.monotonic() - t0, 2)}
        if res.get("skip"):
            items.skip(con, iid, now, str(res["skip"]))
            _cadence(con, now, f"agenda: {kind} {best['subject']} skipped: {res['skip']}"[:300], False, {"item": iid})
            return {"state": "skipped", "item_id": iid, "kind": kind, "subject": best["subject"], "why": str(res["skip"])}
        effect, outcome = str(res.get("effect") or ""), str(res.get("outcome") or "")
        useful = bool(res.get("useful"))
        if useful and not _valid_effect(effect):             # useful means a belief, a forecast weight or a decision changed, or he was answered: name which
            useful, outcome = False, (outcome + " (marked useful without naming what it changed: counted as not useful)").strip()
        items.finish(con, iid, now, outcome, useful, effect if useful else "")
        stats = items.refresh_stats(con, market, kind, now)
        _cadence(con, now, f"agenda: {kind} {best['subject']}: {outcome}"[:300], useful, {"item": iid, "effect": effect, "yield": stats["yield"]})
        try:
            rt.bump("agenda")
        except Exception:
            pass
        return {"state": "done", "item_id": iid, "kind": kind, "subject": best["subject"], "useful": useful, "effect": effect if useful else "", "outcome": outcome,
                "seconds": round(time.monotonic() - t0, 2), "multiplier": stats["multiplier"]}
    except Exception as e:                                   # the loop that calls this must never die of it
        return {"state": "error", "error": f"{type(e).__name__}: {str(e)[:200]}"}


def tick(rt, now: Optional[datetime] = None, mode: Optional[str] = None) -> dict:
    """Refill what is empty, then do one item. Safe to call from the idle loop at any rate; a call while another is running returns {"state": "busy"}."""
    now = now or rt.clock()
    if not _LOCK.acquire(blocking=False):
        return {"state": "busy"}
    try:
        con = rt.cursor()
        added: Dict[str, Dict[str, int]] = {}
        try:
            for market in _markets(now, mode):
                if _needs_refill(rt, con, market, now):
                    _LAST_REFILL[(str(getattr(rt, "pm_dir", "")), market)] = now
                    added[market] = refill(con, market, now)
        except Exception:
            pass
        out = work_one(rt, now, mode)
        if added:
            out["refilled"] = {m: sum(v.values()) for m, v in added.items()}
        return out
    finally:
        _LOCK.release()


# --- what the screen and the agents see ------------------------------------------------------------------------------------------------

def _plain(it: dict) -> dict:
    keep = ("item_id", "market", "kind", "subject", "reason", "expected_value", "cost_rupees", "cost_seconds", "state", "outcome", "useful", "effect", "skip_reason",
            "score", "multiplier", "held")
    d = {k: it[k] for k in keep if k in it}
    for k in ("created_at", "started_at", "finished_at"):
        if it.get(k):
            d[k] = str(it[k])[:19]
    return d


def snapshot(con, now: Optional[datetime] = None, market: Optional[str] = None) -> dict:
    """{available, mode, urgent, running, recent_done (10), recent_skipped (10), queue (head, with score and why), held, kind_yields, counts, useful_today}.
    Never raises: before the table exists it says `available: False`."""
    now = now or datetime.now()
    try:
        mode = _markets(now, None)
        primary = next(iter(mode.items()))
        try:
            from pflab import markets
            primary = markets.primary(now)
        except Exception:
            pass
        run = items.running(con)
        queue, held = [], []
        for m, md in mode.items():
            if market and m != market:
                continue
            ok, hd = picker.candidates(con, m, md, now, mark=False)
            queue += ok
            held += hd
        queue.sort(key=lambda i: (-i["score"], i["item_id"]))
        today = datetime(now.year, now.month, now.day)
        n_useful = int(con.execute("SELECT count(*) FROM mind_agenda WHERE state='done' AND useful AND finished_at >= ?", [today]).fetchone()[0])
        return {"available": True, "market": primary[0], "mode": primary[1], "modes": mode, "urgent": picker.urgent_pending(con),
                "running": _plain(run) if run else None,
                "recent_done": [_plain(i) for i in items.recent(con, "done", 10) if not market or i["market"] == market],
                "recent_skipped": [_plain(i) for i in items.recent(con, "skipped", 10) if not market or i["market"] == market],
                "recent_failed": [_plain(i) for i in items.recent(con, "failed", 5) if not market or i["market"] == market],
                "queue": [_plain(i) for i in queue[:8]], "held": [_plain(i) for i in held[:5]],
                "kind_yields": items.kind_stats(con), "kinds": kinds.names(), "counts": items.counts(con), "useful_today": n_useful}
    except Exception as e:
        return {"available": False, "error": f"{type(e).__name__}: {str(e)[:120]}", "running": None, "recent_done": [], "recent_skipped": [], "recent_failed": [], "queue": [],
                "held": [], "kind_yields": [], "counts": {}}
