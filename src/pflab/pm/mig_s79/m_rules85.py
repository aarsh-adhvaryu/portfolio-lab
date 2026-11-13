"""S85 `rules` (E4, A69 door b: standing instructions): versions 325-328 (329 is spare).

325  hq_rules.until: the date a rule lapses (the new kinds default to 30 days from the day they are made; older kinds keep NULL = no end).
326  rules_held_back_s85: every order a standing instruction skipped or shrank (day, market, name, side, the rule's id, name and words, where in the code it was met), the
     source of the "not bought: your rule ..." lines in the book card and the 15:45 report.
327  rules_notes_s85: what he said that fits no rule kind: a NOTE the strategist reads at its next session (status unread -> read).
328  rules_requests_s85: a chat request to change his targets, limits or stock list: it is put to him as a Yes/No question (a `limit_proposals` preference row) and nothing changes
     unless he says yes.
"""
MIGRATIONS = [
    (325, "hq_rules_until_s85", """
    ALTER TABLE hq_rules ADD COLUMN IF NOT EXISTS until DATE;
    """),
    (326, "rules_held_back_s85", """
    CREATE TABLE IF NOT EXISTS rules_held_back_s85 (
        held_id BIGINT PRIMARY KEY, day DATE, ts TIMESTAMP, market VARCHAR, isin VARCHAR, symbol VARCHAR, side VARCHAR, rule_id BIGINT, rule_name VARCHAR, rule_text VARCHAR,
        site VARCHAR, order_kind VARCHAR, value DOUBLE, note VARCHAR
    );
    """),
    (327, "rules_notes_s85", """
    CREATE TABLE IF NOT EXISTS rules_notes_s85 (
        note_id BIGINT PRIMARY KEY, created_at TIMESTAMP, text VARCHAR, source VARCHAR, chat_id BIGINT, status VARCHAR, read_at TIMESTAMP, read_by VARCHAR
    );
    """),
    (328, "rules_requests_s85", """
    CREATE TABLE IF NOT EXISTS rules_requests_s85 (
        request_id BIGINT PRIMARY KEY, created_at TIMESTAMP, text VARCHAR, prefs_kind VARCHAR, pref_key VARCHAR, pref_value VARCHAR, proposal_id BIGINT, q_id BIGINT, status VARCHAR,
        decided_at TIMESTAMP
    );
    """),
]
