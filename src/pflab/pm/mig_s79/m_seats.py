"""S79b item 17 (local-first compute): the seat swaps, the escalation log and the teacher log. Versions 94-95 are reserved for this item."""
MIGRATIONS = [
    (94, "seats_escalation_s79", """
    CREATE TABLE IF NOT EXISTS escalation_log_s79 (
        esc_id INTEGER PRIMARY KEY, market VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL, kind VARCHAR, subject VARCHAR, rule VARCHAR NOT NULL,
        n_samples INTEGER, n_valid INTEGER, agreed BOOLEAN, confidence DOUBLE, cloud_used BOOLEAN, cap_ok BOOLEAN, cost_rupees DOUBLE,
        answer VARCHAR, seat VARCHAR, note VARCHAR
    );
    CREATE TABLE IF NOT EXISTS seat_event_s79 (
        event_id INTEGER PRIMARY KEY, market VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL, mode VARCHAR, seat VARCHAR, model VARCHAR, backend VARCHAR,
        action VARCHAR, applied BOOLEAN, free_ram_gb DOUBLE, reason VARCHAR
    );
    """),
    (95, "teacher_log_s79", """
    CREATE TABLE IF NOT EXISTS teacher_log_s79 (
        teacher_id INTEGER PRIMARY KEY, market VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL, call_id INTEGER, source VARCHAR, agent VARCHAR, model VARCHAR,
        system_text VARCHAR, input_text VARCHAR, output_text VARCHAR, tokens_in INTEGER, tokens_out INTEGER, cost_inr DOUBLE,
        n_redactions INTEGER, sha VARCHAR, score DOUBLE, score_kind VARCHAR, scored_at TIMESTAMP, note VARCHAR
    );
    """),
]
