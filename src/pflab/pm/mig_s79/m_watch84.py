"""S84 watch (T1 NOTICE, `pflab/think/watch.py`): version 220 (221-224 are spare).

220  think_watch_runs_s84: one row per pass of the watch that is a unit of the catch-up (the India close of a day, the US morning of a day): `run_key` is 'close:IN:<day>' or
     'us_morning:US:<day>'. The catch-up reads it to find the sessions it has not looked at yet, so a gap is run once and each date once. Session-loop passes are not logged here
     (they run every few minutes; their signals are the record).
"""
MIGRATIONS = [
    (220, "think_watch_runs_s84", """
    CREATE TABLE IF NOT EXISTS think_watch_runs_s84 (
        run_key VARCHAR PRIMARY KEY, mode VARCHAR, market VARCHAR, day DATE, ran_at TIMESTAMP, signals INTEGER, cases_opened INTEGER, noticed INTEGER
    );
    """),
]
