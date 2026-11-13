"""S85 wide (L1: the wide watch, exposure through funds, "what did I miss", threshold tuning): versions 270-274 (273-274 are spare).

270  think_tuning_s84: one dated row per proposed or applied change of ONE `[think]` threshold (`think/tuning.py`); the change is applied through `think_overrides_s84`, never by editing the config file.
     `state` is 'applied' or 'reverted'; a revert is a new fact on the same row (`reverted_on`, `reverted_why`), never a delete.
271  think_overrides_s84: the threshold values `think.settings()` reads on top of the config (one row per parameter; `active` is false once the change is reverted).
272  think_wide_runs_s85: one row per wide-watch pass (market, day): how many names it looked at, how many signals it found, how many it stored, how many cases it opened, how long it took.
"""
MIGRATIONS = [
    (270, "think_tuning_s84", """
    CREATE TABLE IF NOT EXISTS think_tuning_s84 (
        tuning_id BIGINT PRIMARY KEY, proposed_on DATE, param VARCHAR, old_value DOUBLE, new_value DOUBLE, config_value DOUBLE, direction VARCHAR, reason VARCHAR, counts_json VARCHAR,
        state VARCHAR, reverted_on DATE, reverted_why VARCHAR
    );
    """),
    (271, "think_overrides_s84", """
    CREATE TABLE IF NOT EXISTS think_overrides_s84 (
        param VARCHAR PRIMARY KEY, value DOUBLE, since DATE, tuning_id BIGINT, active BOOLEAN
    );
    """),
    (272, "think_wide_runs_s85", """
    CREATE TABLE IF NOT EXISTS think_wide_runs_s85 (
        run_key VARCHAR PRIMARY KEY, market VARCHAR, day DATE, ran_at TIMESTAMP, scanned INTEGER, signals INTEGER, stored INTEGER, cases_opened INTEGER, seconds DOUBLE, note VARCHAR
    );
    """),
]
