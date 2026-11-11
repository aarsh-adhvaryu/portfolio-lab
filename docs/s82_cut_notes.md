# S82 `cut` agent notes (C11 the next cut, C12 small fixes)

Branch `s82/cut` (worktree `D:\s82_wt\cut`). 2026-11-11, written by the cut agent, unattended. Method: every candidate got a reader list built by a script (`D:\s82_scratch\cut\deadfn2.py`: a top-level name is
"live" if its bare word appears in ANY other file of `src`, `tools`, `configs` or the UI `.js/.html`, or in its own file outside its definition; then repeated to a fixed point so a function read only by
a dead function is dead too) and checked by hand with grep for aliases (`gv.`, `hv.`) and for the routes and tool names the UI and the chat use. Nothing was deleted that has a live reader or a live writer.
Tables and rows all stay (no table was dropped; no migration was written: the 165-166 range is unused).

## What the brief listed, and what was already gone

| Candidate | Readers | Writer | Action |
|---|---|---|---|
| `paper/provenance` crediting (`decision_provenance_s79`, `source_credit_s79`, `source_scorecard_s79`) | none in `src`/`tests`/UI (only the migration that made the tables) | none | ALREADY DELETED in S81 B9 (commit 7e22fac). Tables stay. |
| the proposals' scorecard claim writers | `hq/scorecard.table/proposal_view/verdict_of` are still READ by the route `GET /api/scorecard`, the chat tool `scorecard` (listed in `app/assistant.py` READ) and the Rules screen of the UI | none (`hq_claims` has no writer since B9) | The readers STAY (deleting them breaks the Rules screen and a tool the chat lists; layout and chat are not mine). They return empty today. Only the dead constants `HORIZONS`, `KIND` went. Left for S84. |
| the learner's suggestion rules | `learner/record.run` | none | the suggestion/prediction rules were already gone (B9). Now also deleted: `wilson`, `p_better` (+ `WILSON_Z`, `BOOT`, `SEED`, `P_SURE`), `new_outcomes` and the "sooner when 20 outcomes were scored" trigger (read two tables nobody writes), `record_text`, `PROPOSE_SYSTEM`, `PROPOSE_SCHEMA`, `MIN_PASSES`, the always-empty `model_props` and the unused `passes.pair()` call. `due()` is now weekly only. |
| the keeper's prediction scoring | `keeper.run` (job), Agent HQ screen (`views.hq`: `keeper.scorecard`, `hq_predictions`) | none (the brain's passes are gone; no caller of `add_prediction`) | DELETED the writer and scorer: `add_prediction`, `score_due`, `base_rate`, `hit`, `sessions_between`, `scorecard_text`, constants. KEPT `scorecard()` (reads old rows for the HQ screen), `closes`, `followups`, `tidy_notes`, `write_outcomes`, `run` (its result no longer has `scored`). |
| dead callers of `paper/allocation.propose_allocation` | `lab/alloc_lab.py` (the lab's live tool), `verify_book`, `tools/drills_*`, `tools/reseed_s79.py`, 6 tests: all live | the strategist's tool | The function STAYS (a live reader). Deleted the paper team's DEAD helpers in the same file: `dossier_text`, `playbook_text` (the team's dossier and playbook text; no caller). Also the dead `hq/tools_s79/t_allocation._sectors` (parser of the old team tool). |
| `hq/cases` | HQ screen, `GET /api/cases/{id}`, 8 chat tools, `service.round_`/`start`, keeper, `objectives`, `quant/trusted`, `app/world`, `app/inbox`, ~12 test files | `cases.open_case` by the chat tools | STAYS as a module. Deleted its dead functions: `discover` (opened cases for stores that nothing fills; no caller), `brief`, `defer`, `CASE_PASS_EVERY`. |
| `hq/board` | `app/assistant.py` (told to stay), server routes `/api/hq/tasks/..`, `hq/service.round_` (runs the board each round), phone, tools | `board.post` from Telegram `/order`, chat | STAYS. Deleted `run_parallel`, `WORKERS` (no caller). |
| `hq/roster` | `app/server.py /api/hq/order`, `app/world.py`, `service`, `phone`, `views` | n/a (it maps agent names to runners) | STAYS, no dead function. |
| `hq/scorecard` | see row 2 | | STAYS (`skeptical`, `MIN_N` are read by `paper/manager.record`, `paper/cadence.postmortem`; `state_at` by `core/loop`). |
| `hq/keeper` | see row 4 | | STAYS (smaller). |

