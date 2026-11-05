"""The agenda's table (`mind_agenda`) and the per-kind yield (`agenda_kind_stats`). Plain functions over a DuckDB cursor; nothing here decides what to do."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from pflab.pm.store import next_id

EFFECTS = ("belief", "forecast_weight", "decision", "answered_him")      # the only things that make an act useful
STATES = ("queued", "running", "done", "skipped", "failed")
COLS = ("item_id", "market", "kind", "subject", "reason", "expected_value", "cost_rupees", "cost_seconds", "state", "created_at", "started_at",
        "finished_at", "outcome", "useful", "effect", "skip_reason", "payload")
WINDOW = 30                  # the yield is the useful rate of a kind's last WINDOW acts
MIN_ACTS = 10                # under this many acts a kind's multiplier is neutral (1.0): too few to judge
FLOOR, CEIL = 0.15, 1.5      # the multiplier's bounds: a kind that never helps is still tried now and then; one that often does gets a boost
STALE_DAYS = 2               # a queued item older than this is dropped as stale (the world moved on)


def _row(r) -> dict:
    d = dict(zip(COLS, r))
    try:
        d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
    except ValueError:
        d["payload"] = {}
    return d


def get(con, item_id: int) -> Optional[dict]:
    r = con.execute(f"SELECT {', '.join(COLS)} FROM mind_agenda WHERE item_id=?", [item_id]).fetchone()
    return _row(r) if r else None


def add(con, market: str, kind: str, subject: str, reason: str, expected_value: float, cost_rupees: float, cost_seconds: float, now: datetime,
        payload: Optional[dict] = None) -> Optional[int]:
    """Queue an item; None when the same kind + subject was already put on the agenda today (any state) or is still queued/running."""
    if con.execute("SELECT 1 FROM mind_agenda WHERE market=? AND kind=? AND subject=? AND (CAST(created_at AS DATE)=? OR state IN ('queued','running')) LIMIT 1",
                   [market, kind, subject, now.date()]).fetchone():
        return None
    iid = next_id(con, "mind_agenda", "item_id")
    con.execute("INSERT INTO mind_agenda (item_id, market, kind, subject, reason, expected_value, cost_rupees, cost_seconds, state, created_at, payload) "
                "VALUES (?,?,?,?,?,?,?,?,'queued',?,?)",
                [iid, market, kind, subject[:200], (reason or "")[:400], float(expected_value), float(cost_rupees), float(cost_seconds), now,
                 json.dumps(payload or {}, default=str)[:2000]])
    return iid


def ever_handled(con, market: str, kind: str, subject: str) -> bool:
    """True when this kind + subject was ever worked, skipped or failed (producers use it for subjects that must be handled once, not once a day)."""
    return bool(con.execute("SELECT 1 FROM mind_agenda WHERE market=? AND kind=? AND subject=? AND state IN ('done','skipped','failed') LIMIT 1",
                            [market, kind, subject]).fetchone())


def start(con, item_id: int, now: datetime) -> None:
    con.execute("UPDATE mind_agenda SET state='running', started_at=? WHERE item_id=?", [now, item_id])


def finish(con, item_id: int, now: datetime, outcome: str, useful: bool, effect: str) -> None:
    con.execute("UPDATE mind_agenda SET state='done', finished_at=?, outcome=?, useful=?, effect=? WHERE item_id=?",
                [now, (outcome or "")[:500], bool(useful), (effect or "")[:300], item_id])


def fail(con, item_id: int, now: datetime, error: str) -> None:
    con.execute("UPDATE mind_agenda SET state='failed', finished_at=?, outcome=?, useful=FALSE, effect='' WHERE item_id=?", [now, (error or "")[:500], item_id])


def skip(con, item_id: int, now: datetime, reason: str) -> None:
    con.execute("UPDATE mind_agenda SET state='skipped', finished_at=?, skip_reason=? WHERE item_id=?", [now, (reason or "")[:300], item_id])


def sweep_interrupted(con, now: datetime, minutes: int = 30) -> int:
    """An item left 'running' by a stop is failed (it never finished); returns how many."""
    rows = con.execute("SELECT item_id FROM mind_agenda WHERE state='running' AND started_at < ?", [now - timedelta(minutes=minutes)]).fetchall()
    for (i,) in rows:
        fail(con, i, now, "interrupted: the process stopped while it ran")
    return len(rows)


def queued(con, market: Optional[str] = None) -> List[dict]:
    q = f"SELECT {', '.join(COLS)} FROM mind_agenda WHERE state='queued'" + (" AND market=?" if market else "") + " ORDER BY item_id"
    return [_row(r) for r in con.execute(q, [market] if market else []).fetchall()]


def running(con) -> Optional[dict]:
    r = con.execute(f"SELECT {', '.join(COLS)} FROM mind_agenda WHERE state='running' ORDER BY started_at DESC LIMIT 1").fetchone()
    return _row(r) if r else None


def recent(con, state: str, limit: int = 10) -> List[dict]:
    return [_row(r) for r in con.execute(f"SELECT {', '.join(COLS)} FROM mind_agenda WHERE state=? ORDER BY coalesce(finished_at, created_at) DESC, item_id DESC LIMIT ?",
                                         [state, limit]).fetchall()]


# --- the yield of a kind --------------------------------------------------------------------------------------------------------------

def multiplier_of(rate: Optional[float], n: int) -> float:
    """2 x the useful rate (a kind useful half the time is neutral), kept between FLOOR and CEIL; neutral under MIN_ACTS acts."""
    if rate is None or n < MIN_ACTS:
        return 1.0
    return max(FLOOR, min(CEIL, 2.0 * rate))


def refresh_stats(con, market: str, kind: str, now: datetime) -> dict:
    """Recompute a kind's row from its last acts (done or failed; a failure counts as not useful)."""
    last = [bool(u) for (u,) in con.execute("SELECT coalesce(useful, FALSE) FROM mind_agenda WHERE market=? AND kind=? AND state IN ('done','failed') "
                                           "ORDER BY finished_at DESC, item_id DESC LIMIT ?", [market, kind, WINDOW]).fetchall()]
    n_done, n_useful = con.execute("SELECT count(*) FILTER (WHERE state='done'), count(*) FILTER (WHERE state='done' AND useful) FROM mind_agenda "
                                   "WHERE market=? AND kind=?", [market, kind]).fetchone()
    rate = (sum(last) / len(last)) if last else None
    mult = multiplier_of(rate, len(last))
    con.execute("DELETE FROM agenda_kind_stats WHERE market=? AND kind=?", [market, kind])
    con.execute("INSERT INTO agenda_kind_stats VALUES (?,?,?,?,?,?,?)", [market, kind, int(n_done), int(n_useful), rate, mult, now])
    return {"kind": kind, "n_done": int(n_done), "n_useful": int(n_useful), "yield": rate, "multiplier": mult}


def multiplier(con, market: str, kind: str) -> float:
    r = con.execute('SELECT multiplier FROM agenda_kind_stats WHERE market=? AND kind=?', [market, kind]).fetchone()
    return float(r[0]) if r and r[0] is not None else 1.0


def kind_stats(con) -> List[dict]:
    return [{"market": m, "kind": k, "n_done": int(n or 0), "n_useful": int(u or 0), "yield": None if y is None else round(float(y), 3),
             "multiplier": round(float(x), 3)}
            for m, k, n, u, y, x in con.execute('SELECT market, kind, n_done, n_useful, "yield", multiplier FROM agenda_kind_stats ORDER BY market, kind').fetchall()]


def counts(con) -> Dict[str, int]:
    return {s: int(n) for s, n in con.execute("SELECT state, count(*) FROM mind_agenda GROUP BY 1").fetchall()}
