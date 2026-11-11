# S82 agent brief: read this first, every agent

You are one of several parallel development agents for S82 ("Night 1 of 4: close the gaps") of `portfolio-lab` (package `pflab`) on the investor's own PC (Windows, `D:\portfolio_lab`, real
Ollama, Docker). He is asleep and will not answer. Do not ask anything; decide on the defaults written in your brief, record each decision as a dated line in your own notes file
(`docs/s82_<item>_notes.md`), and carry on. Read `CLAUDE.md` first (rules and working rules). Today is 2026-11-11; the building window ends 01:50 IST on 2026-11-12 (check `Get-Date`).
At that time stop adding, commit what is green, and put anything unfinished behind a config switch that is OFF (nothing else may depend on it).
The coordinator (the main session) integrates your branch, does `docs/PLAN.md`, `docs/BUILT.md`, `CLAUDE.md`, `configs/core.toml` (except the keys your brief names) and runs the full suite. You do NOT edit those.

## His decisions (2026-11-10, amendments A56-A60; permanent)
- A56 a broad-market index ETF (Nifty 50 and Nifty 500 index ETFs only, listed by symbol in config) may hold up to 60% of the book; every other ETF stays at 35%; stocks 10%, sectors 25%.
- A57 the 10% international share is held in the US paper sub-book (USD, real prices, FX). ONE book: the sub-book is funded by a TRANSFER OUT of the rupee book's cash (never new money); the whole
  book's value is the rupee book plus the sub-book in rupees. India-listed international ETFs stay allowed when their premium is under the rail. Real money (Phase C) is not tonight.
- A58 filings with no release time are used from the next trading day after their date (available at the next session's open), in the knowledge graph and in every test, instead of being excluded.
- A59 the US book works from daily closes: decided in the IST morning on the last US close; orders fill at the next US open; stops act at the next US open; no US session loop, no Kite US check.
- A60 what failed its test is removed: the swing sleeve is deleted from the live paths; the starting split is core 60 / longterm 40 / swing 0; exemption and loss harvesting is OFF in the live book until a narrower study passes.
- Rules that STAY: point-in-time; 2022-2025 is spent; ISIN is the key (US: real ISIN or `ZZ`+10-digit CIK); paper only (no trading path, no GTT); privacy; one store writer; the five protected engine
  suites unchanged; his `targets.toml` never changed; the kill switch; A55 (no internal spend throttle stops a function before 2026-12-09; his Rs 2,500 monthly cap is the only hard limit).

## Environment (this matters)
- You work in YOUR OWN git worktree (a copy of branch `pm/s82-gaps`). Run Python as `D:\portfolio_lab\.venv\Scripts\python.exe` with the environment variable `PYTHONPATH` set to YOUR worktree's
  `src` folder FIRST (otherwise the editable install imports the main checkout's code, not yours). Run pytest from your worktree root:
  `$env:PYTHONPATH = "<your worktree>\src"; D:\portfolio_lab\.venv\Scripts\python.exe -m pytest -q --basetemp D:\s82_scratch\<yourname>_tmp tests\<your files>`.
  Run ONLY your own tests plus any test file your changes could touch (grep for the modules you edit). Do NOT run the full suite (the coordinator does it).
- Scratch folder for everything temporary: `D:\s82_scratch\<yourname>\` (create it). Delete big outputs when done.
- Tests run from the Bash tool for anything that starts headless Edge (it does not start from PowerShell).
- `PFLAB_DATA_DIR` and `PFLAB_PM_DIR` may point at the workshop; tests use temporary stores and synthetic data (rule 7). NEVER write to `D:\PortfolioLabApp` or its store (the coordinator backed it up to
  `D:\PL_backup\s82_pre_20261111`; real-path runs use a COPY of that backup, never the live files). Never print or read secrets. No paid API call unless your brief says so; a model in a test is a scripted fake.
  The local Ollama model may be used for real paths (the GPU is clock-capped; if it errors, fall back and say so).
- Write code with the file tools (Write/Edit), not shell heredocs (a heredoc eats backslashes; scan for control characters after any scripted edit). PowerShell: multi-line Python goes in a scratch file.
- Only one process may hold a store. Take new ids with `store.next_id`, never a DuckDB sequence. Beware DuckDB reserved words as column names (`at`, `asof`, ...).
- Migrations: put yours in a new module `src/pflab/pm/mig_s79/m_<item>.py` with `MIGRATIONS = [(version, name, sql), ...]`, using ONLY your version range: US 144-149, fills+strategist 150-155, kg 156-159,
  lab (C3/C4) 160-164, cut/fixes 165-166. Highest existing is 143. `CREATE TABLE IF NOT EXISTS`.

## Non-negotiables restated
Maths decides, models read and explain (no model-made numbers); every new claim is a pre-registered study (protocol committed BEFORE the run, rule in code, counted in the learner's counter); never
weaken, skip or stub a test (tests of deleted code go with it; tests of behaviour that still exists are rewritten, not deleted); tax rates, exemptions and costs come from the tax engine's dated rows or a
primary source, else are labelled estimates; plain words in anything he reads; money is float rupees, dates `datetime.date`; `D:\portfolio_lab\.venv\Scripts\python.exe -m pflab.hq.security` must print
"privacy grep: clean" (no real data in git or fixtures).

## Shared contracts
- Whole-book value = rupee book + US sub-book in rupees at the stated FX source. The function that gives it is written by the US agent (`pflab.us.wholebook`, see its brief); other agents call it, they
  do not recompute it.
- Every new figure a later screen should show is exposed through a plain function or an existing API route (JSON-able dict), documented in your notes file under "Exposed for screens".
- Functions that serve a second market take `market: str = "IN"` and default to it.

## How to work
- Commit on your worktree's branch often (commit message at most 10 lines, ending with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`). Do not push, do not merge, do not tag.
- Touch shared files minimally (`core/loop.py`, `core/state.py`, `core/policy.py`, `core/rails.py`, `core/baseline_v2.py`, `core/card.py`, `lab/service.py`, `lab/promotion.py`, `lab/engine.py`,
  `app/server.py`, `service/*`): new logic in new modules, the smallest possible hook in a shared file; list every shared file you touched in your final report.
- Write `docs/s82_<item>_notes.md` in your worktree: what is built, each decision, what is OFF and why, how to switch it on, tests added, shared files touched, "Exposed for screens", what is left.
- Final report to the coordinator (all that comes back, so make it complete and plain): branch name and last commit, what works (with the test names), what is OFF and why, shared files touched,
  anything you could not verify, any decision that is needed.