## Other writer-less code found by the scan and deleted

| Item | Why dead |
|---|---|
| `hq/skills.py` + the folder `src/pflab/skills/` (6 `SKILL.md`) | skills for the paper team's roles; the workers that read them are gone; only its own test read it |
| `hq/history_replay.py` | a 2-line re-export of `fcast.replay`; no importer |
| `hq/governor.mode_pace` | the agenda's per-hour spend pace (agenda deleted; A55 says no throttle) |
| `paper/benchmark.dossier_text`, `construct/run.dossier_text` | blocks for the paper team's dossier; no caller |
| `paper/cadence.lessons_text`, `acted_since` | no caller (`lessons()` stays: the paper view shows it) |
| `paper/manager`: `ACTIONS`, `REVIEW_EVERY_DAYS`, `MOVE_DAY/SINCE/LIVE`, `ACTIVE` | constants of the deleted mission code |
| `agents/analyst.propose_harness`, `HARNESS_SYSTEM`, `HARNESS_TASKS`, `HARNESS_CHARS` | the S47 "harness editor" paid path; no caller anywhere (a paid call nobody can make) |
| `agents/needs.closing_checklist`, `CLOSING_KEY` | a one-off question about closing his bank accounts; no caller; personal-record era |

## Left in place on purpose (found, not removed)

