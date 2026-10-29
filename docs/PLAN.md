# PLAN: intent, frame, decisions, and what remains

(Condensed 2026-10-28, S65. The old build plan, the session log and the handoffs are in git history; what exists is in `docs/BUILT.md`, the tests and
verdicts in `docs/STUDIES.md`, how to install and run in `README.md`.)

## Intent: the investor's companion
He is an employee, not a trader, quant or hedge fund; he has a portfolio and invests by feel. In his words (2026-10-25): *"They say AI can't trade... but AI
and LLMs, if used correctly with their power, can work... what if I had a companion: web search, calculating, recommending, forecasting... The system turns on.
I am logged in to Kite. Now the autonomous part starts... Let's not panic, let's research... I have to make sure the news is current, not old... let me provide
this to a mathematician... the maths is a language; we use it to be sure of what happens... it can hallucinate or drift; the maths works better... there will be
days the user is not providing me tasks; it is my job to keep on looking... I saw today that if I had bought this, it would have failed. An idea didn't work
here; I will try it in some other situation... Consider me a normal guy, and the system the big guy who works at Jane Street or D. E. Shaw... So regardless of
what I say or not, it should work on its own, build on its own, find strategies to get returns in the long run."*
And (2026-10-28): *it must run by itself like an app, from a clean reset, updated like software; Claude Code and its memory are for development only.*
**Maths decides; models read, connect and explain.** It never places an order: it brings a reasoned suggestion with a price and he decides.

## The frame (his, fixed; changes only on his written word)
- Allocation in `targets.toml` (stocks-heavy, debt, gold 10-15%, a future international split); the **35% fall limit**; the monthly amount and FD tranches;
  FD money over 8-12 months; PhD maybe 2028. The system proposes, with evidence; his yes applies; it then holds itself to it (theme limits, dip reserve,
  opportunity pot, the US sleeve share).
- **Reaching him:** Telegram only when it matters today (a crash, a buy price reached, a big risk) plus a 09:00 and a 21:45 summary; the rest on the screen.
- **Kite read-only.** Buy prices are our own price watches (a message with a ready ticket), never a GTT. F&O: data yes, trading no. IPOs and missed winners:
  a small separate pot with its own limit, each idea with a reason, a buy price, an exit and a score.
- **Cost:** everything inside Rs 2,500 a month; local wherever good enough; paid calls priced first.
- **What it may not do:** trade or move money; change targets or limits; edit its own code or run commands. It may write calculation code in the Docker sandbox
  (a second independent version checks it) and propose tools, which a Claude Code session reviews with him.
- **Taxes:** Quicko files his return; the system prepares its inputs (`pflab pm quicko`) and reconciles; it files nothing.
- **US sleeve:** BETA until January or February 2027 (Zerodha GIFT City; approved; no money sent, no US holdings). Collection runs so history builds.
- **Two installations (2026-10-28):** the APP runs his money, installed from a release tag in its own folder, updates like an app with backup and rollback; the
  WORKSHOP (the repo checkout) is the beta where Claude Code develops, sends nothing outward and makes no paid call unless told. His record (the store) is his:
  an update never wipes it.

## How it improves (the research rule)
It forms ideas from what it watches, its journal and papers, writes each as a test before running it, checks it on data it never saw, wires in what passes and
keeps what fails as "tried, did not work". An "edge" is only what passed such a test, counted in the learner's counter (the bar rises with every test). A crash is
never predicted, only described by probability with its n. Research principles that stay: point-in-time or it does not exist; survivorship is a data error (the
universe includes every name that traded); taxes and costs are in the objective; LLMs never decide; a single backtest, or one live year, is not evidence.

## Design decisions, one line each
- 2026-10-06: Portfolio Manager scope (Indian shares, IPOs, funds, gold, bonds, cash); tax rule tables sourced and dated; both regimes shown, he chooses; Kite Connect read-only;
  maintained libraries over hand-written code; capital-gains rule coverage starts at transfer date 2024-07-23 (earlier raises).
