# The cut: from the repo as it is to the portfolio buddy

This file is the work order for Claude Code on his PC (Sonnet 5.5, high effort). It is written to be read at the start of every session and to carry the state between sessions.
The target is `docs/BUDDY.md`. Read that page first, every session. It is short.

## State (update this block at the end of every session)

- [ ] Phase 0. Baseline on the PC
- [ ] Phase 1. Telegram out
- [ ] Phase 2. Paid engines, rupee budgets, unused libraries out
- [ ] Phase 3. One portfolio: his
- [ ] Phase 4. The trader out (the paper account and everything that feeds it)
- [ ] Phase 5. The old layers out
- [ ] Phase 6. Compute: fill the gaps
- [ ] Phase 7. Screens
- [ ] Phase 8. Documents, acceptance, his Yes

**Next step:** Phase 0, step 1.

## How to work (every session)

1. **One phase a session.** Do the first phase that is not ticked. When its "Done when" holds, tick it, write the "Next step" line, give him the report and stop. He starts the next session himself. If you run low on context in the middle of a phase: commit what is whole, write exactly where you stopped in "Next step" and in the Log, and stop. A half-finished phase that is written down costs nothing; one that is not costs a session.
2. **Read little.** Read `docs/BUDDY.md`, this file's State and your phase. Do not read `docs/PLAN.md`, `docs/BUILT.md` or `docs/STUDIES.md` in full: they describe what is being removed (search them when you need one fact). Use `python tools/reach.py` instead of reading code to find out what depends on what; it runs in seconds.
3. **Where `CLAUDE.md` and `docs/BUDDY.md` disagree about what the system is, `docs/BUDDY.md` wins.** The working rules and the non-negotiables in `CLAUDE.md` still hold, with two changes for this cut: the first-week check and the 60-day freeze are suspended (he asked for this cut), and rule 10's "its code is deleted, its study record stays" is the model for everything here.
4. **Delete, do not switch off.** The reason this cut exists is that six designs were switched off one after another and left in place. So: no `on = false`, no `if False`, no "kept for later", no commented-out code, no wrapper that skips. A deleted feature loses its code, its job, its route, its chat tool, its command, its screen parts, its section in `configs/`, and its tests. Git keeps the history; the branch `legacy/full-system` (Phase 0) keeps the whole old system.
5. **The order inside every phase is fixed, because `tools/reach.py` follows imports and not calls:**
   1. delete the entry points the phase lists (jobs, routes, chat tools, `cli.py` commands, screen parts, config sections);
   2. cut the seams: the places where code that stays imports code that goes (`python tools/reach.py --seams <packages>` lists every one);
   3. run `python tools/reach.py`; delete what it lists (`--paths` gives the files), except the files in "Allowed to stay unreachable" below;
   4. run `python tools/reach.py --tests`: a file marked `only` is deleted, a file marked `mixed` loses the tests of deleted code and keeps the rest;
   5. `python -m pytest -q --collect-only` must show no error; then run the tests of the modules you touched; then the full suite once at the end of the phase.
6. **Tests.** A test of a deleted feature is deleted with it: never skipped, never marked as an expected failure. A failing test of a feature that stays means the code is wrong: fix the code. The engine tests (`test_engine_*`, `test_lookahead`, `test_negative_control`, `test_measurement_fixes`, `test_accounting_audit`) are never edited.
7. **Small commits.** One step, one commit, on the branch `pm/s94-buddy`. Message of 10 lines or fewer. After each commit add one line to the Log at the bottom of this file. Before each push: `.venv\Scripts\python -m pflab.hq.security push` must print "privacy grep: clean". Nothing is merged to `main`, tagged or installed in this cut; that is his Yes at the end of Phase 8.
8. **Do not rename or move what stays** (no new package names, no renaming of `tasks_s79_*` files or `*_s89` tables). Renaming is a separate pass after the cut; mixing the two makes every diff unreadable. Two moves are allowed because a deletion needs them, and they are named in Phases 3 and 5.
9. **Do not design.** Where this file says what to build, build that. Where something is unclear or a step turns out wrong, do the smallest thing that keeps the phase's "Done when" true, write one line in the Log starting "CALL:", and go on. Stop and ask him only for the things in "Ask him first".
10. **Report to him at the end of a session: 15 lines or fewer, plain words:** what is gone (lines and files), what still works and how you checked it, what you could not check, the CALL lines, what is next.

