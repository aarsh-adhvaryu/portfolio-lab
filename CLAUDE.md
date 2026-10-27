# CLAUDE.md — instructions for Claude Code on this repo

`portfolio-lab` (package `pflab`) is the investor's **Portfolio Manager** for NSE
equities: tax-aware FIFO lots, corporate actions, BSE results and
announcements, a price and NAV panel, data loaders, and around it a team of
agents (PLAN amendment A7: researcher, API analyst, advisor, trader planner,
trade check, event research, thesis tracker, Telegram bot) that runs overnight.
The build follows `docs/PLAN.md` (sessions S0–S49), one session at a time, using
`docs/SESSION_TEMPLATE.md`. Read `docs/HANDOFF.md` "Start here" first.

## Non-negotiables

1. **The old research project lives only on GitHub**, since S63 in its own private repo
   `portfolio_system_archive` on the same account (branch `research-archive`, the default,
   and its `lock/*` and `shelved/2026-10-01` tags; this repo, `portfolio-lab`, started
   fresh on 2026-10-25 and has no remote pointing there); there is no local copy. It
   is never checked out into `master`, merged, cherry-picked or rebased until
   The investor says so in writing. File copies out of it are allowed only as listed
   in `docs/MIGRATED.md` (done in S0). Hooks `.githooks/pre-merge-commit` and
   `.githooks/pre-rebase` enforce this; activate with
   `git config core.hooksPath .githooks`. Do not edit or bypass them.
2. **The 2022–2025 period is spent** (live use loads it); it is no longer
   evidence of anything out-of-sample.
3. **Point-in-time.** A feature at date M uses only rows dated <= M.
   Announcements use the dissemination timestamp.
4. **ISIN is the security key.** Never join on symbol without a date. A US instrument uses its real ISIN when a statement shows
   one; until then the pseudo-ISIN "ZZ" + the 10-digit SEC CIK (12 characters; ZZ is not an ISO country, so it never meets a real
   ISIN), mapped to the real one in `instrument_alias` from a date (S64 Phase 6).
