"""S79 item 5 (never idle): the agenda the system owns and works through when nothing urgent is happening."""
MIGRATIONS = [
    (65, "agenda_s79", """
    CREATE TABLE mind_agenda (
        item_id INTEGER PRIMARY KEY, market VARCHAR NOT NULL, kind VARCHAR NOT NULL, subject VARCHAR NOT NULL, reason VARCHAR,
        expected_value DOUBLE, cost_rupees DOUBLE, cost_seconds DOUBLE, state VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL,
        started_at TIMESTAMP, finished_at TIMESTAMP, outcome VARCHAR, useful BOOLEAN, effect VARCHAR, skip_reason VARCHAR, payload VARCHAR
    );
    CREATE TABLE agenda_kind_stats (
        market VARCHAR NOT NULL, kind VARCHAR NOT NULL, n_done INTEGER, n_useful INTEGER, "yield" DOUBLE, multiplier DOUBLE,
        updated_at TIMESTAMP, PRIMARY KEY (market, kind)
    );
    """),
]
