"""S79b item 15 (market waves: macro attribution and rotation). Versions 89-90 are reserved for this item."""
MIGRATIONS = [
    (89, "macro_attribution", """
    CREATE TABLE macro_attribution (
        market VARCHAR NOT NULL, session DATE NOT NULL, part VARCHAR NOT NULL, pct DOUBLE, beta DOUBLE, factor_move DOUBLE, unit VARCHAR,
        n INTEGER, r2 DOUBLE, window_desc VARCHAR, method VARCHAR, note VARCHAR, as_of DATE, created_at TIMESTAMP,
        PRIMARY KEY (market, session, part)
    );
    """),
    (90, "wave_stats_and_flags", """
    CREATE TABLE wave_stats (
        market VARCHAR NOT NULL, session DATE NOT NULL, adv_share DOUBLE, n_all INTEGER, xs_disp DOUBLE, med_ret DOUBLE, disp_ratio DOUBLE,
        dom_share DOUBLE, n_univ INTEGER, created_at TIMESTAMP,
        PRIMARY KEY (market, session)
    );
    CREATE TABLE wave_flag (
        market VARCHAR NOT NULL, session DATE NOT NULL, kind VARCHAR NOT NULL, direction VARCHAR, salience VARCHAR, known_on DATE,
        stats_json VARCHAR, thresholds_json VARCHAR, definition VARCHAR, call_id INTEGER, claim_id INTEGER, created_at TIMESTAMP,
        PRIMARY KEY (market, session, kind)
    );
    """),
]