- A2: Telegram send-only through `requests` (no bot framework); the two-way bot only while the dashboard is closed.
- A7 (S37-S49): a team of agents (researcher, analyst, advisor, trader planner, trade check, event, thesis, memory, questions); the API analyst is the only doorbell.
- A9: the small-numbers rule (under 20 observations: the count, no conclusion).
- A11 (S57): Graphify not adopted; the system's own graph is cleaned instead.
- A16-A18 (S59-S60): agent HQ and one tool-calling brain under a spend governor and an egress gate; its journal, suggestions ledger and predictions are scored later.
- A22 (S62): the learner (sources, claims, templates, protocol hashes, counter); the security agent; web search through the brain.
- A23 (S63): a fresh repo `portfolio-lab` (private); the old research project lives only in a private archive repo.
- A24 (S64): model-written calculations run in Docker (`--network none --read-only`, 2 GB), `contained: True` recorded.
- S64: TimesFM removed (failed every registered test); price ranges come from calibrated statistics and are scored; maths tools (CAPM, process, comove) are descriptive.
- S64: the one picture (`hq/picture.py`) is the brain's first tool; option-implied probabilities, gauges, valuation in plain words, nudges, IPO planner, scanners, replay bench.
- S65: the app/workshop split (`release.toml`, outward guard, `pflab update`, install and seed scripts); the system onboards him (Setup, secrets, content recognition,
  bank labels as questions, IPO and cost forms); the Quicko pack; the US sleeve as a beta feature flag; the learner's counter carried into a fresh install.
- S65: the investor's three other repos (the research archive, Q_Alpha, Q_Alpha_Research) read on his instruction; ported: the twin-books scoreboard and the
  stress-gauge hedge as forward test F5; their results recorded in STUDIES; the repos deleted after.
