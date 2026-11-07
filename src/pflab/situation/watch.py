"""Watch triggers of the situation (S79b item 16): the report's ACT section can say "watch this level"; the code checks it on every later run and, when it holds, puts
an EVENT on the system's stream: a claim of kind `event`, an agenda item the agenda works (kind `watch_fired`), and a flag that makes the next situation run a
flag-triggered synthesis. The brain and the agents see it through the claim and the agenda; nothing is traded.

A trigger is `series op threshold`: the series is a file stem of `data/global` (WTI, BRENT_FUT, US_VIX, DOLLAR_INDEX, GOLD, US_10Y_YIELD ...) or an index key
(NIFTY50_PRICE); op is `>` or `<`; the threshold must be a number a tool printed in a claim (checked by `synth`, not invented by the model). The test is the latest
close on or before the date checked (point-in-time).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

import pandas as pd

from pflab.pm.store import next_id

OPS = (">", "<")
MAX_ACTIVE = 12
LIFE_DAYS = 30


def series_names(root: Optional[Path] = None) -> List[str]:
    from pflab.data import data_dir
    root = Path(root) if root else data_dir()
    try:
        out = sorted(p.stem for p in (root / "global").glob("*.parquet"))
    except OSError:
        out = []
    return out + ["NIFTY50_PRICE"]


def latest(series: str, as_of: date, root: Optional[Path] = None):
    """(date, close) of the series on or before as_of, or (None, None)."""
    from pflab.data import data_dir, global_markets, indices
    root = Path(root) if root else data_dir()
    try:
        df = indices.load(series, root) if series.startswith(("NIFTY", "SECTOR_")) else global_markets.load(series, root)
    except Exception:
        return None, None
    s = df[pd.to_datetime(df["date"]) <= pd.Timestamp(as_of)].dropna(subset=["close"]).sort_values("date")
    if s.empty:
        return None, None
    r = s.iloc[-1]
    return pd.Timestamp(r["date"]).date(), float(r["close"])


def history(series: str, as_of: date, root: Optional[Path] = None, n: int = 21):
    """The last n (date, close) pairs on or before as_of, oldest first; [] when the series is unreadable."""
    from pflab.data import data_dir, global_markets, indices
    root = Path(root) if root else data_dir()
    try:
        df = indices.load(series, root) if series.startswith(("NIFTY", "SECTOR_")) else global_markets.load(series, root)
    except Exception:
        return []
    s = df[pd.to_datetime(df["date"]) <= pd.Timestamp(as_of)].dropna(subset=["close"]).sort_values("date").tail(n)
    return [(pd.Timestamp(d).date(), float(c)) for d, c in zip(s["date"], s["close"])]


def add(con, market: str, text: str, series: str, op: str, threshold: float, set_on: date, now: datetime, claim_id: Optional[int] = None,
        report_id: Optional[int] = None, root: Optional[Path] = None) -> dict:
    """Store a trigger; {'stored': id} or {'stored': False, 'problem': why}. The same series, op and threshold active twice is stored once."""
    if op not in OPS:
        return {"stored": False, "problem": f"op must be one of {OPS}"}
    if series not in series_names(root):
        return {"stored": False, "problem": f"series {series!r} is not one the system collects"}
    if con.execute("SELECT count(*) FROM situation_watch WHERE market=? AND status='active'", [market]).fetchone()[0] >= MAX_ACTIVE:
        return {"stored": False, "problem": f"{MAX_ACTIVE} watch triggers are already active"}
    r = con.execute("SELECT watch_id FROM situation_watch WHERE market=? AND series=? AND op=? AND threshold=? AND status='active'", [market, series, op, float(threshold)]).fetchone()
    if r:
        return {"stored": int(r[0]), "again": True}
    d, c = latest(series, set_on, root)
    if c is not None and ((op == ">" and c > threshold) or (op == "<" and c < threshold)):
        return {"stored": False, "problem": f"already true at the latest close ({c:g} on {d}): a trigger is for a change, not a state"}
    wid = next_id(con, "situation_watch", "watch_id")
    con.execute("INSERT INTO situation_watch (watch_id, market, report_id, claim_id, text, series, op, threshold, set_on, expires_on, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,'active',?)",
                [wid, market, report_id, claim_id, text[:240], series, op, float(threshold), set_on, set_on + timedelta(days=LIFE_DAYS), now])
    return {"stored": wid}


def active(con, market: Optional[str] = None) -> List[dict]:
    q = "SELECT watch_id, market, text, series, op, threshold, set_on, expires_on, status, fired_on, fired_value, agenda_item_id FROM situation_watch" + (" WHERE market=?" if market else "") + " ORDER BY watch_id DESC LIMIT 40"
    cols = ("watch_id", "market", "text", "series", "op", "threshold", "set_on", "expires_on", "status", "fired_on", "fired_value", "agenda_item_id")
    return [dict(zip(cols, r)) for r in con.execute(q, [market] if market else []).fetchall()]


def check(con, market: str, as_of: date, now: datetime, root: Optional[Path] = None) -> List[dict]:
    """Test every active trigger of the market at `as_of` (latest close on or before it). A fired one is closed, a claim of kind `event` is written, and an agenda item is queued.
    Returns the fired ones. Expired ones are closed."""
    from pflab.agenda import items
    from pflab.situation import claims as C
    fired = []
    for w in [x for x in active(con, market) if x["status"] == "active"]:
        if w["expires_on"] is not None and w["expires_on"] < as_of:
            con.execute("UPDATE situation_watch SET status='expired' WHERE watch_id=?", [w["watch_id"]])
            continue
        d, c = latest(w["series"], as_of, root)
        if c is None or d is None or d <= w["set_on"]:                       # only a close AFTER the trigger was set can fire it
            continue
        hit = (w["op"] == ">" and c > w["threshold"]) or (w["op"] == "<" and c < w["threshold"])
        if not hit:
            continue
        iid = items.add(con, market, "watch_fired", f"watch #{w['watch_id']}: {w['series']} {w['op']} {w['threshold']:g}", f"{w['text']} (close {c:g} on {d})", 3.0, 0.0, 60.0, now,
                        {"watch_id": w["watch_id"], "series": w["series"], "value": c, "date": str(d)})
        con.execute("UPDATE situation_watch SET status='fired', fired_on=?, fired_value=?, agenda_item_id=? WHERE watch_id=?", [d, c, iid, w["watch_id"]])
        cid = C.add(con, market, "event", f"watch_fired_{w['watch_id']}", f"Watch fired: {w['text'][:200]} - {w['series']} closed at {c:g}, {w['op']} {w['threshold']:g}", value=c,
                    as_of=d, ttl_sessions=3, source="watch", now=now, themes=[w["series"]])
        fired.append({**w, "fired_on": d, "fired_value": c, "claim_id": cid, "agenda_item_id": iid})
    return fired


def unreacted(con, market: str) -> List[dict]:
    """Fired triggers whose agenda item has not been worked yet (the flag for the next situation run)."""
    out = []
    for w in active(con, market):
        if w["status"] != "fired" or not w["agenda_item_id"]:
            continue
        st = con.execute("SELECT state FROM mind_agenda WHERE item_id=?", [w["agenda_item_id"]]).fetchone()
        if st and st[0] in ("queued", "running"):
            out.append(w)
    return out
