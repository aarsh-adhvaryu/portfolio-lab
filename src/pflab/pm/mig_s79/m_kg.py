"""S81 B7: the knowledge graph rebuilt on the agreed design (docs/KG_AUDIT_S80.md). Versions 123-130.

Three layers and an audit; nothing is a row without an ISIN, a source and a date.
  kg2_node         one row per company/instrument ISIN in scope (name, symbol, source, as-of)
  kg2_fact         layer 1: structured facts by ISIN (key, value, source, as-of, known-from)
  kg2_relation     layer 2: relations by a NAMED rule (never written by a model)
  kg2_event        layer 3: filings and news attached to an ISIN by a confident rule, with the rule and its proof
  kg2_unlinked     events no confident rule could attach (kept as counts and reasons, never shown)
  kg2_event_class  the local model's classification of an event's kind and severity from a CLOSED list, validated by code (a cache: the graph reads it)
  kg2_audit        the nightly audit's verdict and its checks
  kg2_build        each build's input hash and output hashes (the rebuild-is-identical check)
"""

MIGRATIONS = [
    (123, "kg2_node_s81", """
    CREATE TABLE IF NOT EXISTS kg2_node (
        isin VARCHAR NOT NULL PRIMARY KEY, name VARCHAR, symbol VARCHAR, origin VARCHAR, source VARCHAR NOT NULL, as_of DATE NOT NULL
    );
    """),
    (124, "kg2_fact_s81", """
    CREATE TABLE IF NOT EXISTS kg2_fact (
        isin VARCHAR NOT NULL, fkey VARCHAR NOT NULL, fvalue VARCHAR, value_num DOUBLE, source VARCHAR NOT NULL, as_of DATE NOT NULL, known_from DATE NOT NULL,
        PRIMARY KEY (isin, fkey, as_of)
    );
    """),
    (125, "kg2_relation_s81", """
    CREATE TABLE IF NOT EXISTS kg2_relation (
        src_isin VARCHAR NOT NULL, dst_isin VARCHAR NOT NULL, rule VARCHAR NOT NULL, detail VARCHAR, source VARCHAR NOT NULL, as_of DATE NOT NULL,
        PRIMARY KEY (src_isin, dst_isin, rule)
    );
    """),
    (126, "kg2_event_s81", """
    CREATE TABLE IF NOT EXISTS kg2_event (
        event_id VARCHAR NOT NULL PRIMARY KEY, isin VARCHAR NOT NULL, source VARCHAR NOT NULL, ref VARCHAR NOT NULL, ts TIMESTAMP NOT NULL, event_date DATE NOT NULL,
        kind VARCHAR NOT NULL, severity VARCHAR NOT NULL, headline VARCHAR, link_rule VARCHAR NOT NULL, link_proof VARCHAR NOT NULL, dedupe_key VARCHAR NOT NULL
    );
    """),
    (127, "kg2_unlinked_s81", """
    CREATE TABLE IF NOT EXISTS kg2_unlinked (
        source VARCHAR NOT NULL, ref VARCHAR NOT NULL, ts TIMESTAMP, reason VARCHAR NOT NULL, scope_name VARCHAR
    );
    """),
    (128, "kg2_event_class_s81", """
    CREATE TABLE IF NOT EXISTS kg2_event_class (
        event_id VARCHAR NOT NULL PRIMARY KEY, kind VARCHAR NOT NULL, severity VARCHAR NOT NULL, method VARCHAR NOT NULL, model VARCHAR, classified_at TIMESTAMP
    );
    """),
    (129, "kg2_audit_s81", """
    CREATE TABLE IF NOT EXISTS kg2_audit (
        day DATE NOT NULL PRIMARY KEY, passed BOOLEAN NOT NULL, checks_json VARCHAR NOT NULL, ran_at TIMESTAMP NOT NULL
    );
    """),
    (130, "kg2_build_s81", """
    CREATE TABLE IF NOT EXISTS kg2_build (
        built_on DATE NOT NULL, built_at TIMESTAMP NOT NULL, as_of_day DATE NOT NULL, input_hash VARCHAR, output_hash VARCHAR, counts_json VARCHAR,
        PRIMARY KEY (built_on, as_of_day)
    );
    """),
]