- S65 amendment: frozen protocols and results of the live tests stay as files in `docs/protocols/` (a claim's protocol is hashed at registration); the other
  protocol and result files were folded into `docs/STUDIES.md`.

## Handoff to the cloud Claude Code session (2026-10-28, end of the local S66 work)
State: `main` = tag `v2026.10.28.11`, suite green (2076), nothing uncommitted. The app on his PC takes the newest tag at each start of its one icon.
**The cloud session cannot see:** his installed app, its store, `%USERPROFILE%\.pflab` (secrets, the Gmail token, `privacy_terms.json`), Ollama or Docker on his PC.
So: no real-data checks; the tests are synthetic and run anywhere (`pip install -r requirements.lock`, `pip install -e ".[dev]"`, `pytest -q`); the pre-push privacy
check (`.githooks`, `python -m pflab.hq.security`) blocks without `privacy_terms.json` and is not installed in a fresh clone, so grep the staged diff by hand for amounts,
names and ids before every push (CLAUDE.md). Work on a branch `pm/sN-<slug>`, merge to `main` only when the suite passes and the change is confirmed, tag `vYYYY.MM.DD[.N]`.
**Pending his word:** a true empty start (move the record aside, restore only targets and stock list, let Gmail and Kite rebuild it) or keep the record rebuilt on 2026-10-28.
**Pending him:** the one-time Google step (README step 5) then Settings > Connect Gmail; the 10 bank-label questions; the companion's proposals.
**Next, in order:** (1) the first real Gmail run: expect small fixes in `ingest/gmail.py` and `ingest/mail_read.py` (built and tested on a fake mailbox and four invented emails only);
(2) the tick installs a waiting update by itself when it ends (today an update is refused while the tick or the window holds the record);
(3) the `plans` job (13.6 min cold) and the news step of `collect`; (4) the other screens (Agent HQ, Portfolio, Schedule) in the style of the new Command centre;
(5) route simple local questions in the chat to `system_status` and `mail_facts` (the brain already has them).

## S67 completion cycle (cloud session 2026-10-29, branch `claude/wonderful-bardeen-z07h1e`; Sonnet 5.5 is the development model only)
**Status: implementation complete and cloud-tested candidate; local checks pending (below). Nothing was merged or tagged; the app takes release tags, so it has not seen any of this.**
Baseline on `d81efb8` (Linux, Python 3.13, `requirements.lock` without `pywin32`): 2061 passed, 7 skipped, 7 failed, all environmental and failing the same on a pristine
checkout: the 6 `test_engine_golden` digests (platform float digests; the engine tests were not touched) and `test_app_launcher::test_children_end_with_the_system` (Windows
process tree). Docker is not available in the cloud container (no daemon): the sandbox is tested through its adapter with a fake Docker, the fail-closed path and the probe's
verdicts; the real container test (`-m docker`) is skipped here and is part of `pflab verify` on his PC.
**Result on the candidate (same Linux environment): 2125 passed, 8 skipped (the `docker` marker and platform skips), 7 failed: exactly the 7 environmental failures above, nothing new.** New tests: `tests/test_s67_*.py` (cycle, status, sandbox, workflow, update, verify, health; about 90 tests, including a real headless worker force-killed and restarted).
What changed (details in `docs/BUILT.md`): migration 43; durable board states and recovery; investigations (`hq/cases.py`) with the brain's case tools, discovery, dependencies,
reproducible calculations and a process review; the sandbox fails closed and proves its containment; connectors coloured by real operations, retained data marked stale, job
sub-step failures propagate; email provenance policy and the local/cloud list; chat and background parity (the system and mail tools in the ask centre, chat history and open
work to the brain); readiness, known gaps, a resumable bhavcopy backfill job; a recoverable mail workflow; rehearsed migrations and a rollback that keeps post-upgrade rows;
`pflab verify` and `tools\verify_candidate.ps1`; a headless worker; the heartbeat; the UI for investigations, held work, changes since the last visit, readiness and processing.
Measured here (pytest -s, `test_the_screen_stays_responsive_while_a_slow_dependency_and_a_slow_job_run`): with Ollama and Docker probes of 3 s each and a backfill running, the
status call answered in 0.9 s the first time and within 0.1 s after; his laptop's real throughput is a local check.
**Local acceptance (his):** the one command is in `README.md` ("Local acceptance of a candidate release"). It must print no FAIL; the "needs you" items it lists are Kite login,
`pflab mail connect` (OAuth), Docker running with the image `pflab-sandbox:2` built, and the two real-world steps (a real sleep and wake with `-WakeCheck`, and the app running
after Claude Code is closed). A bounded live model run through the gate is `-LiveModel`.
**After acceptance, to ship:** (1) the workshop: `git switch main; git merge --no-ff claude/wonderful-bardeen-z07h1e`, run the suite (7 environmental failures above are the cloud's, his PC should show none),
the privacy grep (`python -m pflab.hq.security` must print "privacy grep: clean"); (2) `git tag vYYYY.MM.DD[.N]; git push origin main --tags`; (3) the app takes the newest tag at its next start (backup, rehearsal on a copy, install, undone on a failure).
Build the sandbox image once on the PC: `docker build -t pflab-sandbox:2 -f sandbox/Dockerfile .` (the install script does it for a new install; an existing one needs it before the first calculation).
**Recovery:** `pflab update --rollback` (app closed) returns to the previous tag and the store from before the update, then brings back every row written since (events renumbered by a rebuild are matched by content), and keeps the store as it was in `backups\ledger_before_rollback_<date>.duckdb`; tables only the newer version has stay in that file.
A failed update undoes itself the same way; the backup is taken before anything else.
**Not done, on purpose:** no OpenCode, agent SDK or OpenSandbox (no acceptance failure needed them); no new service; the `plans` job's 13.6 min cold run is still the tuning item below.

## S67 local session (2026-10-29 16:08-17:00, branch `pm/s67-local-candidate` on the cloud candidate `4139646`; Sonnet 5.5, 53 minutes)
**Status: the repairs below are built and tested on synthetic data; the full-suite result is in the commit message of the last commit. Not merged, not tagged, not installed, no real profile touched.** The brief (one local session to a usable application) is far larger than the time; what is done and what is left is exact:
- DONE (each with tests in `tests/test_s67_local.py`, `_activation`, `_mail_walk`, `_fresh`): (E) the sandbox result is read bounded, links and non-regular files refused, must be a JSON object (`sandbox.read_result`); (B) an effect is `started` then `done` (schema v44, `board.once`; `board.once_db` commits marker and store effect together; `board.uncertain` lists effects that stopped halfway and are never repeated blindly), and a task or case that THIS process is running is never reaped by a wake (`board._LIVE`, `cases._LIVE`; a dead process owns nothing); (D) each recommendation is current only on the prices of its own instruments (`system.instrument_stale`, per-item `current` and `why`; the whole is current only if every item is); (A) rollback prepares and checks the older store beside the live one and switches it in only when whole, carries over changed rows, removals and corrected events (not only inserts), and on any failure changes nothing (`update.rollback`, `merge_new_rows`: added/updated/deleted/errors); (C) acceptance needs every required check to pass (`Report.incomplete`, `OPTIONAL_CHECKS`) and a heartbeat must be fresh with its process alive; the first-launch gate (`activation.py`: `pm/activation.json` pending until the icon's launcher opens it; jobs, Gmail and Kite do nothing while pending; a profile without the file is active, so today's app is unchanged); the mailbox walk (`gmail.scan_ids`, schema v45 `mail_scan`: saved 60-day windows newest first over ten years, 600 new messages per run, per-mailbox checkpoints, `gmail.coverage` says the attachments were read to a date and that link-only mail was NOT checked); `pflab pm fresh --archive-to <folder> [--statements <folder>]` (verified opaque archive with a sanitized manifest, the old profile moved aside not deleted, a new empty profile that waits for the icon and keeps only `learn_tests` and a reduced spend record) and `pflab pm restore <archive> <empty folder>`.
- ALSO DONE, last: the first conversation (`app/onboarding.py`): a new, activated profile (no accounts, no events) gets one grouped welcome question in Needs from you (goals and date, cash that must stay, the fall he can accept, other mailboxes or accounts), asked once; `system.picture()['onboarding']` lists what is still unknown, computed from the store. NOT yet shown on the dashboard screen (`app.js` does not render that key) and the chat's first reply does not use it yet.
- NOT DONE (nothing here is claimed): rollback does not rebuild derived tables or handle tables with no key beyond the whole-row compare; (F) research provenance (immutable input snapshots, report-dependency matching by company/type/period); the no-attachment and link-only mail candidates; the account/period coverage matrix, grouped inventory question and the first-use flow screens; the bounded experiment loop (register, baseline, fixed evaluation, record, keep/reject) over the learner; the live-model check still only asks for "ok"; a restart drill that seeds a real agent; the real Docker, sleep/wake, one-hour and icon checks (his, after install); the installed empty candidate itself (no `fresh` has been run on the real profile, no install, no shortcut change).
- Found: the sandbox probe script calls `os.getuid` (not on Windows) and `test_backfill_fills_holes_newest_first...` fail on this PC even on the untouched candidate; the symlink tests skip here (no privilege).

## What remains (dated; update at each stop)
0. **DONE 2026-10-28: the app runs his money.** `D:\PortfolioLabApp` (release `v2026.10.28.x` from GitHub; clean-room install and a real update and rollback tested), market data and news seeded (3.9 GB), his preferences carried, the RECORD rebuilt by the system itself from his files (13 of 13 checks, 1,383 events, 14 FDs), the desktop shortcuts and the scheduled tick point at it, the user-level PFLAB_DATA_DIR removed. Live checks: two Telegram summaries delivered; one brain pass (Opus, Sonnet rival) Rs 13.07; October's spend Rs 1,420 of 2,500 (the workshop's carried). Found and fixed on the way: a hidden source file, untested library versions (now `requirements.lock`), a long-path limit, the tick needing his user.
   **Read-only Gmail (v2026.10.28.5-.6):** built and tested on a fake Gmail (`ingest/gmail.py`, job `mail`); Connect fetches at once; a cold start reads a
   year of mail, asks one password per locked sender (a slot in Settings > Keys; saving it fetches again), then asks him to approve the accounts in Setup; after
   Setup, checked statements ask for his press. Not yet run against his real mailbox: his one-time Google step first (README step 5).
   **What his emails say (S66, v2026.10.28.9):** the daily `mail` job also reads money emails (trades, IPO allotments, dividends, deposit bookings and maturities, bank
   alerts, corporate actions, research) with the LOCAL model only (`ingest/mail_read.py`; job `mail_reading` on the slider offers nothing else). A number or date
   survives only when the email itself states it; code then checks each fact against Kite and the record (matched, pending, new, conflict); only a missing or
   disagreeing trade, IPO allotment or deposit is asked (nothing is written to the record from an email); research that names no id of his becomes a graph document
   the readers read. Tried on the real local model with four invented emails (a trade, a deposit, a dividend, an OTP: all read right; 8-14 s an email; a first look
   stops after 25 minutes and continues next run). Not yet seen on his real mail.
   **The dashboard reworked (S66, v2026.10.28.11):** the Command centre now opens on the system itself (`app/system.py`): a verdict line, the connectors (Kite, Gmail, Telegram, the local model,
   the Claude API against his cap, the sandbox, the release), then Needs you (grouped), The system at work (in plain words, not JSON) and Is it in sync? (each source's latest
   data against the last session), with the portfolio below. The AI centre is a full-height chat beside a live "what the assistant can reach" panel; the assistant has
   `system_status` and `mail_facts` as tools, so it answers "is everything working?" from the same facts. Found on the way and fixed: Bank Nifty read a file collected
   once (35 days old; now in the daily step), a stopped window left `collect` "running" and blocked its slot (released at the next start), the header said "agents idle"
   while a job ran, a false high "test suite failed" alert (the sparse app clone has no `tests\`), a duplicated symbol in research flags.
   **One icon (v2026.10.28.7):** only "Portfolio Lab" on the desktop; each start takes the newest release first (`launcher.update_first`: backup, self-test,
   undone on a failure), then starts on it; a double-click while a background run holds the record waits for it (up to 20 min, v2026.10.28.10). The "Portfolio Lab Update" icon is gone.
   **The workshop holds nothing personal (2026-10-28):** its statements (`new\`), its store and his settings files (`pm\`), the old store copies and the
   pre-rewrite history bundle (`data\backups`) and his tax-P&L parquets (`data\inbox`) were moved to `D:\PortfolioLabApp\backups\workshop_personal_2026-10-28`
   (nothing deleted; 27 of its 44 files exist nowhere else). The workshop keeps the collected market data and news (duplicated in the app; fine) and runs the
   beta on what the collectors bring. The full suite passes without any of it (2058).
   **How a change ships (his rule 2026-10-28):** work on a branch in the workshop (the beta); suite, privacy grep, and the beta confirmed bug free; then merge
   to `main`, tag `vYYYY.MM.DD[.N]`, push; the app takes it at its next start.
   **Waiting for him:** the Google client file (README step 5), then Settings > Connect Gmail in the app; 10 bank-label questions; the companion's proposals (3 theme baskets, 3 theme limits, the opportunity pot, the US sleeve share); deleting the three old GitHub repos (`gh auth refresh -h github.com -s delete_repo`, then `gh repo delete <your account>/<name> --yes` for portfolio_system_archive, Q_Alpha, Q_Alpha_Research); deleting the throwaway `D:\pl_cleanroom`.
   **Tuning next:** the `plans` job took 13.6 minutes cold in the app (19 s warm in the workshop): cache the buy zones it recomputes; the news step of `collect` is the slowest daily step.
1. **Switch-over (S65 Phase 9, his yes 2026-10-28).** The app starts a fresh RECORD (the ledger rebuilt by the system from his statement files; empty journal,
   memory, suggestions; the learner's counter carried by code) and keeps his PREFERENCES (targets, stock list, theme baskets, groups, API cap, FD list), which the AI
   may change when he asks, with his yes (`plan/prefs.py`). Rehearsed 2026-10-28 from his real files: Setup proposed from the files, 13 of 13 checks, 1,383 events,
   no hand-made bank rules (10 label questions asked instead).
2. **The forward ledger (S66).** So the app never needs his statements again: Kite captures each day's trades and holdings as they happen; the monthly CAS
   arrives by read-only Gmail and reconciles them; FD intake by form or certificate in Setup; statements only open the books once, then are deleted.
3. **Forward tests and the record (S65).** F1-F4 (`docs/protocols/s65_forward_protocol.md`: the passed avoid rule and the reversed leads) and F5 (the stress-gauge
   hedge on paper, from the investor's Q_Alpha_Research) run by themselves on live data; decided once (F1-F4 at 24 months, F5 at 24 months and 2 episodes). The
   scoreboard (`plan/twin.py`) records his book, the brain's suggestions on paper and the equal-weight bar from the app's first night. Nothing to do but wait and read.
4. **US sleeve (January or February 2027).** A sync check first; the SEC contact (`[sec] user_agent` in secrets); the primary-source check of the foreign-tax rows
   (2027-01-01 or the first remittance); the GIFT City statement parser (opens with his first statement); the sleeve question (share and start month).
5. **Filing time.** The 112A template's own header row and a possible column 1b; check the pack against Quicko's own summary (`pflab pm quicko --fy N --check export`).
6. **Optional, not built:** advance-tax reminders and harvesting suggestions; segment revenue and 3-year peer growth (no data on record); alpha-sign and build-up scans
   (no testable history).
