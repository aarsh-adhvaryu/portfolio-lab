"""Material events on named ISINs, read from the rebuilt graph's tables (S81 B7). A thin reader: it writes nothing and makes no number.

`material_events(con, isins, since)` -> [{"isin","kind","severity","ts","source","ref","text"}] for events of the thesis-break kinds (results miss, guidance cut,
auditor resignation, promoter pledge increase, regulatory action, rating downgrade, fraud/investigation, large order loss) at any severity, and any event of
severity `high`, whose dissemination timestamp `ts` is at or after `since` (a date or a datetime). Newest first. The tables hold nothing unless the graph's audit
passed and its switch is on (`kg2/job.py`), so with the graph OFF this returns [].
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, List

from pflab.kg2.classify import THESIS_BREAK_KINDS


def material_events(con, isins: Iterable[str], since) -> List[dict]:
    isins = sorted({i for i in isins if i})
    if not isins:
        return []
    if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'kg2_event'").fetchone()[0]:
        return []
    since_ts = since if isinstance(since, datetime) else datetime(since.year, since.month, since.day)
    ph = ",".join("?" * len(isins))
    kinds = ",".join("?" * len(THESIS_BREAK_KINDS))
    rows = con.execute(f"""SELECT isin, kind, severity, ts, source, ref, headline FROM kg2_event
                           WHERE isin IN ({ph}) AND ts >= ? AND ts IS NOT NULL AND (kind IN ({kinds}) OR severity = 'high')
                           ORDER BY ts DESC, event_id""", [*isins, since_ts, *THESIS_BREAK_KINDS]).fetchall()
    return [{"isin": r[0], "kind": r[1], "severity": r[2], "ts": r[3], "source": r[4], "ref": r[5], "text": r[6] or ""} for r in rows]
