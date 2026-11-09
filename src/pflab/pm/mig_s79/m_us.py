"""S81 B8 phase B (A53): the paper US sub-book (`pflab/us/`), versions 131-136. Everything is in USD except the Indian-tax columns (`_inr`). Separate from `us_trades`
(his real US record, ledger/foreign.py) and from `paper_*` (the rupee paper book): nothing here touches them.

131  us_account_s81: the one account (start size in rupees and dollars, the start FX rate and where it came from); us_cash_s81: every dollar movement.
132  us_lots_s81: open and closed FIFO lots (dollar cost per share with charges, the tax FX rate at purchase); us_trades_s81: fills with charges, FX, realised gain and tax in rupees.
133  us_orders_s81: orders placed at a close, filled at the next session's open plus slippage; us_dividends_s81: gross, the 25% withheld, the Indian tax and the credit.
134  us_days_s81: the book marked at each US close (dollars, the rate and its source, rupees); us_runs_s81: one row per US session the close function handled.
135  us_events_s81: splits detected from the data, and other notes that change a lot.
136  (spare)
"""
MIGRATIONS = [
    (131, "us_account_s81", """
    CREATE TABLE IF NOT EXISTS us_account_s81 (
        account_id INTEGER PRIMARY KEY, opened_on DATE NOT NULL, start_inr DOUBLE NOT NULL, start_fx DOUBLE NOT NULL, fx_source VARCHAR NOT NULL, start_usd DOUBLE NOT NULL,
        share_of_book DOUBLE, note VARCHAR, opened_at TIMESTAMP NOT NULL
    );
    CREATE TABLE IF NOT EXISTS us_cash_s81 (
        entry_id INTEGER PRIMARY KEY, day DATE NOT NULL, usd DOUBLE NOT NULL, kind VARCHAR NOT NULL, ref VARCHAR, logged_at TIMESTAMP NOT NULL
    );
    """),
    (132, "us_lots_trades_s81", """
    CREATE TABLE IF NOT EXISTS us_lots_s81 (
        lot_id INTEGER PRIMARY KEY, isin VARCHAR NOT NULL, symbol VARCHAR, acq_date DATE NOT NULL, qty DOUBLE NOT NULL, cost_usd_per_share DOUBLE NOT NULL,
        fx_tax_acq DOUBLE, fx_tax_acq_source VARCHAR, origin VARCHAR NOT NULL
    );
    CREATE TABLE IF NOT EXISTS us_trades_s81 (
        trade_id INTEGER PRIMARY KEY, day DATE NOT NULL, order_id INTEGER, isin VARCHAR NOT NULL, symbol VARCHAR, side VARCHAR NOT NULL, qty DOUBLE NOT NULL, price_usd DOUBLE NOT NULL,
        charges_usd DOUBLE NOT NULL, fx_rate DOUBLE, fx_source VARCHAR, realised_inr DOUBLE, tax_inr DOUBLE, detail_json VARCHAR
    );
    """),
    (133, "us_orders_dividends_s81", """
    CREATE TABLE IF NOT EXISTS us_orders_s81 (
        order_id INTEGER PRIMARY KEY, placed_day DATE NOT NULL, placed_at TIMESTAMP NOT NULL, isin VARCHAR NOT NULL, symbol VARCHAR, side VARCHAR NOT NULL, qty DOUBLE, amount_usd DOUBLE,
        status VARCHAR NOT NULL, fill_day DATE, reason VARCHAR
    );
    CREATE TABLE IF NOT EXISTS us_dividends_s81 (
        div_id INTEGER PRIMARY KEY, day DATE NOT NULL, isin VARCHAR NOT NULL, symbol VARCHAR, qty DOUBLE NOT NULL, per_share_usd DOUBLE NOT NULL, gross_usd DOUBLE NOT NULL,
        withheld_usd DOUBLE NOT NULL, withholding_rate DOUBLE NOT NULL, fx_tax DOUBLE, fx_tax_source VARCHAR, gross_inr DOUBLE, india_tax_inr DOUBLE, credit_inr DOUBLE, residual_tax_inr DOUBLE,
        label VARCHAR
    );
    """),
    (134, "us_days_runs_s81", """
    CREATE TABLE IF NOT EXISTS us_days_s81 (
        day DATE PRIMARY KEY, value_usd DOUBLE NOT NULL, cash_usd DOUBLE NOT NULL, fx_rate DOUBLE, fx_source VARCHAR, value_inr DOUBLE, holdings_json VARCHAR
    );
    CREATE TABLE IF NOT EXISTS us_runs_s81 (
        day DATE PRIMARY KEY, ran_at TIMESTAMP NOT NULL, status VARCHAR NOT NULL, seconds DOUBLE, targets_json VARCHAR, orders_json VARCHAR, fills_json VARCHAR, note VARCHAR
    );
    """),
    (135, "us_events_s81", """
    CREATE TABLE IF NOT EXISTS us_events_s81 (
        event_id INTEGER PRIMARY KEY, day DATE NOT NULL, isin VARCHAR NOT NULL, kind VARCHAR NOT NULL, detail_json VARCHAR, logged_at TIMESTAMP NOT NULL
    );
    """),
]
