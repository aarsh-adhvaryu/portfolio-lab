"""S79b item 18D (plug-in lenses): the admission log and the drafted candidate stubs (versions 96-97).

lens_admission  one row per check of a lens (market, horizon, forecast date): the live sessions counted, the pinball with and without it, the Diebold-Mariano t, the bar, and the verdict.
lens_candidates the lens candidates the agenda drafted as PROTOCOL STUBS (a text file under docs/protocols/lens_candidates/); a stub is never code and never live."""
MIGRATIONS = [
    (96, "lens_admission_s79b", """
    CREATE TABLE lens_admission (
        lens VARCHAR NOT NULL, market VARCHAR NOT NULL, horizon_sessions INTEGER NOT NULL, as_of DATE NOT NULL, n_live INTEGER,
        pinball_with DOUBLE, pinball_without DOUBLE, t DOUBLE, bar DOUBLE, admitted BOOLEAN, reason VARCHAR, checked_at TIMESTAMP
    );
    """),
    (97, "lens_candidates_s79b", """
    CREATE TABLE lens_candidates (
        candidate_id BIGINT PRIMARY KEY, market VARCHAR NOT NULL, name VARCHAR NOT NULL, idea VARCHAR, protocol_path VARCHAR, status VARCHAR NOT NULL,
        drafted_at TIMESTAMP, note VARCHAR
    );
    """),
]
