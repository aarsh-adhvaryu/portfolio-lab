"""S85 `loopchat` (E7, the chat and the thinking loop): versions 340-344 (`think/chat_hooks.py`).

340  watch_from_you_s85: every name he suggested ("look at X"): the verdict (pick / wait_for / pass), why, the condition it waits for, and the 120-session watch window (`since`..`until`). The watch
     scope includes a name while its row is active; `state` is active, queued (the day's 5 are used: it waits for the next desk), expired or done.
341  think_case_origin_s85: where a case came from when the entrance was the source (a "look into", a note he sent, a suggested name that reopened): the chat to tell, the words, the document.
     (A side table: `think_cases_s84` is filled by position, so a column there would break every writer.)
342  overrules_s85: "hold it" / "do not buy that": the case, the loop's own choice at that time, his choice; scored on the `user` track beside the rule and the model.
343  from_you_notes_s85: a note or report he sent that was already taken to the loop (the same document again costs nothing and opens nothing).
344  market_notes_s85: a note about the whole market or a sector: it goes to the storylines (a note with source "you") and to the next pre-open plan.
"""
MIGRATIONS = [
    (340, "watch_from_you_s85", """
    CREATE TABLE IF NOT EXISTS watch_from_you_s85 (
        watch_id BIGINT PRIMARY KEY, name VARCHAR, isin VARCHAR, symbol VARCHAR, market VARCHAR, suggested_on DATE, suggested_at TIMESTAMP, since DATE, until DATE, chat_id BIGINT,
        his_reason VARCHAR, state VARCHAR, verdict VARCHAR, why VARCHAR, thesis VARCHAR, condition_kind VARCHAR, condition_text VARCHAR, ref_price DOUBLE, ref_day DATE, floor_ok BOOLEAN,
        floor_note VARCHAR, cost_inr DOUBLE, skip_id BIGINT, met_on DATE, told_json VARCHAR
    );
    """),
    (341, "think_case_origin_s85", """
    CREATE TABLE IF NOT EXISTS think_case_origin_s85 (
        case_id BIGINT PRIMARY KEY, source VARCHAR, chat_id BIGINT, doc_id BIGINT, words VARCHAR, created_at TIMESTAMP, state VARCHAR, told_json VARCHAR
    );
    """),
    (342, "overrules_s85", """
    CREATE TABLE IF NOT EXISTS overrules_s85 (
        overrule_id BIGINT PRIMARY KEY, case_id BIGINT, isin VARCHAR, symbol VARCHAR, said_at TIMESTAMP, day DATE, words VARCHAR, user_option VARCHAR, loop_option VARCHAR, rule_id VARCHAR,
        chat_id BIGINT, kind VARCHAR
    );
    """),
    (343, "from_you_notes_s85", """
    CREATE TABLE IF NOT EXISTS from_you_notes_s85 (
        doc_id BIGINT PRIMARY KEY, processed_at TIMESTAMP, chat_id BIGINT, names_json VARCHAR, result_json VARCHAR
    );
    """),
    (344, "market_notes_s85", """
    CREATE TABLE IF NOT EXISTS market_notes_s85 (
        note_id BIGINT PRIMARY KEY, doc_id BIGINT, chat_id BIGINT, received_at TIMESTAMP, day DATE, scope VARCHAR, topic VARCHAR, text VARCHAR, state VARCHAR
    );
    """),
]
