"""Material events on named ISINs, read from the rebuilt graph's tables (S81 B7). A thin reader: it writes nothing and makes no number.

`material_events(con, isins, since)` -> [{"isin","kind","severity","ts","source","ref","text"}] for events of the thesis-break kinds (results miss, guidance cut,
auditor resignation, promoter pledge increase, regulatory action, rating downgrade, fraud/investigation, large order loss) at any severity, and any event of
severity `high` of a FILING, and news events only at severity medium or high (a news keyword alone is severity low: a lead, never a thesis break), whose time `ts` is at or after `since` (a date or a datetime) and, when `until` is given, not after it (a datetime or a date, that day's end). Newest first.
A filing with no release time carries a DERIVED `ts` (the next trading day's 09:15 IST, `ts_rule = "next_open_no_release_time"`, A58): it is a row of the graph the evening it is dated
but a reader must hold it back until its time, so every caller passes `until` (its own clock) or filters `ts` itself; the same-day reader never sees it, the next trading day's does. The tables hold nothing unless the graph's audit
passed and its switch is on (`kg2/job.py`), so with the graph OFF this returns [].
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, List

from pflab.kg2.classify import THESIS_BREAK_KINDS


def material_events(con, isins: Iterable[str], since, until=None) -> List[dict]:
    isins = sorted({i for i in isins if i})
    if not isins:
        return []
    if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'kg2_event'").fetchone()[0]:
        return []
    since_ts = since if isinstance(since, datetime) else datetime(since.year, since.month, since.day)
    until_ts = None
    if until is not None:
        until_ts = until if isinstance(until, datetime) else datetime(until.year, until.month, until.day, 23, 59, 59)
    until_sql = " AND ts <= ?" if until_ts else ""
    ph = ",".join("?" * len(isins))
    kinds = ",".join("?" * len(THESIS_BREAK_KINDS))
    rows = con.execute(f"""SELECT isin, kind, severity, ts, source, ref, headline, ts_rule FROM kg2_event
                           WHERE isin IN ({ph}) AND ts >= ? AND ts IS NOT NULL{until_sql} AND ((source = 'bse_announcement' AND (kind IN ({kinds}) OR severity = 'high'))
                                OR (source <> 'bse_announcement' AND kind IN ({kinds}) AND severity IN ('medium', 'high')))
                           ORDER BY ts DESC, event_id""", [*isins, since_ts, *([until_ts] if until_ts else []), *THESIS_BREAK_KINDS, *THESIS_BREAK_KINDS]).fetchall()
    return [{"isin": r[0], "kind": r[1], "severity": r[2], "ts": r[3], "source": r[4], "ref": r[5], "text": r[6] or "", "ts_rule": r[7]} for r in rows]
