# CLAUDE.md — instructions for Claude Code on this repo

`portfolio-lab` (package `pflab`) is the investor's **companion** for NSE equities (a small US sleeve in beta): tax-aware FIFO
lots, corporate actions, filings, prices and NAVs, collectors, and a team of agents with one tool-calling brain that runs by
itself. **Claude Code is for development only: the system runs, learns and asks by itself.** Read `docs/PLAN.md` (intent and
frame), `docs/BUILT.md` (what exists, jobs, tools, sources, tables, switches), `docs/STUDIES.md` (every test and verdict), and
`README.md` (first run). Two installations: the **APP** (an install of a release tag in its own folder, runs his money) and the
**WORKSHOP** (this checkout: the beta, where Claude Code develops; no `release.toml`). The workshop sends nothing outward and makes
no paid call unless told (`pflab --live`, `pflab --paid`; `src/pflab/guard.py`).

## Non-negotiables
1. **Point-in-time.** A feature at date M uses only rows dated <= M. Announcements use the dissemination timestamp.
2. **The 2022–2025 period is spent** (live use loads it): not evidence of anything out-of-sample.
3. **ISIN is the security key.** Never join on symbol without a date. A US instrument uses its real ISIN when a statement shows one,
   else the pseudo-ISIN "ZZ" + the 10-digit SEC CIK (12 characters; "ZZ" is no ISO country), mapped in `instrument_alias` from a date.
4. **Prefer maintained libraries over hand-written code.** Pinned: pandas, pyarrow, duckdb, numpy, requests, python-dateutil,
   pypdf, openpyxl 3.1.5, kiteconnect 5.2.2 (read-only wrapper `ingest/kite.py`), casparser 1.4.1, PyYAML 6.0.3, langgraph 1.2.13,
   langchain-ollama 1.1.0 / langchain-core 1.6.6, msoffcrypto-tool 5.4.2, xlrd 2.0.1, trafilatura 2.0.0, statsmodels 0.14.6,
   anthropic 1.15.0 (only in `agents/analyst.py`, behind the egress gate and his cap), fastapi 0.159.1, uvicorn 0.54.0. No
   backtesting frameworks, no lightgbm, no torch or forecasting models (TimesFM was tested, failed, removed).
5. **Data lives under `PFLAB_DATA_DIR`, the store under `PFLAB_PM_DIR`** (gitignored). An installed app's `release.toml` sets both
   and wins over the environment. Secrets: `%USERPROFILE%\.pflab\secrets.toml` (never print or echo them; `pflab setup secrets`).
6. **Engine tests pass unchanged:** `test_engine_*`, `test_lookahead`, `test_negative_control`, `test_measurement_fixes`,
   `test_accounting_audit`. Fix code, not those tests.
7. **Money is float rupees; dates are `datetime.date`;** long-format parquet, DuckDB for queries, pandas for logic. Tests are synthetic.
8. **Maths decides; models read, connect and explain.** No model-made numbers; no trading path (Kite stays read-only; a GTT is an
   order: never placed); tax rows sourced and dated; estimates labelled. Local drafts pass `llm/guard.py`; the API analyst's answers
   pass `analyst.only_sourced_numbers`; order "tickets" are text for him to enter himself.
9. **Models.** Local: qwen3:8b-q8_0 and nomic-embed-text (never delete). API: Claude Opus 5.5 through the doorbell in
   `agents/analyst.py`; his portfolio may go (holdings, amounts, weights, goals), his identity and banking details never. Any model
   change is a measured decision.
10. **Every new claim is a pre-registered study** (protocol committed before the run, rule in code) and **counts in the learner's
    counter** (the bar rises with N). What passes is wired into the agents; what fails has no live feature. A feature or covariate
    enters a model only if a registered comparison beats the simpler model on unseen data (that comparison counts as a test).
11. **Never change his targets, limits or the stock list:** propose, and wait for his yes. When unsure whether something is wanted,
    ask him.

## Working rules (his standing preferences)
- **Reports to him: 15 lines or fewer, plain words** (he is not a trader: say what a number means for him). Commit messages: 10 lines
  or fewer. Notes are findings plus decisions needed.
- **Long runs are his** (anything over ~5 minutes: backfills, rebuilds, evaluations): give the exact PowerShell command from the repo
  folder, what it produces, how long, how to tell it finished; never trust a completion notice over the process table and the files.
  **Run the real path yourself on a short sample first**; he wants no reruns from untested fixes.
- **Technical choices are yours** (models, methods, fixes): decide, record a dated amendment with a safe fallback, do not hand him
  options. His money, preferences and limits stay his.
- **Act then and there:** new data starts its jobs; no manual restarts; schedules only where data timing forces them.
- **Local first; paid only where it beats local,** inside his Rs 2,500 monthly cap, priced first; the workshop's paid calls count
  against `dev_monthly_cap_rupees` (default 0).
- **Personal inputs go after calibration** (statements, PDFs, exports); statement passwords only in the secrets file `[passwords]`.
  No real data in git: grep the staged diff for amounts, names, ids (Indian grouping too) and test fixtures before every push;
  `.venv\Scripts\python -m pflab.hq.security` must print "privacy grep: clean".
- **The system asks only what only he can answer** (Needs from you); one brain with tools, no rivals; the knowledge graph and memory
  must update themselves. Tools and models are used to their full capability where they help, never as a demo.
- **Only one process may hold the store:** close the dashboard and the bot before CLI work; back the store up before any migration or
  real-path write. The store migrates itself; take new ids with `store.next_id`, never a DuckDB sequence.
- Write code with the file tools, not shell heredocs (a heredoc turned `\b` into a backspace twice); after a scripted edit grep for
  control characters. In PowerShell put multi-line or quoted Python in a scratch file, never `python -c`; do not name a function like
  an alias or keyword (`Cli`, `Do`).
- Never re-read a file already read in the session. Edit files with the file tools (UTF-8 is garbled by `Get-Content`/`Set-Content`
  without `-Encoding UTF8`).
- **Tests:** `.venv\Scripts\python -m pytest -q --basetemp <a folder in your scratchpad>` (the default temp folder is denied on this PC);
  about 4-8 minutes. Each session works on branch `pm/sN-<slug>`; at each stop update `docs/PLAN.md` "What remains" and `docs/BUILT.md`
  if the system changed, then commit.
- The laptop GPU (RTX 5070 Ti Laptop) drops off the bus at top boost under sustained load: cap the clocks first from an Administrator
  PowerShell (`nvidia-smi -lgc 210,2100` and `nvidia-smi -lmc 405,9001`); after a loss use Restart, not Shut down.

## Daily commands
`pflab pm init|networth|guards|alerts|propose|advise|deploy|simulate|fd show|tax --fy N|quicko --fy N|reset`, `pflab ask`, `pflab list`,
`pflab kg`, `pflab research`, `pflab analyst`, `pflab learner status|test --claim N`, `pflab service run|tick|status`, `pflab conductor`,
`pflab hq`, `pflab us`, `pflab setup secrets|status`, `pflab update [--check|--rollback]`, `pflab --paid|--live ...` (workshop only).
Installing the app: `tools\install_app.ps1`, then `tools\seed_app.ps1` once. The desktop shortcut "Portfolio Lab" starts the dashboard
and all jobs in one process (it holds the store); `tools\register_tasks.ps1` registers the tick (the app only).
