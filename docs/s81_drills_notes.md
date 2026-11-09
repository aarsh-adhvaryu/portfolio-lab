# S81 drills: notes of the drills agent

Branch: the drills agent's worktree branch (`worktree-agent-a8dcd6c716e2e3dc2`), based on `pm/s81-loop` at `7a3b368`. Files: `tools/drills_s81.py` (new), `tools/drills_s79.py` (stamped
"superseded"), `tests/test_s81_drills_harness.py`, `tests/test_s81_drills_fixes.py`, and three small fixes in `src/` (below). No table, no migration, no config. `tools/rehearse.py` is
untouched (nothing here needs it: the profile is built from nothing).

## What it is

`python tools/drills_s81.py list | steps | run [--only a,b] [--jobs 8] [--out F.json] [--findings F.md] [--start 2026-10-15] [--run-name NAME]`
(from the repo folder, `.venv\Scripts\python`, `PYTHONPATH` set to the checkout's `src` as for pytest). Output: a JSON report and a findings markdown (a table of drills and of accelerated
steps, then each finding with where and how to reproduce). Result per drill: PASS | FAIL | OFF | ERROR with evidence lines (`ok:` / `FAIL:` / notes). Exit code 0 when every drill is PASS or OFF.
`S81_DRILLS_DIR` (default `D:\s81_scratch\drills`) is where runs go; `S81_SRC=<another checkout>\src` runs the drills against that checkout's code (its `configs/` come with it), which is how
the harness was checked against the other agents' branches before the merge. A full run takes about 3.5 minutes (net_down alone is 200 s: the real fetch jobs wait out their retries).

How the world is faked (nothing leaves the PC, nothing touches the app, the workshop's store, the secrets or the Kite token): a profile built from nothing (synthetic names, ISINs `INE9S..`/`INF9S..`,
synthetic prices with a seed, the account re-seeded from invented Kite holdings, one allocation target; the prices from the start day on are held back and "arrive" one session at a time through the
faked `prices` job, together with the data files the jobs read: the Nifty series, a US series, the lab's panel); an injectable clock and a Runtime that is never started with threads (`Runtime.start`'s
on-open code is called for real); every request raises ConnectionError; a fake Ollama through `requests`; a fake Telegram transport; a counting stand-in for the paid client. The fetching jobs are
replaced by fakes (`FAKE_JOBS`); every other job in the registry runs for real, including `core_loop`, `paper`, `catch_up`, `story_daily`, `lab_close`, `strategist`, `kite_token`, `voice`.

## The drills (each in its own child process on its own clone of the profile)

