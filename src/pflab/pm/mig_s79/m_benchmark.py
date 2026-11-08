"""S79b items 18B and 18E (versions 86-87).

86  blended_benchmark_s79: the benchmark that matches the system's own allocation, one row per marked day, recorded point-in-time (weights in force, the day's return of each
    class, the level, and which target the weights come from); attribution_s79: the monthly split of the book's excess return into allocation, selection, timing, costs, tax
    and an explicit residual.
87  verify_book_s79: the log of the book verification harness (corporate actions applied, top-ups deployed): what was checked, and whether it held.
"""
MIGRATIONS = [
    (86, "blended_benchmark_attribution_s79", """
    CREATE TABLE IF NOT EXISTS blended_benchmark_s79 (
        market VARCHAR NOT NULL, as_of DATE NOT NULL, weights_json VARCHAR NOT NULL, level DOUBLE NOT NULL, day_return DOUBLE, class_ret_json VARCHAR,
        source VARCHAR, target_id INTEGER, rebalanced BOOLEAN, computed_at TIMESTAMP, PRIMARY KEY (market, as_of)
    );
    CREATE TABLE IF NOT EXISTS attribution_s79 (
        market VARCHAR NOT NULL, month DATE NOT NULL, period_start DATE, period_end DATE, sessions INTEGER, book_return DOUBLE, bench_return DOUBLE, excess DOUBLE,
        allocation DOUBLE, selection DOUBLE, timing DOUBLE, costs DOUBLE, tax DOUBLE, residual DOUBLE, detail_json VARCHAR, computed_at TIMESTAMP,
        PRIMARY KEY (market, month)
    );
    """),
    (87, "verify_book_s79", """
    CREATE TABLE IF NOT EXISTS verify_book_s79 (
        run_id INTEGER PRIMARY KEY, market VARCHAR, ran_at TIMESTAMP NOT NULL, kind VARCHAR NOT NULL, ok BOOLEAN NOT NULL, checks_json VARCHAR, note VARCHAR
    );
    """),
]