### Never touch in this cut
- `src/pflab/pm/mig_s79/` and the store's base schema. His store carries those versions. If a migration imports a module you are deleting, copy the few lines of table definition it needs into the migration and delete the import.
- **His store's tables.** Deleted features leave tables behind in his store; leave them. Phase 8 lists them and asks him.
- `docs/protocols/*.md` (their text is fingerprinted) and `docs/STUDIES.md` (the record; you may add to it, never remove).
- `learner/templates.py`, `quant/index_event_study.py`, `agents/workshop_runner.py` (fingerprinted: any edit changes a study's or the sandbox's identity).
- His limits: the watchlist's cap of 25, the token budgets, the alarm thresholds.

### Allowed to stay unreachable
The research engine behind the protected engine tests, and one pending study: `data/etf_events.py`, `data/panel.py`, `data/repairs.py`, `data/symbol_isin.py`, `eval/artifacts.py`, `execution/costs.py`, `kg2/study.py`.

### Ask him first (a Yes/No question in the chat, then wait)
- anything that would change a number he set, or drop a table from his store;
- deleting a feature that `docs/BUDDY.md` lists under the four jobs;
- a new library (rule 4).

---

## Phase 0. Baseline on the PC (no code change)

Why: every later phase is judged against a known starting point, and two branches (`pm/s92-audit`, `pm/s93-jarvis`) have only been tested in a Linux container.

