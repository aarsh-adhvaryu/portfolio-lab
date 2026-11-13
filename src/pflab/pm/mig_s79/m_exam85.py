"""S85 exam and shadow: versions 300-304 (301-304 spare).

300  think_calibration_engine_s85 (the likelihood word -> probability table PER ENGINE: an engine other than claude starts from the default table and is corrected by its own scored cases; claude keeps
     `think_calibration_s84`), think_shadow_s85 (what a shadow engine would have chosen for a case, beside the in-use engine's decision; scored at 5/20/60 like the model's, never acts).
"""
MIGRATIONS = [
    (300, "engine_calibration_shadow_s85", """
    CREATE TABLE IF NOT EXISTS think_calibration_engine_s85 (
        engine VARCHAR, word VARCHAR, probability DOUBLE, n BIGINT, hits BIGINT, updated_on DATE, PRIMARY KEY (engine, word)
    );
    CREATE TABLE IF NOT EXISTS think_shadow_s85 (
        shadow_id BIGINT PRIMARY KEY, case_id BIGINT, engine VARCHAR, decided_on DATE, isin VARCHAR, symbol VARCHAR, klass VARCHAR, option VARCHAR, rule_option VARCHAR,
        cost_rupees DOUBLE, note VARCHAR, created_at TIMESTAMP, words_json VARCHAR
    );
    """),
]