| drill | what it injects, what it asserts |
|---|---|
| smoke | the registry loads, a close loop runs, the Today endpoints (19) answer, the outbox queues once and delivers through the fake transport, no job fails except by the network |
| accelerated | ten sessions (a weekend and the 20 Oct holiday inside) through the real loop: one run row, one mark, one card, one act per close; every decision has one order; orders fill at the next close; the book moves toward the allocation target; the rails hold on every marked day (company 10, ETF 35, sector 25, no borrowing, no short, 10% a day, 40% a month); claims registered and the 7-day ones scored; point in time (the state at D is identical with and without the later closes); no paid call; no failed job. Then the pluggable steps (below) |
| accelerated_long | the same standing assertions over thirty sessions (a month boundary, the 28-day claims) |
| kill9 | (1) a process holding the store is killed with a job running and a transaction open; (2) the close loop is killed after its first order; (3) killed during the card write. The restarted app: one run row a day, no double order, no decision without its order, nothing half-written, the next close as normal |
| off_fri_mon, off_10_days | the app off from Friday 16:00 to Monday 09:00, and to Monday 26 Oct (the 20 Oct holiday inside): the gap recorded and shown as "off from X to Y", every missed session marked once in order, forecast and scored in order, no holiday treated as a session, one loop pass on the latest close, no double order, the away digest once and naming the gap, no stampede, the day's own close then closed once |
| net_down | the fetching jobs run for real against an empty data folder: they fail soft (`offline`/`skipped`), say so, raise no alert, are not shown as down; the loop still closes the book from stored prices |
| ollama_down | the storyline reader leaves the items unread and says so, invents nothing, the World says the model is down, the loop closes; with the model back the items are read and attached with their source |
| docker_down | a lab run is refused with the reason (as a tool result), nothing half-recorded, `lab_close` waits with the reason and raises no alert, the champion keeps deciding |
| kite_logged_out | no token: the poller does nothing, `bars_1m` skips and says so, the loop and the book work; the login question once a day and on Telegram once a day; (the session loop's own line is asserted in the replay step) |
| budget_exhausted | the month's cap is spent: the governor refuses with a resume time; the strategist session, the checker and the reader's escalation make no paid request (a counting client); every local job still runs; the screen says so (`spend` guard node, `/api/core`) |
| failing_champion | a promoted lab policy whose `decide` raises: the baseline decides that close, the act names the error; also through the job path |
| probation_withdrawn | a slice whose live record is worse than the stand-in's is withdrawn by code with its reason, the better one is kept; OFF naming the module when `lab/probation` is not in the tree |
| kill_switch | `[core] kill = true`: no loop, no order, no AI session, no paid call; the book is still marked; lifted, the loop closes the missed day |

## The accelerated run's steps (how to add one)

`ACCELERATED_STEPS` is a list of `(name, fn, applicable_fn)`. `applicable_fn(env)` returns `(True, "")` or `(False, "waiting for module X ...")`, and the step is then reported OFF with that sentence
(`needs("pflab.core.exits", why="B4")` builds one). `fn(env, c, phase)` is called with `"setup"` (before the sessions: inject what the step needs, for instance lower a held-back price), with
`"tick"` after every step of the run when `fn.ticks = True` (inject something that arrives DURING the run, with its dissemination time), and with `"check"` after the ten sessions (assert on the store,
the outbox and the act log). A step that raises is reported ERROR for itself and never stops the others. `python tools/drills_s81.py steps` lists which are applicable in a tree.

| step | needs | what it does |
|---|---|---|
| standing | (always) | the standing assertions above |
| allocation_proposed_and_adopted | the lab tool `propose_allocation` (B2) | a new active target appeared during the run, with its reasons |
| core_etfs_bought | `core.sleeves`, `core.baseline_v2` (B1) | JUNIORBEES (in the store, not in the book) was bought, and is in the core sleeve |
| exit_plan_fires | `core.exits` (B4) | SYNFMCG2 falls 45% on the third session: its stop fires once and only once (`exit_events_s81`), a sale decision is placed, it fills |
| harvest_sale_and_buyback | `core.exits` (B4) | a harvesting sale then a buy-back on a later session, the plan re-opened at the reset cost; OFF when none was decided |
| thesis_break_sale | `kg.events`, `core.exits` (B7, B4) | a `guidance_cut` event on SYNIT1 enters `kg2_event` on the second afternoon with its dissemination time: one thesis exit, the reason names the event |
| us_subbook_close | `us.adapter` (B8 B) | the US run rows on the US calendar, FX rate and its source on every marked day |
| session_replay | `core.session` (B6b) | one replayed day of synthetic minute bars: a stop hit mid-session filled at the quote plus slippage never better; a swing entry only after 15 minutes; its same-day exit held to the next session and carried out at its start; a filing released at 13:20 breaks a thesis and the name is sold then, not before; the Kite login lost mid-session said once; the 15:45 report and the Today card |
| swing_opened_closed_scored | `core.session`, `core.exits`, `core.sleeves` | reads that swing trade: a plan in the swing sleeve, closed with the exit |

## First full run (2026-11-09 23:55 IST, this branch, 12 drills in parallel, 203 s; report `D:\s81_scratch\drills\first_full\report.json` and `report.md`)

| drill | result | seconds | evidence |
|---|---|---|---|
| smoke | PASS | 14 | 20 checks |
| accelerated | PASS | 43 | standing and tactical-view steps PASS; the S81 steps OFF (below) |
| accelerated_long (30 sessions) | PASS | 104 | the 28-day claims scored; the month turnover cap held in October and November; the first-week verdict not FAIL and queued once |
| kill_switch | PASS | 11 | 13 checks |
| off_fri_mon | PASS | 18 | 29 checks |
| off_10_days | PASS | 20 | 30 checks (gap Fri 16 Oct 16:00 to Mon 26 Oct 09:00, the 20 Oct holiday inside) |
| net_down | PASS | 201 | 15 checks |
| ollama_down | PASS | 16 | 14 checks |
| docker_down | PASS | 12 | 12 checks (after the fix below) |
| kite_logged_out | PASS | 15 | 13 checks (the session loop's own line is asserted when `core.session` is in the tree: checked on the session agent's branch) |
| budget_exhausted | PASS | 14 | 17 checks, 0 paid requests (a counting client) |
| failing_champion | PASS | 15 | 8 checks |
| probation_withdrawn | OFF | 1 | waiting for module `pflab.lab.probation` (B3); written against the core-lab agent's module and PASSED on that agent's worktree (`S81_SRC=...\agent-a893...\src`, 2 s) |
| kill9 | PASS | 20 | 19 checks (it FAILED before the fix below) |

Accelerated steps in this tree: `standing` PASS, `tactical_view_issued_executed_scored` PASS, every S81 step OFF with the module it waits for (`python tools/drills_s81.py steps`):
`allocation_proposed_and_adopted` (lab tool `propose_allocation`, B2), `core_etfs_bought` (`core.sleeves`, `core.baseline_v2`, B1), `exit_plan_fires` and `harvest_sale_and_buyback` (`core.exits`, B4),
`thesis_break_sale` (`kg.events`, `core.exits`), `us_subbook_close` (`us.adapter`), `session_replay` and `swing_opened_closed_scored` (`core.session`, `core.exits`, `core.sleeves`).
Checked against the other agents' worktrees before the merge (`S81_SRC`): `session_replay` PASSED on the session agent's tree on its first run (stop hit mid-session filled at the quote plus slippage, swing
entry after the first 15 minutes, same-day exit held and carried out next session, a filing at 13:20 breaking a thesis, the Kite login lost mid-session said once, the 15:45 report, the Today card), and the
Kite drill's session part passed there too. The exit, harvest, thesis, core-ETF, allocation and US steps could not be run (their modules are on other branches that do not meet in one tree yet): they are written
against the modules' tables and functions as read in the worktrees (`exit_plans_s81`, `exit_events_s81`, `kg2_event`, `us_runs_s81`, `us_days_s81`, `session_*_s81`) and need a first run on the merged tree.

## Findings

Fixed (root cause, one test each in `tests/test_s81_drills_fixes.py`):

1. **kill9: the close was not atomic.** `core/loop.py` placed each decision, order and claim one by one and wrote the day's `core_runs_s80` row last. A process killed after the first order left that
   decision and order with no run row; the restarted loop then said "orders from an earlier session have not filled yet", never wrote the day, and the book held half a close (seen: 1 of 5 orders, no run
   row). Placing the orders and the run row are now one `store.transaction`: a kill leaves none of it and the restarted app decides the day again, whole. Test:
   `test_a_close_killed_between_two_orders_leaves_none_of_it_and_is_decided_again`.
2. **The `strategist` job failed (and alerted) whenever it had no cloud client.** `strategist.tick` made the client before its own budget check: in the workshop (`OutwardBlocked`), with no key or a bad key
   the job was recorded failed and a Telegram "job failed" went out at every cooldown (seen: 7 failures in one simulated day). Now it is skipped with the reason. Test:
   `test_a_strategist_session_with_no_cloud_client_waits_and_says_why_instead_of_failing_the_job`.
3. **`lab_close` failed (and alerted) every 15 minutes while Docker was not running** and a challenger was in shadow (`SandboxUnavailable`). Docker down is a state to wait in: the job is skipped with the
   reason, not started again every tick, and tries again after 15 minutes; the champion decides all the same. Test:
   `test_a_lab_close_with_the_sandbox_down_waits_and_says_why_instead_of_failing_and_alerting_him`.

Not fixed (his or the coordinator's decision, or another agent's module):

4. **Design, decision needed: after a gap the loop decides once, on the latest closed session.** Off Friday to Monday (or ten days) the app marks, fills, forecasts and scores EVERY missed session in order,
   once each (asserted), but `loop.run` decides only the latest closed one. The brief asked "the loop runs for each missed close in order"; that would not be point in time: by the time the app opens
   the lots already hold the later fills, so an earlier close's decision would be made from a position that did not exist then. The drills assert the actual behaviour. If he wants a pass per missed close, the
   loop would need as-of-date positions first.
5. **`data_s79b` offline holds the scheduler thread for 163 s** (and `global` 23 s) because each source retries before giving up; jobs run one at a time on that thread, so every other job waits. It ends
   recorded `failed` because, on the drill's empty data folder, its other parts lack their files (`FileNotFoundError`); with a real data folder those parts would run and the job would probably be `offline`
   (not verified: it needs the real folder). Suggest a short per-source
   timeout once the first part of a job has found the network down. Not changed.
6. **A kill between the run row and the card leaves that day without a card** (the loop then says "already done"); the next close writes its card against the last one it has. Accepted: a window of a few
   milliseconds; no fix.
7. **Other agents' modules (not in this tree, so not fixed here):** (a) `core/preopen.py gap_estimate`: `np.polyfit` raised `LinAlgError: SVD did not converge` on a synthetic US series that was an exact copy
   of the Indian one, and the `preopen_job` was recorded failed (a real series with an infinite or constant value could do the same): guard with `np.isfinite` and return None. (b) `lab/probation.py record()`:
   `core_shadow_s80` rows after `day` count towards `review(con, now, day)` (no `a.day <= day`), so a review for a past day would see the future. Harmless live (no later rows exist); matters for a replay.
8. **Nothing found wrong** in: catch-up and the away digest, the offline handling of every fetching job (one real exception: item 5), the Ollama-down reader, the budget refusal (the strategist session, the checker
   and the escalation made no paid request), the failing-champion fallback, the kill switch, the rails and the monthly cap over 30 sessions, point in time of the state at a close, the first-week check, the tactical lane.

## Decisions (2026-11-10, no one to ask)

- The profile is built from nothing (synthetic prices and ISINs), not from the workshop's data: a drill never depends on `PFLAB_DATA_DIR`, and the data folder it hands the jobs is its own (the Nifty series,
  a US series, the lab's panel, rebuilt from the store's prices so that a file never holds a close the store does not).
