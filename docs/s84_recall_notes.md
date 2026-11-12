# S84 recall: T2x, what we already know (`src/pflab/think/recall.py`)

Branch `s84/recall`. Code, no model, no cost. One function reads the two stores that did not meet (the paid analyst's notes in the OLD graph and memory, and the rebuilt `kg2` graph) plus storylines, picks and skips, and earlier cases.

## Built
- `think/recall.py`: `recall(con, now, *, isin, symbol, topic, sector, asof, limit_chars, kind) -> {"items", "text", "n", "resolved"}` (items `{"kind","id","day","source","title","text"}`, newest first, per-kind caps, size limit; `kind` adds earlier cases of the same case kind on other names).
  `mark_used(con, items, *, by_kind, by_ref, day)` (one `knowledge_use_s84` row per item, reader and day), `knowledge_line(con, day)`, `same_subject_fresh(con, now, *, isin, topic, since_move, question, symbol)`, `write_back(...) -> doc id`,
  plus `resolve`, `changed_since(con, now, isin, since)` (what happened to a name since a note: events and the move against its threshold) and `move_since`.
- Item kinds: `analyst_note` (old graph document of an API note), `note` (written back), `memory`, `kg2_event`, `kg2_relation`, `kg2_peer_event`, `kg2_sector_event`, `storyline`, `pick`, `skip`, `case`, `case_same_kind`. Item ids: doc id, mem id, event id, `pick:<id>`, `skip:<id>`, `case:<id>`, `story:<id>`.
- Migration `pm/mig_s79/m_recall84.py`: 215 `recall_notes_s84` (written-back notes keyed by ISIN, symbol, topic with their rupee cost), 216 `picks_s83.takes_from`.
- Readers wired: `lab/screen.py company_card` gets `what_we_already_know` (`{n, text, ids}`, items marked used by "card"); `core/picks.propose` refuses a name with an earlier note or case unless the item carries `takes_from` (20+ characters), stores it (`picks_s83.takes_from`) and marks the items used by "pick"; `lab/tools.py` `propose_picks` item schema has `takes_from`.
- Never pay twice: `agents/analyst.py` has `_fresh_on_subject` called from `ring` (after the existing same-topic reuse; by ISIN when the request has one, else by topic) and from `web_search` (by question: the new question must share half its words with the note's question; the names in capitals in it are checked for events and moves). A note is USED when it is younger than `recall_max_age_days` (45; `recall_topic_days` = 14 when there is no name to check events for)
  and no material kg2 event (severity medium or high, or a result / thesis-break kind) is dated after it and the close-to-close move since is under `min(fall_pct_10d, max(2%, move_sigmas x usual daily move x sqrt(sessions)))`. The caller may pass its own `since_move`.

## Decisions (2026-11-12)
1. Web facts and written-back notes are NOT written into `kg2_event`: the nightly job deletes and reloads those tables from raw files and its audit demands a byte-identical rebuild, so an added row would be lost or fail the audit. They live in `recall_notes_s84` (with source and rupee cost) and `recall` returns them; the old `kg_docs` document and `memory` row are written too, so the old chat reads them. S85 may add a raw input file the graph build reads.
2. The old graph is switched off (`kg/switch.py`): `about` edges are never written, so analyst notes are found by `api_calls.topic` (the symbols) or, for generic topics such as "brain web", by the symbol written in capitals in the note's question. With the graph on, edges are used too.
3. Memory rows come back only for kinds note/outcome with a name as subject, never from "investor"/"cli", and never an analyst note's own memory row (it is the same note as its document).
4. Freshness knobs (`recall_max_age_days`, `recall_topic_days`, `recall_item_chars`, `recall_similarity`) have defaults in `think/recall.py DEFAULTS` and may be set in `[think]`; I did not edit `configs/core.toml`.
5. A pick refused for a missing `takes_from` counts earlier notes, written-back notes, memory notes and cases, not kg2 events, storylines or a skip. The `case` agent's `opportunity` picks must pass `takes_from` when the name has an earlier note/case (the refusal says what to cite).
6. The strategist has no web tool in `lab/tools.py` (the old brain's `hq/tools.py` has one and calls `analyst.web_search`): the check sits in `analyst.web_search` itself, so every caller, including the case session's web check, is covered. `agents/escalate.py` and `app/chat.py` also call `web_search` and now get the same saving.

## What is OFF
Nothing is behind a switch: the hooks never raise (a failure means "ask" or "no section").

## Shared files touched
`agents/analyst.py` (the `_fresh_on_subject` helper and two 2-line hooks), `lab/screen.py` (`company_card` plus `what_we_know`), `lab/tools.py` (one schema property), `core/picks.py` (`propose` hook plus two helpers). Nothing else; `cases.py` untouched.

## Exposed for screens
- `think.recall.knowledge_line(con, day)` -> `{"paid_notes_this_month", "read_by_a_decision", "unread_30d_rupees", "text"}` (text block for Today and the reports).
- `think.recall.recall(...)["text"]` is a text block; `company_card(...)["what_we_already_know"]` is `{n, text, ids}`.

## For the other agents
- `case`/`desk` call `recall.recall(con, now, isin=..., kind=case_kind)`, then `recall.mark_used(con, r["items"], by_kind="case"|"desk", by_ref=f"case:{id}", day=day)`, and write what they paid for with `recall.write_back(con, now, isin=..., title=..., text=..., source="think case #N", cost_rupees=..., case_id=...)` (the cost makes it a "paid note" in the knowledge line; the gateway's own cost log is separate).
- `watch` can use `recall.move_since` for a note-staleness test but needs nothing from it.

## Real path (a COPY of the schema-102 store, `D:\PL_backup\s82_pre_20261111`; the fresher copy had no ledger file yet)
Counts only: 7 analyst notes as graph documents (25 notes in `api_calls`, 11 topics, most with the generic topic "brain web" and, on the old graph, no company edge). `kg2_*` tables, picks and skips are empty in that copy (graph off, picks not yet named), the copy has no held lots in `paper_lots`.
Names written in capitals in the notes' questions resolved to instruments (8 of 25 notes); for the four recent ones `recall` returned the note (1-2 `analyst_note` items each), the oldest notes have no document row left, so nothing. A repeated question on the newest note was recognised as fresh (2.8 days old, within the 14-day topic window); an unrelated question was not. The knowledge line on the copy: 9 paid notes this month, none yet read by a decision (nothing reads them before this release).

## Tests
`tests/test_s84_recall.py` (14), `tests/test_s84_recall_card.py` (2: a seeded note on a name is in its company card and counted as used; another name's note and a later-dated note are not), `tests/test_s84_recall_picks.py` (3). Named for the brief: a seeded analyst note on a held name appears in that name's recall; a note about another name does not; nothing after `asof` (notes, events, derived-time filings, picks, cases); the second paid call on an unchanged subject costs zero (`ring` and `web_search`); the knowledge line counts.

## Could not verify
The real `kg2` side on real data (the copy's graph tables are empty, so peers, sector and event items are proved on synthetic rows only); that a real case session reads the card's new section within the 16,000-character card limit (the section is cut to 2,500 characters and the card is still trimmed by `fit_card`).
