"""S79b item K: what the minute-bar history on disk covers (one row per name; the bars themselves are parquet under PFLAB_DATA_DIR\\bars_1m, see `ingest/kite_backfill.py`).
`bars_1m` itself keeps only the last 60 sessions. A day that came back short is counted in `short_days` and listed in the name's state file: stated, never filled."""

MIGRATIONS = [
    (100, "bars_1m_history_s79", """
    CREATE TABLE bars_1m_history_s79 (
        market VARCHAR NOT NULL, name VARCHAR NOT NULL, isin VARCHAR,
        first_day DATE, last_day DATE, n_rows BIGINT, n_windows INTEGER, short_days INTEGER, bytes BIGINT, updated_at TIMESTAMP NOT NULL,
        PRIMARY KEY (market, name)
    );
    """),
]
