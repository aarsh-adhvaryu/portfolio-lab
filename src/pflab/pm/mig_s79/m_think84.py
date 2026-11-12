"""S84 (A64-A68, the thinking loop `pflab/think/`): versions 230-233 (234-239 are spare). ONE module for the shared tables so every agent's branch carries the same DDL.

230  think_signals_s84: one row per signal the watch noticed (a number with its threshold, the surprise, the exposure in rupees and a score); `case_id` is set when it opened or joined a case,
     `status` says whether it was examined (new, joined, examined, not_examined).
231  think_cases_s84: one row per case (a situation thought through); its steps, options, decisions and scores hang on `case_id`.
232  think_steps_s84 / think_options_s84 / think_decisions_s84 / think_scores_s84: the six steps of the loop, stored with the engine, model, thinking level, cost and cached tokens that made each model step;
     the options of both tracks ('rule' and 'model') in rupees; the decision (what the rule chose, what the model chose, what was done); the scores at 5, 20 and 60 sessions against every option not taken.
233  think_calibration_s84 (the likelihood word -> probability table T8 corrects), think_freezes_s84 (a system-made "no new buying of X until <date or event>"), knowledge_use_s84 (what `recall`
     handed to a decision) and think_misses_s84 (a move on an exposed name that opened no case in the two sessions before, and false alarms).
"""
MIGRATIONS = [
    (230, "think_signals_s84", """
    CREATE TABLE IF NOT EXISTS think_signals_s84 (
        signal_id BIGINT PRIMARY KEY, case_id BIGINT, day DATE, ts TIMESTAMP, market VARCHAR, isin VARCHAR, symbol VARCHAR, signal VARCHAR, value DOUBLE, threshold DOUBLE,
        surprise DOUBLE, exposure_inr DOUBLE, score DOUBLE, detail_json VARCHAR, status VARCHAR
    );
    """),
    (231, "think_cases_s84", """
    CREATE TABLE IF NOT EXISTS think_cases_s84 (
        case_id BIGINT PRIMARY KEY, opened_on DATE, opened_at TIMESTAMP, market VARCHAR, kind VARCHAR, isin VARCHAR, symbol VARCHAR, title VARCHAR, state VARCHAR, klass VARCHAR,
        pending VARCHAR, next_look_on DATE, next_look_cond VARCHAR, exposure_inr DOUBLE, exposure_pct DOUBLE, score DOUBLE, closed_on DATE, closed_reason VARCHAR, opened_by VARCHAR,
        summary VARCHAR, names_json VARCHAR
    );
    """),
    (232, "think_steps_options_decisions_scores_s84", """
    CREATE TABLE IF NOT EXISTS think_steps_s84 (
        step_id BIGINT PRIMARY KEY, case_id BIGINT, step_at TIMESTAMP, step VARCHAR, engine VARCHAR, model VARCHAR, thinking VARCHAR, cost_rupees DOUBLE, cached_tokens BIGINT, payload_json VARCHAR
    );
    CREATE TABLE IF NOT EXISTS think_options_s84 (
        option_id BIGINT PRIMARY KEY, case_id BIGINT, track VARCHAR, isin VARCHAR, symbol VARCHAR, option VARCHAR, worst_inr DOUBLE, likely_inr DOUBLE, best_inr DOUBLE, expected_inr DOUBLE,
        worst_pct_book DOUBLE, size_inr DOUBLE, reason VARCHAR, chosen BOOLEAN, created_at TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS think_decisions_s84 (
        decision_id BIGINT PRIMARY KEY, case_id BIGINT, decided_on DATE, isin VARCHAR, symbol VARCHAR, rule_option VARCHAR, model_option VARCHAR, acted_option VARCHAR, differs BOOLEAN,
        order_refs_json VARCHAR, reason VARCHAR, advisory BOOLEAN
    );
    CREATE TABLE IF NOT EXISTS think_scores_s84 (
        score_id BIGINT PRIMARY KEY, decision_id BIGINT, horizon_sessions INTEGER, track VARCHAR, option VARCHAR, result_inr DOUBLE, vs_nothing_inr DOUBLE, scored_on DATE
    );
    """),
    (233, "think_calibration_freezes_use_misses_s84", """
    CREATE TABLE IF NOT EXISTS think_calibration_s84 (
        word VARCHAR PRIMARY KEY, probability DOUBLE, n BIGINT, hits BIGINT, updated_on DATE
    );
    CREATE TABLE IF NOT EXISTS think_freezes_s84 (
        freeze_id BIGINT PRIMARY KEY, isin VARCHAR, symbol VARCHAR, market VARCHAR, since DATE, until DATE, until_event VARCHAR, case_id BIGINT, active BOOLEAN, reason VARCHAR
    );
    CREATE TABLE IF NOT EXISTS knowledge_use_s84 (
        use_id BIGINT PRIMARY KEY, item_kind VARCHAR, item_id VARCHAR, item_day DATE, used_by_kind VARCHAR, used_by_ref VARCHAR, day DATE
    );
    CREATE TABLE IF NOT EXISTS think_misses_s84 (
        miss_id BIGINT PRIMARY KEY, day DATE, kind VARCHAR, market VARCHAR, isin VARCHAR, symbol VARCHAR, move_pct DOUBLE, exposure_inr DOUBLE, detail VARCHAR
    );
    """),
]
