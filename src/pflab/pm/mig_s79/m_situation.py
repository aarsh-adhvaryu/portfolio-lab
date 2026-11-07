"""S79b item 16 (the shared situation): typed claims per market, the synthesized reports, the causal chains, the predictions scored later.
Versions 81-84 are reserved for this item."""
MIGRATIONS = [
    (81, "situation_claims", """
    CREATE TABLE situation_claim (
        claim_id INTEGER PRIMARY KEY, market VARCHAR NOT NULL, kind VARCHAR NOT NULL, subject VARCHAR NOT NULL, text VARCHAR,
        value DOUBLE, entities VARCHAR, themes VARCHAR, call_ids VARCHAR, confidence DOUBLE,
        as_of DATE NOT NULL, created_at TIMESTAMP NOT NULL, ttl_sessions INTEGER, expires_on DATE, source VARCHAR, run_id INTEGER
    );
    """),
    (82, "situation_reports", """
    CREATE TABLE situation_report (
        report_id INTEGER PRIMARY KEY, market VARCHAR NOT NULL, as_of DATE NOT NULL, mode VARCHAR, created_at TIMESTAMP NOT NULL,
        author VARCHAR, coded_only BOOLEAN, sections VARCHAR, text VARCHAR, n_claims INTEGER, sources VARCHAR, flags VARCHAR, rejected VARCHAR
    );
    CREATE TABLE situation_run (
        run_id INTEGER PRIMARY KEY, market VARCHAR NOT NULL, as_of DATE NOT NULL, mode VARCHAR, started_at TIMESTAMP NOT NULL,
        finished_at TIMESTAMP, report_id INTEGER, n_claims INTEGER, sources VARCHAR, note VARCHAR
    );
    """),
    (83, "situation_chains", """
    CREATE TABLE situation_chain (
        chain_id INTEGER PRIMARY KEY, report_id INTEGER, market VARCHAR NOT NULL, as_of DATE NOT NULL, chain_type VARCHAR,
        links VARCHAR, ok BOOLEAN, reason VARCHAR, created_at TIMESTAMP NOT NULL
    );
    CREATE TABLE situation_contradiction (
        contradiction_id INTEGER PRIMARY KEY, report_id INTEGER, market VARCHAR NOT NULL, as_of DATE NOT NULL, subject VARCHAR,
        claim_ids VARCHAR, explanations VARCHAR, agenda_item_id INTEGER, created_at TIMESTAMP NOT NULL
    );
    """),
    (84, "situation_predictions", """
    CREATE TABLE situation_prediction (
        pred_id INTEGER PRIMARY KEY, report_id INTEGER, market VARCHAR NOT NULL, made_on DATE NOT NULL, chain_type VARCHAR,
        statement VARCHAR, series VARCHAR, direction VARCHAR, threshold DOUBLE, probability DOUBLE, call_ids VARCHAR,
        horizons VARCHAR, created_at TIMESTAMP NOT NULL, event VARCHAR, level DOUBLE
    );
    CREATE TABLE situation_watch (
        watch_id INTEGER PRIMARY KEY, market VARCHAR NOT NULL, report_id INTEGER, claim_id INTEGER, text VARCHAR NOT NULL, series VARCHAR NOT NULL,
        op VARCHAR NOT NULL, threshold DOUBLE NOT NULL, set_on DATE NOT NULL, expires_on DATE, status VARCHAR NOT NULL, fired_on DATE, fired_value DOUBLE,
        agenda_item_id INTEGER, created_at TIMESTAMP NOT NULL
    );
    CREATE TABLE situation_outcome (
        pred_id INTEGER NOT NULL, horizon INTEGER NOT NULL, target_date DATE, outcome INTEGER, observed DOUBLE, brier DOUBLE,
        scored_at TIMESTAMP, PRIMARY KEY (pred_id, horizon)
    );
    """),
]
