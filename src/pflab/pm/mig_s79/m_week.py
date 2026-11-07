"""S79b migration 101: the app's own first-week check (armed at its first start on this release) and the modes it has actually reached."""
MIGRATIONS = [
    (101, "week_check_s79", """
    CREATE TABLE week_check_s79 (
        check_id INTEGER PRIMARY KEY, armed_at TIMESTAMP NOT NULL, release VARCHAR,
        verdict VARCHAR,                       -- pass | fail | not_yet | NULL while waiting
        verdict_at TIMESTAMP, details_json VARCHAR, sent BOOLEAN DEFAULT FALSE, freeze_from DATE
    );
    CREATE TABLE mode_seen_s79 (
        day DATE NOT NULL, market VARCHAR NOT NULL, mode VARCHAR NOT NULL, first_seen TIMESTAMP NOT NULL,
        PRIMARY KEY (day, market, mode)
    );
    """),
]