- The core ETFs carry the tickers `configs/core.toml [baseline_v2]` names (NIFTYBEES, GOLDBEES, MON100, JUNIORBEES) with synthetic ISINs, names and prices, so the merged baseline can find them; JUNIORBEES is in
  the store and not in the book (the "core ETF bought" step).
- ten sessions start on Thu 2026-10-15 and end Thu 29 Oct (a weekend and the Tue 20 Oct holiday inside); the first close the loop makes is the seed day's, as in the real app.
- The fetching jobs are faked in every drill except `net_down`; a job added later runs for real unless its name is added to `FAKE_JOBS`.
- Paid calls: none are possible (the guard, an absent secrets file, a counting client where a drill needs to look at a refusal).

## What the coordinator needs to do with it after the merge

1. `python tools/drills_s81.py steps` lists which steps are applicable. Run the full set: `.venv\Scripts\python tools\drills_s81.py run --run-name merged --jobs 12` (about 3.5 minutes).
2. Expected first FAILs on the merged tree, by design, until the loop is wired: `exit_plan_fires` ("pflab.core.exits exists but pflab.core.loop never calls it"), `thesis_break_sale` (`check_thesis` not
   called), `us_subbook_close` (`close_us` not called by the loop or a job), and the probation drill's last line (the loop calling `lab.probation`). Each says exactly what is missing.
