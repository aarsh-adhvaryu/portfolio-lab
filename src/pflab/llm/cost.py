"""S79b item 17: what a USEFUL ACT costs, by seat (code only, no model).

A useful act is an agenda item that finished and changed something (`mind_agenda.useful`). For a window of days this view adds up, by seat:

    fast / thinker   local calls from `llm_runs` (a local call costs 0 rupees: no paid energy is metered, so the cost shown is SECONDS of the card and tokens), the seat a
                     call belongs to is read from its model name against the registered picks (llm/seats.py `model_to_seat`); calls whose note is a diag label
                     (truncated, loop, empty, format) are counted as wasted
    cloud            paid calls from `api_calls` (status done): rupees, tokens, seconds from created to finished

and divides each by the number of useful acts in the window: seconds, tokens and rupees PER USEFUL ACT. `by_kind` attributes the calls whose start falls inside an
act's running time to that act's kind (an honest approximation: calls are not tagged with their item; the attributed share is shown so the gap is visible).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional


def _per(x: float, n: int) -> Optional[float]:
    return round(x / n, 3) if n else None


def _seat_rows(con, since: datetime, until: datetime, cfg: Optional[dict], picks: Optional[list]) -> Dict[str, dict]:
    from pflab.llm import seats
    cfg = seats.load_config() if cfg is None else cfg
    picks = seats.load_picks() if picks is None else picks
    out: Dict[str, dict] = {s: {"calls": 0, "failed": 0, "wasted": 0, "seconds": 0.0, "tokens_in": 0, "tokens_out": 0, "rupees": 0.0, "models": {}} for s in ("fast", "thinker", "other")}
    for model, status, note, ti, to, sec in con.execute(
            "SELECT model, status, coalesce(note,''), coalesce(tokens_in,0), coalesce(tokens_out,0), coalesce(seconds,0) FROM llm_runs WHERE started_at >= ? AND started_at < ?",
            [since, until]).fetchall():
        d = out[seats.model_to_seat(model, cfg, picks)]
        d["calls"] += 1
        d["failed"] += 1 if status != "ok" else 0
        d["wasted"] += 1 if (status == "ok" and note and note != "ok") else 0
        d["seconds"] += float(sec)
        d["tokens_in"] += int(ti)
        d["tokens_out"] += int(to)
        d["models"][model] = d["models"].get(model, 0) + 1
    return out


def cost_view(con, market: str = "IN", days: int = 7, now: Optional[datetime] = None, *, cfg: Optional[dict] = None, picks: Optional[list] = None) -> dict:
    """The cost per useful act by seat over the last `days` days (see the module doc). Safe on an empty store."""
    now = now or datetime.now()
    since, until = now - timedelta(days=days), now + timedelta(seconds=1)
    seats_ = _seat_rows(con, since, until, cfg, picks)
    c = con.execute("SELECT count(*), coalesce(sum(cost_inr),0), coalesce(sum(input_tokens),0), coalesce(sum(output_tokens),0), "
                    "coalesce(sum(CASE WHEN finished_at IS NOT NULL THEN epoch(finished_at) - epoch(created_at) ELSE 0 END),0) "
                    "FROM api_calls WHERE status='done' AND created_at >= ? AND created_at < ?", [since, until]).fetchone()
    cloud = {"calls": int(c[0]), "rupees": round(float(c[1]), 2), "tokens_in": int(c[2]), "tokens_out": int(c[3]), "seconds": round(float(c[4]), 1)}
    acts = con.execute("SELECT item_id, kind, started_at, finished_at FROM mind_agenda WHERE market=? AND state='done' AND useful AND finished_at >= ? AND finished_at < ?",
                       [market, since, until]).fetchall()
    n = len(acts)
    by_kind: Dict[str, dict] = {}
    attributed_calls = 0
    for _iid, kind, st, fin in acts:
        k = by_kind.setdefault(kind, {"kind": kind, "useful_acts": 0, "local_calls": 0, "local_seconds": 0.0, "tokens": 0, "cloud_calls": 0, "cloud_rupees": 0.0})
        k["useful_acts"] += 1
        if st is None or fin is None:
            continue
        r = con.execute("SELECT count(*), coalesce(sum(seconds),0), coalesce(sum(coalesce(tokens_in,0)+coalesce(tokens_out,0)),0) FROM llm_runs WHERE started_at >= ? AND started_at <= ?",
                        [st, fin]).fetchone()
        k["local_calls"] += int(r[0])
        k["local_seconds"] += float(r[1])
        k["tokens"] += int(r[2])
        attributed_calls += int(r[0])
        a = con.execute("SELECT count(*), coalesce(sum(cost_inr),0) FROM api_calls WHERE status='done' AND created_at >= ? AND created_at <= ?", [st, fin]).fetchone()
        k["cloud_calls"] += int(a[0])
        k["cloud_rupees"] += float(a[1])
    seat_out = {}
    for s in ("fast", "thinker", "other"):
        d = seats_[s]
        if s == "other" and not d["calls"]:
            continue
        seat_out[s] = {**{k: (round(v, 1) if isinstance(v, float) else v) for k, v in d.items() if k != "models"}, "models": d["models"], "tokens": d["tokens_in"] + d["tokens_out"],
                       "per_useful_act": {"seconds": _per(d["seconds"], n), "tokens": _per(d["tokens_in"] + d["tokens_out"], n), "rupees": 0.0 if n else None}}
    seat_out["cloud"] = {**cloud, "tokens": cloud["tokens_in"] + cloud["tokens_out"],
                         "per_useful_act": {"seconds": _per(cloud["seconds"], n), "tokens": _per(cloud["tokens_in"] + cloud["tokens_out"], n), "rupees": _per(cloud["rupees"], n)}}
    total_local = sum(seats_[s]["calls"] for s in seats_)
    esc: dict = {}
    try:
        from pflab.llm import escalate
        esc = escalate.summary(con, market, since)
    except Exception:
        pass
    return {"market": market, "days": days, "since": since.isoformat(timespec="seconds"), "useful_acts": n, "seats": seat_out,
            "by_kind": sorted(({**v, "local_seconds": round(v["local_seconds"], 1), "cloud_rupees": round(v["cloud_rupees"], 2)} for v in by_kind.values()), key=lambda r: -r["useful_acts"]),
            "local_calls_total": total_local, "local_calls_in_acts": attributed_calls, "escalations": esc,
            "note": "local calls cost no rupees (no metered energy); their cost is seconds of the card and tokens. Cloud is rupees from api_calls. Per useful act = window total / useful acts."}


def world_panel(con, now: Optional[datetime] = None, market: str = "IN", days: int = 7) -> dict:
    """The World screen's 'cost per useful act, by seat' panel: a small, display-ready slice of `cost_view` plus which model sits in each seat."""
    from pflab.llm import seats, teacher
    if not seats.is_on():
        return {"available": False, "off": True}
    v = cost_view(con, market, days, now)
    label = {"fast": "Fast seat (market hours)", "thinker": "Thinker seat (after close)", "other": "Other local", "cloud": "Cloud (paid)"}
    rows = []
    for s in ("fast", "thinker", "other", "cloud"):
        d = v["seats"].get(s)
        if not d:
            continue
        p = d["per_useful_act"]
        rows.append({"seat": s, "label": label[s], "calls": d["calls"], "seconds": round(float(d["seconds"]), 1), "tokens": d["tokens"], "per_act_seconds": p["seconds"],
                     "per_act_tokens": p["tokens"], "per_act_rupees": p["rupees"], "rupees": d.get("rupees", 0.0)})
    picks = {}
    for s in seats.SEATS:
        try:
            r = seats.seat(s)
            picks[s] = {"model": r["key"], "fallback": r["fallback"], "reason": r["reason"] if r["fallback"] else ""}
        except Exception:
            picks[s] = {"model": "?", "fallback": True, "reason": "seat could not be read"}
    try:
        t = teacher.stats(con, market)
    except Exception:
        t = {"examples": 0, "scored": 0}
    esc = v.get("escalations") or {}
    return {"available": True, "days": days, "useful_acts": v["useful_acts"], "rows": rows, "picks": picks, "escalations": esc, "teacher": t,
            "note": "local calls cost seconds of the card, not rupees; cloud is rupees. Per useful act."}
