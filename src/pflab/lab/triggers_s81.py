"""The strategist's S81 triggers (B6): reasons for a session that come from the S81 pieces, each by code, each a sentence with the numbers.

    a thesis-break event on a held name      the exit manager emitted a thesis exit since the last session
    the harvesting window opening            a tax-harvest sale or buy-back was emitted since the last session, or the last quarter of the financial year began; ONLY while
                                             harvesting is on in some sleeve (`[exits] harvest_core` or `harvest_longterm`, both false since A60: no paid session every January)
    a probation slice to grow or withdraw    `probation_s81` recorded a growth or a withdrawal since the last session
    an allocation drift beyond its band      the book is further from the active allocation target than its band (`paper/allocation.drift`)

Every part tolerates a missing table or an unreadable input (it adds no reason); nothing here spends anything: the strategist's own budget rules decide whether a session runs.
"""
from __future__ import annotations

from datetime import datetime
from typing import List


def _since(con, now: datetime):
    last = con.execute("SELECT max(started_at) FROM core_sessions_s80").fetchone()[0]
    return last or datetime(1970, 1, 1)


def harvesting_on() -> bool:
    """A60: exemption and loss harvesting is OFF in the live book (`[exits] harvest_core`, `harvest_longterm`); the window is a reason for a paid session only when one is on."""
    try:
        from pflab.core import exits
        s = exits.settings()
        return bool(s.get("harvest_core", False) or s.get("harvest_longterm", False))
    except Exception:
        return False


def reasons(con, now: datetime) -> List[str]:
    out: List[str] = []
    since = _since(con, now)
    try:
        n = con.execute("SELECT count(*) FROM exit_events_s81 WHERE kind='thesis' AND emitted_at > ? AND status IN ('emitted','filled')", [since]).fetchone()[0]
        if n:
            out.append(f"{n} thesis-break exit(s) on held names since the last session")
    except Exception:
        pass
    try:
        if harvesting_on():
            n = con.execute("SELECT count(*) FROM exit_events_s81 WHERE kind='harvest' AND emitted_at > ? AND status IN ('emitted','filled')", [since]).fetchone()[0]
            q4 = now.month in (1, 2, 3) and since.date() < now.date().replace(month=1, day=1)
            if n or q4:
                out.append("the tax-harvesting window is open" + (f": {n} harvest order(s) since the last session" if n else " (the last quarter of the financial year began)"))
    except Exception:
        pass
    try:
        rows = con.execute("SELECT policy_id, kind, share FROM probation_s81 WHERE made_at > ? AND kind IN ('grow','withdraw') ORDER BY change_id", [since]).fetchall()
        for pid, kind, share in rows[:3]:
            out.append(f"probation slice of {pid}: {kind} ({share:.0%})")
    except Exception:
        pass
    try:
        from pflab.paper import allocation, book
        tgt = allocation.active_target(con)
        if tgt:
            day = con.execute("SELECT max(day) FROM paper_days").fetchone()[0]
            d = allocation.drift(book.holdings(con, day), tgt) if day else None
            far = [x for x in (d or {}).get("classes", []) if abs(x.get("gap_pct", 0.0)) > allocation.BAND_PCT * 2]
            if far:
                out.append("the book is far from its allocation target: " + ", ".join(f"{x['name']} {x['gap_pct']:+.1f} points" for x in far[:3]))
    except Exception:
        pass
    return out
