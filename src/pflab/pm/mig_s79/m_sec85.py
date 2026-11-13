"""S85 `sec` (US company filings from the SEC): versions 275-279 (277-279 spare).

275  sec_8k_s85      one row per 8-K filing the collector looked at: accession number (the document key), CIK, the pseudo-ISIN the events carry, the items the SEC lists, the filing's date and
                    SEC acceptance time (UTC), and what became of it (`status`: stored, no_wanted_item, fetch_failed, no_text) so a filing is never fetched twice.
276  sec_8k_cik_s85  one row per company the collector asks about: when it was last asked and how it went (a failing company is retried with a back-off, never in a loop).
"""
MIGRATIONS = [
    (275, "sec_8k_s85", """
    CREATE TABLE IF NOT EXISTS sec_8k_s85 (
        accession VARCHAR PRIMARY KEY, cik BIGINT, isin VARCHAR, symbol VARCHAR, company VARCHAR, form VARCHAR, items_listed VARCHAR, filed DATE, accepted_utc TIMESTAMP,
        status VARCHAR, tries INTEGER, first_seen TIMESTAMP, fetched_at TIMESTAMP, wanted_items VARCHAR, note VARCHAR
    );
    """),
    (276, "sec_8k_cik_s85", """
    CREATE TABLE IF NOT EXISTS sec_8k_cik_s85 (
        cik BIGINT PRIMARY KEY, isin VARCHAR, symbol VARCHAR, last_checked TIMESTAMP, last_status VARCHAR, failures INTEGER, filings_seen BIGINT
    );
    """),
]
