"""S79 lead migrations 61-64: presence (app-open time), catch-up state and the away digest, question terms (default + deadline), button markup."""
MIGRATIONS = [
    (61, "app_presence_s79", """
    CREATE TABLE app_presence_s79 (
        seg_id INTEGER PRIMARY KEY, opened_at TIMESTAMP NOT NULL, last_beat TIMESTAMP NOT NULL,
        pid INTEGER, reason VARCHAR,              -- start | wake
        off_from TIMESTAMP, off_to TIMESTAMP      -- the gap this segment closed: "off from X to Y"
    );
    """),
    (62, "catchup_digest_s79", """
    CREATE TABLE catchup_s79 (
        catch_id INTEGER PRIMARY KEY, market VARCHAR NOT NULL, opened_at TIMESTAMP NOT NULL,
        from_session DATE, to_session DATE, missed_sessions INTEGER,
        stage VARCHAR,                            -- data | scoring | done
        state VARCHAR NOT NULL,                   -- running | done | failed
        finished_at TIMESTAMP, detail VARCHAR
    );
    CREATE TABLE away_digest_s79 (
        digest_id INTEGER PRIMARY KEY, created_at TIMESTAMP NOT NULL, off_from TIMESTAMP, off_to TIMESTAMP,
        text VARCHAR NOT NULL, facts_json VARCHAR, seen BOOLEAN DEFAULT FALSE
    );
    """),
    (63, "question_terms_s79", """
    CREATE TABLE question_terms_s79 (
        q_id INTEGER PRIMARY KEY, default_answer VARCHAR, deadline TIMESTAMP, urgent BOOLEAN DEFAULT FALSE,
        options_json VARCHAR, sent_at TIMESTAMP, resolved_by VARCHAR,      -- him | default
        resolved_at TIMESTAMP, market VARCHAR DEFAULT 'IN'
    );
    CREATE TABLE outbox_markup_s79 (msg_id INTEGER PRIMARY KEY, markup_json VARCHAR NOT NULL);
    """),
]
