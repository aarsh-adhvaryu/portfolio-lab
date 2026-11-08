"""What the existing agents bring to the storylines (S80 phase 3). Each adapter turns an agent's output into dated EVIDENCE ITEMS, by code, with the source named. An item is
{key, date, text, source_kind, source_ref}; the local reader (reader.py) decides which storyline it bears on, or that it bears on none. Nothing is a pile: an item that fits no
storyline is dropped after it has been read once.

    flows        foreign and domestic institutions' net cash-market buying (data/flows), the day and its 5-session total
    attribution  the split of the index's move into crude, rupee, US yield, Nasdaq, foreign flows and Asia (`macro_attribution`)
    waves        market-wide waves and rotations flagged from the NSE daily files (`wave_flag`)
Filings and tone adapters join the same registry when their tables exist; a missing source gives no items, never an error.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List

from pflab.story import series


def flows_items(root, asof: date) -> List[dict]:
    s = series.known("FII_NET_CR", asof, root)
    d = series.known("DII_NET_CR", asof, root)
    out = []
    if s is None or not len(s):
        return out
    for ts in s.index[-3:]:
        day = ts.date()
        fii = float(s.loc[ts])
        dii = float(d.loc[ts]) if d is not None and ts in d.index else None
        five = float(s.loc[:ts].tail(5).sum())
        out.append({"key": f"flows:{day}", "date": day, "source_kind": "tool", "source_ref": f"FII_NET_CR:{day}",
                    "text": (f"Foreign institutions were net {'buyers' if fii > 0 else 'sellers'} of Rs {abs(fii):,.0f} crore of Indian shares on {day} "
                             f"(Rs {five:,.0f} crore net over the last 5 sessions)" + (f"; domestic institutions Rs {dii:,.0f} crore net" if dii is not None else ""))})
    return out


def attribution_items(con, asof: date) -> List[dict]:
    try:
        rows = con.execute("SELECT session, part, pct FROM macro_attribution WHERE market='IN' AND session <= ? AND session >= ? AND part <> 'total' ORDER BY session DESC, abs(pct) DESC",
                           [asof, asof - timedelta(days=5)]).fetchall()
    except Exception:
        return []
    by = {}
    for sess, part, pct in rows:
        by.setdefault(sess, []).append((part, pct))
    return [{"key": f"attribution:{sess}", "date": sess, "source_kind": "tool", "source_ref": f"macro_attribution:{sess}",
             "text": f"On {sess} the Nifty's move was explained mostly by: " + "; ".join(f"{p} {v:+.2f} points" for p, v in parts[:3] if v is not None)} for sess, parts in by.items()]


def wave_items(con, asof: date) -> List[dict]:
    try:
        rows = con.execute("SELECT session, kind, direction, salience, definition FROM wave_flag WHERE market='IN' AND session <= ? AND session >= ? ORDER BY session DESC",
                           [asof, asof - timedelta(days=5)]).fetchall()
    except Exception:
        return []
    return [{"key": f"wave:{sess}:{kind}", "date": sess, "source_kind": "tool", "source_ref": f"wave_flag:{sess}:{kind}",
             "text": f"On {sess} the wave scan flagged a {salience or ''} {kind.replace('_', ' ')} ({direction or 'no direction'}): {(definition or '')[:160]}".replace("  ", " ")}
            for sess, kind, direction, salience, definition in rows]


ADAPTERS = ("flows", "attribution", "waves")


def collect(con, root, asof: date) -> List[dict]:
    """Every item of the last few sessions, oldest first; the caller skips what the reader has already read (`storyline_reader_s80`)."""
    items = flows_items(root, asof) + attribution_items(con, asof) + wave_items(con, asof)
    return sorted(items, key=lambda i: (i["date"], i["key"]))
