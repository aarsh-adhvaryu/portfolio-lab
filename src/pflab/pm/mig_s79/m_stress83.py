"""S83 L7 (stress scenarios on what the book holds, `pflab/core/stress.py`): versions 185-189 (186-189 spare).

185  stress_s83: one row per day, scope (IN, US, ALL) and scenario: the book's fall and the holdings the figures were made on (detail_json).
"""
MIGRATIONS = [
    (185, "stress_s83", """
    CREATE TABLE IF NOT EXISTS stress_s83 (
        stress_id BIGINT PRIMARY KEY, day DATE NOT NULL, scope VARCHAR NOT NULL, scenario VARCHAR NOT NULL, fall_pct DOUBLE, detail_json VARCHAR
    );
    """),
]