3. Shared files touched: `src/pflab/core/loop.py` (the transaction around the placing block, 12 lines: the coordinator's wiring of the exit manager, thesis check and US close must stay INSIDE that
   `with store.transaction(con):` if they place orders), `src/pflab/lab/strategist.py` (tick), `src/pflab/service/tasks_s79_lab.py` (`_lab_close`, `_lab_close_redo`). No migration, no table.
4. Tests added: `tests/test_s81_drills_fixes.py` (3), `tests/test_s81_drills_harness.py` (7, fast). `tests/test_s79_drills.py` (the old harness's building blocks) still passes unchanged.


## Merged tree (run name `merged2`, 2026-11-10 night): harness changes and real bugs

The coordinator's first run on the merged tree (`merged`) failed 8 drills. Classified: HARNESS (assumptions of the pre-merge tree): the baseline's name (`baseline_v2` now; `BASELINES`), the seeded
swing variants in `lab_runs_s80`, the withdrawn slice's date (the drill now runs the app up to the close after the withdrawal), the allocation step (the strategist's tool is called by the step and the
history scores the A50 rule reads are written by the drill: the lab's replay needs Docker and the real panel), the thesis victim (SYNCAPG1: SYNIT1 is the harvest's), the swing name (SYNAUTO1: SYNBANK1 is
the tactical view's), the replay's positions (topped up when the earlier steps sold what they were for), the "toward the target" and rail measures (a target adopted mid-run and the exit manager's sales move the mix
on purpose; a rail is judged on a day the name was bought), a data folder with the US ETF bars, FX and the lab panel (rebuilt from the store's prices), `news_s81_topup` and `us_prices_daily` faked outside net_down.
REAL BUGS (each fixed minimally, each with a test in `tests/test_s81_drills_fixes.py`):

1. **`paper` job failed on a sale at a loss after gains** (`EventError: charge amount is positive`): `book.fill` booked the incremental tax as a ledger `charge`, which is negative when a loss sets off an earlier
   taxed gain; the fill raised, the day was never marked and the loop stalled (4 closes in a simulated fortnight instead of 11). Tax floored at 0 (no refund booked; cautious).
2. **`kg2_nightly` and `news_s81_topup` failed on a data folder without the graph's raw inputs** (`FileNotFoundError name_map.parquet`) and alerted at every cooldown: they skip with the reason.
   (`us_close` already waits for its bars; `us_prices_daily` with no network is `offline`: both asserted, in net_down and in a test.)
3. **A swing trigger's stop and target were ignored by the exit manager**: `core/session.py` passed `stop_price`/`target_price`, the override keys of `exits.open_plan` are `stop`/`target`: the plan
   carried the defaults. Both names are passed now.
4. **The exit manager's harvesting ignored the turnover caps** (a close traded 15% of the book against 10% a day, 73% in a month against 40%): `rails.check(used=...)` takes the caps net of what harvesting trades
   (sales and buy-backs); stops, targets, thesis breaks and rail trims are risk exits and stay exempt. `core/loop.py` passes it (outside the transaction block's contents: only the call changed).

Not a bug, noted: the same-day exit of a swing entry is not even ordered by the exit manager on the day of entry (it waits for the next session, A54), so `session_queue_s81` stays empty; the drill asserts
"no sale on the day of entry, the exit carried out at the next session's start". `probation.slices()` excludes a withdrawn slice from the withdrawal's date on (asserted; the first failure was the drill running
the loop on days before that date). `lab_close` and the strategist job skip softly (fixed earlier).

The kill9 drill's reopening retries for 20 s (a killed process's file handle can outlive the kill on Windows) and kills the process tree.

Result on the merged tree (`merged2`; accelerated re-run alone as `merged2a` after the last harness edit): smoke, accelerated (all ten steps PASS: standing, tactical view, allocation proposed and adopted,
core ETF bought, exit plan fires, harvest sale and buy-back, thesis-break sale from a graph event, US sub-book close, session replay, swing opened/closed), accelerated_long, kill_switch, off_fri_mon,
off_10_days, net_down, ollama_down, docker_down, kite_logged_out, budget_exhausted, failing_champion, probation_withdrawn, kill9: PASS. Nothing OFF, nothing failing. Tests: 328 passed across the
core, paper, exits, session, swing, US, kg, probation, strategist and drill files.
