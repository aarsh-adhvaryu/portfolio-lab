"""S81 (market-hours rhythms, A54, `pflab/core/session.py`): versions 137-142.

137  session_plans_s81: the pre-open plan of a session (conditional orders with their triggers, the global close, the expected gap, a code-written text);
     session_triggers_s81: the swing entry triggers (a plain table: the swing policies write it at the close, the session loop reads it).
138  session_log_s81: every check, fill, wait, queue and degradation of the session loop with its code-written reason; session_fills_s81: every paper fill at a live quote
     with the quote, the price charged, the spread and slippage of the liquidity model and its flags.
139  session_queue_s81: orders the no-same-day-round-trip guard held to the next session.
140  session_said_s81: what was said once (Kite login lost, the 15:45 report), so it is never said twice in a day.
141  session_adv_s81: the average traded value of a name over its last sessions (the liquidity model's input), computed once a day from the minute bars.
142  session_exit_fb_s81: the tiny fallback exit plans (stop, target, time) used ONLY while `pflab.core.exits` is missing.
"""
MIGRATIONS = [
    (137, "session_plans_s81", """
    CREATE TABLE IF NOT EXISTS session_plans_s81 (
        market VARCHAR NOT NULL, day DATE NOT NULL, made_at TIMESTAMP NOT NULL, late BOOLEAN, global_json VARCHAR, gap_json VARCHAR, orders_json VARCHAR, n_orders INTEGER,
        text VARCHAR, PRIMARY KEY (market, day)
    );
    CREATE TABLE IF NOT EXISTS session_triggers_s81 (
        trigger_id INTEGER PRIMARY KEY, market VARCHAR NOT NULL, isin VARCHAR NOT NULL, kind VARCHAR NOT NULL, direction VARCHAR NOT NULL, level DOUBLE NOT NULL,
        amount DOUBLE, qty DOUBLE, stop_price DOUBLE, target_price DOUBLE, sleeve VARCHAR, policy_id VARCHAR, reason VARCHAR, plan_json VARCHAR,
        valid_from DATE NOT NULL, valid_until DATE NOT NULL, status VARCHAR NOT NULL, created_at TIMESTAMP, fired_at TIMESTAMP, fired_price DOUBLE
    );
    """),
    (138, "session_log_fills_s81", """
    CREATE TABLE IF NOT EXISTS session_log_s81 (
        log_id INTEGER PRIMARY KEY, ts TIMESTAMP NOT NULL, market VARCHAR NOT NULL, day DATE NOT NULL, kind VARCHAR NOT NULL, isin VARCHAR, symbol VARCHAR, what VARCHAR NOT NULL,
        flag VARCHAR, detail_json VARCHAR
    );
    CREATE TABLE IF NOT EXISTS session_fills_s81 (
        fill_id INTEGER PRIMARY KEY, ts TIMESTAMP NOT NULL, market VARCHAR NOT NULL, day DATE NOT NULL, isin VARCHAR NOT NULL, symbol VARCHAR, side VARCHAR NOT NULL, qty DOUBLE,
        quote DOUBLE, price DOUBLE, half_spread_bps DOUBLE, slippage_bps DOUBLE, adv_rupees DOUBLE, order_rupees DOUBLE, participation DOUBLE, cost_rupees DOUBLE,
        kind VARCHAR, plan_id INTEGER, reason VARCHAR, flag VARCHAR, order_id INTEGER, trade_id INTEGER, decision_id INTEGER
    );
    """),
    (139, "session_queue_s81", """
    CREATE TABLE IF NOT EXISTS session_queue_s81 (
        queue_id INTEGER PRIMARY KEY, market VARCHAR NOT NULL, isin VARCHAR NOT NULL, side VARCHAR NOT NULL, qty DOUBLE, amount DOUBLE, kind VARCHAR, plan_id INTEGER, reason VARCHAR,
        queued_on DATE NOT NULL, run_on DATE NOT NULL, status VARCHAR NOT NULL, done_at TIMESTAMP, result VARCHAR
    );
    """),
    (140, "session_said_s81", """
    CREATE TABLE IF NOT EXISTS session_said_s81 (
        day DATE NOT NULL, key VARCHAR NOT NULL, said_at TIMESTAMP NOT NULL, text VARCHAR, PRIMARY KEY (day, key)
    );
    """),
    (141, "session_adv_s81", """
    CREATE TABLE IF NOT EXISTS session_adv_s81 (
        market VARCHAR NOT NULL, isin VARCHAR NOT NULL, as_of_day DATE NOT NULL, adv_rupees DOUBLE, typical_minute_volume DOUBLE, sessions INTEGER, source VARCHAR,
        PRIMARY KEY (market, isin, as_of_day)
    );
    """),
    (142, "session_exit_fb_s81", """
    CREATE TABLE IF NOT EXISTS session_exit_fb_s81 (
        plan_id INTEGER PRIMARY KEY, market VARCHAR NOT NULL, isin VARCHAR NOT NULL, opened_on DATE NOT NULL, entry_price DOUBLE, qty DOUBLE, stop_price DOUBLE, target_price DOUBLE,
        time_stop_on DATE, status VARCHAR NOT NULL, closed_on DATE, note VARCHAR
    );
    """),
]
