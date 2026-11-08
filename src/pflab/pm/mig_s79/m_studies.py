"""S79b items 15, 15b, 7b: the pre-registered event studies' results. Versions 98-99 are reserved for this item (99 is spare)."""
MIGRATIONS = [
    (98, "wave_study_results_s79", """
    CREATE TABLE wave_study_results_s79 (
        test VARCHAR NOT NULL, market VARCHAR NOT NULL, n_events INTEGER, n_baseline INTEGER, effect DOUBLE, ci_low DOUBLE, ci_high DOUBLE,
        p DOUBLE, t_needed DOUBLE, n_counter INTEGER, passed BOOLEAN, verdict VARCHAR, halves_json VARCHAR, ran_at TIMESTAMP,
        protocol_sha VARCHAR, code_sha VARCHAR,
        PRIMARY KEY (test, market)
    );
    """),
]
