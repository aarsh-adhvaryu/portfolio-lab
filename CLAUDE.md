# CLAUDE.md — instructions for Claude Code on this repo

`portfolio-lab` (package `pflab`) is the investor's **companion** for NSE equities (a small US sleeve in beta). It collects data, keeps its own paper book,
watches what he holds, thinks situations through, learns whether it was right, and answers him in a chat. **Claude Code is for development only: the system runs,
learns and asks by itself.** Read `docs/PLAN.md` (intent, rules and what remains), `docs/BUILT.md` (what exists: jobs, tools, sources, tables, switches), `docs/STUDIES.md`
(every test and verdict), `docs/RUNNING.md` (install, first run, updates, acceptance), `docs/s87_operator_notes.md` and `docs/s88_light_notes.md` (the operator and what it costs).
`README.md` is the front page.

## Two installations
- The **APP**: an install of a release tag in its own folder (`release.toml` sets its data and store folders). It runs his money's companion: dashboard, jobs, intake, Telegram, one process.
  The desktop icon "Portfolio Lab" starts it; it takes the newest tag at its next start.
- The **WORKSHOP**: this checkout, where Claude Code develops. It sends nothing outward and makes no paid call unless told (`pflab --live`, `pflab --paid`; `src/pflab/guard.py`).
  It holds nothing personal: no statements, no copy of his store. Never start the app from here on his data.

## What the system is (current design)
- **His money vs the system's book.** The app's ledger is the SYSTEM'S OWN account: his Zerodha holdings as the starting positions, a fake bank and broker with fake money, only the system's
  own events after (`ledger/system.py`). While `pm/system_account.toml` exists, never rebuild the ledger from statements. Kite is a read-only data feed. The paper book
  (`core/`, `paper/`) is a CORE (index, gold and international ETFs) plus a satellite `longterm` sleeve of picks, plus a US paper sub-book in dollars funded by a transfer from the rupee
  cash. Goal: beat the index after tax (Nifty 500 for India, S&P 500 in rupees for the US) without a deeper fall in a crash.
