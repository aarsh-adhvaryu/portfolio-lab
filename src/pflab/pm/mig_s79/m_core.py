"""S80 (v2 core, `pflab/core` and the strategy lab `pflab/lab`): versions 102-107.

102  core_policies_s80: the versioned policies (champion / challenger / retired) with the code hash and why; core_runs_s80: one row per session the close loop ran, with the
     state it saw, the targets the policy gave, what the rails did to them and the orders placed (the loop's whole audit trail).
103  core_cards_s80: the book card written by code at each close (text, estimated tokens, the facts the next card is compared with).
104  lab_s80: the strategy lab: policy code and lineage on core_policies_s80, lab_runs_s80 (every scored variant), core_shadow_s80 (challengers in shadow), core_promotions_s80,
     core_sessions_s80 (strategist sessions), core_notes_s80 (the strategist's memory).
105  story_s80: storylines (the world model that replaces the situation report): claim, signals (measurable, tied to a series), dated evidence for and against, exposure per
     holding, probability by code each close, predictions at 5 and 20 sessions scored when due, and the record of which kinds of story hold.
106  views_s80: the tactical lane: the strategist's same-day views (direction, names, share of the tactical budget, horizon, exit, storyline), executed at the close and scored.
107  checker_s80: Sonnet's pass-or-veto on big trades.
"""
MIGRATIONS = [
    (102, "core_s80", """
    CREATE TABLE IF NOT EXISTS core_policies_s80 (
        policy_id VARCHAR PRIMARY KEY, status VARCHAR NOT NULL, code_hash VARCHAR, created_at TIMESTAMP NOT NULL, promoted_at TIMESTAMP, note VARCHAR
    );
    CREATE TABLE IF NOT EXISTS core_runs_s80 (
        day DATE PRIMARY KEY, ran_at TIMESTAMP NOT NULL, policy_id VARCHAR NOT NULL, status VARCHAR NOT NULL, seconds DOUBLE, state_json VARCHAR,
        targets_json VARCHAR, clipped_json VARCHAR, orders_json VARCHAR, skipped_json VARCHAR, note VARCHAR
    );
    """),
    (103, "core_cards_s80", """
    CREATE TABLE IF NOT EXISTS core_cards_s80 (
        day DATE PRIMARY KEY, made_at TIMESTAMP NOT NULL, text VARCHAR NOT NULL, tokens_est INTEGER, facts_json VARCHAR
    );
    """),
    (104, "lab_s80", """
    ALTER TABLE core_policies_s80 ADD COLUMN parent_id VARCHAR;
    ALTER TABLE core_policies_s80 ADD COLUMN hypothesis VARCHAR;
    ALTER TABLE core_policies_s80 ADD COLUMN session_id INTEGER;
    ALTER TABLE core_policies_s80 ADD COLUMN code VARCHAR;
    ALTER TABLE core_policies_s80 ADD COLUMN params_json VARCHAR;
    CREATE TABLE IF NOT EXISTS lab_runs_s80 (
        run_id INTEGER PRIMARY KEY, policy_id VARCHAR NOT NULL, win VARCHAR NOT NULL, params_json VARCHAR NOT NULL, ran_at TIMESTAMP NOT NULL, session_id INTEGER,
        score_json VARCHAR, shuffled_json VARCHAR, mc_json VARCHAR, dsr DOUBLE, sharpe_daily DOUBLE, n_trials INTEGER, seconds DOUBLE, contained BOOLEAN
    );
    CREATE TABLE IF NOT EXISTS core_shadow_s80 (
        day DATE NOT NULL, policy_id VARCHAR NOT NULL, weights_json VARCHAR, ret DOUBLE, scored_at TIMESTAMP, PRIMARY KEY (day, policy_id)
    );
    CREATE TABLE IF NOT EXISTS core_promotions_s80 (
        promo_id INTEGER PRIMARY KEY, happened_at TIMESTAMP NOT NULL, kind VARCHAR NOT NULL, from_policy VARCHAR, to_policy VARCHAR, diff VARCHAR, scorecard_json VARCHAR, reason VARCHAR
    );
    CREATE TABLE IF NOT EXISTS core_sessions_s80 (
        session_id INTEGER PRIMARY KEY, started_at TIMESTAMP NOT NULL, finished_at TIMESTAMP, reason VARCHAR, status VARCHAR NOT NULL, model VARCHAR, cost_inr DOUBLE,
        lab_runs INTEGER, variants INTEGER, challengers INTEGER, budget_inr DOUBLE, note VARCHAR, transcript_json VARCHAR
    );
    CREATE TABLE IF NOT EXISTS core_notes_s80 (
        note_id INTEGER PRIMARY KEY, session_id INTEGER, written_at TIMESTAMP NOT NULL, text VARCHAR NOT NULL
    );
    """),
    (105, "story_s80", """
    CREATE TABLE IF NOT EXISTS storylines_s80 (
        storyline_id INTEGER PRIMARY KEY, market VARCHAR NOT NULL, claim VARCHAR NOT NULL, kind VARCHAR, direction INTEGER NOT NULL, subject VARCHAR NOT NULL,
        opened_on DATE NOT NULL, status VARCHAR NOT NULL, status_on DATE, prior DOUBLE NOT NULL, probability DOUBLE, ai_adjust DOUBLE, ai_reason VARCHAR, influence DOUBLE,
        created_by VARCHAR, updated_at TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS storyline_signals_s80 (
        signal_id INTEGER PRIMARY KEY, storyline_id INTEGER NOT NULL, template VARCHAR, series VARCHAR NOT NULL, transform VARCHAR NOT NULL, op VARCHAR NOT NULL,
        threshold DOUBLE NOT NULL, stance VARCHAR NOT NULL, weight DOUBLE NOT NULL, label VARCHAR
    );
    CREATE TABLE IF NOT EXISTS storyline_evidence_s80 (
        evidence_id INTEGER PRIMARY KEY, storyline_id INTEGER NOT NULL, evidence_date DATE NOT NULL, stance VARCHAR NOT NULL, text VARCHAR NOT NULL, source_kind VARCHAR NOT NULL,
        source_ref VARCHAR, strength DOUBLE NOT NULL, added_by VARCHAR, added_at TIMESTAMP, dedup VARCHAR UNIQUE
    );
    CREATE TABLE IF NOT EXISTS storyline_exposure_s80 (
        storyline_id INTEGER NOT NULL, isin VARCHAR NOT NULL, exposure DOUBLE NOT NULL, source VARCHAR, as_of DATE, PRIMARY KEY (storyline_id, isin)
    );
    CREATE TABLE IF NOT EXISTS storyline_predictions_s80 (
        pred_id INTEGER PRIMARY KEY, storyline_id INTEGER NOT NULL, made_on DATE NOT NULL, horizon_sessions INTEGER NOT NULL, subject VARCHAR NOT NULL, expected_sign INTEGER NOT NULL,
        ref_level DOUBLE, due_on DATE NOT NULL, scored_at TIMESTAMP, outcome VARCHAR, outcome_json VARCHAR, UNIQUE (storyline_id, made_on, horizon_sessions, subject)
    );
    CREATE TABLE IF NOT EXISTS storyline_prob_s80 (
        storyline_id INTEGER NOT NULL, prob_date DATE NOT NULL, probability DOUBLE NOT NULL, logodds DOUBLE, detail_json VARCHAR, PRIMARY KEY (storyline_id, prob_date)
    );
    CREATE TABLE IF NOT EXISTS storyline_record_s80 (
        kind VARCHAR PRIMARY KEY, n_open INTEGER, n_confirmed INTEGER, n_faded INTEGER, n_broken INTEGER, mean_sessions DOUBLE, updated_at TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS storyline_reader_s80 (
        item_key VARCHAR PRIMARY KEY, read_at TIMESTAMP NOT NULL, action VARCHAR, storyline_id INTEGER, rule VARCHAR, outcome VARCHAR, cost_rupees DOUBLE
    );
    """),
    (106, "views_s80", """
    CREATE TABLE IF NOT EXISTS core_views_s80 (
        view_id INTEGER PRIMARY KEY, made_on DATE NOT NULL, made_at TIMESTAMP NOT NULL, session_id INTEGER, storyline_id INTEGER, direction INTEGER NOT NULL, names_json VARCHAR NOT NULL,
        share_of_budget DOUBLE NOT NULL, horizon_sessions INTEGER NOT NULL, exit_json VARCHAR, reason VARCHAR, status VARCHAR NOT NULL, due_on DATE, ref_level DOUBLE, executed_json VARCHAR,
        scored_at TIMESTAMP, outcome VARCHAR, outcome_json VARCHAR
    );
    """),
    (107, "checker_s80", """
    CREATE TABLE IF NOT EXISTS core_checks_s80 (
        check_id INTEGER PRIMARY KEY, day DATE NOT NULL, checked_at TIMESTAMP NOT NULL, kind VARCHAR NOT NULL, subject VARCHAR, order_json VARCHAR, verdict VARCHAR NOT NULL, reason VARCHAR,
        cost_inr DOUBLE, model VARCHAR
    );
    """),
]
