"""S83 L3 (the strategist names stocks): version 195 (196-199 are spare).

195  core_notes_s80.learned: the part of a strategist note that says what the picks scorecard taught it (required once five picks of a market have a score).
"""
MIGRATIONS = [
    (195, "strategist_notes_learned_s83", """
    ALTER TABLE core_notes_s80 ADD COLUMN IF NOT EXISTS learned VARCHAR;
    """),
]
