"""S83 L4 (the pick scorecard, `pflab/core/pick_score.py`): versions 175-179 (176-179 spare).

175  pick_scores_s83: every pick, sale and skip scored against the index at 1, 3, 6 and 12 months (one row per item and horizon), after the estimated tax and charges for a pick
     and a sale, price only for a skip; pick_sleeve_daily_s83: the picks sleeve's day against the index (after estimated tax), with the worst falls so far.
"""
MIGRATIONS = [
    (175, "pick_scores_sleeve_daily_s83", """
    CREATE TABLE IF NOT EXISTS pick_scores_s83 (
        score_id BIGINT PRIMARY KEY, kind VARCHAR NOT NULL, ref_id BIGINT NOT NULL, market VARCHAR NOT NULL, isin VARCHAR, horizon_months INTEGER NOT NULL, start_on DATE, end_on DATE,
        return_pct DOUBLE, index_return_pct DOUBLE, excess_pct DOUBLE, tax_charges_pct DOUBLE, after_tax BOOLEAN, scored_on DATE,
        index_raw_pct DOUBLE, symbol VARCHAR, detail_json VARCHAR
    );
    CREATE TABLE IF NOT EXISTS pick_sleeve_daily_s83 (
        market VARCHAR NOT NULL, day DATE NOT NULL, sleeve_value DOUBLE, index_value DOUBLE, sleeve_return_after_tax DOUBLE, index_return DOUBLE, worst_fall_sleeve DOUBLE,
        worst_fall_index DOUBLE, index_return_raw DOUBLE, detail_json VARCHAR, PRIMARY KEY (market, day)
    );
    """),
]
