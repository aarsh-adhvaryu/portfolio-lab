"""S79b item 18A (portfolio construction): the log of what `construct` computed (live advice, sizings it offered, and the one registered backtest comparison).
Version 85 is reserved for this item."""
MIGRATIONS = [
    (85, "construct_runs", """
    CREATE TABLE construct_runs_s85 (
        run_id BIGINT PRIMARY KEY, market VARCHAR NOT NULL, kind VARCHAR NOT NULL, as_of DATE, created_at TIMESTAMP NOT NULL,
        ok BOOLEAN, adopted BOOLEAN, summary_json VARCHAR, result_json VARCHAR
    );
    """),
]
