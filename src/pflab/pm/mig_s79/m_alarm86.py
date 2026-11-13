"""S86 the alarm lane (A73-A78): versions 345-349.

345  headlines_s86     one row per headline the collector kept (deduplicated by name and near-identical title): source, outlet, published time, FIRST-SEEN time (the time it counts from), its lane
                     (red / amber / grey), kind and severity by code, and the alarm it raised.
346  headline_src_s86  one row per (source, name): when it was last asked and how it went (back-off after failures; a name is not asked in a loop).
347  alarm_s86         one row per alarm: the four times (first published, first seen, case opened, Telegram queued), the case, the freeze, who decided and when, and a cause when it was slow.
348  eyes_s86          one row per source the system watches with (news, filings, quotes): last answer, how long silent, whether the blind-spot line was said (and the "back" line).
349  alarm_gap_s86     one row per gap the app was off: from, to, what was found, the message sent (so a gap is told once).
"""
MIGRATIONS = [
    (345, "headlines_s86", """
    CREATE TABLE IF NOT EXISTS headlines_s86 (
        item_id VARCHAR PRIMARY KEY, isin VARCHAR NOT NULL, symbol VARCHAR, market VARCHAR, title VARCHAR NOT NULL, url VARCHAR, outlet VARCHAR, source VARCHAR NOT NULL,
        published TIMESTAMP, first_seen TIMESTAMP NOT NULL, lane VARCHAR, kind VARCHAR, severity VARCHAR, alarm_id BIGINT, in_graph BOOLEAN
    );
    """),
    (346, "headline_src_s86", """
    CREATE TABLE IF NOT EXISTS headline_src_s86 (
        source VARCHAR NOT NULL, isin VARCHAR NOT NULL, last_checked TIMESTAMP, last_status VARCHAR, failures INTEGER, items_seen BIGINT, PRIMARY KEY (source, isin)
    );
    """),
    (347, "alarm_s86", """
    CREATE TABLE IF NOT EXISTS alarm_s86 (
        alarm_id BIGINT PRIMARY KEY, isin VARCHAR NOT NULL, symbol VARCHAR, market VARCHAR, lane VARCHAR, kind VARCHAR, severity VARCHAR, headline VARCHAR, outlet VARCHAR, source VARCHAR,
        item_id VARCHAR, weight_pct DOUBLE, published_at TIMESTAMP, first_seen_at TIMESTAMP, case_id BIGINT, case_opened_at TIMESTAMP, telegram_queued_at TIMESTAMP, decided_at TIMESTAMP,
        decision VARCHAR, freeze_id BIGINT, joined_items INTEGER, mode VARCHAR, slow_cause VARCHAR, day DATE
    );
    """),
    (348, "eyes_s86", """
    CREATE TABLE IF NOT EXISTS eyes_s86 (
        source VARCHAR PRIMARY KEY, label VARCHAR, last_try TIMESTAMP, last_ok TIMESTAMP, last_error VARCHAR, items_last BIGINT, blind_since TIMESTAMP, blind_told_at TIMESTAMP, back_told_at TIMESTAMP,
        requests BIGINT
    );
    """),
    (349, "alarm_gap_s86", """
    CREATE TABLE IF NOT EXISTS alarm_gap_s86 (
        gap_id BIGINT PRIMARY KEY, off_from TIMESTAMP, off_to TIMESTAMP, found_at TIMESTAMP, items INTEGER, red INTEGER, message VARCHAR, release VARCHAR
    );
    """),
]
