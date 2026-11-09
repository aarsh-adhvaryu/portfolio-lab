# S81 agent brief: read this first, every agent

You are one of six parallel development agents building the S81 overnight work for `portfolio-lab` (package `pflab`) on the investor's own PC (Windows, `D:\portfolio_lab`, real Ollama,
Docker). He is asleep and will not answer. Do not ask anything; decide on the defaults in `docs/s81_autonomy_loop_prompt.md` (read it fully: A48-A55 and the items B1-B9 and
his appendix of answers), record each decision as a dated line in your own notes file, and carry on. Also read `CLAUDE.md` (rules and working rules) and `docs/CUT_PLAN_S80.md`.
The coordinator (the main session) integrates your branch, wires `core/loop.py`, writes `docs/PLAN.md`, `docs/BUILT.md` and `CLAUDE.md`, and runs the full suite. You do NOT edit those three files.

## Environment (this matters)
- You work in YOUR OWN git worktree (a copy of branch `pm/s81-loop`). Run Python as `D:\portfolio_lab\.venv\Scripts\python.exe` with the environment variable
  `PYTHONPATH` set to YOUR worktree's `src` folder FIRST (otherwise the editable install imports the main checkout's code, not yours). Run pytest from your worktree root:
  `$env:PYTHONPATH = "<your worktree>\src"; D:\portfolio_lab\.venv\Scripts\python.exe -m pytest -q --basetemp <a folder under the scratchpad> tests\<your files>`.
  Run ONLY your own tests plus any test file your changes could touch (grep for the modules you edit). Do NOT run the full suite (it takes 20 minutes and the coordinator does it).
- `PFLAB_DATA_DIR` and `PFLAB_PM_DIR` point at the workshop; tests use temporary stores and synthetic data (rule 7). NEVER write to `D:\PortfolioLabApp` (the live app's folder) except
  where your item says so explicitly, and never to its store. Never print or read secrets (`%USERPROFILE%\.pflab\secrets.toml`). No paid API call (no `--paid`); a model in a test is a scripted fake.
  The local Ollama model may be used for real paths (the GPU is clock-capped; if it errors, fall back and say so).
- Write code with the file tools (Write/Edit), not shell heredocs (a heredoc eats backslashes: scan for control characters after any scripted edit). PowerShell: put multi-line Python in a scratch file.
- Only one process may hold the real store; you never touch it. Take new ids with `store.next_id`, never a DuckDB sequence. Beware DuckDB reserved words as column names (`at`, `asof`, ...).
- Migrations: add your own module `src/pflab/pm/mig_s79/m_<item>.py` with `MIGRATIONS = [(version, name, sql), ...]` (the package collects every `m_*.py`). Use ONLY your version range:
  core-lab 108-112, exits 113-117, swing 118-122, kg 123-130, us 131-136, session 137-142. `CREATE TABLE IF NOT EXISTS` so two agents may create the same shared table safely.

## Non-negotiables (CLAUDE.md, restated)
Point-in-time (a feature at date M uses only rows dated <= M; announcements use the dissemination timestamp); the 2022-2025 period is spent; ISIN is the key; money is float rupees,
dates are `datetime.date`; maths decides, models read and explain (no model-made numbers; every number in a reply or note comes from code); no trading path (paper only; Kite read-only; no GTT);
his `targets.toml` is never changed; the rails (company 10%, sector 25%, ETF 35%, no F&O, no borrowing, no shorting) and turnover caps stay; privacy: no real data in git or fixtures,
`D:\portfolio_lab\.venv\Scripts\python.exe -m pflab.hq.security` must print "privacy grep: clean"; the engine tests (`test_engine_*`, `test_lookahead`, `test_negative_control`,
`test_measurement_fixes`, `test_accounting_audit`) pass UNCHANGED (never weaken, skip or stub any test); every new claim is a pre-registered study (protocol committed before the run) and counts in the learner's counter.
Never invent a number that is a rule of law or a cost (tax rates, exemptions, charges, withholding): read it from the tax engine's dated rows or a primary source and cite it; unverified = labelled estimate.

## Shared contracts (so six branches merge)
- Sleeves: every position belongs to one sleeve, `core` (index, gold and international ETFs), `longterm` (stock picks held months to years) or `swing` (days to weeks). Table
  `sleeves_s81(market VARCHAR, isin VARCHAR, sleeve VARCHAR, opened_on DATE, PRIMARY KEY (market, isin))` (create it IF NOT EXISTS in your migration if you need it; core-lab owns it, version 108).
  Helper `pflab.core.sleeves.sleeve_of(con, isin, market="IN") -> str` (core-lab writes it; default: ETFs and gold/international instruments -> core, everything else -> longterm).
- Exit plans (exits owns): table `exit_plans_s81`; module `pflab.core.exits` with `open_plan(con, now, market, isin, sleeve, entry_price, qty, plan=None) -> int`,
  `check_close(con, day, prices, state) -> list[dict]` (the post-close checks), `check_quote(con, now, quotes, state) -> list[dict]` (the session checks on live quotes), `check_thesis(con, day, events) -> list[dict]`.
  An order dict is `{"market","isin","side":"sell"|"buy","qty":float|None,"fraction":float|None,"kind":"stop"|"target"|"time"|"thesis"|"harvest"|"trim"|"rebalance","reason":str,"plan_id":int|None}`; the reason is written by code.
- Events (kg owns): module `pflab.kg.events` with `material_events(con, isins, since) -> list[dict]` where each event is `{"isin","kind","severity","ts","source","ref","text"}` (`ts` is the dissemination time; no event without one).
- Quotes and bars (session owns): `pflab.core.session` (live loop) and `pflab.core.fills` (quote fill + spread + slippage by liquidity, never better than the quote; the no-same-day-round-trip guard).
- Markets: functions that will serve a second market take `market: str = "IN"` and default to it, so Indian behaviour does not change.

## How to work
- Commit on your worktree's branch often (commit message at most 10 lines, ending with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`). Do not push, do not merge, do not tag.
- Touch shared files minimally (`core/loop.py`, `core/state.py`, `core/policy.py`, `core/rails.py`, `lab/service.py`, `lab/promotion.py`, `lab/engine.py`, `app/server.py`, `service/*`):
  put new logic in new modules and make the smallest possible hook in a shared file; list every shared file you touched in your final report.
- Real path: run your item once for real on this PC where it makes sense (real files under the app's `data` read-only; Docker sandbox; local Ollama), on a COPY, never the live store.
- Time: the building window ends at 03:15 IST (check `Get-Date`). At 03:15 stop adding, commit what is green, and put anything unfinished behind a config switch that is OFF
  (nothing else may depend on it). Write `docs/s81_<item>_notes.md` in your worktree: what is built, what each decision was, what is OFF and why, how to switch it on, tests added, shared files touched, what is left.
- Final report to the coordinator (it is all that comes back, so make it complete and plain): the branch name and last commit, what works (with the test names), what is OFF and why, shared files touched, anything you could not verify, any decision of his that is needed.
