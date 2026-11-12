"""S85 (E6, Telegram upgraded): versions 335-339.

335  tg_prefs_s85: what he picked with /model and /think in Telegram, kept per scope (one row, 'telegram'); the next messages go to the intake with it until he says `auto`.
336  tg_files_s85: one row per file or photo that came through the Bot API's getFile (name, size, outcome); the file itself is scratch and is deleted once the intake has answered.
"""
MIGRATIONS = [
    (335, "tg_prefs_s85", """
    CREATE TABLE IF NOT EXISTS tg_prefs_s85 (
        scope VARCHAR PRIMARY KEY, model VARCHAR, thinking VARCHAR, updated_at TIMESTAMP
    );
    """),
    (336, "tg_files_s85", """
    CREATE TABLE IF NOT EXISTS tg_files_s85 (
        update_id BIGINT PRIMARY KEY, received_at TIMESTAMP, kind VARCHAR, name VARCHAR, mime VARCHAR, size_bytes BIGINT, outcome VARCHAR, detail VARCHAR
    );
    """),
]
