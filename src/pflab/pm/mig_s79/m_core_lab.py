"""S81 core-lab (B1-B3): versions 108-112.

108  sleeves_s81: every position belongs to one sleeve (core, longterm, swing), set when an order is placed (the contract shared with the exits and swing work).
109  probation_s81: the satellite slices of lab variants (A50): every grant, growth, hold and withdrawal with its reason and record, newest last.
110  allocation_sleeves_s81: the sleeve shares of a proposed allocation target (the strategist's `propose_allocation`), and the lab variant that stands for it.
111  alloc_verdicts_s81: what the adoption rule (A50) found about each proposed allocation, with its figures.
112  spare.
"""
MIGRATIONS = [
    (108, "sleeves_s81", """
    CREATE TABLE IF NOT EXISTS sleeves_s81 (
        market VARCHAR NOT NULL, isin VARCHAR NOT NULL, sleeve VARCHAR NOT NULL, opened_on DATE, PRIMARY KEY (market, isin)
    );
    """),
    (109, "probation_s81", """
    CREATE TABLE IF NOT EXISTS probation_s81 (
        change_id INTEGER PRIMARY KEY, policy_id VARCHAR NOT NULL, changed_on DATE NOT NULL, kind VARCHAR NOT NULL, share DOUBLE NOT NULL, reason VARCHAR NOT NULL,
        record_json VARCHAR, made_at TIMESTAMP NOT NULL
    );
    """),
    (110, "allocation_sleeves_s81", """
    CREATE TABLE IF NOT EXISTS allocation_sleeves_s81 (
        target_id INTEGER PRIMARY KEY, market VARCHAR NOT NULL, sleeves_json VARCHAR NOT NULL, variant_policy VARCHAR, made_at TIMESTAMP NOT NULL
    );
    """),
    (111, "alloc_verdicts_s81", """
    CREATE TABLE IF NOT EXISTS alloc_verdicts_s81 (
        verdict_id INTEGER PRIMARY KEY, target_id INTEGER, policy_id VARCHAR NOT NULL, decided_at TIMESTAMP NOT NULL, outcome VARCHAR NOT NULL, reasons_json VARCHAR, figures_json VARCHAR
    );
    """),
    (112, "core_lab_spare_s81", """
    CREATE TABLE IF NOT EXISTS core_lab_spare_s81 (k VARCHAR PRIMARY KEY, v VARCHAR);
    """),
]
