"""S81 (coordinator): the chat can ask the strategist to look into something: version 143.

143  strategist_requests_s81: one row per request typed in the chat ("look into X"): the text, who asked, the state (open, running, done, refused) and the session that took it.
"""
MIGRATIONS = [
    (143, "strategist_requests_s81", """
    CREATE TABLE IF NOT EXISTS strategist_requests_s81 (
        req_id INTEGER PRIMARY KEY, made_at TIMESTAMP NOT NULL, text VARCHAR NOT NULL, made_by VARCHAR NOT NULL, status VARCHAR NOT NULL,
        session_id INTEGER, finished_at TIMESTAMP, note VARCHAR
    );
    """),
]
