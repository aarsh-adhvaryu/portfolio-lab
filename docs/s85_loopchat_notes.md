# S85 loopchat (C6): E7, the chat and the thinking loop

Branch `s85/loopchat` (based on `pm/s85-entrance`). Module `src/pflab/think/chat_hooks.py`, migration `pm/mig_s79/m_loopchat85.py` (340-344), tests `tests/test_s85_loopchat.py` (21, green, scripted fakes only: no paid call).
Not touched: PLAN.md, BUILT.md, CLAUDE.md.

## What is built
- `look_into(con, now, name_or_isin, chat_id, why="") -> case_id` (and `look_into_result` with the words to say): a case at once (`opened_by="you"`, signal `from_you` whose detail `why` is HIS WORDS, so the case's first message holds them). Counts in the day's 3
  (`watch.settings()["max_cases_per_day"]`); a name with an open case is JOINED; a full day stores the case as `noticed` + origin state `queued` and says so; `release_queued` (called at the start of every `watch._commit`) opens it on the next day with room.
- `suggest_stock(con, now, name, reason, chat_id)`: `recall` + `screen.company_card` (the card's own liquidity block is the floor check: India `clears_picks_floor`, US `clears_a62_floor`) + ONE read (role `read`, agent `chat`, `chat_id`, strict closed schema
  `VERDICT_SCHEMA`: verdict pick / wait_for / pass, thesis, break condition, takes_from, learned_from, wait_kind from a closed list; no size/price/weight/probability field exists). pick -> `picks.propose` (code sizes inside the rails and the reserve; a refusal turns the verdict into
  pass with the refusal said), wait_for -> a stored condition (`next_results`, `next_filing`, `pullback_10`, `pullback_20`, `other_event`; the pullback price is code's: reference price at suggestion) checked by `scan`, pass -> `picks.skip_idea`. A wait_for is ALSO recorded as a skip so it is scored
  against the index like every skip. A name that fails the floor is passed with the reason WITHOUT a paid read. Whatever the verdict the name joins `watch_from_you_s85` for 120 sessions (`markets.session_after`); `watch.scope` includes it (hook), so T1's signals run on it; a passed name's skip row gives it the
  missed-run signal; a new event reopens it through the normal thesis/news signals. A dated note "from you" is written back with `recall.write_back(source="you")`. At most 5 a day (`MAX_NAMES_A_DAY`): more are stored `queued`, said so, and `run_queued_suggestions` (called by `desk.tick_hook`) answers them
  on a later day IN THEIR OWN CHAT ("From the desk: ..."). The same name twice in a day returns the stored verdict, one read.
- `note_from_him(con, now, doc_id, chat_id)`: reads `received_docs_s85` (readers' row: claims, ISINs); the names are the reader's ISINs plus names code finds in the claims, kept only when they are held, picked, watched or reached through funds (`watch.scope`). Per name: `recall` first; if
  every claim is already in an earlier stored item (75% of the claim's words, not this note's own row) -> `nothing new: already known from <source, date>` and NO case; else `open_or_join` (signal `from_you`, kind `news`, the claims in the signal detail so the first message has them) and the case
  is thought through at once (at most 3 per note while he waits, `think_now=True`; the rest are left to the loop). The answer text is `case_card`: one option per name with worst / likely / best in rupees from the case's option rows, and why. A note touching no held/picked/watched name goes to
  `market_notes_s85` + a dated note "from you" (topic market) and its line is added to `desk.plan_text` (the pre-open plan) for 2 days. The same document again: the stored answer, no read, no new case (`from_you_notes_s85`). The chat never decides: the tool text says "report this, never decide".
- `overrule(con, now, name, action hold|no_buy, chat_id, case_id=None, words=, gateway_call=)`: builds a plain sentence and sends it through `rules_intake.standing_instruction` (hold_name / pause_buys on the name; undo and change date work as for any rule; a refusal is passed on), then records an `overruled` step on the name's case
  and a row in `overrules_s85` (his option: hold / nothing; the loop's option at that time). `score_user` scores both ways through `score._score_decision` (tracks `user` and `user_loop`, decision id `2e9 + overrule_id`, idempotent), called at the end of `score.score_due`; `scorecard_text` shows the pair.
- Chat tools registered in `entrance.tools.REGISTRY` (registered from `entrance/tools.py`'s tail): `thinking_cases`, `case_outcomes`, `decision_scorecard`, `reserve`, `what_do_you_know` (the same `recall`), `look_into`, `suggest_stock`, `overrule`.
- The loop tells the chat: `session.tell` now first calls `chat_hooks.tell_chat`: a case with an origin row (his look, his note, a name he suggested that reopened) is told in THAT chat with `store.post_system(kind="loop", key=loop:case:<id>:<n decisions>)`, once per stage. A reopened suggested name
  gets its origin row from the watch list at that moment ("A name you suggested is back on the table: ...").
- The intake runs it: `intake._read_file` calls `note_from_him` for every kept document with facts; the result text goes into the file block as "WHAT THE LOOP DID WITH IT" (so the chat reports what the cases did).

## Decisions (2026-11-13, nobody awake)
- The brief's tool `cases` is registered as `thinking_cases`: `cases` is in `entrance.tools.CORE_RETIRED` (the v1 investigation-cases tool) and `test_s85_chat` asserts no retired name is offered.
- Case origin is a SIDE TABLE `think_case_origin_s85`, not columns on `think_cases_s84` (that table is filled by position in `cases.open_case`: an added column would break every writer).
- A document he sends is a signal in two ways: `readers` writes the graph event (news, low: "a lead, never a thesis break"), which the watch counts like any other news (test: four such events make a `news_burst`); the case for a name comes from `note_from_him`, not from a single low-severity event.
- A wait_for's price condition is a closed step (10% or 20% under the price on the suggestion day), never a number the model writes. Event conditions are any later graph event of the right kind on the name.
- The chat message is laptop-only (`post_system` channels laptop); Telegram is told by the loop's own `session.tell` (acted or over 2% of the book) as before. A case that only reports (hold) therefore appears in the chat but not on Telegram.
  When the chat is also the active chat, a case that acts shows twice in it: the loop's outbox text (mirrored by `chat`) and this case card (what was decided, worst / likely / best, why).
- Sizes and verdict wording are code's; `desk._clean` strips any sentence of the model with a figure that is not in the facts it was given (rule 8).
- The model's thesis for a pick goes to `picks.propose` as written (60+ characters, a break condition, `takes_from` when an earlier note exists); anything short is refused by `propose` and the verdict becomes pass with that reason.

## OFF / not done
- Nothing is behind a switch: the hooks are inert with no suggestion, note or overrule. `think.on()` (the loop's own switch) still governs `think_case`.
- Not wired: the US side of `look_into` / `suggest_stock` needs US bars/`company_card` for the name (works through `rules_intake.resolve_name`; only India was exercised in tests).
- A note's `think_now` cases cost real model money in the app (Sonnet read + Sonnet/Opus answer per name, at most 3 per note); the chat's per-item timeout (420 s) bounds it.
- Not verified: a real model round trip (scripted fakes only), the real store, Telegram's side of a "loop" message.

## Shared files touched (each hunk is small and inside a try)
`think/watch.py` (`scope`: the watch-list entries; `_commit`: `release_queued` + `scan`), `think/session.py` (`tell`: `tell_chat`), `think/score.py` (`score_due`: `score_user`), `think/desk.py` (`plan_text`: notes about the market; `tick_hook`: queued suggestions),
`entrance/tools.py` (registers the 8 tools at the tail), `entrance/intake.py` (`_read_file` calls `note_from_him`; the file block carries `loop_text`).

## Exposed for screens
Plain functions returning JSON-able dicts/text: `chat_hooks.cases_text(con, day)`, `case_card(con, case_id)`, `case_outcomes(con, case_id)`, `scorecard_text(con)`, `reserve_text(con, day)`, `what_do_you_know(con, now, name)`, `watch_from_you(con, day)`, `preopen_text(con, day)`.
Tables: `watch_from_you_s85`, `think_case_origin_s85`, `overrules_s85`, `from_you_notes_s85`, `market_notes_s85`.

## Lines for the coordinator's docs
- BUILT.md: `think/chat_hooks.py`; tables above (migrations 340-344); chat tools `thinking_cases`, `case_outcomes`, `decision_scorecard`, `reserve`, `what_do_you_know`, `look_into`, `suggest_stock`, `overrule`; score tracks `user` and `user_loop`; the watch list "from you" (120 sessions, 5 a day).
- PLAN.md: E7 done. His registered live test for the overrule track is the T8 style count: the `user` track beside the rule and the model (no new claim is registered; it is a record, not a rule).
- Rule 10 note: the overrule scoring and the suggested-name scoring are RECORDS (every suggestion and overrule is scored after tax against holding/the index); no model or rule is changed by them.

## Tests
`tests/test_s85_loopchat.py` (21): look_into opens at once with his words in the first message; the day's 3 and the queue/release; unknown name; a pick verdict through `propose_picks` with the 120-session watch and no size field; a name failing the floor passed with the reason, no read, still watched;
a wait_for and its pullback reopening; the same name twice = one read; the 5-a-day cap and the next desk; the 120-session expiry; a passed name running 20 points ahead reopens and is told in the chat; a note on a held name opens a case whose first message has the claims and whose answer has worst / likely /
best; the same note twice = one read; a note that adds nothing says where it is already known from; a market note goes to the plan; a document's event reaches the watch; overrule scored both ways (and idempotent); an overrule on a name with no case; the chat tools; a case that acts tells its own chat only.
