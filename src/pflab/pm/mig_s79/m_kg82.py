"""S82 (kg agent, A58): the graph's event time says where it came from. Version 156.

kg2_event.ts_rule: `release_time` (the exchange's own dissemination time), `next_open_no_release_time` (a filing with a date but no release time: used from the next trading
day's open, 09:15 IST), `article_day_next_day` (a news article dated D, usable from D+1). Rows stored before this version keep NULL (never rewritten); the next build fills it.
"""

MIGRATIONS = [
    (156, "kg2_event_ts_rule_s82", """
    ALTER TABLE kg2_event ADD COLUMN IF NOT EXISTS ts_rule VARCHAR;
    """),
]
