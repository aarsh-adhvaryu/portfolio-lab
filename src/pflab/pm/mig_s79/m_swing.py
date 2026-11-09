"""S81 item B5, the lab for swing (versions 118-122).

118  swing_study_s81: the registered swing / harvesting study's verdict rows (kind 'history' per variant, 'harvest', 'final' per variant: a 'final' row is written once and never again,
     so the 2018-2021 check cannot be repeated). One row per (kind, subject).
"""
MIGRATIONS = [
    (118, "swing_study_s81", """
    CREATE TABLE IF NOT EXISTS swing_study_s81 (
        run_id INTEGER PRIMARY KEY, kind VARCHAR NOT NULL, subject VARCHAR NOT NULL, ran_at TIMESTAMP NOT NULL, span VARCHAR, verdict VARCHAR, summary_json VARCHAR,
        protocol_sha VARCHAR, UNIQUE (kind, subject)
    );
    """),
]