- `paper/watch.handled` and `watch.reasons`: no live caller (they belonged to the paper team's decision), BUT `handled` is the only thing that re-arms or closes a `triggered` watch item, so deleting it
  would leave items triggered for ever. Needs a design decision (who closes a triggered watch in v2); not mine. Their tests stay.
- `hq_suggestions` readers (`app/system.py` x2, `app/research.py` watch ticket, `plan/twin._fills`, `service/summary._suggestion_lines`, `hq/picture`, `hq/cases.link_outcomes`): they read a table with no writer
  (empty today) inside live screens and a live Telegram summary; touching them changes screens/tests. Candidates for S84 together with the screens.
- `hq/views.hq` Agent HQ screen still shows "brain", "predictions", agents: the UI redesign (S84) owns it.
- `core/rails.py` line 35 calls `book.tax_of(after)` without a day (it uses today's financial year, which equals the close's day in the live loop). Not mine; the rails owner may pass `day`.
- `lab/engine.py` keeps its own pinned copy of the tax constants (a test pins it to `book.tax_of`); `kg2/position.py` falls back to `book.LT_EXEMPT`: so `book.LT_EXEMPT` stays as a labelled constant.
- Other dead names the scan listed outside the brief's scope (data/, pm/, quant/, ingest/ helpers, 30+ names, most with tests) were NOT touched.

## C12 small fixes

- a. `data/gdelt_s79b.py` (the S79b data module; every other `src/pflab/data/*` request already carried a timeout, checked by an AST scan of all `requests`/`urlopen` calls): its one `session.get` used a literal
  `timeout=90`; now `TIMEOUT = (20, 60)` (connect, read) is a module constant and the call uses it. Tests: `test_gdelt_requests_carry_the_module_timeout_and_a_hang_ends` (a fake server that hangs unless it is
  given a timeout), `test_gdelt_a_good_answer_still_passes_through`.
- b. `paper/book.tax_of(g, day=None)` reads the exemption through `core/tax_rows.exemption(day)` (the tax engine's dated row for the FY of `day`; `rules.exemption`). The fill passes the sale's day;
  `construct/costs.lots_tax` passes its `day`. A year BEFORE the first dated row (FY2024-25; the 2012 construction study) falls back to the labelled `LT_EXEMPT` instead of crashing (the construction
  study test needs it). Tests: `test_tax_of_reads_the_exemption_from_the_dated_row_not_a_literal` (a different dated row, and the FY boundary 31 Mar / 1 Apr), `test_tax_of_before_the_first_row_...`.
- c. `data/index_membership._session` deleted (no caller anywhere, including `tools/`; the constant it used no longer exists). Test: `test_the_dead_membership_session_is_gone`.
- d. `D:\pl_real_s80` and every `D:\pl_test_tmp_*`: already gone (checked; nothing to delete, nothing personal looked at).
- e. The other code items in PLAN "What remains": the two named there (timeout, `tax_of`) are done above; the rest are his decisions, time, studies (drift overlay, core harvesting), calibration, the strategist session,
  the UI redesign: not mine. Closed with that reason.

## Research overview text (text only, no layout or behaviour change)

`app/static/redesign.js` (`research()` and its `FLOW`): the overview had already been rewritten in S81 B9 to the close loop. Now it also names the knowledge graph (Events box, first blurb), the lab (second
blurb), the strategist as an AI that writes rules while code decides, and the small US paper book in dollars. Three stale old-team sentences were reworded (same elements, only words): Today's "The team is
looking into / idle" line, the Watchlist "What happens next" chips ("The team looks again", "The independent review" -> "The promoted rule looks again", "The rails check it"), and in `ui.js` the Assistant
home blurb and the Investigations screen caption (no more "research and quant workers", "coordinator", "reviewer").

## Tests deleted or rewritten (reason)

| Test | Action | Reason |
|---|---|---|
| `test_hq.py::test_predictions_scored_after_they_were_made`, `::test_base_rate_counts_the_stocks_own_history` | replaced by `test_the_old_predictions_record_is_still_read_but_nothing_writes_or_scores_one` | writer/scorer deleted; the reading of old rows (`scorecard`) that still exists is tested; `test_round_runs_...` now asserts `scored` is gone |
| `test_s62_learner.py::test_wilson_interval` | deleted | `wilson` deleted (nothing used it) |
| `test_s62_learner.py::test_record_due_weekly_or_on_outcomes` | rewritten as `..._weekly_only` | the outcomes trigger read tables nobody writes; the weekly behaviour is still tested, and that old scored rows no longer trigger |
| `test_s64_recency_needs.py::test_the_closing_checklist_...` | deleted | `closing_checklist` deleted |
| `test_s67_cycle.py` IPO-allotment test | rewritten as `test_the_ipo_strategy_weighs_holding_as_much_as_selling_from_the_numbers` | the first half tested `cases.discover` (deleted); the `ipo.strategy` half, which is live behaviour, is kept unchanged |
| `test_s77_account.py` two skills tests | deleted | `hq/skills.py` deleted |
| `test_s79b_benchmark.py` dossier test | rewritten (`status` source and tax label asserted) | `dossier_text` deleted; what it read is still tested |
| `test_s79b_construct.py::test_dossier_text_is_labelled_and_off_switch_silences_it` | deleted | `construct/run.dossier_text` deleted |

The five protected engine suites are untouched. New: `tests/test_s82_cut.py`.

## Shared files touched

`paper/book.py` (`tax_of`, the fill's call), `construct/costs.py` (one call), `hq/board.py`, `hq/cases.py`, `hq/governor.py`, `hq/keeper.py`, `hq/scorecard.py`, `learner/record.py`, `paper/allocation.py`,
`paper/benchmark.py`, `paper/cadence.py`, `paper/manager.py`, `agents/analyst.py`, `agents/needs.py`, `construct/run.py`, `hq/tools_s79/t_allocation.py`, `data/gdelt_s79b.py`, `data/index_membership.py`,
`app/static/redesign.js`, `app/static/ui.js`. None of: core/session, preopen, sleeves, baseline_v2, exits, loop, harvest, rails, lab/, us/, chat, assistant, inbox, bot, voice.

## Exposed for screens

Nothing new. Note for S84: `GET /api/scorecard` and `GET /api/hq` ("predictions", "scorecard") read tables that nothing writes any more.

## Left

Decisions for the coordinator or S84: who closes a triggered watch item (`watch.handled`); whether to retire the `hq_claims`/`hq_predictions`/`hq_suggestions` readers with their screens;
`core/rails.py` could pass `day` to `book.tax_of`.
