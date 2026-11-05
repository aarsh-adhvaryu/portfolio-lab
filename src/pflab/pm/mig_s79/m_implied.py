"""S79 item 11: the option-implied probabilities kept next to what happened (version 74)."""

MIGRATIONS = [
    (74, "implied_calibration_s79",
     "CREATE TABLE IF NOT EXISTS implied_calibration_s79 ("
     "market VARCHAR, \"asof\" DATE, horizon INTEGER, fall_pct DOUBLE, p_implied DOUBLE, outcome INTEGER, resolved_at DATE, "
     "expiry DATE, spot DOUBLE, end_level DOUBLE);"),
]
