"""S79 item 12: the bull-vs-bear debate on the local model and the scored bear warnings (versions 75-76)."""

MIGRATIONS = [
    (75, "debates_s79", """
    CREATE TABLE debates_s79 (
        debate_id INTEGER PRIMARY KEY, market VARCHAR NOT NULL, subject VARCHAR NOT NULL, symbol VARCHAR, case_id INTEGER,
        created_at TIMESTAMP NOT NULL, bull_json VARCHAR, bear_json VARCHAR, disagreements_json VARCHAR,
        evidence_ids VARCHAR, evidence_json VARCHAR, status VARCHAR NOT NULL, seconds DOUBLE
    );
    """),
    (76, "bear_warnings_s79", """
    CREATE TABLE bear_warnings_s79 (
        warning_id INTEGER PRIMARY KEY, debate_id INTEGER NOT NULL, market VARCHAR NOT NULL, symbol VARCHAR NOT NULL, isin VARCHAR,
        claim VARCHAR NOT NULL, direction VARCHAR NOT NULL, horizon_sessions INTEGER NOT NULL, benchmark VARCHAR NOT NULL,
        threshold_pct DOUBLE, ref_date DATE NOT NULL, ref_close DOUBLE NOT NULL, bench_ref DOUBLE, base_rate DOUBLE,
        made_at TIMESTAMP NOT NULL, due_date DATE NOT NULL, resolved_at TIMESTAMP, outcome VARCHAR, hit BOOLEAN, detail VARCHAR
    );
    """),
]
