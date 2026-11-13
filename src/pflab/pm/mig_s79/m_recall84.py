"""S84 recall (`pflab/think/recall.py`, T2x: what we already know): versions 215-216 (217-219 are spare).

215  recall_notes_s84: a dated note written back by a decision, a desk step or a web check (`recall.write_back`), keyed by ISIN, symbol and topic so `recall` finds it WITHOUT the old
     graph's links (the old graph is switched off: `kg/switch.py`). The same note is also a `kg_docs` document of kind `analyst_note` and a `memory` row, so the old chat still reads it.
     `cost_rupees` is what the paid call that produced it cost (0 for a note made by code), the base of the nightly knowledge line.
"""
MIGRATIONS = [
    (215, "recall_notes_s84", """
    CREATE TABLE IF NOT EXISTS recall_notes_s84 (
        note_id BIGINT PRIMARY KEY, doc_id VARCHAR, isin VARCHAR, symbol VARCHAR, topic VARCHAR, day DATE, written_at TIMESTAMP, source VARCHAR, title VARCHAR, text VARCHAR,
        cost_rupees DOUBLE, case_id BIGINT
    );
    """),
    (216, "picks_takes_from_s84", """
    ALTER TABLE picks_s83 ADD COLUMN IF NOT EXISTS takes_from VARCHAR;
    """),
]
# 216  picks_s83.takes_from: the sentence a pick gave, when `recall` held an earlier note or case on the name, of what the pick takes from it (`core/picks.propose`).