5. **Prefer maintained libraries over hand-written code.** Core: pandas,
   pyarrow, duckdb, numpy, requests, python-dateutil, tomli/tomllib, pypdf,
   openpyxl 3.1.5 (added 2026-10-06, S16: AMC monthly portfolio Excel files).
   kiteconnect 5.2.2 (added 2026-10-06, S4; only behind the read-only wrapper in
   `ingest/kite.py`). casparser 1.4.1 (added 2026-10-06, S5; brings casparser-isin,
   pypdfium2). PyYAML 6.0.3, langgraph 1.2.13, langchain-ollama 1.1.0 with
   langchain-core 1.6.6 (added 2026-10-06, S21). msoffcrypto-tool 5.4.2 and
   xlrd 2.0.1 (added 2026-10-14, S6: encrypted SBI .xlsx, legacy HDFC .xls). trafilatura 2.0.0
   (added 2026-10-15, S38: article text for the knowledge graph). statsmodels 0.14.6 (added 2026-10-16,
   S39: cointegration tests, Newey-West; brings patsy). anthropic 1.15.0 (added 2026-10-17, S44: the A7
   research analyst, only in `agents/analyst.py`, behind the egress gate and the investor's budget). fastapi 0.159.1 and uvicorn 0.54.0 (added 2026-10-22,
   S54: the dashboard, 127.0.0.1 only). Planned, each pinned and recorded here when added: python-telegram-bot only if Telegram
   commands are ever wanted (send-only uses `requests`, PLAN §10 A2); graphify not adopted (S57, PLAN A11: a Claude
   Code skill for code folders, it sends documents to Claude; the system's own graph is cleaned instead);
   torch/transformers/peft only in `.venv-train`: pinned 2026-10-18 for S47 pass 2 (`tools/qlora_setup.ps1`) as
   torch 2.14.1 (CUDA 13.0 build), transformers 5.20.1, peft 0.21.2, bitsandbytes 0.50.2, accelerate 1.15.0;
   sentencepiece 0.2.1 and llama.cpp release v0.7.0 (its converter and gguf-py, in `PFLAB_DATA_DIR\tools`) added
   2026-10-19 to write GGUF Q8_0 (`tools/qlora_gguf.ps1`; Ollama on Windows cannot quantise a safetensors import);
   timesfm 3.0.2 added 2026-10-20 (S50; TimesFM 2.5 weights Apache-2.0, 3.0 non-commercial, which the investor accepts for
   his personal use). No backtesting frameworks;
   no lightgbm. Library output is still covered by our tests.
6. **Data lives under `PFLAB_DATA_DIR`** (`D:\portfolio_lab\data`, set in the
   user environment and `.claude/settings.json`); gitignored. Verify:
   `python -c "from pflab.data import data_dir; print(data_dir().resolve())"`.
   The Portfolio Manager ledger lives in `PFLAB_PM_DIR` (`D:\portfolio_lab\pm`,
   gitignored): `pflab pm init`. Secrets: `%USERPROFILE%\.pflab\secrets.toml`.
7. **Engine tests pass unchanged:** `test_engine_*`, `test_lookahead`,
   `test_negative_control`, `test_measurement_fixes`, `test_accounting_audit`.
   Fix code, not those tests.
8. Money is float rupees; dates are `datetime.date`; long-format parquet,
   DuckDB for queries, pandas for logic. Tests are synthetic and fast.
9. No LLM-made numbers, no trading path, tax rows sourced and dated,
   estimates labelled (PLAN §1). Local drafts pass the guard (`llm/guard.py`); the API
   analyst's answers pass `analyst.only_sourced_numbers`; order "tickets" are text for
   The investor to enter himself (GTTs are orders: never placed).
11. **Models.** Local: qwen3:8b-q8_0 (agents: routing, guarded answers, briefs) and
   nomic-embed-text, both installed once and kept (never delete them). API: Claude Opus 5.5,
   the analyst for all research and analysis, only through the doorbell in `agents/analyst.py`
   (public filings, results, news and market-data exports; the investor 2026-10-24: his portfolio may go too
   (holdings, amounts, weights, goals), his identity and banking details never: PAN, account/folio/client/DP numbers,
   bank account details, contact details, the statement files; priced first against the investor's monthly cap). Design of
   the agent layers and the brain: `docs/BRAIN.md`. Any change of model is a measured decision.
12. **Every new claim is a pre-registered study** (protocol committed before the run, rule in code);
   what passes is wired into the agents, what fails has no live feature.
10. When unsure whether something is wanted, stop and ask the investor.

## Layout
`src/pflab/` kept modules (`data`, `tax`, `portfolio`, `execution`,
`backtest`, `eval`, `signals`) plus packages added in S0 (`llm`, `risk`,
`monitor`, `fundamentals`, `theses`, `ledger`), then `agents` (S37 ask centre and its
read-only tools; S43 `tradecheck`, `memory`, `questions`; S44 `researcher`, `analyst`,
`analyst_compare`; S46 `event`, `thesis`, `quant`; S49 `memory_compare`; `inbox`; S53 `workshop` with its sandbox
`workshop_runner`), `conductor` (S53: `calendar`, `sync`, `situation`, `run`; the job that runs last in every tick), `hq` (S59 agent HQ,
PLAN A16: `egress`, `governor`, `llm`, `roster`, `board`, `reception`, `phone`, `watcher`, `messenger`, `readers`, `brain`
(shadow mode; S60 a tool loop, PLAN A18), `keeper`, `service`, S60 `tools`, `stocks`, `suggestions`, `redact`, `fetch`, S61 `models` (the slider), S62 `security`; runs
on the dashboard's threads or as the tick's `hq` job), `app` (S54 dashboard:
`launcher` from the desktop shortcut, `runtime` owns the store and runs the jobs, `views`, `server`, `static/`, `chat`
(AI centre modes), `research` (watch list, plan, price watches, check my idea)), `plan.buyzone` and `quant.technicals` (S54c), `learner` (S62, PLAN A22: `sources`, `claims`, `templates`, `live`, `record`, `run`), `kg`
(time-aware knowledge graph, S38), `plan` (targets, deploy, safety, guards, stock list,
S45 `advisor`, `trader`), `quant` (S40 Hawkes, S41 order book, S45 `execution_study`, S46
`drift`, `event_study`, S50 `vol_study`, S52 `tfm2`, `tfm2_prep`, `tfm2_eval`, `tfm2_live`), `llm` (guard, client, registry, eval12, S47 `tuning`, `adopted`),
`fundamentals.integrated` (BSE integrated XBRL results, standalone and consolidated), `data.nse_deals` and
`data.bse_institutions` (S48), `service` (jobs, Telegram outbox, S43 `bot`) and `risk.montecarlo` (S36). `tools/` holds
collectors, backfills and live runners (`overnight.ps1` the unattended night run; S52 `timesfm2_*`, `s52_unattended.ps1`
and `gpu_log.ps1` refresh and re-check the live TimesFM forecast; `qlora_setup.ps1` builds `.venv-train` (S64 replaces it
with a TimesFM-only setup); `s48_collect.py` backfills deals and institutional holdings; finished studies' runners were
retired in S63, their results stay in `docs/`;
`build_pm_ledger.py` rebuilds the ledger from the investor's documents, `kite_login.py`,
`split_study.py` and the other study tools); `docs/` holds PLAN, STATE, MIGRATED,
`docs/data/` findings, `docs/llm/` (model evaluations, tuning) and `docs/research/`
(pre-registered protocols and results). One file per document, in the repo. Run
Python and tests with `.venv`: `.venv\Scripts\python -m pytest -q` (about 2-4 minutes).
The PM store migrates itself (schema v34); take new ids with `store.next_id`, never a
DuckDB sequence (a killed run leaves a sequence behind its rows).

## The investor's data (never in git)
`PFLAB_PM_DIR` (`D:\portfolio_lab\pm`) holds the ledger and his own files: `sources.toml` (documents the
ledger is rebuilt from), `fd_holdings.toml`, `targets.toml`, `stock_list.toml`, `bank_rules.local.toml`,
`targets_notes.md`, `api_budget.toml` (analyst cap, `adopted`), `inbox/` (files he drops in; `inbox/market/`
for market-data exports the analyst may read), `analyst_compare/`, `reports/` (morning reports, overnight
logs and `.status`), `obsidian/`, `session_notes_*.md`. Raw statements sit in `new/` (gitignored). Secrets
live in `%USERPROFILE%\.pflab\secrets.toml`: Kite, Telegram, `[anthropic] api_key`, and `[passwords]` for
the statement files (The investor's choice, 2026-10-17; never print or echo them). Before every push, grep the
staged diff for amounts, names and ids, including formatted numbers (Indian grouping, e.g. 1,23,456) and test fixtures: docs,
tests and status notes must not carry his figures or his list's company names (git history was scrubbed
of them on 2026-10-17).

## Daily commands (once the system runs)
`collect_daily.py` (prices NSE/BSE, actions, dividends, surveillance, indices, VIX, GKG news), `pflab pm prices
--refresh`, `pflab pm networth | guards | alerts | propose | advise | deploy | simulate | fd show | tax --fy`,
`pflab ask "..."`, `pflab list add|remove|show`, `pflab kg build|show|text|viz|obsidian`, `pflab research
run|show|deep|digest`, `pflab analyst ask|notes|spend|submit|collect`, `pflab event "news"`, `pflab quant "idea"`,
`pflab thesis add|show|update|close`, `pflab drift`, `pflab inbox`, `pflab trades check`, `pflab questions`,
`pflab memory add|show|compare|index|find`, `pflab bot run [--once]`, `pflab llm tune <task>|report`, `pflab llm
qlora|harness <step>`, `pflab studies split|memory`, `pflab forecast run|show`, `pflab conductor status|run|sheet`, `pflab service run learner|security` (S62), `pflab workshop
ask|list|show|promote|rerun`, `tools/kite_login.py`, `tools/build_pm_ledger.py` after new
statements. Switch-on steps are the investor's: `docs/SWITCH_ON.md`. The desktop shortcut "Portfolio Lab"
(`tools\install_shortcut.ps1`) starts the dashboard and the jobs in one process; closing its window stops them; while it
runs it holds the store (CLI and the night run must wait).

## Running jobs
Anything over ~5 minutes (backfills, rebuilds, evaluations) is the investor's to run: give the
exact PowerShell command from `D:\portfolio_lab`, what it produces, expected
duration and how to tell it finished. Never trust a completion notice over
the process table and the artifacts on disk. The night run is
`powershell -ExecutionPolicy Bypass -File tools\overnight.ps1 [-DeepAll]` (unattended: timed steps,
internet steps first and retried, report in `PFLAB_PM_DIR\reports`); test a change to it with
`-DryRun`, `-Phases selftest` and `-Phases <name>` before handing it over. Only one process may
hold the PM store: close the bot and other `pflab` runs first.

## Working style
- Reports to the investor: 15 lines or fewer. Commit messages: 10 lines or fewer.
- Notes are findings plus decisions needed; no essays.
- Never re-read a file already read in the same session.
- Write code with the file tools, not shell heredocs: heredocs have turned `\b` into a backspace
  character more than once (S35, S37). After any scripted edit, grep for control characters.
- PowerShell: put multi-line or quoted Python (SQL with quotes) in a scratch script file, never in
  `python -c`; in scripts, do not name a function like a built-in alias (`Cli` is Clear-Item).
- New tools and models (TimesFM, Harness2, ...) are used where they can really help this system and configured to
  their full capability (inputs, outputs, covariates, fine-tuning), never as a narrow demo (The investor 2026-10-20); still
  pre-registered and judged on unseen data.
- Long GPU jobs: probe memory on the worst case first, checkpoint and resume, keep the screen on (Modern Standby cut
  the power twice), log GPU telemetry (`tools/gpu_log.ps1`). Runs on a mobile hotspot: retry with backoff, resume.
- The laptop GPU (RTX 5070 Ti Laptop, driver 617.42) drops off the bus at its top boost under sustained load ("GPU is
  lost", the laptop hangs; Ollama's 0xc0000409 load crashes look related). Cap the clocks first, from an Administrator
  PowerShell: `nvidia-smi -lgc 210,2100` and `nvidia-smi -lmc 405,9001` (a reboot clears them; `tools/s52_unattended.ps1`
  sets them itself when run as Administrator). After a loss: Start > Restart (not Shut down: Fast Startup keeps the
  driver state). Do not add stop-start temperature pauses: the load swings made it worse (2026-10-21).
- Before a GPU run, test the whole path on the GPU in minutes (a tiny train -> save -> reload -> forecast, a timing
  probe of real steps, the evaluation on the files so far without reading results): The investor wants no reruns.
- PowerShell `Get-Content`/`Set-Content` without `-Encoding UTF8` garbles UTF-8 (the morning report, STATE.md once):
  edit files with the file tools.
- Technical choices (models, methods, harness fixes) are Claude's to decide, recorded as dated
  amendments with a safe fallback; the investor's money, preferences and limits stay his to set.
- Each session works on branch `pm/sN-<slug>`.
- At each STOP: update `docs/STATE.md` and `docs/HANDOFF.md` "Start here",
  commit, and stop.
