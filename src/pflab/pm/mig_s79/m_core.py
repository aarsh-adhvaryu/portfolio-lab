"""S80 phase 1 (v2 core, `pflab/core`): version 102.

103  core_cards_s80: the book card written by code at each close (text, estimated tokens, the facts the next card is compared with).
102  core_policies_s80: the versioned policies (champion / challenger / retired) with the code hash and why; core_runs_s80: one row per session the close loop ran, with the
     state it saw, the targets the policy gave, what the rails did to them and the orders placed (the loop's whole audit trail).
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
]
