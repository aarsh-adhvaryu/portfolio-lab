# CLAUDE.md — instructions for Claude Code on this repo

`portfolio-lab` (package `pflab`) is the investor's **companion** for NSE equities (a small US sleeve in beta): tax-aware FIFO
lots, corporate actions, filings, prices and NAVs, collectors, and a team of agents with one tool-calling brain that runs by
itself. **Claude Code is for development only: the system runs, learns and asks by itself.** Read `docs/PLAN.md` (intent and
frame), `docs/BUILT.md` (what exists, jobs, tools, sources, tables, switches), `docs/STUDIES.md` (every test and verdict), and
`docs/RUNNING.md` (install, first run, updates, acceptance; `README.md` is the project's front page). Two installations: the **APP** (an install of a release tag in its own folder, runs his money) and the
**WORKSHOP** (this checkout: the beta, where Claude Code develops; no `release.toml`). The workshop sends nothing outward and makes
no paid call unless told (`pflab --live`, `pflab --paid`; `src/pflab/guard.py`). The workshop holds nothing personal (no statements,
no copy of his store): it runs the beta on what the collectors bring. Since 2026-11-02 (A36) the app holds no personal record of his either: its ledger is the SYSTEM'S OWN account
(`ledger/system.py`: his Zerodha holdings as the starting positions, a fake bank and broker with fake money, only the system's own events after; his later real trades, statements, FDs,
tax packs and notes are removed and never read again). Kite is its data feed only. While `pm/system_account.toml` exists, never rebuild the ledger from statements.

## Non-negotiables
1. **Point-in-time.** A feature at date M uses only rows dated <= M. Announcements use the dissemination timestamp.
2. **The 2022–2025 period is spent** (live use loads it): not evidence of anything out-of-sample.
3. **ISIN is the security key.** Never join on symbol without a date. A US instrument uses its real ISIN when a statement shows one,
   else the pseudo-ISIN "ZZ" + the 10-digit SEC CIK (12 characters; "ZZ" is no ISO country), mapped in `instrument_alias` from a date.
4. **Prefer maintained libraries over hand-written code.** Pinned: pandas, pyarrow, duckdb, numpy, requests, python-dateutil,
   pypdf, openpyxl 3.1.5, kiteconnect 5.2.2 (read-only wrapper `ingest/kite.py`), casparser 1.4.1, PyYAML 6.0.3, langgraph 1.2.13,
   langchain-ollama 1.1.0 / langchain-core 1.6.6, msoffcrypto-tool 5.4.2, xlrd 2.0.1, trafilatura 2.0.0, statsmodels 0.14.6,
   anthropic 1.15.0 (only in `agents/analyst.py`, behind the egress gate and his cap), fastapi 0.159.1, uvicorn 0.54.0.
   Email is removed (his decision 2026-10-30: he drops every file by hand; no Gmail code or library). No
   Since 2026-11-05 (A40) no library or model is banned: torch, transformers, lightgbm, statistical or learned forecasters and backtest helpers are
   allowed **when they enter through a pre-registered comparison that beats the simpler alternative on unseen data (rule 10)**, and are pinned in
   `requirements.lock`. Heavy ML (torch/CUDA) lives in the optional extra `pip install -e ".[ml]"` and the separate workspace `tools/model_lab/`, so the app
   installs and runs without it (TimesFM was tested, failed, removed).
5. **Data lives under `PFLAB_DATA_DIR`, the store under `PFLAB_PM_DIR`** (gitignored). An installed app's `release.toml` sets both
   and wins over the environment. Secrets: `%USERPROFILE%\.pflab\secrets.toml` (never print or echo them; `pflab setup secrets`).
6. **Engine tests pass unchanged:** `test_engine_*`, `test_lookahead`, `test_negative_control`, `test_measurement_fixes`,
   `test_accounting_audit`. Fix code, not those tests.
7. **Money is float rupees; dates are `datetime.date`;** long-format parquet, DuckDB for queries, pandas for logic. Tests are synthetic.
8. **Maths decides; models read, connect and explain.** No model-made numbers; no trading path (Kite stays read-only; a GTT is an
   order: never placed); tax rows sourced and dated; estimates labelled. Local drafts pass `llm/guard.py`; the API analyst's answers
   pass `analyst.only_sourced_numbers`; order "tickets" are text for him to enter himself. The paper portfolio (`paper/`, A35, his decision 2026-11-01) is
   the system's own: there the PROMOTED POLICY decides at every close and in the session (A47-A54: the AI writes and promotes policies, code sizes, applies the rails, fills and taxes; no committee, no per-trade approval); nothing reaches a broker.
9. **Models.** Local: qwen3:8b-q8_0 and nomic-embed-text (never delete). API: Claude Opus 5.5 through the doorbell in
   `agents/analyst.py`; his portfolio may go (holdings, amounts, weights, goals), his identity and banking details never. Any model
   change is a measured decision. (A41, 2026-11-05) Further local models (a larger MoE, a tuned GGUF from `tools/model_lab/`) are added by a measured
   decision, the two above never deleted; steering and LoRA live only in `model_lab`; the app sees a GGUF through Ollama.
10. **Every new claim is a pre-registered study** (protocol committed before the run, rule in code) and **counts in the learner's
    counter** (the bar rises with N). What passes is wired into the agents; what fails has no live feature. A feature or covariate
    enters a model only if a registered comparison beats the simpler model on unseen data (that comparison counts as a test).
11. **Never change his targets, limits or the stock list:** propose, and wait for his yes. When unsure whether something is wanted,
    ask him.

## Working rules (his standing preferences)
- **Reports to him: 15 lines or fewer, plain words** (he is not a trader: say what a number means for him). Commit messages: 10 lines
  or fewer. Notes are findings plus decisions needed.
- **Long runs** (2026-10-31: bounded acceptance runs are the development session's to run and observe; during the acceptance window until 2026-11-07 the Rs 1,500 window cap replaces the day limits, see PLAN.md S68). For anything over ~5 minutes that is genuinely long (backfills, rebuilds), a sample first, then: give the exact PowerShell command from the repo
  folder, what it produces, how long, how to tell it finished; never trust a completion notice over the process table and the files.
  **Run the real path yourself on a short sample first**; he wants no reruns from untested fixes.
- **Technical choices are yours** (models, methods, fixes): decide, record a dated amendment with a safe fallback, do not hand him
  options. His money, preferences and limits stay his.
- **No waiting on schedules (A42, 2026-11-05):** the system runs whenever the app is open. On open it catches up first (every missed session's data and scoring,
  point-in-time, by code), then works by the clock's MODE (`pre_open`, `session`, `post_close`, `deep`, per market) and its own agenda, never by job times; an
  analysis job is due whenever its input is newer than its last run (only data arrival, such as NSE files after the close, waits). The laptop being off is normal,
  never an error: silence and staleness count app-open time only, a gap is recorded as "off from X to Y". The bot runs inside the app process. No manual restarts.
- **Feature freeze (A44, armed 2026-11-08):** the app checks its own first week (`service/week_check.py`, job `week_check`: catch-ups after every gap, every mode reached, forecasts made and scored, no job failure, cost within the cap) and tells him once on Telegram. From the day that verdict PASSES (stored in `week_check_s79.freeze_from`) there are 60 days of bug fixes only: no new feature, tool or model unless he asks. A FAIL means fix first, no freeze.
- **The v2 core (A47, 2026-11-08, his decision; PLAN.md S80):** the paper book is decided by the promoted policy in `src/pflab/core/` at every close (code, no committee, no per-trade approval). The A44 freeze is lifted. Rules 8 and 10 and A25/A35 are changed as PLAN.md A47 says; the missions, workers, brain passes and the paper team are DELETED (S80 phase 4).
- **S81, core + satellite and the autonomous loop (A48-A55, 2026-11-09, his decisions; PLAN.md S81):** the book is a CORE (index, gold and international ETFs) plus the SATELLITE sleeve `longterm` (the `swing` sleeve was DELETED in S82, A60: its registered study failed); intraday is dropped as a strategy (minute data only times entries and exits); the strategist proposes the allocation (sleeve caps in code: longterm at most 60%, core at least 30%; the starting split is core 60 / longterm 40, A60; his `targets.toml` untouched); promotion needs the history within the index limits after tax on both sides (A50) and a probation slice (5%, 10%, 20%) while live shadow proves it; selling is code (exit plans, tax harvesting, the 12-month guard, thesis break) and every sale is scored after tax against holding; the knowledge graph is rebuilt on the agreed three layers and switches ON only when its nightly audit passes; the US leg is Indian-listed international ETFs inside the core (premium-to-NAV rail) plus a paper US sub-book; the system works in three rhythms per market (pre-open plan, a 5-minute session loop on live quotes, post-close loop) and never makes a same-day round trip in a name. **A55: until the system is proved working, no internal spend throttle may stop a function** (the strategist's budget-halving rules are recorded but not applied until 2026-12-09); his Rs 2,500 monthly cap stays the only hard limit; every call is still priced and logged.
- **S82, his decisions of 2026-11-10 (A56-A60; PLAN.md S82):** **A56** a broad-market index ETF (Nifty 50 and Nifty 500 index ETFs only, listed by symbol in config) may hold up to 60% of the book; every other ETF 35%, a stock 10%, a sector 25%. **A57** the 10% international share is held in the US paper sub-book (USD, real prices, FX): ONE book, funded by a TRANSFER out of the rupee book's cash (never new money), the whole book's value is the rupee book plus the sub-book in rupees; India-listed international ETFs stay allowed under the premium rail (now international AND gold); real money stays Phase C (Jan-Feb 2027). **A58** a filing with no release time is used from the next trading day's open (graph and tests), not excluded. **A59** the US book works from daily closes: decided in the IST morning on the last US close, orders fill at the next US open, stops act at the next US open (gap risk stated); no US session loop. **A60** what fails its registered study is switched off and its code deleted unless something that passed needs it (the study records stay): the swing sleeve is gone; exemption and loss harvesting is OFF per sleeve (`[exits] harvest_core`, `harvest_longterm`) until a narrower study passes; the inventory is in PLAN.md.
- **S83, the learning book (A61-A63, his decisions of 2026-11-10; PLAN.md S83):** **A61** the goal of the paper book is to OUTPERFORM the index after tax (the Nifty 500 for India, the S&P 500 in rupees for the US sub-book) without a deeper fall in a crash; the book keeps a PICKS sleeve in both markets that the index fallback never empties: India's `longterm` sleeve (his Kite stocks plus the system's own picks) starts at 40% and moves in 5-point steps between 20% and 60% by its live record; from 2026-11-12 (A64, his decision) its start is his Kite stocks' weight plus 20 points, at most 60%: 10 points for ordinary picks and 10 an OPPORTUNITY RESERVE in cash that only the thinking loop may spend (`pick_share.set_start_by_decision`, protocol Amendment A1), and the US sub-book keeps 10 points as a reserve too; F2: a US pick named after the sub-book is invested, a reserve buy and the full exit of a withdrawn pick are outside the monthly churn cap (25% of the sub-book a day) (`core/pick_share.py`, a registered live test: `docs/protocols/s83_picks_live_protocol.md`; a shrink is never a forced sale); the US picks share of the sub-book starts at 50% (30% to 70%), SPY at least 30%; every pick has a thesis, a break condition and storylines, and every pick, sale and skipped idea is scored after tax against the index at 1, 3, 6 and 12 months (`core/pick_score.py`); the strategist reads the scorecard each session and its next picks must cite what it taught. History cannot judge picks, so the lab's A50 gate does not apply to the picks sleeve (it still applies to the core's split and to every coded policy). **A62** the system picks US stocks itself, any size: rails as shares of the sub-book (SPY 30% to 100%, a stock at most 10%, at most 12 stocks, price at least USD 5 and median daily traded value at least USD 2 million); "assumed tradable, checked before Phase C" unless a GIFT City list is found; history of single US stocks is survivorship-biased and never shown as evidence. **A63** this changes rule 8 in one place: the strategist may name stocks for the picks sleeve through `propose_picks`, each with a thesis; it never writes a size, a price or a weight; code checks the rails, sizes by risk inside the sleeve's share, spreads the buying inside the turnover caps and scores it. Coded policies, the lab, promotion and the tactical views are unchanged.
- **Not built (A43, decided):** no MCP server, no social-media sentiment agent, no Hermes/OpenClaw/TradingAgents framework, no agent-SDK migration.
- **The system's own book (A45, 2026-11-05):** it starts from his Kite holdings and nothing else, then decides its own allocation (the strategist proposes it with reasons through a lab tool, code checks it against the rails and the sleeve caps,
  the lab tests it like any policy, re-examined at every weekly session, A49) inside the code rails; that target is the system's, his `targets.toml` stays his.
- **Local first; paid only where it beats local,** inside his Rs 2,500 monthly cap, priced first; the workshop's paid calls count
  against `dev_monthly_cap_rupees` (default 0).
- **Personal inputs go after calibration** (statements, PDFs, exports); statement passwords only in the secrets file `[passwords]`.
  No real data in git: grep the staged diff for amounts, names, ids (Indian grouping too) and test fixtures before every push;
  `.venv\Scripts\python -m pflab.hq.security` must print "privacy grep: clean" (it checks against `%USERPROFILE%\.pflab\privacy_terms.json`,
  which the app's daily privacy check rewrites; `python -m pflab.hq.security export` in the app's folder writes it at once).
- **The system asks only what only he can answer** (Needs from you); coordinated specialists (amendment A25, 2026-10-31: a coordinator, research and quant workers and an independent reviewer on the one board; the old "one brain, no rivals" no longer applies); the knowledge graph and memory
  must update themselves. Tools and models are used to their full capability where they help, never as a demo.
- **Only one process may hold the store:** close the dashboard and the bot before CLI work; back the store up before any migration or
  real-path write. The store migrates itself; take new ids with `store.next_id`, never a DuckDB sequence.
- Write code with the file tools, not shell heredocs (a heredoc turned `\b` into a backspace twice); after a scripted edit grep for
  control characters. In PowerShell put multi-line or quoted Python in a scratch file, never `python -c`; do not name a function like
  an alias or keyword (`Cli`, `Do`).
- Never re-read a file already read in the session. Edit files with the file tools (UTF-8 is garbled by `Get-Content`/`Set-Content`
  without `-Encoding UTF8`).
- **Tests:** `.venv\Scripts\python -m pytest -q --basetemp <a folder in your scratchpad>` (the default temp folder is denied on this PC);
  about 4-8 minutes. Each session works on branch `pm/sN-<slug>` (the beta); at each stop update `docs/PLAN.md` "What remains" and
  `docs/BUILT.md` if the system changed, then commit. Only a beta confirmed bug free goes to `main`: merge, tag `vYYYY.MM.DD[.N]`, push;
  the app takes the newest tag at its next start (one desktop icon; `launcher.update_first`).
- The laptop GPU (RTX 5070 Ti Laptop) drops off the bus at top boost under sustained load: cap the clocks first from an Administrator
  PowerShell (`nvidia-smi -lgc 210,2100` and `nvidia-smi -lmc 405,9001`); after a loss use Restart, not Shut down.

## Daily commands
`pflab pm init|networth|guards|alerts|propose|advise|deploy|simulate|fd show|tax --fy N|quicko --fy N|reset`, `pflab ask`, `pflab list`,
`pflab kg`, `pflab research`, `pflab analyst`, `pflab learner status|test --claim N`, `pflab service run|tick|status`, `pflab conductor`,
`pflab hq`, `pflab us`, `pflab setup secrets|status`, `pflab update [--check|--rollback]`, `pflab verify [--app F] [--report F] [--wake-check] [--live-model] [--offline]` (local acceptance of a candidate on a copy of the record; `tools\verify_candidate.ps1` runs it from an isolated checkout), `pflab --paid|--live ...` (workshop only).
Installing the app: `tools\install_app.ps1`, then `tools\seed_app.ps1` once. The desktop shortcut "Portfolio Lab" starts the dashboard
and all jobs in one process (it holds the store); `tools\register_tasks.ps1` registers the tick (the app only).
