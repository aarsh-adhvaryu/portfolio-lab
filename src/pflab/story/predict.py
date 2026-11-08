"""A storyline's predictions (S80 phase 3): what it implies for its subject over 5 and 20 sessions, registered when the storyline opens and scored when due. A storyline whose
predictions keep failing loses influence by itself: `influence` is the Laplace-smoothed hit rate of its scored predictions (0.5 until three are scored), floored at 0.1.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pflab.story import series, store

HORIZONS = (5, 20)
MIN_SCORED = 3
FLOOR = 0.1


def _session_after(day: date, n: int, market: str = "IN") -> date:
    from pflab import markets
    return markets.get(market).session_after(day, n)


def register(con, now: datetime, sid: int, made_on: date, root=None) -> int:
    """The storyline's predictions at each horizon (idempotent): the subject moves in the storyline's direction between the close of `made_on` and the due session."""
    from pflab.pm.store import next_id
    s = store.get(con, sid)
    ref = series.level_on(s["subject"], made_on, root)
    if ref is None:
        return 0
    n = 0
    for h in HORIZONS:
        try:
            due = _session_after(made_on, h, s["market"])
        except Exception:
            continue
        try:
            con.execute("INSERT INTO storyline_predictions_s80 (pred_id, storyline_id, made_on, horizon_sessions, subject, expected_sign, ref_level, due_on) VALUES (?,?,?,?,?,?,?,?)",
                        [next_id(con, "storyline_predictions_s80", "pred_id"), sid, made_on, h, s["subject"], s["direction"], ref, due])
            n += 1
        except Exception:                                                        # the unique key: already registered
            pass
    return n


def score_due(con, now: datetime, today: date, root=None) -> int:
    """Score every prediction whose session has closed: good when the subject moved in the expected direction, bad when not (no minimum move: a flat result is a miss)."""
    n = 0
    for pid, sid, ref, due, sign, subject in con.execute("SELECT pred_id, storyline_id, ref_level, due_on, expected_sign, subject FROM storyline_predictions_s80 "
                                                         "WHERE scored_at IS NULL AND due_on <= ?", [today]).fetchall():
        last = series.load(subject, root)
        if last is None or not len(last) or last.index[-1].date() < due:
            continue                                                             # the due session's close is not in the data yet
        end = series.level_on(subject, due, root)
        ret = end / ref - 1.0
        out = "good" if ret * sign > 0 else "bad"
        import json
        con.execute("UPDATE storyline_predictions_s80 SET scored_at=?, outcome=?, outcome_json=? WHERE pred_id=?", [now, out, json.dumps({"return": round(ret, 5), "to": str(due)}), pid])
        update_influence(con, now, sid)
        n += 1
    return n


def update_influence(con, now: datetime, sid: int) -> float:
    good, bad = (int(x or 0) for x in con.execute("SELECT count(*) FILTER (WHERE outcome='good'), count(*) FILTER (WHERE outcome='bad') FROM storyline_predictions_s80 WHERE storyline_id=?", [sid]).fetchone())
    n = good + bad
    inf = 0.5 if n < MIN_SCORED else max(FLOOR, (good + 1.0) / (n + 2.0))
    con.execute("UPDATE storylines_s80 SET influence=?, updated_at=? WHERE storyline_id=?", [inf, now, sid])
    return inf


def record(con, sid: int) -> dict:
    rows = con.execute("SELECT horizon_sessions, due_on, outcome, outcome_json FROM storyline_predictions_s80 WHERE storyline_id=? ORDER BY due_on", [sid]).fetchall()
    return {"predictions": [{"horizon": h, "due": str(d), "outcome": o or "not due"} for h, d, o, _ in rows]}
