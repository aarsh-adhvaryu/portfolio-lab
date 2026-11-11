"""S82 item C4, the lab agent's migrations (versions 160-164).

160  c4_study_s82: the verdict rows of the registered C4 studies (kind 'a_index', 'a_stocks', 'b_stops'; one row per (kind, subject); the table also makes `c4_study.run` refuse a second run).
"""
MIGRATIONS = [
    (160, "c4_study_s82", """
    CREATE TABLE IF NOT EXISTS c4_study_s82 (
        run_id INTEGER PRIMARY KEY, kind VARCHAR NOT NULL, subject VARCHAR NOT NULL, ran_at TIMESTAMP NOT NULL, span VARCHAR, verdict VARCHAR, summary_json VARCHAR,
        protocol_sha VARCHAR, UNIQUE (kind, subject)
    );
    """),
]
