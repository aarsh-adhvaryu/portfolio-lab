"""S79b item 18C (decision provenance): which sources stood behind each paper decision, how each was credited when the decision was scored, and the running
scorecard per source kind. Version 88 (reserved for this item).

decision_provenance_s79   one row per (decision, source_kind, source_id): who/what fed the decision. `weight` is how strongly (0 = listed for the record, not credited),
                          `direction` the source's own call on the stock (+1 up, -1 down, NULL = it backed the decision itself), `supports` whether the source stood WITH the
                          decision (NULL = cannot tell, not credited).
source_credit_s79         one row per (decision, source_kind, horizon): the decision's scored outcome credited to the source (hit/miss, contribution in percentage points).
source_scorecard_s79      the running table per (market, source_kind, decision_kind, horizon): n, hits, mean contribution; rebuilt from source_credit_s79 (idempotent).
"""
MIGRATIONS = [
    (88, "decision_provenance_s79", """
    CREATE TABLE IF NOT EXISTS decision_provenance_s79 (
        decision_id INTEGER NOT NULL, market VARCHAR NOT NULL, source_kind VARCHAR NOT NULL, source_id VARCHAR NOT NULL, role VARCHAR, weight DOUBLE,
        direction INTEGER, supports BOOLEAN, detail VARCHAR, recorded_at TIMESTAMP,
        PRIMARY KEY (decision_id, source_kind, source_id)
    );
    CREATE TABLE IF NOT EXISTS source_credit_s79 (
        decision_id INTEGER NOT NULL, market VARCHAR NOT NULL, source_kind VARCHAR NOT NULL, source_id VARCHAR, horizon_days INTEGER NOT NULL,
        decision_kind VARCHAR, outcome VARCHAR, supports BOOLEAN, hit BOOLEAN, gain_pct DOUBLE, contribution DOUBLE, due_on DATE, credited_at TIMESTAMP,
        PRIMARY KEY (decision_id, source_kind, horizon_days)
    );
    CREATE TABLE IF NOT EXISTS source_scorecard_s79 (
        market VARCHAR NOT NULL, source_kind VARCHAR NOT NULL, decision_kind VARCHAR NOT NULL, horizon_days INTEGER NOT NULL,
        n INTEGER NOT NULL, hits INTEGER NOT NULL, mean_outcome DOUBLE, updated_at TIMESTAMP,
        PRIMARY KEY (market, source_kind, decision_kind, horizon_days)
    );
    """),
]
