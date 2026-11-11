"""S83 L5 (the picks sleeve's share follows its live record, `pflab/core/pick_share.py`): version 180 (181-184 are spare).

180  sleeve_share_s83: one dated row per JUDGMENT of the rule (the share moved or not: old_share = new_share is a "level" judgment), with the reason and the figures it used.
"""
MIGRATIONS = [
    (180, "sleeve_share_s83", """
    CREATE TABLE IF NOT EXISTS sleeve_share_s83 (
        change_id BIGINT PRIMARY KEY, market VARCHAR, decided_on DATE, old_share DOUBLE, new_share DOUBLE, reason VARCHAR, figures_json VARCHAR
    );
    """),
]
