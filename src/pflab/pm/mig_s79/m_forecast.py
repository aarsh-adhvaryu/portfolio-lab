"""S79 items 8 and 9: predict, score, correct (versions 68-70) and the history replay's run log (71).

`source` is 'live' or 'replay' in every table: the replay (2012-2021) is kept apart and never counted in the 60 live sessions."""
MIGRATIONS = [
    (68, "forecasts_s79", """
    CREATE TABLE forecasts_s79 (
        forecast_id BIGINT PRIMARY KEY, market VARCHAR NOT NULL, source VARCHAR NOT NULL, as_of DATE NOT NULL,
        subject VARCHAR NOT NULL, symbol VARCHAR, horizon_sessions INTEGER NOT NULL, forecaster VARCHAR NOT NULL,
        quantiles_json VARCHAR NOT NULL, base_price DOUBLE, matures DATE, meta_json VARCHAR, made_at TIMESTAMP
    );
    CREATE TABLE forecast_scores_s79 (
        forecast_id BIGINT PRIMARY KEY, market VARCHAR NOT NULL, source VARCHAR NOT NULL, as_of DATE NOT NULL, matures DATE,
        subject VARCHAR NOT NULL, horizon_sessions INTEGER NOT NULL, forecaster VARCHAR NOT NULL,
        realised DOUBLE, pinball_json VARCHAR, pinball_mean DOUBLE, covered_80 BOOLEAN, covered_90 BOOLEAN, scored_at TIMESTAMP
    );
    """),
    (69, "forecaster_weights_s79", """
    CREATE TABLE forecaster_weights (
        market VARCHAR NOT NULL, source VARCHAR NOT NULL, horizon_sessions INTEGER NOT NULL, forecaster VARCHAR NOT NULL,
        as_of DATE NOT NULL, weight DOUBLE NOT NULL, n INTEGER NOT NULL, updated_at TIMESTAMP
    );
    """),
    (70, "fall_risk_s79", """
    CREATE TABLE fall_risk_s79 (
        market VARCHAR NOT NULL, source VARCHAR NOT NULL, as_of DATE NOT NULL, horizon_sessions INTEGER NOT NULL,
        p_raw DOUBLE, p DOUBLE, n_cal INTEGER, ref_high DOUBLE, threshold DOUBLE, outcome BOOLEAN, brier DOUBLE,
        made_at TIMESTAMP, scored_at TIMESTAMP
    );
    """),
    (71, "replay_runs_s79", """
    CREATE TABLE replay_runs_s79 (
        run_id BIGINT PRIMARY KEY, market VARCHAR NOT NULL, ran_at TIMESTAMP, start_date DATE, end_date DATE,
        sessions INTEGER, summary_json VARCHAR
    );
    """),
]
