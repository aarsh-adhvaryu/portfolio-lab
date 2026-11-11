"""S82 (A56-A59): the US paper sub-book is funded by a TRANSFER out of the rupee book's cash (never new money). Version 144 (range 144-149 is the US agent's).

144  us_transfers_s82: one row per transfer: the rupees taken out of the rupee book, the dollars credited at the stated rate less the funding markup, the rupee date of the debit,
     which phase it was (open, build, topup, converted_seed) and what the sub-book held of the whole book afterwards.
"""
MIGRATIONS = [
    (144, "us_transfers_s82", """
    CREATE TABLE IF NOT EXISTS us_transfers_s82 (
        transfer_id INTEGER PRIMARY KEY, us_day DATE NOT NULL, rupee_day DATE NOT NULL, inr DOUBLE NOT NULL, fx_rate DOUBLE NOT NULL, fx_source VARCHAR NOT NULL,
        markup DOUBLE NOT NULL, usd DOUBLE NOT NULL, markup_inr DOUBLE NOT NULL, phase VARCHAR NOT NULL, rupee_ref VARCHAR, share_after DOUBLE, reason VARCHAR, created_at TIMESTAMP NOT NULL
    );
    """),
]
