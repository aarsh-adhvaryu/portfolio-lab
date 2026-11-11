"""S83 L1 (the picks, `pflab/core/picks.py`): versions 170-171 (172-174 are spare).

170  picks_s83: one row per pick (market IN or US): the thesis, what would break it, the storylines it rests on, the session that made it, what the scorecard taught, and its state
     (proposed -> buying -> held -> withdrawn / stopped / broken). `source` is 'system' (a name the strategist picked) or 'kite' (one of his Kite stocks adopted with the thesis
     "held from his Kite portfolio" until the strategist writes a real one or withdraws it).
171  skips_s83: an idea the strategist looked at and skipped (a price record to score later, never a book).
"""
MIGRATIONS = [
    (170, "picks_s83", """
    CREATE TABLE IF NOT EXISTS picks_s83 (
        pick_id BIGINT PRIMARY KEY, market VARCHAR, isin VARCHAR, symbol VARCHAR, source VARCHAR, thesis VARCHAR, break_condition VARCHAR, storylines_json VARCHAR,
        session_ref VARCHAR, learned_from VARCHAR, state VARCHAR, proposed_on DATE, state_changed_on DATE, state_reason VARCHAR
    );
    """),
    (171, "skips_s83", """
    CREATE TABLE IF NOT EXISTS skips_s83 (
        skip_id BIGINT PRIMARY KEY, market VARCHAR, isin VARCHAR, symbol VARCHAR, why VARCHAR, skipped_on DATE, session_ref VARCHAR
    );
    """),
]
