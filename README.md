# Portfolio Lab (`pflab`)

The investor's companion for NSE equities (a small US sleeve in beta): it collects data, keeps a tax-aware ledger, researches, forecasts, simulates, tests its own ideas
and tells him what matters. It never places an order. Not investment advice. What exists: `docs/BUILT.md`; every test and verdict: `docs/STUDIES.md`; intent and
what remains: `docs/PLAN.md`; rules for Claude Code: `CLAUDE.md`.

## First run, from a fresh clone (Windows 11, PowerShell; his steps in this order)
1. **Install** Python 3.13, git, [Ollama](https://ollama.com) and, if you want contained calculations, Docker Desktop. Then `ollama pull qwen3:8b-q8_0` and
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
   **Gmail (read-only, once; about 10 minutes):** at console.cloud.google.com create a project; APIs and Services > Library > enable "Gmail API"; OAuth consent
   screen > External, app name "Portfolio Lab", add your own address as a test user; Credentials > Create credentials > OAuth client ID > "Desktop app" > download
   the JSON (leave it in Downloads: Connect moves it to `%USERPROFILE%\.pflab\gmail_client.json`). Then Settings > Connect Gmail (or `pflab mail connect`):
   Google's page opens; approve "Read your email" only. The first look reads a year of mail at once; after that, once a day at 21:15. Statement
   attachments (by content; everything else is dropped unread) come into the inbox like a file you drop; protected ones open with the passwords you saved (the file
   is stored as it came, still locked). Files none opens are asked about once per sender, with a slot named after it in Settings > Keys (NSDL, SBI ...); saving it
   tries again at once. Then Needs from you asks you to approve the accounts in Setup. The same daily run also reads what money emails say (trades, deposits, dividends, IPO allotments, bank alerts, research) with the model on this PC only, checks each fact against Kite and your record, and asks only about what is missing or disagrees; nothing is written to your record from an email. Testing-mode tokens expire after 7 days: publish the consent screen
   ("In production", unverified is fine for yourself) to keep it connected.
6. **Switch it on.** Settings: Telegram on (held alerts are then delivered), the brain on "economy", preset "full". Close the window, then register the tick (every
   15 minutes, at logon, at wake): `powershell -ExecutionPolicy Bypass -File tools\register_tasks.ps1` (preview with `-WhatIf`). After that it runs, learns and asks by itself.

## Day to day
Nothing: it wakes with the laptop, watches, researches, simulates, and writes to you only when it matters (plus 09:00 and 21:45 summaries). Tell it your monthly amount
when the money comes ("I'm investing 50k this month"). Taxes: `pflab pm quicko --fy 2027` writes the Quicko inputs to `pm\reports\quicko`.
**Update:** nothing to do: each start of "Portfolio Lab" takes the newest release first (or `pflab update` with the app closed): it backs the store up, installs the newest release tag, self-tests, and undoes itself on a
failure; `pflab update --rollback` returns to the previous release. Your record is never wiped.

## The workshop (development; not the app)
A checkout of this repo without `release.toml` is the beta: `python -m venv .venv`, `.venv\Scripts\pip install -e ".[dev]"`, tests with
`.venv\Scripts\python -m pytest -q --basetemp <folder>`. It sends nothing outward and makes no paid call unless run as `pflab --live ...` or `pflab --paid ...`
(paid calls count against `dev_monthly_cap_rupees` in `api_budget.toml`, default 0); it never registers a scheduled task. Releases: merge to `main`, run the suite and the
privacy grep (`python -m pflab.hq.security`), tag `vYYYY.MM.DD`, push. `data/` and `pm/` are gitignored and are never in a release.
