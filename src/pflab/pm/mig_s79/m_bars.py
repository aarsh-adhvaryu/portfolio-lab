"""S79 item 7: minute bars (the raw material of "why did it move"), recorded after every session, per market.

`bars_1m` holds the bars as the broker's feed gave them (ts is the exchange's own wall clock, no timezone). An index is stored under the key `INDEX:<name>`
(it has no ISIN). `bars_1m_runs` says, for every name and day the job looked at, how many bars came back out of how many a full session has, so a missing
minute is a stated gap and is never filled in."""

MIGRATIONS = [
    (66, "bars_1m_s79", """
    CREATE TABLE bars_1m (
        market VARCHAR NOT NULL, isin VARCHAR NOT NULL, ts TIMESTAMP NOT NULL,
        open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE,
        PRIMARY KEY (market, isin, ts)
    );
    """),
    (67, "bars_1m_runs_s79", """
    CREATE TABLE bars_1m_runs (
        market VARCHAR NOT NULL, isin VARCHAR NOT NULL, day DATE NOT NULL, symbol VARCHAR,
        n_bars INTEGER NOT NULL, expected INTEGER NOT NULL, status VARCHAR NOT NULL, note VARCHAR, recorded_at TIMESTAMP NOT NULL,
        PRIMARY KEY (market, isin, day)
    );
    """),
]
