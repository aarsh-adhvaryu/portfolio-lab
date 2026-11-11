"""Catch-up on open (S79 item 3, A42): every missed session's data per market, then each missed session's scoring in order, point-in-time, by code.

The data jobs (collect, prices, nav, global, filings ...) are due the moment the app opens (`service/ondemand.py` and their slots already passed); this module
is the second stage: `run(con, root, now)` waits for each market's latest closed session to be in the store, then runs `fcast.run.catch_up` (forecasts scored
and weights updated for every missed session in order), and writes the state the World screen shows (`catchup_s79`). Waiting for data is a state, never an error.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from pflab import markets


def data_through(con, root: Path, market: str) -> Optional[date]:
    """The latest session of this market whose closes are in the store."""
    if market == "IN":
        r = con.execute("SELECT max(date) FROM prices WHERE source='nse_bhavcopy'").fetchone()[0]
        return r
    try:
        from pflab.data import global_markets
        df = global_markets.load(markets.get(market).benchmark, root)
        return None if df is None or len(df) == 0 else df["date"].max().date() if hasattr(df["date"].max(), "date") else df["date"].max()
    except Exception:
        return None


def _state_row(con, market: str, now: datetime, closed: date) -> int:
    from pflab.pm.store import next_id
    r = con.execute("SELECT catch_id FROM catchup_s79 WHERE market=? AND to_session=? AND state IN ('running','done') ORDER BY catch_id DESC LIMIT 1", [market, closed]).fetchone()
    if r:
        return int(r[0])
    cid = next_id(con, "catchup_s79", "catch_id")
    last = con.execute("SELECT max(to_session) FROM catchup_s79 WHERE market=? AND state='done'", [market]).fetchone()[0]
    m = markets.get(market)
    missed = m.session_count(last, closed) if last else None
    con.execute("INSERT INTO catchup_s79 VALUES (?,?,?,?,?,?,?,?,?,?)", [cid, market, now, last, closed, missed, "data", "running", None, None])
    return cid


def run(con, root: Path, now: datetime) -> dict:
    out: dict = {}
    for market in markets.codes():
        m = markets.get(market)
        closed = m.session_closed_by(now)
        have = data_through(con, root, market)
        cid = _state_row(con, market, now, closed)
        if con.execute("SELECT state FROM catchup_s79 WHERE catch_id=?", [cid]).fetchone()[0] == "done":
            out[market] = {"done": str(closed)}
            continue
        if have is None or have < closed:
            con.execute("UPDATE catchup_s79 SET stage='data', detail=? WHERE catch_id=?",
                        [f"waiting for {market} closes of {closed} (have {have}): data arrival", cid])
            out[market] = {"waiting": f"closes of {closed} (have {have})"}
            continue
        con.execute("UPDATE catchup_s79 SET stage='scoring' WHERE catch_id=?", [cid])
        res: dict = {}
        try:
            from pflab.fcast import run as fr
            res = fr.catch_up(con, market, closed, now=now) or {}
        except ImportError:
            res = {"note": "forecasting is not installed"}
        except Exception as e:                                   # a failed scoring is recorded and retried, never silent
            con.execute("UPDATE catchup_s79 SET state='failed', stage='scoring', finished_at=?, detail=? WHERE catch_id=?", [now, f"{type(e).__name__}: {e}"[:300], cid])
            out[market] = {"failed": f"{type(e).__name__}: {e}"[:300]}
            continue
        if market == "US":                                       # S82 (A59): the US sub-book's step runs for every missed US session, oldest first, once each (the `us_close` job is the same step)
            try:
                from pflab import us
                if us.on():
                    ub = us_adapter_close(con, now, root)
                    res = {**res, "us_book": {k: ub[k] for k in ("day", "status", "caught_up", "waiting", "skipped") if k in ub}}
            except Exception as e:                               # never stops the catch-up: the `us_close` job tries again
                res = {**res, "us_book": {"failed": f"{type(e).__name__}: {str(e)[:160]}"}}
        con.execute("UPDATE catchup_s79 SET state='done', stage='done', finished_at=?, detail=? WHERE catch_id=?", [now, json.dumps(res, default=str)[:900], cid])
        out[market] = {"done": str(closed), "new": True, **({"scoring": res} if res else {})}
    return out


def us_adapter_close(con, now: datetime, root: Path) -> dict:
    from pflab.us import adapter
    return adapter.close_us(con, now, root)


def status(con) -> dict:
    """For the World screen: what the catch-up is doing right now."""
    rows = con.execute("SELECT market, to_session, missed_sessions, stage, state, detail FROM catchup_s79 WHERE catch_id IN (SELECT max(catch_id) FROM catchup_s79 GROUP BY market)").fetchall()
    return {"markets": [{"market": a, "to_session": str(b), "missed": c, "stage": d, "state": e, "detail": f} for a, b, c, d, e, f in rows]}
