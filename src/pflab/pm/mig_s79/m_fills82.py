"""S82 (fill-cost calibration C8 and the first real strategist session C9): versions 150-155 (this module uses 150-151).

150  session_fills_s81.source: where the fill's quote came from ('live' = a live Kite quote in the app's session loop; anything else: a test, a drill, a replay or a simulation).
     Rows written before S82 have no source and are NEVER counted as real. fills_calibration_s82: every refit of the fill-cost model (old and new values, the fit, accepted or not).
151  strategist_first_s82: the once-only trigger of the first real strategist session in the app (one row per key; its status, attempts and result).
"""
MIGRATIONS = [
    (150, "fills_calibration_s82", """
    ALTER TABLE session_fills_s81 ADD COLUMN IF NOT EXISTS source VARCHAR;
    CREATE TABLE IF NOT EXISTS fills_calibration_s82 (
        cal_id INTEGER PRIMARY KEY, made_at TIMESTAMP NOT NULL, market VARCHAR NOT NULL, status VARCHAR NOT NULL, accepted BOOLEAN NOT NULL, n_fills INTEGER, n_used INTEGER,
        old_json VARCHAR, new_json VARCHAR, fit_json VARCHAR, reason VARCHAR
    );
    """),
    (151, "strategist_first_s82", """
    CREATE TABLE IF NOT EXISTS strategist_first_s82 (
        key VARCHAR PRIMARY KEY, status VARCHAR NOT NULL, attempts INTEGER NOT NULL, paid_attempts INTEGER NOT NULL, first_tried_at TIMESTAMP, last_tried_at TIMESTAMP,
        session_id INTEGER, cost_inr DOUBLE, detail VARCHAR
    );
    """),
]
