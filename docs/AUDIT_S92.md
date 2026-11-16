# Audit S92 (2026-11-16): what to remove, what to simplify, and a simpler way to run the autonomy

Branch `pm/s92-audit`, cut from `main` at `bf4e37d` (tag line v2026.11.16). Nothing here is merged, tagged or installed.

**How it was done.** The repo was read and measured by script, not by eye: an import graph of all 633 modules, the 78 registered jobs, every route in the server against every call the one UI makes, every declared library against every import, and every document path the code or docs name.
**What I could not see.** Your installed app, its store and its usage record. So every statement about tokens below is what the code allows or what your own notes measured, not what was actually spent last week.

## The short version
1. The code is about 119,000 lines in 633 modules. Only 19 modules are truly unreachable; I removed the 5 that were safe (section 1).
2. The real weight is not dead files. It is **six generations of design still shipped together** (statements and tax, the agent team, the brain and missions, the paper team, the close loop, the thinking loop, the operator). The older ones are switched off by config, not deleted, and they are woven into the newer ones, so they cannot be removed file by file. They need ordered cuts (section 2).
3. The autonomy spends on a timetable, not on outcomes. Unattended model work is allowed 1.4 million tokens a day before you type anything. The parts that already work the way you describe (plan cards, Yes/No cards, standing rules, the code-first alarm) exist; they are just not the centre of the design (section 5).

---

## 1. Removed on this branch (behaviour is unchanged)

Rule used: a module goes only if (a) nothing in `src/` imports it, by a normal import, a lazy import or a name in a string; (b) no job, tool plug-in or migration loads it; (c) it is not a file whose text is fingerprinted (see "Do not touch" below); (d) its study record, if any, stays in `docs/`.

