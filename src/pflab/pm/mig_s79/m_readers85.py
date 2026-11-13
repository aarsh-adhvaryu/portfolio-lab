"""S85 `readers` (E3, A71, A72: what he sends is screened, read, kept and passed to the loop): versions 320-324 (322-324 are spare).

320  received_docs_s85: one row per file he sent that was KEPT (a file that is refused as a personal record is never stored, so it has no row). `sha` is the file's SHA-256: the same bytes sent again
     are answered from this row (one read, one price). `path` is the kept copy under `<data>/received_s85/YYYYMMDD/`; `facts_json` the checked facts [{claim, quote, page}]; `isins_json` the ISINs the
     graph's confident rule attached (code, never a model); `event_id` the knowledge-graph event (source "you") or NULL when no ISIN was attached; `note_doc` the written-back note `recall` finds.
321  link_checks_s85: one row per link he sent: the claim, the sources opened (URL, kind of source, date fetched), the verdict and the answer shown; a link checked the same day with the same claim is
     answered from this row.
"""
MIGRATIONS = [
    (320, "received_docs_s85", """
    CREATE TABLE IF NOT EXISTS received_docs_s85 (
        doc_id BIGINT PRIMARY KEY, sha VARCHAR, name VARCHAR, mime VARCHAR, kind VARCHAR, path VARCHAR, size_bytes BIGINT, received_at TIMESTAMP, chat_id BIGINT, msg_id BIGINT,
        pages INTEGER, status VARCHAR, summary VARCHAR, facts_json VARCHAR, isins_json VARCHAR, event_id VARCHAR, note_doc VARCHAR, cost_inr DOUBLE, warnings_json VARCHAR, result_json VARCHAR
    );
    """),
    (321, "link_checks_s85", """
    CREATE TABLE IF NOT EXISTS link_checks_s85 (
        link_id BIGINT PRIMARY KEY, url VARCHAR, claim VARCHAR, checked_at TIMESTAMP, chat_id BIGINT, verdict VARCHAR, sources_json VARCHAR, answer VARCHAR, isins_json VARCHAR, event_id VARCHAR,
        note_doc VARCHAR, cost_inr DOUBLE, warnings_json VARCHAR, result_json VARCHAR
    );
    """),
]
