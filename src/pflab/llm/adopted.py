"""Harness texts adopted by S47 pass 3's registered rule (docs/STUDIES.md, 2026-10-22).

The text is appended to the prompt exactly as it was evaluated: straight after the question, no separator. Generated
from data/llm_eval/harness/research.json ("final"); tests/test_harness.py pins its hash. Writing was not adopted.
"""

RESEARCH = (
    "Most rejections are 'uncited' sentences. The checker splits text at every full stop and requires a "
    'tag at the end of each piece. Follow these rules. 1) Put the tag at the end of every sentence, '
    'before the full stop: [S#], [F:name] or [inf]. A tag earlier in the sentence does not count. 2) '
    "Never use a full stop inside a sentence. Drop honorifics and initials: write the person's first and "
    'last name only, with no Mr., Ms., Shri, Dr. or middle initial. Write Regulation, not Reg.; Number, '
    'not No.; Limited, not Ltd.; leave out times like P.M. 3) Never write a standalone comment such as '
    "'This indicates...', 'These ratings reflect...' or 'This shows...'. Join it to the fact with a comma"
    ' inside the cited sentence, or end it with [inf]. 4) The first sentence must be a specific cited '
    'fact, not a general summary. 5) Keep the note to 5 to 8 sentences so the ending is not cut off '
    'unfinished. If you list several filings, put their tags at the end, for example [S2][S5]. Also write'
    ' no numbers as words (hundred, lakh, spelled ordinals, even in names), and leave out meeting '
    'ordinals and clock times. Before submitting, read each sentence and confirm it ends with a tag and '
    'contains no other full stop. When flagged, fix every sentence with the same problem.'
)
