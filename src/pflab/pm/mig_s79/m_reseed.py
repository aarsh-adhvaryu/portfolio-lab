"""S79 item 2 (A45): the re-seed of the system's own account from Kite holdings, the archive of the old paper record, and the system's own allocation target
(versions 78-80). The archive tables themselves (`<table>_archive_s79`) are created by `paper/reseed.py` when it archives, with the source table's own columns."""

MIGRATIONS = [
    (78, "reseed_s79", """
    CREATE TABLE IF NOT EXISTS reseed_s79 (
        reseed_id INTEGER PRIMARY KEY, market VARCHAR, applied_at TIMESTAMP NOT NULL, seed_date DATE NOT NULL, cash DOUBLE NOT NULL, source VARCHAR,
        holdings_json VARCHAR, archive_id INTEGER, backup_file VARCHAR, forced BOOLEAN, summary_json VARCHAR
    );
    CREATE TABLE IF NOT EXISTS paper_archive_s79 (
        archive_id INTEGER PRIMARY KEY, market VARCHAR, archived_at TIMESTAMP NOT NULL, label VARCHAR NOT NULL, period_from DATE, period_to DATE, rows_json VARCHAR
    );
    """),
    (79, "system_allocation_s79", """
    CREATE TABLE IF NOT EXISTS system_allocation_s79 (
        target_id INTEGER PRIMARY KEY, market VARCHAR, proposed_at TIMESTAMP NOT NULL, proposed_by VARCHAR, case_id INTEGER,
        classes_json VARCHAR NOT NULL, sectors_json VARCHAR, reasons VARCHAR NOT NULL, status VARCHAR NOT NULL,
        verdict VARCHAR, verdict_notes VARCHAR, reviewed_at TIMESTAMP, activated_at TIMESTAMP, review_due DATE,
        reexamined_at TIMESTAMP, reexamined_notes VARCHAR, superseded_by INTEGER
    );
    """),
]
