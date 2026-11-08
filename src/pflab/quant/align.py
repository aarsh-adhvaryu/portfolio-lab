"""Line up a day's minute bursts against what was published (S79 item 7): exchange filings (BSE announcements, at their DISSEMINATION time, the moment the
market could see them) and news (the knowledge graph's articles, at their published time). By code.

Rule: an event "preceded" a burst when the event's minute is at or before the burst's first minute and within WINDOW minutes of it. A burst in the first
15 minutes of the session also takes everything published since the previous session's close (the open is where the night's news is priced). A burst with no
event in its window is UNEXPLAINED: the data does not say why it moved, and nothing here guesses.
Point in time: events after the burst's minute are never counted as its cause.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import List, Optional

import pandas as pd

WINDOW_MIN = 30
OPEN_GRACE_MIN = 15
NEWS_SKIP_KINDS = ("filing", "result")                 # the filings come from the BSE store itself, not twice


def scrips_for(root: Path, isin: str, day: date) -> List[str]:
    """BSE scrip codes that carried this ISIN on `day` (the map keeps the ISIN history of a company)."""
    from pflab.data import bse_scrip_isin
    try:
        m = bse_scrip_isin.load(root)
    except FileNotFoundError:
        return []
    m = m[m["isin"] == isin]
    d = pd.Timestamp(day)
    m = m[(m["valid_from"].isna() | (pd.to_datetime(m["valid_from"]) <= d)) & (m["valid_to"].isna() | (pd.to_datetime(m["valid_to"]) >= d))]
    return sorted(set(m["scrip_code"].astype(str)))


def filings(root: Path, isin: str, start: datetime, end: datetime) -> List[dict]:
    """BSE announcements of the name disseminated in [start, end]."""
    codes = scrips_for(root, isin, end.date())
    if not codes:
        return []
    out: List[dict] = []
    d = start.date()
    while d <= end.date():
        p = Path(root) / "bse_announcements" / f"{d.year}" / f"{d}.parquet"
        if p.exists():
            x = pd.read_parquet(p)
            x = x[x["scrip_code"].astype(str).isin(codes)]
            x = x[(x["dissem_dt"] >= pd.Timestamp(start)) & (x["dissem_dt"] <= pd.Timestamp(end))]
            for r in x.itertuples():
                out.append({"at": pd.Timestamp(r.dissem_dt).to_pydatetime(), "kind": "filing", "what": f"{r.category}: {r.subcategory}" if r.subcategory else str(r.category),
                            "headline": str(r.headline)[:140]})
        d += timedelta(days=1)
    return sorted(out, key=lambda e: e["at"])


def news(con, isin: str, start: datetime, end: datetime) -> List[dict]:
    """Knowledge-graph documents about the name published in [start, end] (articles and notes; filings come from the BSE store)."""
    rows = con.execute("SELECT d.published_at, d.kind, d.title, d.source FROM kg_docs d JOIN kg_edges e ON e.src = d.doc_id AND e.rel = 'about' AND e.dst = ? "
                       "WHERE d.published_at >= ? AND d.published_at <= ? AND d.kind NOT IN ('filing','result') ORDER BY d.published_at", [f"company:{isin}", start, end]).fetchall()
    return [{"at": pd.Timestamp(r[0]).to_pydatetime(), "kind": "news", "what": str(r[1]), "headline": str(r[2])[:140], "source": r[3]} for r in rows]


def align(burst_events: List[dict], events: List[dict], day: date, prev_close_dt: datetime, open_t: time = time(9, 15), window: int = WINDOW_MIN) -> dict:
    """Each burst with the events that preceded it inside the window, and the list of unexplained bursts. `burst_events` carry a datetime under `ts`."""
    grace = datetime.combine(day, open_t) + timedelta(minutes=OPEN_GRACE_MIN)
    rows, unexplained = [], []
    for b in burst_events:
        t = pd.Timestamp(b["ts"]).floor("min").to_pydatetime()
        lo = prev_close_dt if t < grace else t - timedelta(minutes=window)
        pre = [e for e in events if lo <= pd.Timestamp(e["at"]).floor("min").to_pydatetime() <= t]
        row = {"at": t.strftime("%H:%M"), "return_pct": b["return_pct"], "z": b.get("z"), "minutes": b.get("minutes", 1),
               "preceded_by": [{"at": pd.Timestamp(e["at"]).strftime("%H:%M" if pd.Timestamp(e["at"]).date() == day else "%d %b %H:%M"), "minutes_before": int((t - pd.Timestamp(e["at"]).floor("min").to_pydatetime()).total_seconds() // 60),
                                "kind": e["kind"], "what": e["what"], "headline": e["headline"]} for e in pre[-4:]],
               "n_events_in_window": len(pre), "window": "since the previous close" if t < grace else f"{window} minutes"}
        row["explained"] = bool(pre)
        rows.append(row)
        if not pre:
            unexplained.append(row["at"])
    return {"window_minutes": window, "bursts": rows, "n_bursts": len(rows), "n_unexplained": len(unexplained), "unexplained_at": unexplained,
            "rule": (f"an event preceded a burst when it was published at or before the burst's minute and within {window} minutes of it (filings at their dissemination time, "
                     f"news at its published time); a burst in the first {OPEN_GRACE_MIN} minutes takes everything since the previous close; no event in the window = unexplained")}
