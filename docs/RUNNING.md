# RUNNING: install, run, update, verify

The operator's guide (Windows 11, PowerShell). What the system is: `README.md`; what exists in detail: `docs/BUILT.md`; every test and verdict:
`docs/STUDIES.md`; intent and what remains: `docs/PLAN.md`; rules for Claude Code: `CLAUDE.md`.

There are two installations. The **app** is an install of a release tag in its own folder, and it is what runs. The **workshop** is a checkout of this repo
with no `release.toml`: the beta, where development happens. It sends nothing outward and makes no paid call unless told to.

## First run of the app (in this order)
1. **Install** Python 3.13, git, [Ollama](https://ollama.com) and Docker Desktop. Model-written calculations run only in the Docker sandbox: without Docker
   they wait, and nothing runs on the host. Then `ollama pull qwen3:8b-q8_0` and `ollama pull nomic-embed-text` (about 9 GB, once; never delete them).
2. **Install the app** into its own folder from the GitHub repo at a release tag:
   `powershell -ExecutionPolicy Bypass -File tools\install_app.ps1 -DryRun` to look, then run it again without `-DryRun` (3-6 minutes; it prints "INSTALLED" at the end).
   The default folder is `D:\PortfolioLabApp` (it needs 10 GB free). It makes `app\` (the clone and `.venv`), `data\`, `pm\`, `backups\`, `release.toml` and ONE
   desktop shortcut, "Portfolio Lab". From here every command runs in `<folder>\app` as `.venv\Scripts\python -m pflab.cli ...`.
3. **Keys:** `pflab setup secrets` (typed, never echoed): Kite API key and secret, Telegram token and chat id, Anthropic key; add `--only sec` for the SEC
   contact later. The file is `%USERPROFILE%\.pflab\secrets.toml`, outside the repo.
4. **Market history.** Each backfill is resumable and takes more than 5 minutes; start with the first two:
   `tools\backfill_bhavcopy.py --from 2012-01-01`, `tools\build_index_membership.py --all`, `tools\backfill_bse.py 2018-01-01 <today> bse.log`,
   `tools\backfill_shareholding.py`, `tools\backfill_fo.py --start 2024-01-01`, `tools\backfill_us.py`, `tools\backfill_deals.py --source deals`.
   Then build the adjusted price panel once (about 5 minutes): `tools\collect_daily.py --sources corporate_actions,dividends,panel`. After that, daily data and
   the panel arrive by themselves (the `collect` job and the others), and the `backfill` job fills any missing sessions hourly.
   If the workshop already has the history, `tools\seed_app.ps1` copies its non-personal market data and news once (about 4 GB). The store is not copied
   (`-WithStore` copies it too, only into an app with no store); the learner's test counter is carried by code.
5. **Open "Portfolio Lab".** It starts the dashboard and every job in one process. Log in to Kite each trading morning with the "Log in to Kite" button
   (read-only: Kite is a data feed). Answer what **Needs from you** asks.
   The account is the system's own (PLAN amendment A36, `ledger/system.py`): it starts from the Zerodha holdings as positions, with a fake bank and broker
   holding fake money, and records only the system's own events after that. While `pm/system_account.toml` exists, statements are not read and the ledger is
   never rebuilt from them.
6. **Switch it on.** In Settings: Telegram on (held alerts are then delivered), the brain on "economy", preset "full". Close the window, then register the tick
   (every 15 minutes, at logon and at wake): `powershell -ExecutionPolicy Bypass -File tools\register_tasks.ps1` (preview with `-WhatIf`).
   After that it runs, learns and asks by itself.

## Day to day
There is nothing to do. It wakes with the laptop, watches, researches, simulates, runs its paper portfolio, and writes only when it matters (plus a 09:00 and a
21:45 summary). Taxes: `pflab pm quicko --fy 2027` writes the Quicko inputs to `pm\reports\quicko`.

## What it watches, how fast, and when it is blind (S86)
- **Headlines on what the book is exposed to** (held, picked, reserve, names you suggested; both markets): Google News and Yahoo Finance every 15 minutes, day and night, while the app is open (GDELT as a third, often refused). A serious one (a leadership shock, fraud, an auditor leaving, a regulator, a default, a guidance cut, or many outlets at once) reaches your phone as "Heard at HH:MM ..." within minutes (target 20), new buying in that name is frozen, and a case is thought through at once.
- **The company's own filings** (BSE every 15 minutes in market hours, the SEC every 2 hours) open a case in the same cycle.
- **US names** are looked at every 5 minutes in US regular hours and every 15 in pre-market and after-hours, each quote's delay stored; orders fill at the first quote after the decision. India: the 5-minute session loop as before.
- **Eyes:** `pflab service status` and `pflab alarm status` list each source's last answer. A news source silent for an hour (app open) is one line on Telegram, and one when it returns. If the day's alarms took too long, the 15:45 report says so with the cause.
- **After a gap** (laptop off 30 minutes or more): the lane fetches everything since (7 days at most) first and sends one message, "Off from X to Y. While off: ...", then replays the gap as a ghost book and says what being off cost (or saved).
- **Honest limit:** nothing on a closed laptop can watch. A serious headline at 2 a.m. with the laptop off is read at the next open, not at 2 a.m. An always-on watcher outside the laptop is on the parked list, not built.
- **Not seen:** anything the sources do not carry, a headline that names the company only in its body, a rumour on social media, and (tonight) a model's reading of a headline the rules cannot place.

## Updates
Each start of "Portfolio Lab" takes the newest release first (or run `pflab update` with the app closed). It backs the store up, installs the newest release tag,
runs a self-test, and undoes itself on a failure. `pflab update --check` only looks; `pflab update --rollback` returns to the previous release. The record is
never wiped.

## Local acceptance of a candidate release
Before a candidate is merged and tagged, this PC checks it. From the workshop folder:
`powershell -ExecutionPolicy Bypass -File tools\verify_candidate.ps1 -Ref <branch, tag or commit>` (default `main`).
It clones the candidate into `D:\PortfolioLabApp\verify\candidate` and builds its own environment (`verify\venv`), so the workshop's edited files, the app's
`.venv` and the running app are never touched. Then `pflab verify` reports (also in `verify\report.txt`):
- the candidate commit and the installed tag, and the prerequisites;
- the sandbox containment probe in a real container (build the image once with `docker build -t pflab-sandbox:2 -f sandbox/Dockerfile .` from `verify\candidate`);
- a read-only Kite read (Telegram is checked as configured only: no message is sent);
- the candidate's migrations on a copy of the record, and an upgrade, write and rollback rehearsal on copies;
- a force-kill and restart drill of a headless worker, freshness and readiness on the copy;
- a before and after proof that the live ledger file is unchanged.

It is resumable: do the steps it lists under "Next, in order" (log in to Kite, start Docker, stop the dashboard so the store can be copied), then run the same
command again. Exit code 0 means accepted, 1 a check failed, 2 evidence still pending. Two checks no program can do alone: with the app open, sleep the laptop
for 5+ minutes, wake it, wait 2 minutes, then add `-WakeCheck`; and leave the app running for an hour, then add `-HourCheck`. `-LiveModel` adds one small model
call through the app's privacy gate and budget; `-Offline` skips Kite.

## A fresh start
Close the dashboard and the bot first. `pflab pm fresh --archive-to <a folder outside the profile and data folders> [--statements <folder>]` lists what it would
do; add `--confirm start-fresh` to do it. It copies the profile (and the statements folder) as opaque bytes into the archive, checks every file's hash, moves
the old profile aside (never deletes it), and makes a new EMPTY profile that does nothing until the "Portfolio Lab" icon is double-clicked
(`pm/activation.json`). Only the test counter and a reduced spend record are carried over. The old profile comes back only as a separate copy:
`pflab pm restore <archive> <empty folder>`.

## The workshop (development)
```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
git config core.hooksPath .githooks          # the privacy grep runs before every push
.venv\Scripts\python -m pytest -q --basetemp <a scratch folder>
```
The suite takes about 4-8 minutes. Tests marked `docker` need Docker and the sandbox image, and tests marked `ui` drive a headless Edge; both are skipped
where those are missing. The workshop makes no paid call unless run as `pflab --paid ...` (counted against `dev_monthly_cap_rupees` in `api_budget.toml`,
default 0), sends nothing outward unless run as `pflab --live ...`, and never registers a scheduled task.

**Releases:** work on a branch `pm/sN-<slug>`; once it is confirmed bug free, merge to `main`, run the suite and the privacy grep
(`.venv\Scripts\python -m pflab.hq.security` must print "privacy grep: clean"), tag `vYYYY.MM.DD[.N]`, and push. The app takes the newest tag at its next start.
`data/` and `pm/` are gitignored and are never in a release.
