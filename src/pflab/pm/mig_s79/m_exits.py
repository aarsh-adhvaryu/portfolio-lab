"""S81 (B4, the exit manager and tax selling, `pflab/core/exits.py`): versions 113-115 (116-117 are spare).

113  exit_plans_s81: one exit plan per position, written when the position is opened (target, stop, time stop, thesis-break kinds, the tax boundary: the day the
     oldest short-term lot turns long-term). status: open / rebuy_pending (a harvest sold it and the buy-back is waiting for its session) / closed.
114  exit_events_s81: every order the manager emitted (stop, target, time, thesis, harvest, trim) with the reason, the lots it would consume and its fate
     (emitted / filled / void / guarded). This is what makes each exit fire once and only once.
115  exit_scores_s81: every sale scored AFTER TAX against holding the same shares over the same sessions, at 20 and 60 sessions.
"""
MIGRATIONS = [
    (113, "exit_plans_s81", """
    CREATE TABLE IF NOT EXISTS exit_plans_s81 (
        plan_id INTEGER PRIMARY KEY, market VARCHAR NOT NULL, isin VARCHAR NOT NULL, sleeve VARCHAR NOT NULL, opened_on DATE NOT NULL, entry_price DOUBLE, qty DOUBLE,
        target DOUBLE, stop DOUBLE, time_stop_days INTEGER, thesis_break_kinds VARCHAR, tax_boundary_date DATE, status VARCHAR NOT NULL, closed_on DATE, closed_reason VARCHAR,
        source VARCHAR, vol DOUBLE, note VARCHAR, created_at TIMESTAMP, updated_at TIMESTAMP
    );
    """),
    (114, "exit_events_s81", """
    CREATE TABLE IF NOT EXISTS exit_events_s81 (
        event_id INTEGER PRIMARY KEY, plan_id INTEGER, market VARCHAR NOT NULL, isin VARCHAR NOT NULL, side VARCHAR NOT NULL, kind VARCHAR NOT NULL, day DATE NOT NULL,
        emitted_at TIMESTAMP, qty DOUBLE, fraction DOUBLE, price DOUBLE, reason VARCHAR, status VARCHAR NOT NULL, link_event_id INTEGER, ref VARCHAR, trade_id INTEGER,
        filled_on DATE, detail_json VARCHAR
    );
    """),
    (115, "exit_scores_s81", """
    CREATE TABLE IF NOT EXISTS exit_scores_s81 (
        score_id INTEGER PRIMARY KEY, event_id INTEGER, plan_id INTEGER, market VARCHAR NOT NULL, isin VARCHAR NOT NULL, kind VARCHAR NOT NULL, sleeve VARCHAR,
        trade_id INTEGER NOT NULL, sold_on DATE NOT NULL, qty DOUBLE, sale_price DOUBLE, proceeds_after_tax DOUBLE, tax DOUBLE, horizon_sessions INTEGER NOT NULL,
        due_on DATE, scored_on DATE, sale_value DOUBLE, hold_value DOUBLE, diff DOUBLE, diff_pct DOUBLE, outcome VARCHAR, detail_json VARCHAR,
        UNIQUE (trade_id, horizon_sessions)
    );
    """),
]