1. `git fetch origin`, then `git checkout pm/s94-buddy`. Make the safety branch of the whole old system and push it: `git branch legacy/full-system origin/main`, `git push origin legacy/full-system`. (A branch, not a tag: the app installs the newest tag that looks like `vYYYY.MM.DD`.)
2. `.venv\Scripts\python -m pip install -e .` if the install is stale, then the full suite once: `.venv\Scripts\python -m pytest -q --basetemp <scratch> -o tmp_path_retention_policy=failed` (the option deletes each passed test's temporary folder; without it one full run left more than 20 GB behind in the container. If this pytest does not know the option, leave it out and clear the scratch folder by hand).
3. Write the result in the Log: passed, failed, and the name of every failing test. In the Linux container 16 tests of `tests/test_s85_engines.py` failed on `main` with "ConsentMissing"; say whether they fail on the PC too. Do not fix anything: Phase 2 deletes that file.
4. `python tools/reach.py` and `python tools/reach.py --seams core paper ledger`: write the two summary lines in the Log (in the container: 12 modules nothing reaches; 182 imports of core, paper and ledger from 100 modules outside them).

Done when: the Log has the baseline, `legacy/full-system` is on the remote, nothing else changed.

## Phase 1. Telegram out

Why: he does not need it. It touches 47 source files and 37 test files but carries no logic the buddy needs, so it is the safest first cut and a good rehearsal of the method.

Delete: `service/telegram.py`, `service/bot.py`, `service/tg_entrance.py`; the jobs `outbox`, `outgoing`, `summary_morning`, `summary_evening`, `autonomy_check`, `idle_cash`; the `cli.py` commands `bot` and `service test-alert`; the Telegram part of Settings (the design file, `settings.js`, `chat.js`), of `pflab setup secrets` and of `configs/`; every `channels=(..., "telegram")` argument and the Telegram half of `entrance/cards.py` (`_to_telegram`, the outbox id on a card).
Keep the message, drop the channel: wherever code told him something on Telegram AND in the chat, the chat line stays. Where it told him ONLY on Telegram and the message serves one of the four jobs (the alarm lane's "heard", the Problems line of the week, the catch-up digest), post it to the chat instead (`entrance/store.post_system`).
Add, small: a serious alarm also raises a Windows notification while the app is open, using what the launcher already has. If that needs a new library, do not add one: show it as a banner at the top of Home and say so in the report.

Done when: `git grep -i telegram -- src configs tools` finds nothing but history notes in docs; the alarm lane's tests pass with the chat as the place it is heard; the full suite passes.

## Phase 2. Paid engines, rupee budgets, unused libraries out

Why: rule 9 is "no paid API", so this code can never run; the rupee budgets control an engine that costs 0 rupees.

Delete: `llm/vendors.py`, `llm/openai_compat.py`, the sections `[engines.claude]` and `[engines.openai]` (and their price tables) in `configs/core.toml`, the `pflab engine` command, the engine exam, shadow and consent code in `llm/gateway.py` (the one door stays: it resolves a role to the plan engine and logs the call), the job `analyst`, `hq/governor.py` and every rupee budget (`session_rupees`, `daily_budget_rupees`, `api_budget.toml`), `tests/test_s85_engines.py`.
Libraries: remove `lightgbm` and `PyYAML` (no import anywhere), `anthropic` and `openai` from `pyproject.toml`; uninstall them from `.venv`; regenerate `requirements.lock` the way `tests/test_s65_release.py` expects (it keeps the lock equal to the venv). `langgraph` and `langchain-ollama` go in Phase 5 with `llm/graphs.py`.

Done when: no file imports `anthropic` or `openai` and neither is in `pyproject.toml` (what remains of those words is the blanking of key variables and the sign-in check in `llm/claude_plan.py`); `tests/test_s65_release.py` passes; the full suite passes.

## Phase 3. One portfolio: his

Why: this is the leak that matters most. `pm/today.build` returns the system's own account when the app runs (`if system.active(): ... his real Kite holdings and cash never overlay it`), and the chat tools `portfolio` and `exposure_shock`, the stress job and others read it. The screens read his real holdings (`app/s89.mine`). After this phase there is one reader, and Phase 4 can delete the ledger without anything going blind.

1. **Move (allowed):** create `src/pflab/holdings.py` from the reading half of `app/s89.py`: `india(con)`, `us(con)`, `watchlist(con)`, `mine(con, now)` (India + US, rupees, weights), `universe(con)` (held + watched, with ISIN and market), `snapshot_at(con)`. It reads `mine_in_s89`, `mine_us_s89`, `watch_s89`; it never writes, never calls Kite, never reads the ledger. `app/s89.py` keeps the refresh from Kite and calls the new module for reading. State plainly in its docstring what it cannot know: purchase dates (so no tax and no holding period), and cash.
2. Run `python tools/reach.py --seams pm` and take every use of `pm.today` outside `pm/`. Each one that stays in the buddy (chat tools, `risk/` scenarios, `quant/` co-movement, stress, forecasts, the alarm's exposure, the think loop's NOTICE) now takes its positions from `holdings.mine` / `holdings.universe`. Give each tool's output a line saying which snapshot it used and when it was taken.
3. The watchlist is part of the universe everywhere a study or an alarm asks "which names": co-movement, pairs, alarms, news top-up, candles, the graph.
4. Tests: one test per re-pointed tool on a synthetic store where the system account and his holdings DIFFER, asserting the tool reports his.

Done when: `python tools/reach.py --why pflab.pm.today` shows no reachable importer outside `pm/` and the entry points Phase 4 deletes; the new tests pass; the full suite passes.

## Phase 4. The trader out

Why: see `docs/BUDDY.md` "What it is not". This is the large phase (182 seams); it may take several sessions. Work the sub-steps in order and commit after each.

**4a. Entry points.** Delete the jobs `core_loop`, `paper`, `paper_daily`, `lab_close`, `strategist`, `pick_score`, `benchmark_attr`, `fills_calibrate`, `preopen_job`, `session_job`, `session_report`, `us_close`, `us_session`, `us_prices_daily`, `bear_resolve`, `twin`, `companion`, `review`, `scans`, `plans`, `tradecheck`, `ledger`, `deposits`, `guards`, `nav`, `conductor`, `research`; the screen "Claude's book" (`book.js`, its template, its design file, its place in the navigation); the chat tools about the paper book, picks, the strategist, money plans, deposits and tax; the `cli.py` commands `pm` (all of it), `us`, `conductor`, `trades`, `inbox`, `research`, `analyst`, `quant`, `event`, `thesis`, `drift`, `ipo`, `workshop` where they serve the paper account or the statements; `hq/rules.py` (standing money rules) and its door in the chat's intake; the sections of `configs/` for all of these.
Before deleting a job, look at what it writes. If a kept screen or tool reads that (for example the price of a held name), keep that part as its own small job and delete the rest; write a CALL line.

**4b. The thinking loop gives views, not trades** (`docs/BUDDY.md` "Views, not trades"). In `think/`: NOTICE runs on `holdings.universe` (held and watched). UNDERSTAND is unchanged. The option list becomes: for a holding hold, add, trim, sell, wait; for a watched name buy in parts, wait, skip. OUTCOMES in rupees are computed on his real position (for a watched name: on a position of 1% of his portfolio, said so). DECIDE picks the view by the existing rule's logic but ACTS on nothing: delete the acting half (orders, the reserve, freezes of buying, parts bought on schedule, the big-trade check, the fast-forward ghost trades). SCORE compares the view at 5, 20 and 60 sessions with simply holding, before tax, and keeps calibrating the words. The registered live test of the acting rule ends: add a dated line to `docs/STUDIES.md` ("ended 16 Nov 2026 by a design change, not by a result"); do not edit its protocol file.
The daily desk keeps only what serves the four jobs: the cases due a look and one line on what changed in his holdings. Its "find an idea for the paper book" part goes.

**4c. Delete by reach.** `python tools/reach.py --seams core paper ledger plan tax` until it prints 0, then steps 3 to 5 of "the order inside every phase". Expected to go whole: `core/`, `paper/`, `ledger/`, `plan/`, `tax/`, `conductor/`, `calc/` and `risk/` parts that only valued the ledger, the statement readers in `ingest/` (keep `kite.py`, `intraday5.py`, `headlines.py`, `sec_8k.py` and whatever the collectors use), most of `pm/` (keep `store.py`, `secrets.py`, `secrets_setup.py`, `mig_s79/`, and what the collectors use), the paper half of `us/` (keep its prices, calendar and filings), `lab/` policies, promotion, strategist and allocation (keep the sandbox, the registered-study runner and what `learner/` needs).

Done when: the packages in `docs/BUDDY.md` "Done when" 2 are gone; a view on a held name and on a watched name is produced, stored and scored in a test on a synthetic store; the full suite passes.

## Phase 5. The old layers out

Why: earlier designs, already switched off by `advisors_off` and `retire_missions`.

1. **Server.** In `app/server.py` delete every route no screen calls: list the paths the screens use with `git grep -ohE "/api/[a-zA-Z0-9_/]*" -- src/pflab/app/static | sort -u`, add the ones `verify.py` and `app/launcher.py` call, delete the rest and the app modules only they used (`world`, `system`, `inbox`, `views`, `research`, `sims` if nothing kept calls it, `readiness`, `onboarding`, `checklists`, the old `chat` and `assistant`).
2. **Jobs** `hq`, `kg` (the v1 graph), `seats_mode`, `voice`; the switches `advisors_off` and `retire_missions` themselves (nothing is left for them to switch).
3. **Move (allowed):** `kg/events.py` becomes `kg2/events.py`; then delete `kg/`.
4. **One tool registry.** `hq/tools.py` holds about 130 tools for the old brain. Keep the tools the two chat roads offer (`oper/tools.py` DEFAULT and the names it lists for `more_tools`, and the quick road's five in `oper/light.py`) minus the ones Phase 4 deleted; delete the rest and `hq/tools_s79/` plug-ins nothing offers.
5. **One chat path.** Intake -> `oper/pathrouter.py` -> quick or full. Delete `entrance/router.py`'s model choice if the path router already decides, `hq/converse.py`, `hq/reception.py`, `agents/centre.py`, `agents/escalate.py` and what only they used.
6. Then by reach: `agents/` (the calculation sandbox stays: `sandbox.py`, `workshop.py`, `workshop_runner.py`), `hq/` (keep `egress.py`, `redact.py`, `security.py`, `tools.py`, `passes.py`, `llm.py` and what they need), `llm/graphs.py` with `langgraph` and `langchain-ollama` (lock and venv as in Phase 2), `story/` and `learner/` only where they served the brain.
7. `tools/`: delete the drills and replays of deleted features (`drills_s79.py`, `drills_s81.py`, `drills_s85_week.py`, `replays_s84*.py`, `replays_s85*.py` are about the paper account and the old loop: keep only a drill that still passes and tests a kept job), the seven "start again" scripts and modules except one.

Done when: `python tools/reach.py` lists only the allowed files; `git grep -n "advisors_off\|retire_missions"` finds nothing; the app starts and every screen's data route answers (`pflab verify --offline` or a test client); the full suite passes.

## Phase 6. Compute: fill the gaps

Why: "Compute" is the reason the project exists (`docs/BUDDY.md` job 2). Do this only after the cut, so new code lands on a clean base.

1. Make the inventory first, in the Log: for each line of job 2 (ranges, stress, together, what-if, forecasts, backtest, search), the tool that does it today, what it reads, and whether it works on `holdings.mine` and on the watchlist. No building before the table is written.
2. Build only what the table shows missing. Expected: **what-if** (a tool that takes "add X rupees of A, trim B by half, replace C with D" and returns the before and after of ranges, stress, concentration and co-movement, by calling the existing tools on a changed copy of the positions) and **search** (weights for his holdings, baskets from the watchlist, pairs): code only, the count of combinations tried in every result, the result judged on a period the search did not see, registered through `learner/` so it counts in the counter, and the answer worded as "best of N tried; on unseen data it did X" and never as a recommendation.
3. Every compute tool returns numbers with their date and source and a short "how sure" line. No tool calls a model.
4. The nine questions of `docs/BUDDY.md` "Done when" 4 become nine tests on a synthetic store.

Done when: the inventory is in the Log, the nine tests pass, the full suite passes.

## Phase 7. Screens

Why: he asked for the screens to be improved, and they must show only what exists.
Source of the screens: the design export `design_s89/` on his PC (it is not in git) and `tools/build_screens.py`. Change a screen by editing its design file and rebuilding; never edit a built template. List every design file you changed in the report, so he can make the same change in his Claude Design canvas. If `design_s89/` is not on the PC, stop and ask him for it.

1. **Navigation:** Home, My portfolio, Watchlist, Lab, Memory, Chat, Engine, Settings. "Claude's book" is gone. Agents and Usage become one screen, Engine: the four standing orders as switches (`GET /api/agents` -> `standing`; `POST /api/agents {"order": key, "on": bool}`), the model and thinking level of each agent, tokens used today and over 7 days per order.
2. **Home** answers three things without scrolling at 1366 x 768: what changed in his holdings today; what needs him (alarms, waiting cases, open cards); what is running (plans, repeating plans with their next run, standing orders).
3. **Watchlist** is its own screen: each name with price, day move, where it stands in its 52-week range, its alerts, the buddy's last view and its date, a "study" button; add and remove in place.
4. **Lab** shows a study as a chart, three numbers and a one-line verdict, not as paragraphs: the range fan, the stress bars, the co-movement grid, the pair's spread, the what-if before and after. Names are picked from his holdings and watchlist.
5. **Stock** works for any held or watched name: price and candles, what is known (Memory), its views with their scores.
6. Nothing dead: no button, tab, setting or empty panel for a deleted feature. Every page draws from stored state with no model call, and asks the server once for its data where it can. Measure each screen's load before and after and put both in the report.
7. Check at 1366 and at 390 pixels wide. If you have a browser tool, look at every screen and say so; if not, say "drawn and tested by code, not seen".

Done when: `docs/BUDDY.md` "Done when" 6 holds and the report lists the design files changed.

## Phase 8. Documents, acceptance, his Yes

1. Rewrite `CLAUDE.md` (120 lines or fewer): what the system is, from `docs/BUDDY.md`; the non-negotiables and working rules that still apply; the commands that still exist. Rewrite `README.md` the same way. Regenerate `docs/BUILT.md` from the code (jobs, routes, tools, tables, switches: listed by script, not from memory). Cut `docs/PLAN.md` to intent, decisions and "What remains"; move its old reports to `docs/history/`.
2. Delete `service/week_check.py`, its job and its tests: `docs/BUDDY.md` "Done when" replaces it. Add `pflab verify` checks for items 1 to 7 of that list where a check can be coded.
3. Run every item of "Done when" and write the result of each in the Log.
4. List the tables his store still holds for deleted features (compare the tables the remaining code names with `information_schema.tables` after the migrations run on an empty store). Do not drop any.
5. Report to him and ask three Yes/No questions: merge `pm/s94-buddy` to `main` and tag it; drop the listed tables after a backup; rename by function (the separate pass).

---

## Log (one line a commit; CALL lines for every decision you made alone)

- 2026-11-16 (cloud, before Phase 0): `docs/BUDDY.md`, this file and `tools/reach.py` written on `pm/s94-buddy`, on top of `pm/s93-jarvis`. Nothing deleted yet. Linux container baseline for `pm/s93-jarvis`: 4,115 passed, 24 failed (6 engine golden digests, 1 process-tree test, 1 Windows-path test, 16 in `tests/test_s85_engines.py`); the same 24 fail on `main` there.
