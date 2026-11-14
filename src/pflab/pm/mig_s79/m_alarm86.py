"""S86 the alarm lane (A73-A78): versions 345-349.

345  headlines_s86     one row per headline the collector kept (deduplicated by name and near-identical title): source, outlet, published time, FIRST-SEEN time (the time it counts from), its lane
                     (red / amber / grey), kind and severity by code, and the alarm it raised.
346  headline_src_s86  one row per (source, name): when it was last asked and how it went (back-off after failures; a name is not asked in a loop).
347  alarm_s86         one row per alarm: the four times (first published, first seen, case opened, Telegram queued), the case, the freeze, who decided and when, and a cause when it was slow.
348  eyes_s86          one row per source the system watches with (news, filings, quotes): last answer, how long silent, whether the blind-spot line was said (and the "back" line).
350  us_quotes_s86    every US quote the session loop read: symbol, the quote's own time, its price, when it was fetched, the delay in minutes and the phase (pre / regular / post); the "eyes" read it.
351  us_fills_s86     every fill the US session loop made: the order, the decision's time, the quote's time and delay, the price, the spread and slippage estimate in basis points.
352  ghost_s86        the fast-forward's ghost record (H7): one row per replayed decision, never the real book; scored apart as `replayed_while_off`.
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
    (350, "us_quotes_s86", """
    CREATE TABLE IF NOT EXISTS us_quotes_s86 (
        symbol VARCHAR NOT NULL, quote_ts TIMESTAMP NOT NULL, price DOUBLE NOT NULL, fetched_at TIMESTAMP NOT NULL, delay_min DOUBLE, phase VARCHAR, PRIMARY KEY (symbol, quote_ts)
    );
    """),
    (351, "us_fills_s86", """
    CREATE TABLE IF NOT EXISTS us_fills_s86 (
        order_id INTEGER PRIMARY KEY, symbol VARCHAR, side VARCHAR, decision_ts TIMESTAMP, quote_ts TIMESTAMP, delay_min DOUBLE, quote_price DOUBLE, fill_price DOUBLE, est_bps DOUBLE, session_day DATE,
        filled_at TIMESTAMP, kind VARCHAR
    );
    """),
    (352, "ghost_s86", """
    CREATE TABLE IF NOT EXISTS ghost_s86 (
        ghost_id BIGINT PRIMARY KEY, gap_id BIGINT, release VARCHAR, isin VARCHAR, symbol VARCHAR, market VARCHAR, decided_at TIMESTAMP, option VARCHAR, source VARCHAR, headline VARCHAR,
        fill_ts TIMESTAMP, fill_price DOUBLE, qty DOUBLE, live_price DOUBLE, cost_of_being_off_inr DOUBLE, label VARCHAR, scored_5 DOUBLE, scored_20 DOUBLE, scored_60 DOUBLE, case_id BIGINT
    );
    """),
    (349, "alarm_gap_s86", """
    CREATE TABLE IF NOT EXISTS alarm_gap_s86 (
        gap_id BIGINT PRIMARY KEY, off_from TIMESTAMP, off_to TIMESTAMP, found_at TIMESTAMP, items INTEGER, red INTEGER, message VARCHAR, release VARCHAR
    );
    """),
]

MIGRATIONS += [
    (353, "page_loads_s86", """
    CREATE TABLE IF NOT EXISTS page_loads_s86 (loaded_at TIMESTAMP, path VARCHAR, status INTEGER, ms DOUBLE);
    """),
    (354, "problems_s86", """
    CREATE TABLE IF NOT EXISTS problems_s86 (
        problem_id BIGINT PRIMARY KEY, kind VARCHAR, key VARCHAR, text VARCHAR, context VARCHAR, first_seen TIMESTAMP, last_seen TIMESTAMP, times INTEGER, reported_at TIMESTAMP
    );
    """),
]
MIGRATIONS += [
    (355, "ghost_model_s86", """
    ALTER TABLE ghost_s86 ADD COLUMN IF NOT EXISTS code_option VARCHAR;
    ALTER TABLE ghost_s86 ADD COLUMN IF NOT EXISTS model_class VARCHAR;
    ALTER TABLE ghost_s86 ADD COLUMN IF NOT EXISTS model_words VARCHAR;
    ALTER TABLE ghost_s86 ADD COLUMN IF NOT EXISTS model_reason VARCHAR;
    ALTER TABLE ghost_s86 ADD COLUMN IF NOT EXISTS model_cost DOUBLE;
    ALTER TABLE ghost_s86 ADD COLUMN IF NOT EXISTS replay_key VARCHAR;
    ALTER TABLE ghost_s86 ADD COLUMN IF NOT EXISTS steps VARCHAR;
    ALTER TABLE ghost_s86 ADD COLUMN IF NOT EXISTS gain_after_tax DOUBLE;
    """),
]
MIGRATIONS += [
    (356, "ghost_after_tax_s86", """
    ALTER TABLE ghost_s86 ADD COLUMN IF NOT EXISTS at_5 DOUBLE;
    ALTER TABLE ghost_s86 ADD COLUMN IF NOT EXISTS at_20 DOUBLE;
    ALTER TABLE ghost_s86 ADD COLUMN IF NOT EXISTS at_60 DOUBLE;
    """),
]
MIGRATIONS.sort(key=lambda m: m[0])
