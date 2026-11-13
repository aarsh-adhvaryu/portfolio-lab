"""S84 T10 the daily desk (`think/desk.py`): versions 255-256 (257-259 spare).

255  desk_sessions_s84: one row per working session of the desk (a person at a desk with an agenda): the day, the mode (india_close | us_morning | catchup), the slots it covers (a catch-up
     covers every slot missed, in ONE session), the status (running | done | quiet | budget | failed), what it spent, the agenda as built by code, and the plan text for Today and the reports.
256  desk_steps_s84: one row per agenda item worked: its rank, kind and reference, the engine, model and thinking level that made it, the cost, the status (done | noted | used | skipped |
     not_reached | failed) and the finding.
"""
MIGRATIONS = [
    (255, "desk_sessions_s84", """
    CREATE TABLE IF NOT EXISTS desk_sessions_s84 (
        session_id BIGINT PRIMARY KEY, day DATE, mode VARCHAR, covers VARCHAR, started_at TIMESTAMP, finished_at TIMESTAMP, since_at TIMESTAMP, status VARCHAR, cost_rupees DOUBLE,
        budget_rupees DOUBLE, agenda_json VARCHAR, plan_text VARCHAR, note VARCHAR
    );
    """),
    (256, "desk_steps_s84", """
    CREATE TABLE IF NOT EXISTS desk_steps_s84 (
        step_id BIGINT PRIMARY KEY, session_id BIGINT, ord INTEGER, kind VARCHAR, ref VARCHAR, market VARCHAR, symbol VARCHAR, step_at TIMESTAMP, engine VARCHAR, model VARCHAR,
        thinking VARCHAR, cost_rupees DOUBLE, cached_tokens BIGINT, status VARCHAR, finding VARCHAR
    );
    """),
]
