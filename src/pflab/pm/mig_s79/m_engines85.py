"""S85 engines (any model behind the one door, `llm/gateway.py`): versions 290-294 (295-299 are spare).

290  engine_state_s85 (the engine IN USE, one row key 'in_use'), engine_shadow_s85 (engines that think beside it and never act), engine_consent_s85 (his dated Yes per vendor and scope:
     exam / shadow / use, with the wording he was shown).
291  engine_events_s85 (one row per model call's outcome per engine and role: ok or the kind of failure; three in a row sends a call to the fallback) and engine_problems_s85 (the Problems list line
     and the once-a-day Telegram line).
292  engine_exam_s85 (what `pflab engine test` found: the form verdict, the grade in words, the thinking level, the cost) written through `gateway.record_exam`; the exam module owns the rest of its detail.
293  api_calls gets chat_id, reply_msg_id (E8: which chat and which reply a call served), vendor and fallback_from. Old rows keep NULL.
294  the consents that stand: Anthropic (the engine in use before S85) for every scope, and OpenAI for the exam and for shadow only (his Yes of 2026-11-12, given in the S85 text). Never for `use`.
"""
MIGRATIONS = [
    (290, "engine_state_shadow_consent_s85", """
    CREATE TABLE IF NOT EXISTS engine_state_s85 (key VARCHAR PRIMARY KEY, value VARCHAR, updated_at TIMESTAMP, note VARCHAR);
    CREATE TABLE IF NOT EXISTS engine_shadow_s85 (engine VARCHAR PRIMARY KEY, since TIMESTAMP, active BOOLEAN);
    CREATE TABLE IF NOT EXISTS engine_consent_s85 (consent_id BIGINT PRIMARY KEY, vendor VARCHAR, scope VARCHAR, given_at TIMESTAMP, given_by VARCHAR, wording VARCHAR, active BOOLEAN);
    """),
    (291, "engine_events_problems_s85", """
    CREATE TABLE IF NOT EXISTS engine_events_s85 (event_id BIGINT PRIMARY KEY, ts TIMESTAMP, engine VARCHAR, role VARCHAR, agent VARCHAR, model VARCHAR, ok BOOLEAN, kind VARCHAR, detail VARCHAR, call_id BIGINT);
    CREATE TABLE IF NOT EXISTS engine_problems_s85 (problem_id BIGINT PRIMARY KEY, ts TIMESTAMP, engine VARCHAR, role VARCHAR, text VARCHAR, told_on DATE);
    """),
    (292, "engine_exam_s85", """
    CREATE TABLE IF NOT EXISTS engine_exam_s85 (exam_id BIGINT PRIMARY KEY, engine VARCHAR, ts TIMESTAMP, thinking VARCHAR, form_pass BOOLEAN, grade VARCHAR, cost_rupees DOUBLE, detail_json VARCHAR);
    """),
    (293, "api_calls_chat_vendor_s85", """
    ALTER TABLE api_calls ADD COLUMN IF NOT EXISTS chat_id BIGINT;
    ALTER TABLE api_calls ADD COLUMN IF NOT EXISTS reply_msg_id BIGINT;
    ALTER TABLE api_calls ADD COLUMN IF NOT EXISTS vendor VARCHAR;
    ALTER TABLE api_calls ADD COLUMN IF NOT EXISTS fallback_from VARCHAR;
    """),
    (294, "engine_consents_seed_s85", """
    INSERT INTO engine_consent_s85 (consent_id, vendor, scope, given_at, given_by, wording, active)
    SELECT 1, 'anthropic', 'use', TIMESTAMP '2026-11-12 00:00:00', 'standing: the engine in use before S85',
           'Anthropic (Claude) has been the engine in use since the system began; holdings, amounts and weights may go to it, his identity and banking details never.', TRUE
    WHERE NOT EXISTS (SELECT 1 FROM engine_consent_s85 WHERE vendor='anthropic' AND scope='use');
    INSERT INTO engine_consent_s85 (consent_id, vendor, scope, given_at, given_by, wording, active)
    SELECT 2, 'openai', 'exam', TIMESTAMP '2026-11-12 23:59:00', 'his Yes of 2026-11-12 (S85 text), for tonight',
           'OpenAI may be sent what the exam and a shadow case need, which includes holdings, amounts and weights (never his identity or banking details), for the exam only.', TRUE
    WHERE NOT EXISTS (SELECT 1 FROM engine_consent_s85 WHERE vendor='openai' AND scope='exam');
    INSERT INTO engine_consent_s85 (consent_id, vendor, scope, given_at, given_by, wording, active)
    SELECT 3, 'openai', 'shadow', TIMESTAMP '2026-11-12 23:59:00', 'his Yes of 2026-11-12 (S85 text), for tonight',
           'OpenAI may be sent what a shadow case needs, which includes holdings, amounts and weights (never his identity or banking details); a shadow engine never acts.', TRUE
    WHERE NOT EXISTS (SELECT 1 FROM engine_consent_s85 WHERE vendor='openai' AND scope='shadow');
    """),
]
