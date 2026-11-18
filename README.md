# Portfolio Lab

> **Parked (18 Nov 2026).** Building stopped: for day-to-day portfolio work the Claude app with a holdings doc does what this was meant to do. `main` is the last
> state, tested (audit S92 in `docs/AUDIT_S92.md`, standing orders S93). The slim redefinition, a "portfolio buddy", is on branch `buddy` (`docs/BUDDY.md`, work
> order `docs/BUDDY_CUT.md`) for if a real need comes back. The newest tag `v2026.11.15.10` is what an installed app runs; `main` is not tagged.

**A local-first companion for an Indian equity portfolio (with a small US sleeve in beta).** It collects market data, filings and news by itself, runs its own
paper portfolio against the index after tax, watches what the investor holds for bad news within minutes, thinks each situation through, and learns whether it
was right. The investor talks to it in a chat (laptop and Telegram). **It never places an order.**

> Maths decides; models read, connect and explain.

| | |
|---|---|
| **Code** | about 116,000 lines of Python in `src/pflab`, about 57,000 lines of tests |
| **Tests** | 4,100+ synthetic tests (unit, migration, restart drills, headless-browser UI) |
| **Store** | one DuckDB file; it migrates itself and is backed up before every update |
| **Runs** | 74 jobs on a clock that follows the markets, inside one app process; a laptop that is off is normal and is caught up on the next open |
| **Models** | Claude through Claude Code on the investor's own plan (no API key anywhere) and a small local model for routine reading |

## What it is

Two installations: the **app** (an installed release tag in its own folder: the thing that runs) and the **workshop** (this checkout: where it is developed and
tested; it sends nothing outward and makes no model call unless told).

- **The system's own book.** It starts from the investor's broker holdings (read-only) and then manages its own paper account with fake money: a CORE (index,
  gold and international ETFs) plus a satellite sleeve of stock picks, and a US sub-book in dollars. The goal is to beat the index after tax without a deeper fall in a
  crash. A coded policy decides at every close; code sizes, checks the rails, fills and taxes. Every pick, sale and skipped idea is scored against the index after tax.
- **The thinking loop.** Code notices a situation (a fall, a news burst, a filing, a missed run) -> a model reads it and names a class from a closed list -> options
  (sell, trim, hold, freeze, wait, buy in parts, nothing) -> worst, likely and best outcomes in rupees by code -> a registered rule decides inside the rails -> the
  decision is scored at 5, 20 and 60 sessions. If the rule trails "do nothing" after tax it turns advisory by itself.
- **The alarm lane.** Fast headlines and company filings on what the book holds are checked every 15 minutes. A serious one is heard on Telegram before any model reads it,
  new buying is frozen by code, a case opens at once, and the decision is told. Its latency is measured (target: 20 minutes to heard, 30 to a decision).
- **The chat is the entrance.** One conversation on the laptop and on Telegram. Plain questions go to a quick road (about 5,000 tokens each); studies, files and links go to
  the full operator, a Claude Code session with the system's tools in its own folder. Anything that changes state waits for a Yes. The operator can open a build on a
  separate git branch to fix a bug; it goes live only after the investor's Yes.
- **The knowledge graph and memory** update themselves; what the system already knows is read by every decision.
- **Collectors.** NSE/BSE prices, corporate actions, filings, shareholding, deals, F&O, FPI flows, macro series, US prices and SEC filings, news feeds. Point-in-time and
  survivorship-free.
- **A tax-aware ledger** (FIFO lots, dated and sourced Indian tax rules) from the earlier statements era; the app's own ledger is now the system's account.

## Rules it keeps
1. **Point-in-time.** A feature at date M uses only rows dated on or before M. Announcements count from their dissemination time.
2. **The 2022-2025 period is spent** by live use: never evidence of anything out of sample.
3. **ISIN is the security key.**
4. **No model makes a number.** Every figure comes from code or a tool, with its source and date; a reply's sentences with unsourced numbers are removed.
5. **No trading path.** The broker connection is read-only; a "ticket" is text for the investor to enter himself.
6. **Every new claim is a pre-registered study** and counts in the learner's counter (the bar rises with the number of tests). What fails has no live feature.
7. **His targets, limits and stock list change only on his Yes.** The monthly model spend has a hard cap, and nothing personal (identity, banking) ever leaves the PC.

## Architecture (short)
```
collectors -> DuckDB store -> knowledge graph / memory
                   |
   scheduler (modes follow the markets: pre-open, session, post-close, deep)
        |-- core/      the promoted policy decides the paper book at each close; exits, tax, rails
        |-- think/     watch -> understand -> options -> outcomes -> rule -> score; the daily desk; alarm lane
        |-- lab/       policies are tested like any claim; promotion needs history within index limits after tax
        |-- us/        the US sub-book (daily closes and a 5-minute session loop)
   entrance/  chat intake (laptop + Telegram), screens, readers, the local privacy screen
   oper/      the operator: quick road, full road, builds with his Yes, weekly introspection
   llm/       the one door for model calls (gateway), the Claude-on-plan engine, usage and budgets
   app/       FastAPI dashboard (vanilla JS), launcher, updater
```

## Repository layout
| Path | What |
|---|---|
| `src/pflab/` | the package (see the architecture above; `ledger/`, `tax/`, `ingest/`, `data/`, `kg2/`, `quant/`, `fcast/`, `risk/`, `paper/`, `service/` and others) |
| `configs/` | all switches and limits (`core.toml` is the main one) |
| `tests/` | synthetic tests; the engine tests (`test_engine_*`, `test_lookahead`, `test_negative_control`, `test_measurement_fixes`, `test_accounting_audit`) never change |
| `tools/` | installers, collectors' backfills, drills and verification scripts |
| `docs/` | `PLAN.md` (intent and what remains), `BUILT.md` (what exists), `STUDIES.md` (every test and verdict), `RUNNING.md` (install, first run, updates), `protocols/` (pre-registered studies), operator notes |

## Quick start (development)
```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.lock
.venv\Scripts\pip install -e .
.venv\Scripts\python -m pytest -q --basetemp <a folder you can write to>
.venv\Scripts\python -m pflab.hq.security        # must print: privacy grep: clean
```
Installing and running the app: `docs/RUNNING.md`. The chat's model engine needs Claude Code signed in with a Claude subscription (`pflab operator status`).

## Disclaimer
A personal research tool, not investment advice and not a product. It trades only on paper. Past tests on the 2022-2025 period are not evidence of future results.