| Removed | Lines | Evidence |
|---|---|---|
| `app/front.py` (the local model as the chat's first turn), `tools/s71_eval.py`, its tests, the test fixture that switched it off for every test | 242 + 115 + 195 | No importer in `src/`. `app/assistant.py` itself said "no longer called ... the module stays only because its helpers and tests are imported elsewhere". PLAN.md said twice (S85, S86) that it "can be deleted". Its one live helper, `app/front_render.py` (rupee formatting, used by `plan/envelope.py`), is kept with its test. |
| `eval/roles.py`, `tools/s70_roles.py`, its test | 225 + 179 + 129 | A paid measurement of which model should sit in the reviewer's and coordinator's seats. Both seats (`hq/workers`, `hq/missions`) were deleted in S80. The protocol and its result stay in `docs/`. |
| `deep_pool.py`, its tests, the `[seats] deep_pool` line in `configs/s79b.toml` | 117 + 88 + 1 | A worker pool for "deep mode". No caller anywhere; the config line was read only by the module itself. |
| `kg2/position.py`, its two tests | 137 + 34 | A read-only "position layer" for the graph. No caller. |
| `data/asia.py`, its test | 55 + 18 | Aligned Asian index closes. No caller (the collector that fetches those series is untouched). |

Total: 17 files, 1,536 lines out, 12 in. The five protected engine suites are not touched.
**Checked:** all 4,142 remaining tests collect and the full suite was run; the result is at the end of this file.

**The other 14 unreachable modules stayed, and why:**
| Module | Why it stayed |
|---|---|
| `eval/artifacts.py`, `data/panel.py`, `data/repairs.py`, `data/etf_events.py`, `execution/costs.py` | the research engine behind the protected engine tests (rule 6) |
| `lab/c4_replay.py`, `lab/policies/baseline_lab.py` | run by file path inside the Docker sandbox, not by import |
| `data/symbol_isin.py`, `paper/reseed.py`, `pm/fresh_start.py`, `llm/s79_eval.py` | each is called by a script in `tools/` you may still run |
| `hq/explain.py` (254 lines) | only one drill (`tools/drills_s79.py`) and one test call it; it goes when the drill is rewritten |
| `kg2/study.py` | the measuring code of a registered study that is still pending |

**Do not touch (found while scoping, worth knowing):** these files are hashed by the code, so even deleting an unused function in them changes a fingerprint and with it a study's identity, a promotion record or a ledger rebuild: `core/policy.py`, `core/baseline_v2.py`, `agents/workshop_runner.py`, `learner/templates.py`, `quant/index_event_study.py`, every `docs/protocols/*.md`, and the eight statement readers in `ingest/` plus `tools/build_pm_ledger.py` (a change there makes the app re-read every statement once).

---

## 2. What could go next (each needs your yes; biggest first)

### A. The old screens' back end is still there
S90 deleted the old screens. Their server side stayed.
- The one UI (`app/static/s89/`, 15 files) calls about 35 addresses. `app/server.py` defines 116.
- **At least 66 routes (527 lines of handlers) are called by no screen, no tool and no other module; 33 of those are not named in any test either.** Examples: `/api/world`, `/api/command`, `/api/hq/*`, `/api/coverage/*`, `/api/inbox/*`, `/api/sims`, `/api/scans`, `/api/twin`, `/api/engines/*`, `/api/setup`, `/api/fd`.
- Behind them sit `app/world.py` (355 lines), `app/system.py` (651), `app/inbox.py` (880), `app/views.py` (511), `app/research.py` (287), `app/sims.py` (259), `app/readiness.py` (254), `app/onboarding.py`, `app/checklists.py`, `app/chat.py`: about 3,500 lines written for screens that no longer exist.
- Why not done today: removing a route is a behaviour change by the letter, and most of these modules are also imported by live modules at the top of the file, so they do not fall away when the routes go. The routes are step one; then each module's remaining importers, group by group, with the suite after each.

### B. The two paid engines
`configs/core.toml` sets `force_in_use = "claude_plan"` and `no_api_key = true`. Still shipped: `[engines.claude]` and `[engines.openai]` (about 150 lines of config with price tables), `llm/vendors.py`, `llm/openai_compat.py` (326 lines), the `anthropic` and `openai` libraries, the `analyst` job (an overnight API batch, off unless the API analyst is "adopted"), the rupee governor (`hq/governor.py`, 299 lines) and rupee budgets such as `[strategist] daily_budget_rupees = 30`. Your own S87 note: "the rupee cap is meaningless on the plan". PLAN.md already says "delete them after the first week on the plan if nothing needs them"; that week started today.

### C. The statements era, switched off while the app keeps its own book
While `pm/system_account.toml` exists (it does in the app), these jobs disable themselves at every tick: `plans`, `tradecheck`, `ledger`, `deposits`. Behind them: the statement readers and account set-up in `ingest/` (11 files, about 2,400 lines), deposits, bonds and the Quicko pack (about 1,000), and much of `plan/` (3,000 lines: targets, deploy, ready plans, the pot, nudges). This is real, tested work, so the question is yours: is the statement ledger coming back? If not, it can leave the app (and live on in git history). If yes, it should be an optional add-on that the app does not load.

### D. The retired advisor layer
`[core] advisors_off = true` and `retire_missions = true`. Still registered and ticking: `hq` (every 15 minutes: the task board, the drop-folder watcher, the keeper), `review` and `companion` (wrapped to skip), `kg` (the v1 graph, `configs/kg.toml on = false` since 8 Nov), `twin` (it scores "the brain's own suggestions" from `hq_suggestions`; the module that wrote them was deleted in S80), `seats_mode` (every 5 minutes; with `manage = false` it "records the plan and touches nothing"). Worth the same check: `conductor` and `scans` (their screens are gone). PLAN.md lists the next cut itself: `hq/cases`, `hq/board`, `hq/roster`, `hq/scorecard`, `hq/keeper`, `paper/provenance`. The plan it points to, `docs/CUT_PLAN_S80.md`, is not in the repo.

### E. Libraries nothing imports
| Library | Imports in the repo | Note |
|---|---|---|
| `lightgbm` (pinned exactly) | 0 | pyproject says "a model's bytes depend on the LightGBM that fitted it"; no model uses it now. Brings scipy/narwhals. |
| `PyYAML` | 0 | |
| `langgraph`, `langchain-ollama` | 1 file (`llm/graphs.py`, 83 lines) | Two frameworks (and about ten packages they bring) kept for one small file that only the old agent layer calls. |
| `anthropic`, `openai` | 1 file (`llm/vendors.py`) | See B. |
| `yfinance` | 1 file (`data/dividends.py`) | |
| `pdfplumber` | 1 file (`data/index_changes.py`) | |
Not removed today because `tests/test_s65_release.py` keeps `requirements.lock` equal to your `.venv`: the lock and the venv must change together on your PC.

### F. Switches that no longer switch anything
- Settings > "Local model first" (`local_first`): the only code that read it was `app/front.py`, which nothing called. It has controlled nothing since the front stopped being called. Remove the switch or wire it to the alarm reader its label describes.
- `[strategist] session_rupees`, `min_session_rupees`, `daily_budget_rupees` and the `[engines.*.prices]` tables: rupee controls on an engine that costs 0 rupees.

### G. Drills and replays live in `tools/`
About 9,900 lines (`drills_s79.py` 1,277, `drills_s81.py` 2,982, `drills_s85_week.py` 568, `replays_s84*.py` and `replays_s85*.py` about 2,000). They are tests in all but place, and they are what keeps otherwise unused modules alive (`hq/explain.py`, 254 lines, is called only by one drill and one test). Move them under `tests/drills/` so the installed app does not carry them and so "used by the app" and "used by a drill" stop looking the same.

### H. The documents describe a system that is gone
- `docs/BUILT.md` opens "as of S69", gives the store as "schema v45" and "v49" (the store is past v143), and still documents Gmail, missions, proposals and the World screen.
- 24 document paths named in code, config or docs do not exist (for example `docs/CUT_PLAN_S80.md`, `docs/s82_cut_notes.md`, `docs/s81_test_findings.md`, `docs/s86b_closeout_notes.md`).
- `README.md` says 74 jobs (78 are registered) and 116,000 lines.
- `pyproject.toml` comments say `anthropic` is "used only by agents/analyst.py" (it is imported only in `llm/vendors.py`).
- `docs/PLAN.md` is 494 lines, of which about 300 are old morning reports. CLAUDE.md asks for "what remains"; a new session has to read all of it.
A new Claude Code session reads these first, so stale docs cost tokens and produce wrong work. Suggest: BUILT.md regenerated from the code (jobs, routes, tables are all listable by script), PLAN.md cut to intent + decisions + what remains, the reports moved to `docs/history/`.

---

## 3. Duplicated logic (same job done in more than one place)

| What | Where | Suggest |
|---|---|---|
| Chat: seven layers, 2,967 lines | `app/chat.py`, `app/assistant.py`, `agents/centre.py`, `agents/escalate.py`, `hq/converse.py`, `hq/passes.py`, `hq/reception.py`, `service/bot.py`, `service/tg_entrance.py`, `entrance/intake.py`, `entrance/router.py`, `oper/pathrouter.py`, `oper/light.py`, `oper/session.py` | Two routers choose a road (`entrance/router.py` picks the model, `oper/pathrouter.py` picks the road). Keep intake -> one router -> quick or full. The rest is the pre-operator chat. |
| Tool registries: five, 2,805 lines + 927 in plug-ins | `hq/tools.py` (1,778 lines, about 130 tools), `agents/tools.py`, `entrance/tools.py`, `oper/tools.py`, `lab/tools.py`, `hq/tools_s79/` | One registry holding the tools the operator and the quick road actually offer (29 by default and 39 by name, per the S88 notes); the old brain's tool loop is what the other 60-odd were written for. |
| Knowledge graph: two | `kg/` (v1, switched off, 1,391 lines) and `kg2/` (live). But live code still imports `kg.events` (the close loop, the session loop, the watch) | Move the one live piece (`kg/events.py`) into `kg2/`, then delete v1. PLAN.md already parks "merging the old and new knowledge graphs". |
| "Start again": seven paths, 968 lines | `pm/fresh.py`, `pm/fresh_start.py`, `pm/reset.py`, `paper/reseed.py`, `tools/fresh_start.py`, `tools/fresh_start_s90.py`, `tools/reseed_s79.py` | One command with modes (mind only / book re-seed / whole profile). |
| Scheduling: three rule sets | each job's own `Daily(...)`/`Interval(...)`, `service/ondemand.py` (`AFTER`, `MAX_AGE_H`), and the market-mode clock | CLAUDE.md says "by the clock's MODE ... never by job times", yet 34 of the 78 jobs still carry a clock time. One table: job, what it follows, how stale it may get. |
| Trading costs: two models | `execution/costs.py` + `configs/costs_zerodha.toml` (research engine) and `pm/costs.py` + `configs/costs_zerodha_pm.toml` (the app) | Keep both only if the engine tests need the first; say so in one line in each. |
| Tax rates | `paper/book.py` hard-codes 20% / 12.5% / 30% beside the dated tables in `configs/tax/` (the file itself notes one constant is "no longer read") | Read the dated rows everywhere (PLAN.md lists this as open). |
| Naming by build session | 52 source files and 143 tables carry a session number (`tasks_s79_think84.py`, `plans_s89`, `core_runs_s80`); 31 job modules are all called `tasks_s79_*` whatever session made them | Name by what it does. Renaming tables needs migrations, so do files first. |

---

## 4. Assumptions that no longer hold

1. **"Money is the limit."** Budgets, the governor, the acceptance window and the strategist's throttle are all in rupees. On the plan every call costs 0 rupees; the real limit is plan tokens per day and week. Two currencies of control are maintained and only one binds.
2. **"A second engine will take over."** OpenAI is configured, priced and shadow-ready. Rule 9 now reads "no paid API".
3. **"The record comes from his statements."** The app's ledger is the system's own account; statements are refused by the chat's privacy screen.
4. **"The local model takes the small jobs."** The chat no longer uses it; the switch for it is dead (2F). It still reads for the alarm, the learner and the storylines.
5. **"A team of agents works the book."** Deleted in S80; its roster, board and case tables still run every 15 minutes.
6. **"The tick runs it while the window is closed."** The design since S79 is "it runs whenever the app is open". If the scheduled tick is no longer registered on your PC, then `tools/register_tasks.ps1`, `pflab service tick` and `hq/service.tick_job` are leftovers (I cannot see your Task Scheduler: confirm before cutting).
7. **"More layers make it safer."** Each rebuild added a layer and switched the previous one off. The result is that a change anywhere must be checked against six designs, the full suite takes 45 to 55 minutes, and one automatic bug-fix attempt cost 562,000 tokens (both figures from CLAUDE.md).

---

## 5. The autonomy loop: why it burns and does not arrive, and the Jarvis design

### What the code does today
Model work that starts with no message from you:
| What | When | Allowed a day | Your own measurement |
|---|---|---|---|
| Daily desk (`think/desk.py`) | after the Indian close and in the US morning | 250,000 tokens | about 14,000 a run |
| Cases (`think/session.py`), up to 3 new a day, plus alarm cases outside the cap | every close, every gap | 350,000 | about 12,000 a case |
| Self-fixing builds (`oper/build.py`) | by itself after a repeated fault, at most once a day (2 builds a day in all) | 800,000 | 398,000 and 562,000 for single builds |
| Weekly introspection, weekly strategist session, fast-forward "looks" after a gap, big-trade check | weekly / per gap / per trade | inside the classes above | |
That is **1.4 million tokens a day the system may spend before you type anything**, on a Pro plan (your S87 note speaks of a weekly limit "already 70% used").

### Why it does not arrive anywhere (from the code and your notes)
- **The answer comes weeks later.** A decision is scored at 5, 20 and 60 sessions; rates count only from 20 scored decisions; a challenger needs 20 shadow sessions. So for the first two months the loop spends daily and can show nothing.
- **The rails and the failed studies leave it few moves.** Harvesting, stops on long holdings and the swing sleeve are off after their studies (`configs/core.toml`); India-listed international ETFs are stopped by the premium rail; one bet may risk at most 1% of the book; at most 3 new cases a day. So a session often has little it is allowed to do, and it pays the full reading cost to find that out.
- **It runs by the calendar.** A desk session happens because the market closed, not because something needs deciding.
- **Fixing itself is the dearest thing it does**, and it does it on a codebase that is expensive to read (section 4, point 7).
- **You are outside it.** It reports after acting. You said the opposite: plan together first, then it carries the plan out.

### The proposal: three gears instead of one loop

**Gear 1, always on, free: code.** Collectors, the close loop, the rails, the exits, the alarm's NOTICE step, scoring. This is already code and stays exactly as it is. This is "Jarvis keeping the house running".

**Gear 2, the model works only on a trigger.** Three triggers, nothing else:
1. you ask (quick road or full road, as now);
2. a **plan you started** (plan cards already exist: `oper/plans.py`, "nothing runs before Start", steps tick live, pause at the limit and resume);
3. a RED alarm on something you hold or the book holds (as now: heard first, then thought through).

**Gear 3, standing orders: how "Jarvis takes over".** A plan card gets one new property: *repeat*. "Every close, look at any holding that moved more than its usual; tell me only if you would act", with a token allowance you approve once. That is a standing order. The desk and the case loop become two standing orders that ship switched on, visible on the Agents screen with their allowance, last run, tokens used and what came of it, and you can pause, edit or delete them in chat. Nothing new runs unless a standing order or you start it.

What changes for the unprompted work:
- Instead of spending, the system **queues one line**: "3 things worth a look: (1) ..., about 25k tokens. Start?" on Home and Telegram. No tokens until Start.
- **Self-fixing never starts by itself.** A repeated fault becomes a card: "this failed twice; a fix attempt costs about 400k tokens. Start / Not now."
- **One budget in one currency**: tokens a day for standing orders, tokens a day for you. The rupee machinery goes (2B).
- **Receipts**: every standing order shows tokens in, outcomes out (a decision, a trade, a finding you opened). A standing order with no outcome for two weeks pauses itself and says so.

Why this is small to build: every part exists. Plan cards (244 lines), Yes/No cards (`oper/actions.py`), standing rules (`hq/rules.py`), the router, the token classes, the code-first alarm. The work is (a) a `repeat` field and a due-check on plans, (b) turning `think_loop`'s model step and the desk into two default standing orders, (c) the queue line instead of auto-start, (d) the build card. I estimate two sessions, most of it deleting the scheduling around the desk.

What you give up: the system will no longer surprise you with a thought you did not ask for unless a standing order or a RED alarm produced it. Given your 13 Nov rule (a late action on serious news is the real failure), the alarm lane stays fully automatic; that is the one place where spending without asking is right.

**This is a design change, so it is not on this branch.** It also changes two of the first-week check's fourteen criteria (`service/week_check.py`: 8 "the daily desk ran on every day the app was open" and 9 "the thinking loop watched every close ... no case without its look"), so those two would be rewritten with it, on your word.

---

## 6. Suggested order (each step leaves a working app and a green suite)
1. Merge this branch (no behaviour change).
2. Decide the Jarvis design (section 5). If yes, build it next: it removes the reason for much of what follows.
3. Cut B (paid engines, rupee governor) and E (libraries) together: one lock change on your PC.
4. Cut A (old routes and their modules), group by group.
5. Cut D (advisor layer) and merge `kg/events.py` into `kg2/`.
6. Decide C (statements era): out, or an optional add-on.
7. Move drills to `tests/` (G), regenerate BUILT.md and shorten PLAN.md (H), rename by function.
My estimate after steps 3 to 7 (an estimate, not a measurement): about 90,000 lines from 119,000 in `src/`, the installed app without 9,900 lines of drills, one chat path, one tool registry, one graph, one scheduler table, and a shorter suite.

---

## Test result for this branch
Run in a Linux cloud container (Python 3.13, `requirements.lock` without the Windows-only packages), not on your PC.
**4,142 tests: 4,101 passed, 17 skipped, 24 failed. None of the 24 comes from this branch:**
- 7 are the failures PLAN.md already records for a Linux run: the 6 `test_engine_golden` digests (platform floating point; the engine tests are untouched) and `test_app_launcher::test_children_end_with_the_system` (Windows process tree).
- 1 uses a Windows path (`test_s87_operator::test_answer_session_cannot_write_src_or_push` reads `C:/Windows/win.ini`).
- 16 are in `tests/test_s85_engines.py`, the tests of the paid engines (section 2B): each stops at `ConsentMissing: nothing is sent to openai before his Yes`.
The last 17 were checked against an untouched copy of `main` in the same container: the same 17 fail there, by name (17 failed, 34 passed in those two files). I cannot tell from here whether the 16 pass on your PC; run `tests/test_s85_engines.py` once there. If they fail there too, that is a fault on `main` from before this branch.
After the doc edits the doc-reading tests and every test file this branch touched were run again and pass.
Still yours before a merge: the suite on your PC and `python -m pflab.hq.security push` (the privacy check needs your `privacy_terms.json`, which the cloud does not have; I read the diff by hand: it is deletions, test trims and these notes, with no amount, name or id of yours).
