# Portfolio Lab (`pflab`)

The investor's companion for NSE equities (a small US sleeve in beta): it collects data, keeps a tax-aware ledger, researches, forecasts, simulates, tests its own ideas
and tells him what matters. It never places an order. Not investment advice. What exists: `docs/BUILT.md`; every test and verdict: `docs/STUDIES.md`; intent and
what remains: `docs/PLAN.md`; rules for Claude Code: `CLAUDE.md`.

## First run, from a fresh clone (Windows 11, PowerShell; his steps in this order)
1. **Install** Python 3.13, git, [Ollama](https://ollama.com) and Docker Desktop (generated calculations run only in its sandbox: without it they wait, nothing runs on the host). Then `ollama pull qwen3:8b-q8_0` and
   `ollama pull nomic-embed-text` (about 9 GB, once; never delete them).
2. **Install the app** into its own folder from the private GitHub repo at a release tag:
   `powershell -ExecutionPolicy Bypass -File tools\install_app.ps1 -DryRun` (look), then without `-DryRun` (3-6 minutes; "INSTALLED" at the end).
   Default folder `D:\PortfolioLabApp` (needs 10 GB free). It makes `app\` (the clone and `.venv`), `data\`, `pm\`, `backups\`, `release.toml`, and ONE desktop
   shortcut, "Portfolio Lab" (nothing else). From here every command runs in `<folder>\app` with `.venv\Scripts\python -m pflab.cli ...`.
3. **Keys:** `pflab setup secrets` (typed, never echoed: Kite API key and secret, Telegram token and chat id, Anthropic key; add `--only sec` for the SEC contact later).
   Statement passwords are asked for by the names Setup gives them. The file is `%USERPROFILE%\.pflab\secrets.toml`, outside the repo.
4. **Market history** (each is resumable and longer than 5 minutes; start with the first two): `tools\backfill_bhavcopy.py --from 2012-01-01`,
   `tools\build_index_membership.py --all`, `tools\backfill_bse.py 2018-01-01 <today> bse.log`, `tools\backfill_shareholding.py`, `tools\backfill_fo.py --start 2024-01-01`,
   `tools\backfill_us.py`, `tools\backfill_deals.py --source deals`; then build the adjusted price panel once (about 5 minutes): `tools\collect_daily.py --sources corporate_actions,dividends,panel`. Daily data, and the panel, then arrive by itself (`collect` and the other jobs). If the workshop has the history,
   `tools\seed_app.ps1` copies its non-personal market data and news once (about 4 GB). The app starts with a fresh record: the store is not copied
   (`-WithStore` copies it too, only into an app with no store); the learner's test counter is carried by code.
5. **Open "Portfolio Lab"** (starts the dashboard and every job in one process). Drop your statements in **Inbox and files** (any names: Console tradebook, funds
   ledger and contract notes, the depository CAS, bank statements, deposit interest certificates; they are recognised by what is inside). **Setup** (Settings > Open Setup)
   then proposes the accounts it found (bank and last four digits, and which saved password opens each file): press "Use these accounts", then "Add everything to the
   ledger" (one rebuild, written only when every check passes). Add each fixed deposit once in Setup's deposit form (checked against the bank's maturity amount).
   Answer what **Needs from you** asks (bank-label questions, IPO entries, FD certificates). Kite: the "Log in to Kite" button each trading morning (read-only).
   **Locked files:** a password-protected file that none of your saved passwords opens is refused with one request in Needs from you: save its
   password in Settings > Keys and passwords, then drop the same file again. There is no email reading: every file comes from your hand.
6. **Switch it on.** Settings: Telegram on (held alerts are then delivered), the brain on "economy", preset "full". Close the window, then register the tick (every
   15 minutes, at logon, at wake): `powershell -ExecutionPolicy Bypass -File tools\register_tasks.ps1` (preview with `-WhatIf`). After that it runs, learns and asks by itself.

## Day to day
Nothing: it wakes with the laptop, watches, researches, simulates, and writes to you only when it matters (plus 09:00 and 21:45 summaries). Tell it your monthly amount
when the money comes ("I'm investing 50k this month"). Taxes: `pflab pm quicko --fy 2027` writes the Quicko inputs to `pm\reports\quicko`.
**Update:** nothing to do: each start of "Portfolio Lab" takes the newest release first (or `pflab update` with the app closed): it backs the store up, installs the newest release tag, self-tests, and undoes itself on a
failure; `pflab update --rollback` returns to the previous release. Your record is never wiped.

## Local acceptance of a candidate release (S67)
Before a candidate is merged and tagged, this PC checks it. One command (PowerShell, from anywhere; `D:\portfolio_lab` is the workshop, `D:\PortfolioLabApp` the app):
`git -C D:\portfolio_lab fetch origin claude/wonderful-bardeen-z07h1e; git -C D:\portfolio_lab show origin/claude/wonderful-bardeen-z07h1e:tools/verify_candidate.ps1 | Set-Content -Encoding UTF8 $env:TEMP\verify_candidate.ps1; powershell -ExecutionPolicy Bypass -File $env:TEMP\verify_candidate.ps1`
It clones the candidate into `D:\PortfolioLabApp\verify\candidate` and builds its own environment (`verify\venv`): your workshop's edited files, the app's `.venv` and the running app are never touched. Then `pflab verify` reports (also in `verify\report.txt`): the candidate commit and the installed tag; prerequisites; the sandbox containment probe in a real container (build the image once with `docker build -t pflab-sandbox:2 -f sandbox/Dockerfile .` from `verify\candidate`); read-only Kite and Gmail reads; the candidate's migrations on a copy of your record and an upgrade, write, rollback rehearsal on copies; a force-kill and restart drill of a headless worker; freshness and readiness on the copy; and a before and after proof that the live ledger file is unchanged. Telegram is checked as configured only: no test message is sent. It is resumable: do the steps it lists under "Next, in order" (log in to Kite, `pflab mail connect`, start Docker, stop the dashboard so the store can be copied) and run the same command again. Two things no program can do: after the first run, with the app open, sleep the laptop 5+ minutes, wake it, wait 2 minutes, then add `-WakeCheck`; and close Claude Code, leave the app running an hour, then `-WakeCheck` again (its heartbeat shows it kept going). `-LiveModel` adds one small model call through the app's privacy gate and budget; `-Offline` skips Kite and Gmail.

**Email is removed (his decision 2026-10-30):** you drop every statement, certificate and screenshot into Inbox and files by hand; passwords go in Settings > Keys and passwords; the World's "What to bring" lists what helps. An account you will not add now is left out on the coverage card (or named there), and added later by dropping its statement.

## A fresh start (S67 local)
Close the dashboard and the bot first. `pflab pm fresh --archive-to <a folder outside the profile and data folders> [--statements <folder>]` lists what it would do; add
`--confirm start-fresh` to do it. It copies the profile (and the statements folder) as opaque bytes into the archive, checks every file's hash, moves the old profile aside
(never deletes it), and makes a new EMPTY profile that does nothing until the "Portfolio Lab" icon is double-clicked (`pm/activation.json`; jobs, Gmail and Kite wait). Only the
test counter and a reduced spend record are carried over. The old profile comes back only as a separate copy: `pflab pm restore <archive> <empty folder>`. Files alone are never called complete: the inventory is yours to confirm.

## The workshop (development; not the app)
A checkout of this repo without `release.toml` is the beta: `python -m venv .venv`, `.venv\Scripts\pip install -e ".[dev]"`, tests with
`.venv\Scripts\python -m pytest -q --basetemp <folder>`. It sends nothing outward and makes no paid call unless run as `pflab --live ...` or `pflab --paid ...`
(paid calls count against `dev_monthly_cap_rupees` in `api_budget.toml`, default 0); it never registers a scheduled task. Releases: merge to `main`, run the suite and the
privacy grep (`python -m pflab.hq.security`), tag `vYYYY.MM.DD`, push. `data/` and `pm/` are gitignored and are never in a release.