- **His real holdings, watched read-only (A89, 15 Nov 2026).** The app also WATCHES what he really holds, beside the paper book: India from Kite at most every 5 minutes (only the latest snapshot, table `mine_in_s89`; no history, no statements, no banking), US entered by hand (`mine_us_s89`; never `/api/us/trade`), and a watchlist of names he does not own (`watch_s89`, cap 25). The alarm lane checks them too. His money and the paper book never mix in a table, a total or a score. Nothing on those screens can trade.
- **Screens.** The redesigned screens (`app/static/s89/`: Home, Your money, Add and watch, Claude's book, Lab, Graph, Chat, Agents, Usage, Settings; the same pages stack at 390 px with a bottom bar) are at `/`; the old ones at `/classic` until the first week has passed. Pages read stored state: no model call on page load. Chat actions (watchlist, a US holding, an agent's setting) show a Yes/No card first (`oper/actions.py`).
- **Who decides.** The PROMOTED POLICY decides at every close and in the session (code sizes, applies the rails, fills and taxes; no committee, no per-trade approval). The strategist proposes
  the allocation inside code caps (longterm at most 60%, core at least 30%); the lab tests every policy like any claim; promotion needs the history within the index limits after tax on both
  sides and a probation slice. Selling is code (exit plans, the 12-month guard, thesis break); every sale is scored after tax against holding. Caps: a broad Nifty index ETF up to 60% of the
  book, any other ETF 35%, a stock 10%, a sector 25%. The picks sleeve (his Kite stocks plus the system's own picks, India and US) is scored against the index at 1, 3, 6 and 12 months;
  an opportunity reserve in cash is spent only by the thinking loop. The US book works from daily closes plus a 5-minute session loop when the laptop is open.
- **The thinking loop** (`think/`): NOTICE (code) -> UNDERSTAND (a model names a class, an option and a likelihood WORD from closed lists) -> OPTIONS (sell, trim, hold, freeze, wait, buy in parts,
  nothing) -> OUTCOMES (worst, likely, best in rupees, by code) -> DECIDE inside the rails by a registered rule -> SCORE at 5, 20 and 60 sessions, calibrate the words; if the rule trails "do
  nothing" after tax it turns advisory. At most 3 cases a day, a bet may lose at most 1% of the book in its worst case, no new money unless the worst case fits. The daily desk is a working
  session after the Indian close and one in the US morning; the weekly introspection (`oper/introspect.py`) writes candidates for new studies, never a live change.
- **The alarm lane** (`think/alarm.py`, every 15 minutes): fast headlines and the company's own filings on what the book is exposed to. RED is heard on Telegram before any model reads it,
  new buying is frozen by code, a case opens and is thought through at once outside the daily cap. An unconfirmed headline never sells by itself. Latency is measured (20 minutes to heard,
  30 to a decision). After a gap the backlog comes first and the loop's rule is replayed as a ghost record (`think/fastforward.py`), scored apart.
- **The chat is the entrance** (`entrance/`, `oper/`): one conversation for the laptop and Telegram (`/new` starts a new chat everywhere). The intake acknowledges within 2 seconds and never blocks
  the loop. Every message and file passes the local screen first (`entrance/screen.py`): identity numbers masked, a personal record refused. What it passes to the loop goes through two doors
  only: evidence (into the graph with source "you" and the time received) and standing instructions (`hq/rules.py`: pause_buys, hold_name, no_new_names, cash_floor; a rule may only tighten;
  a money rule waits for his Yes). Two roads answer: **quick** (`oper/light.py`: its own short prompt, five small tools, at most 4 turns, the last 6 messages plus a code-made summary, about
  5,000 tokens) and **full** (a Claude Code session in the operator's own folder `<PFLAB_DATA_DIR>/operator/` with the system's tools in process, its own skills and subagents; the session is resumed
  by id per chat and starts fresh past 60k tokens of history). `oper/pathrouter.py` chooses by rules, no model call: one-word thanks get a fixed reply; files, links, "look into / study / backtest /
  compare / stress / simulate / move together / build: / fix / add a skill or tool" and `/full` go full; a quick answer that needs more hands over once. Every reply shows its road and tokens.
- **Self-fixing with his Yes** (`oper/build.py`): a new Problems line, "build:" / "fix", or the operator's `request_build` opens a build in its own git worktree on `fix/<date>-<slug>`; it ends in one
  Yes/No card; Yes merges onto origin/main, tags and pushes; No changes nothing; at most 2 a day. Nothing is merged or pushed without his Yes.
- **Knowledge graph and memory** (`kg2/`, `think/recall.py`) update themselves; the graph switches ON only when its nightly audit passes; what the system knows is read by every decision.
- **Collectors and the clock.** The system runs whenever the app is open. On open it catches up first (every missed session's data and scoring, point-in-time), then works by the clock's MODE
  (`pre_open`, `session`, `post_close`, `deep`, per market) and its own agenda, never by job times. A closed laptop is normal, never an error: a gap is recorded as "off from X to Y". Honest limit:
  nothing on a closed laptop can watch.

## Non-negotiables
1. **Point-in-time.** A feature at date M uses only rows dated <= M. Announcements use the dissemination timestamp; a filing with no release time is used from the next trading day's open.
2. **The 2022-2025 period is spent** (live use loads it): never evidence of anything out of sample.
3. **ISIN is the security key.** Never join on symbol without a date. A US instrument uses its real ISIN, else the pseudo-ISIN "ZZ" + the 10-digit SEC CIK, mapped in `instrument_alias` from a date.
4. **Prefer maintained libraries.** Pinned in `requirements.lock`: pandas, pyarrow, duckdb, numpy, requests, python-dateutil, pypdf, openpyxl, kiteconnect (read-only wrapper `ingest/kite.py`),
   casparser, PyYAML, langgraph, langchain-ollama, msoffcrypto-tool, xlrd, trafilatura, statsmodels, fastapi, uvicorn, and `claude-agent-sdk` (imported ONLY in `llm/claude_plan.py`). The older
   `anthropic` and `openai` packages are imported only in `llm/vendors.py` and are unused while the plan engine is in use. A new library or model enters only through a pre-registered comparison that
   beats the simpler alternative on unseen data (rule 10). Heavy ML (torch/CUDA) lives in the optional extra `.[ml]` and `tools/model_lab/`.
5. **Data lives under `PFLAB_DATA_DIR`, the store under `PFLAB_PM_DIR`** (gitignored; an installed app's `release.toml` wins). Secrets: `%USERPROFILE%\.pflab\secrets.toml` (never print or echo them).
6. **Engine tests pass unchanged:** `test_engine_*`, `test_lookahead`, `test_negative_control`, `test_measurement_fixes`, `test_accounting_audit`. Fix code, not those tests.
7. **Money is float rupees; dates are `datetime.date`;** long-format parquet, DuckDB for queries, pandas for logic. Tests are synthetic.
8. **Maths decides; models read, connect and explain.** No model-made numbers (every number in a reply is in a tool result or his words; unsourced sentences are removed by `analyst.only_sourced_numbers`);
   no trading path (Kite is read-only; a GTT is an order: never placed; order "tickets" are text for him); tax rows sourced and dated; estimates labelled. The strategist may name picks through `propose_picks`
   with a thesis, never a size, price or weight.
9. **Models.** **No paid API.** Every model call runs on his Claude plan through Claude Code (Agent SDK, `llm/claude_plan.py`, engine `claude_plan`, set by `[engines] force_in_use`; roles decide / read / quick =
   Opus 5.5 / Sonnet 5.5 / Haiku 5.5) through the one door `llm/gateway.py`. No API key is used by any path: the child process environment has every key variable blanked, only the servers we name are loaded
   (`strict_mcp_config`), the sign-in must be his claude.ai subscription or nothing runs (`analyst.make_client` refuses). Usage is tokens against daily budgets per purpose in `[operator]`
   (`budget_chat_light`, `budget_chat`, `budget_desk`, `budget_cases`, `budget_build`); a plan limit pauses the thinking and never errors the loop (the code-only parts go on). Local models: qwen3:8b-q8_0
   and nomic-embed-text (never delete); a further local model is added only by a measured decision. His portfolio may go to the model (holdings, amounts, weights, goals); his identity and banking details never.
10. **Every new claim is a pre-registered study** (protocol committed before the run, rule in code) and **counts in the learner's counter** (the bar rises with N). What passes is wired in; what fails has no
    live feature (its code is deleted, its study record stays in `docs/STUDIES.md`). A feature or covariate enters a model only if a registered comparison beats the simpler model on unseen data.
11. **Never change his targets, limits or the stock list:** propose, and wait for his yes. When unsure whether something is wanted, ask him.

## Working rules (his standing preferences)
- **Reports to him: 15 lines or fewer, plain words** (he is not a trader: say what a number means for him). Commit messages: 10 lines or fewer. Notes are findings plus decisions needed.
- **Technical choices are yours** (models, methods, fixes): decide, record a dated note with a safe fallback, do not hand him options. His money, preferences and limits stay his.
- **Run the real path yourself on a short sample first**; he wants no reruns from untested fixes. For anything over about 5 minutes (backfills, rebuilds): a sample first, then the exact PowerShell command
  from the repo folder, what it produces, how long, how to tell it finished; never trust a completion notice over the process table and the files.
- **The week check and the freeze.** The app checks its own first week (`service/week_check.py`, job `week_check`, fourteen criteria, counted from the first app open on or after Monday 2026-11-16) and tells him
  once on Telegram; from the day it passes there are 60 days of bug fixes only: no new feature, tool, model or screen unless he asks. A FAIL means fix first. The Problems list (`pflab problems`) is one line a week.
- **No internal spend throttle may stop a function** until the system is proved working (the strategist's budget-halving rules are recorded, not applied before 2026-12-09); the token budgets above are the
  limits. Every call is logged.
- **Only one process may hold the store:** close the dashboard and the bot before CLI work; back the store up before any migration or real-path write. The store migrates itself; take new ids with
  `store.next_id`, never a DuckDB sequence.
- **No real data in git:** grep the staged diff for amounts, names, ids (Indian grouping too) and test fixtures before every push; `.venv\Scripts\python -m pflab.hq.security push` must print
  "privacy grep: clean". Use generic names (AAAA, BBBB) in tests and docs, never stock-list names.
- Write code with the file tools, not shell heredocs (a heredoc turned `\b` into a backspace more than once); after a scripted edit grep for control characters. In PowerShell put multi-line or quoted
  Python in a scratch file, never `python -c`. Never re-read a file already read in the session.
- **Tests:** `.venv\Scripts\python -m pytest -q --basetemp <a folder in your scratchpad>` (the default temp folder is denied on this PC); the full suite takes 45-55 minutes. Tests must not write to the
  repo root (use `tmp_path`). Work on a branch `pm/sN-<slug>`; at each stop update `docs/PLAN.md` "What remains" and `docs/BUILT.md` if the system changed, then commit. Only a beta confirmed bug free
  goes to `main`: merge, tag `vYYYY.MM.DD[.N]`, push (the app takes the newest tag at its next start).
- Not built, decided: no MCP server of our own, no social-media sentiment agent, no agent framework (Hermes, OpenClaw, TradingAgents), no email path.
- The laptop GPU drops off the bus at top boost under sustained load: cap the clocks first from an Administrator PowerShell (`nvidia-smi -lgc 210,2100` and `nvidia-smi -lmc 405,9001`); after a loss use Restart.

## Daily commands
`pflab pm init|networth|guards|alerts|propose|advise|deploy|simulate|fd show|tax --fy N|reset`, `pflab ask`, `pflab list`, `pflab kg`, `pflab research`, `pflab learner status|test --claim N`,
`pflab service run|tick|status`, `pflab conductor`, `pflab hq`, `pflab us`, `pflab alarm status|run`, `pflab operator status|open`, `pflab engine list|test|use|shadow`, `pflab problems`,
`pflab setup secrets|status`, `pflab update [--check|--rollback]`, `pflab verify [--app F] [--report F] [--wake-check] [--live-model] [--offline]` (local acceptance of a candidate on a copy of the record;
`tools\verify_candidate.ps1` runs it from an isolated checkout), `pflab --paid|--live ...` (workshop only). Installing the app: `tools\install_app.ps1`, then `tools\seed_app.ps1` once;
`tools\install_shortcut.ps1` makes the desktop icons.
