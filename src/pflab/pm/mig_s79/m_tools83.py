"""S83 L2 (what the strategist may look at to choose; `pflab/lab/screen.py`): versions 190-194 (191-194 are spare).

190  screen_log_s83: one row per call of `screen_stocks` / `company_card` (the day it was made for, the market, the arguments, the names it showed): the record of what the strategist LOOKED AT
     when it chose, so a pick or a skipped idea can be traced to the screen that put it in front of it. Best effort: a failed write never fails a screen.
"""
MIGRATIONS = [
    (190, "screen_log_s83", """
    CREATE TABLE IF NOT EXISTS screen_log_s83 (
        log_id INTEGER PRIMARY KEY, logged_at TIMESTAMP NOT NULL, day DATE NOT NULL, market VARCHAR NOT NULL, tool VARCHAR NOT NULL, args_json VARCHAR, n_rows INTEGER, symbols_json VARCHAR
    );
    """),
]
