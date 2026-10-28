# S64 build plan: finish the companion, add the maths, add the US, clean to one product, restart

## Kickoff prompt (paste into a new Claude Code session on Sonnet, once per session until Progress is all ticked)
```
You are building S64 of Portfolio Lab, the investor's personal portfolio system (real use, real money).
Read, in this order and in full, before anything else: CLAUDE.md, docs/S64_BUILD_PLAN.md, and the investor's
own words in docs/S64_KICKOFF_PROMPT.md (his intent; do not ask him to re-explain it).
Then look at the "Progress" section at the end of docs/S64_BUILD_PLAN.md and do the NEXT unchecked phase,
exactly as the plan says, on branch pm/s64-finish (Phase 0 creates it). Every choice is already made in the plan:
do not redesign, do not add features, do not skip steps. Stop to ask the investor only at the points marked ASK.
If something in the code differs from what the plan expects, take the safer option, write a dated one-line
amendment in Progress, and continue.
House rules: tests pass before every commit (.venv\Scripts\python -m pytest -q); the engine tests are never
edited; no model-made numbers; anything over ~5 minutes is the investor's to run (give the exact command,
what it writes, how long, how to tell it finished, then stop); paid calls priced first, inside the Rs 2,500 cap;
privacy grep before any push; no real amounts or company names from his list in code, tests or docs.
At the end of the phase: tick it in Progress with one line on what ran on the real path and its cost, commit
(10 lines or fewer), and report to him in 15 lines or fewer. If the context window still has plenty of room,
go on to the next phase; otherwise stop and tell him to start a new session with this same prompt.
```

## Context
The investor wants the system ready as soon as possible, built by a Sonnet session that only has to follow this plan.
His decisions (2026-10-26, do not reopen):
- Docker Desktop: yes. The learner's test counter: yes. Cointegration, mean reversion and CAPM: try them, through
  pre-registered tests.
- The US: the full sleeve, built before the restart. He holds no US stocks yet.
- The restart: wipe only his data (ledger, store, journal, memory, graph, his files in `pm\`) and keep the downloaded
  market data. He then hands his files to the system itself, not to Claude Code, and the system builds everything,
  asking him where it needs to.
- The clean: "delete from all of this pivot changes, all is just one system; get rid of what is not working. At the end:
  one repo, one finished product." That covers the research archive (the GitHub repo and `data\backups`), the old
  branches and tags, the archive hooks and rules, and failed features.
- TimesFM is removed. Forecasting is replaced by calibrated statistics with its own plan (Phase 3).
- Docs at the end: README (the first-run guide), CLAUDE.md, `docs/PLAN.md` (one plan), `docs/BUILT.md` (what is built),
  and `docs/STUDIES.md` (the pre-registered tests; CLAUDE.md rule 12 needs protocols in git before a run).
- After the restart the system runs for weeks and personalises itself, until his money comes in January or he says
  something like "I'm investing 50k this month".
- Claude Code stays for development only.
- He is on Zerodha, with Sensibull, Tijori, Streak, smallcase and Quicko on the same login. **Rule: we never scrape or
  reverse-engineer those apps or their private APIs.** We take their ideas and build our own versions from public data
  (NSE, BSE, SEC, FRED) and the official Kite Connect API. Files he downloads from them himself (Tijori sheets, Console
  or Quicko tax P&L) are welcome as inputs and cross-checks through the drop folder. Where each idea goes:
  - Sensibull: options analytics (5.7)
  - smallcase: theme baskets (5.4)
  - Streak: scanners (5.9)
  - Tijori: the company page (5.10)
  - Quicko: the tax centre (7.10)

## How the executing model works (read before every phase)
- **Phase 0 copies this file into the repo** as `docs/S64_BUILD_PLAN.md`. Each new session reads, in this order: CLAUDE.md,
  `docs/S64_BUILD_PLAN.md`, then the "Progress" section at its end. It then does the next unchecked phase.
- **One branch.** Everything is built on `pm/s64-finish` from `main`.
- **One commit per phase step**, 10 lines or fewer. At the end of each phase: tick its box in Progress, write one line of
  what ran on the real path, and commit.
- **Tests and the privacy grep.** `.venv\Scripts\python -m pytest -q` must pass before every commit. The engine tests in
  CLAUDE.md rule 7 are never edited. Run the privacy grep `.venv\Scripts\python -m pflab.hq.security` before any push.
- **House rules:**
  - New store changes are appended migrations: v35 and up in `src/pflab/pm/store.py` `MIGRATIONS`. An applied migration
    is never edited.
  - New ids come from `store.next_id`.
  - Point-in-time: rows dated <= as-of only.
  - ISIN is the key. US stocks use the pseudo-ISIN rule in Phase 6.
  - No model-made numbers: every price, amount and limit is computed by code, and models only write words.
  - Code is written with the file tools, never shell heredocs. After a scripted edit, grep for control characters.
- **Long runs and paid calls.**
  - Anything over about 5 minutes (backfills, study runs) is the investor's to run. Give the exact PowerShell command from
    `D:\portfolio_lab`, what it writes, how long it takes, and how to tell it finished. Then stop until he reports.
  - Paid calls on the real path are priced first and stay inside the Rs 2,500 monthly cap. Each phase states its
    expected spend.
- **Stop and ask the investor only at the points marked ASK.** Every other choice is made in this plan. A technical
  problem not covered here: choose the safer option, record it as a dated amendment line in Progress, and go on.
- **The dashboard holds the store.** If it is open, CLI runs must wait, so ask him to close it before running against
  the real store.

---

## Phase 0: set-up and rescue (before anything is deleted)
1. The plan is already saved as `docs/S64_BUILD_PLAN.md` (untracked, on `main`). Run `git checkout -b pm/s64-finish
   main` and commit it as the first commit.
2. **Restore F&O code from the bundle.** Read the old files out of
   `data\backups\portfolio_lab_full_history_2026-10-25.bundle` without checking it out:
   - Fetch it: `git fetch data/backups/portfolio_lab_full_history_2026-10-25.bundle refs/heads/pm/s62-learner:refs/rescue/s62`.
   - Read the F&O module: `git show refs/rescue/s62:src/pflab/data/fo_bhavcopy.py > src/pflab/data/fo_bhavcopy.py`, and
     its test if it exists (`git show refs/rescue/s62:tests/` and list it with `git ls-tree`).
   - Find the pairs code with `git log refs/rescue/s62 --diff-filter=D --name-only` for `tools/pairs_study.py` and
     `src/pflab/quant/pairs.py`. Read them with `git show <commit>^:<path>` into the scratchpad only, as a reference for
     Phase 2. They are not restored into the repo.
   - Delete the ref: `git update-ref -d refs/rescue/s62`.
3. **ASK the investor:** "Install Docker Desktop (WSL2 backend), start it once, and tell me when `docker run --rm hello-world`
   works." Go on with Phases 1-3 while he does it.

## Phase 1: the test counter (the learner stops fooling itself)
Today each claim passes on its own at t ≥ 2.0 (development) and t ≥ 1.65 (validation) (`src/pflab/learner/templates.py:33`,
`decide` at :88). Nothing counts how many tests have run.
1. **Protocol first.** Append "Amendment 4 (2026-10-26)" to `docs/research/learner_protocol.md` and commit it before any
   code:
   - Every test ever run is counted in one family, "all": learner claims, the S64 studies, and seed rows for the past
     studies.
   - The development bar becomes `t_needed(N) = max(2.0, Φ⁻¹(1 − 0.05/N))`, where N counts the tests in the family
     including this one (one-sided Bonferroni). For example, N=20 gives 2.81 and N=100 gives 3.29.
   - Validation stays at 1.65, because it is an independent replication.
   - The deflated Sharpe ratio (Bailey and López de Prado 2014) of the development series is recorded and reported, but
     does not decide.
   - Findings that passed under the old rule are re-decided under the new bar. Their live feature ends if they fail.
2. **Migration v35 `learn_tests_s64`:** `CREATE TABLE learn_tests (test_id BIGINT PRIMARY KEY, ran_at TIMESTAMP, family
   VARCHAR, origin VARCHAR, claim_id BIGINT, template VARCHAR, params_json VARCHAR, n_dev INTEGER, t_dev DOUBLE, t_val
   DOUBLE, sr_dev DOUBLE, dsr DOUBLE, threshold_dev DOUBLE, passed BOOLEAN, note VARCHAR)`. `origin` is one of
   learner, study or seed.
3. **New module `src/pflab/learner/counter.py`:**
   - `n_tests(con, family="all") -> int`
   - `t_needed(n) -> float` (scipy.stats.norm.ppf)
   - `deflated_sharpe(returns, sr_trials) -> float` (skew and kurtosis from scipy.stats; formula in the docstring with
     the paper reference)
   - `record(con, ...) -> test_id`
   - `seed(con)`: one row per historical primary test. Read the verdict and t from each `docs/research/*_results.md`
     (pairs, hawkes, dip_rule, timesfm, timesfm2, buyzone, height, market_state_vol, s48, split_study, early_warning,
     maths_audit, memory_compare, brain_shadow, and the learner's tested claims). The rule is idempotent: insert only if
     the note key is absent.
4. **Wire it into the learner:**
   - Change `templates.decide` to take `threshold_dev`.
   - `claims.test()` (`src/pflab/learner/claims.py:259`), just before `tp.run`, reads `n = counter.n_tests(con) + 1` and
     passes `t_needed(n)`. After the run it calls `counter.record`.
   - `register()` writes the N and the threshold in force into the protocol JSON.
   - Add `claims.reregister_stale(con)`. Editing `templates.py` changes `code_sha`, which invalidates every claim that is
     registered but not yet tested, so this function re-registers them (allowed: none has been tested). Call it once
     after this phase.
   - Add `claims.redecide_passed(con)`, which ends the live finding of any old pass that misses the new bar
     (`learner/live.put` ends the prior row).
5. **Show it.**
   - `learner/run.status()` shows "tests run N, bar now t ≥ x".
   - The dashboard's `/learn` board shows the same line.
   - The brain's `findings` tool output includes N and the bar.
6. **Tests:** synthetic pure-noise series over 200 trials, where the counter-adjusted rule passes at most 1 by chance
   (seeded RNG), while a strong drift series still passes. Also test the seed's idempotence and that `reregister_stale`
   leaves tested claims alone.
7. **Real path:** run `seed` on the real store and run `redecide_passed`. Report N and the claims affected. Cost Rs 0.

## Phase 2: the maths (CAPM, mean reversion as a process, cointegration)
Statistics are statsmodels 0.14.6 (already pinned). Reuse:
- `templates.nw_t` (`learner/templates.py:78`)
- `risk/shock_betas.monthly_returns`/`rolling_betas` (`:55`, `:64`)
- `data/indices.load` (NIFTY500_TRI and the 23 `SECTOR_<X>_TRI`)
- `data/sector_map.sector_at` (point in time)
- `data/panel.load`
- `data/index_membership.members_at`

**2a. The risk-free rate** (none exists today).
- Restore `src/pflab/data/fo_bhavcopy.py` (rescued in Phase 0). Check that it reads the 225 month-end files in
  `data\fo_bhavcopy\`.
- New `src/pflab/data/riskfree.py`:
  - `monthly(root) -> Series` gives the cash rate implied by the near-month NIFTY future: annualised basis plus the
    Nifty 50 dividend yield from `data/indices` valuations. This is the S39 method, labelled "estimate (futures carry)".
  - A gap falls back to 6.5% and is labelled "assumed".
  - Tested on a synthetic future and spot.

**2b. CAPM:** new `src/pflab/risk/capm.py`.
- `fit(stock_r, market_r, rf, min_months=36, window=60) -> dict(beta, beta_se, alpha_ann, alpha_t, r2, n, resid_vol)`:
  statsmodels OLS on monthly excess returns, HAC with maxlags = floor(4·(n/100)^(2/9)).
- `expected_return(beta, rf_now, erp)`: ERP is the Nifty 500 TRI excess mean over 2005-2021, computed once and labelled
  "estimate".
- `portfolio(con, root, asof)` gives holdings-weighted values.
- **Wire it in:**
  - `hq/stocks.facts` (`src/pflab/hq/stocks.py:260`) gets a part `"capm"`: beta, alpha with t, "alpha not different from
    0" when |t| < 2.
  - The brain's `stock_facts` tool schema adds "capm" and "process" to the allowed parts.
  - `risk/report.py` shows portfolio beta and alpha.
  - Suggestion scoring (`hq/suggestions.py`) adds a market-adjusted outcome: return − beta × market return. The brain's
    record and the learner's record half judge suggestions on it. An edge now means beating market exposure.

**2c. Mean reversion is a property of the process:** new `src/pflab/quant/process.py`.
- `adf(x)`: statsmodels `adfuller`, regression "c", autolag AIC.
- `variance_ratio(r, qs=(2,4,8,16))`: Lo-MacKinlay with the heteroskedasticity-robust z.
- `ou_half_life(x)`: AR(1) on levels, Δx = a + b·x₋₁, half-life = −ln2/ln(1+b) when b < 0, else None.
- `hurst(r)`: aggregated-variance method, reported with its n and labelled "noisy".
- `describe(series) -> dict` plus one plain sentence, e.g. "behaves like a random walk (ADF p 0.61; VR(4) 1.03, z 0.4)".
- `stocks.facts` part `"process"` runs it on the stock's log price and on its spread to its sector index.
- **It is a description, never a signal.** Tests: a synthetic random walk is not mean-reverting, and a synthetic OU with
  half-life 10 is recovered within ±30%.

**2d. Cointegration and co-movement** (your stocks, all stocks, sectors): new `src/pflab/quant/comove.py`.
- **Universe:**
  - his holdings, his stock list (`plan/stock_list.resolve`), and each one's same-sector Nifty 500 peers (point in time)
  - the 23 sector indices against each other
  - in Phase 6, the US sector ETFs
- **For each pair:**
  - the correlation of monthly returns over 5 years
  - Engle-Granger (`statsmodels.tsa.stattools.coint`) on 3 years of log prices
  - stability: the share of rolling 12-month windows (monthly step, 3 years back) with EG p < 0.05
  - the spread's half-life
- **For sector groups of 6 or fewer names:** Johansen (`coint_johansen`).
- **Multiple testing:** Benjamini-Hochberg at 10% within each run. Each run reports "n pairs tested, k significant, about
  m expected by chance".
- **Output:** `data/derived/comove.parquet`.
- **Weekly job:** `comove`, `Daily(10, 0)` on Saturday (pattern: `register(Job(...))` in `src/pflab/service/tasks.py`).
- **Brain tool `comovement`** (read: symbol in, its peers' correlation, cointegration and stability out, with
  `"source"`). Add it to `TOOLS` at the end, because tool order fixes the prompt cache (`src/pflab/hq/tools.py:586-679`).
- **Dashboard:** a "moves with" block on the stock page.
- **Labelled "description: relations break (S39: 9% stayed cointegrated)".**
- **Pairs trading stays excluded.** It needs shorting, and the system never trades.

**2e. Two pre-registered tests** (they go through the learner's machinery and the counter).
1. **Protocol first.** Write `docs/research/s64_reversion_protocol.md` and commit it before any run:
   - **Template `sector_reversion`** (long-only, usable for buy timing):
     - Each month: Nifty 500 members with at least 36 months of history.
     - Fit EG of the stock against its sector TRI over the prior 36 months. Keep names with EG p < 0.05.
     - z = today's spread residual / its formation standard deviation.
     - Signal: the bottom quintile of z (cheap relative to the sector).
     - Measured: next-month return in excess of its sector TRI, after `stocks.round_trip_pct` costs.
     - Periods: DEV 2010-2017, VAL 2018-2021.
     - Pass: claimed direction, `t_needed(N)` in DEV, 1.65 in VAL, mean above cost, at least 36 months each.
   - **Claim `short_term_reversal`:**
     - If the `cross_section` SCHEMA already has a 1-month return signal, register "1-month losers outperform next month"
       as a claim on it.
     - Otherwise add `reversal_1m` to the closed list in the same amendment.
2. **Code:**
   - Add the template to `templates.SCHEMA`/`run` and to `claims.py` (`READ_SYSTEM`, the `CLAIM` schema enum,
     `params_of`).
   - Run `reregister_stale`.
   - Register both claims by code (origin study), not from a paper.
3. **Run.** Running them takes more than 5 minutes on the full panel, so hand the investor
   `.venv\Scripts\python -m pflab.cli learner test --claim <id>` per claim (add a `--claim` flag to the CLI if missing).
4. **The result decides:**
   - A pass is wired in with `claims.wire` as a "cheap vs sector" line in `plan/buyzone` and the ready plans, at its
     tested size.
   - A fail gets no live feature, and `comove` stays descriptive.
   - The result goes into the results file.

**2f. "Extra features fit noise"** becomes a written rule:
- Learner Amendment 4 adds: a feature or covariate enters a model only if a registered comparison shows it beats the
  simpler model on unseen data, and that comparison counts as a test.
- The rule is copied into CLAUDE.md in Phase 8.

## Phase 3: forecasting without TimesFM
**3a. Remove TimesFM:**
- `src/pflab/quant/tfm2.py`, `tfm2_prep.py`, `tfm2_eval.py`
- `tools/timesfm2_*.py`, `tools/tfm_live_forecast.py`, `tools/s52_unattended.ps1`, `tools/qlora_setup.ps1`,
  `tools/gpu_log.ps1`
- the `.venv-train` mentions
- the TimesFM pins in CLAUDE.md rule 5
- the data folders `data\forecasts\live` and the weights under `PFLAB_DATA_DIR`: list them, then delete
- `vol_study.py`, if no live caller remains after this (check with grep)
- **Keep** what `tfm2_live` did through its baselines: turnover for ticket sizing (`plan/trader.py:48`,
  `plan/advisor.py:128`) and results ranges (`agents/researcher.py:134`, `agents/thesis.py:73`, `app/research.py:78`).
- **Move `bhav_files`** (used by `quant/technicals.py:56`) into `data/bhavcopy.py`.

**3b. New `src/pflab/quant/forecast.py`** (replaces `tfm2_live`; same public names where callers use them:
`turnover_estimate`, `turnover_fn`, `size_note`, `results_lines`, `run`, `score`, `show`).
- **Turnover and results:** the existing baselines, kept as they are.
- **NEW price ranges** for each holding and each name on the list at 21, 63 and 252 sessions, as q10, q50 and q90 of
  price:
  - draws from a stationary block bootstrap (block length 10 sessions) of the stock's own daily log returns over the
    last 3 years
  - the draws are rescaled by the ratio of EWMA volatility (λ 0.94) to the sample volatility
  - the centre drift is the CAPM expected return (2b), never momentum
  - reuse `hq/stocks._windows` and `odds` where they fit (`src/pflab/hq/stocks.py:157-197`)
- **Portfolio value ranges** stay in `risk/montecarlo`.
- **Migration v36 `forecasts_s64`:** `ALTER TABLE tfm_forecasts RENAME TO forecasts`. Values in the existing `model`
  column become `baseline`, `stats_ewma` or `stats_plain`.
- **Update callers:** rename all callers to `pflab.quant.forecast`; the `forecasts` tool (`hq/tools.py:264`) reads
  `forecasts`, with source "quant/forecast.py (calibrated statistics)".
- **Job:** `forecast` stays at `Daily(21, 0)`.
- **CLI:** `pflab forecast run|show` stays.
- **Dashboard:** the agent row (`app/views.py:281`) changes "TimesFM" to "statistics".

**3c. Calibration test.** Write `docs/research/s64_ranges_protocol.md` and commit it before any run.
- Monthly origins on Nifty 500 members: DEV 2010-2017, VAL 2018-2021, horizons 21 and 63.
- Pass for a method: coverage of the 80% interval within [75%, 85%] in both periods.
- The EWMA-scaled method replaces the plain bootstrap only if its pinball loss is better by a Diebold-Mariano HAC test
  with t ≥ `t_needed(N)` in DEV and ≥ 1.65 in VAL. It counts as a test.
- Live serving:
  - The passing method serves.
  - If neither passes coverage, ranges are shown labelled "not calibrated: covered x% in testing".
- Live scoring: each range is scored when due (in or out, pinball loss), and the rolling coverage is shown with the
  range and in the brain's `forecasts` tool.
- Running the test takes more than 5 minutes, so it is the investor's: give him the command.

## Phase 4: the Docker sandbox for the workshop
Today: model-written code passes an AST check, then runs as `python -I` in a subprocess with an emptied environment
(`src/pflab/agents/workshop.py:235-275`). The code's own comment at :137 says this is not a security boundary.

**Decision: plain Docker, behind one interface.**
- OpenSandbox is not adopted for now. It adds a server, and its fast microVM mode is Linux-only. Our jobs are
  single-shot, and `docker run --network none` gives the same isolation.
- The `Sandbox` interface lets OpenSandbox slot in later.
- Record this as an amendment in PLAN.

Steps (Docker Desktop must work: Phase 0 ASK):
1. **`sandbox/Dockerfile`:** `python:3.12-slim` plus numpy, pandas, scipy, statsmodels and pyarrow, pinned to the exact
   versions in `.venv` (read them with `.venv\Scripts\python -m pip freeze`). It runs as a non-root user and copies
   `src/pflab/agents/workshop_runner.py` to `/app/runner.py`.
   - Build: `docker build -t pflab-sandbox:1 sandbox`. It takes a few minutes, so run it yourself.
2. **New `src/pflab/agents/sandbox.py`:**
   - `class Docker`: `run(work: Path, time_limit) -> CompletedProcess` runs `docker run --rm --network none --read-only
     --tmpfs /tmp --memory 2g --cpus 2 --pids-limit 256 --security-opt no-new-privileges -v <work>:/work -w /work
     pflab-sandbox:1 python -I /app/runner.py /work`, with the timeout handled by `subprocess.run(timeout=...)`
     followed by `docker kill`.
   - `class Local`: today's subprocess path, unchanged.
   - `available() -> bool` (`docker info`, 5-second timeout, cached for 10 minutes).
3. **Use it.** `workshop.run` uses Docker when it is available. Otherwise it uses Local and marks the result
   `contained: False`. In that case it opens one Needs-from-you item a day, "Docker Desktop is not running; calculations
   run uncontained", through `agents/questions.ask`. `hq/security.py` reports the count of uncontained runs.
4. **Imports.** Add `statsmodels` to `ALLOWED_IMPORTS` (`workshop.py:139`); the image has it.
5. **Start Docker with the system.** `app/launcher.py` starts Docker Desktop if it is installed and not running
   (`C:\Program Files\Docker\Docker\Docker Desktop.exe`) and does not wait for it.
6. **Tests:** the Docker class is unit-tested with a fake runner. One test marked `docker` runs only when
   `docker info` works: a job that tries `socket` fails, and a normal compute passes.
7. **Real path:** run one workshop calculation through the brain's `order_calculation` path (Sonnet writer, about
   Rs 5), and check `contained: True` in `meta.json`.

## Phase 5: the companion's seven gaps, the replay bench, and the ideas from the Zerodha apps
One migration v37 `companion_s64` for this phase. It also creates `scans (scan_id, name, conditions_json, universe,
active, created_by, created_at, claim_id)` for item 9 and `theme_baskets (theme, isin, weight, since, until, status)`
for item 4.
- `hq_suggestions` gets the columns `price_low DOUBLE, price_high DOUBLE, max_buy DOUBLE, amount DOUBLE, wrong_if
  VARCHAR, wrong_price DOUBLE, stats_json VARCHAR, watch_id BIGINT`.
- `kg_hypotheses (hyp_id, made_at, pass_id, subject, cause, effect, evidence_json, status, check_by, decided_at, why)`
- `limit_proposals (prop_id, kind, key, value, evidence_json, status, proposed_at, decided_at, q_id)`, where `kind` is
  theme_limit, dip_reserve or pot_limit.
- `pot_ideas (idea_id, made_at, isin, symbol, reason, buy_below, exit_above, stop_below, amount, horizon_days, status,
  closed_at, ret, ret_vs_market)`
- `hq_passes` gets `tool_log_json VARCHAR`, if pass tool results are not stored already.

1. **Telegram only when it matters, plus morning and evening summaries.**
   - New `configs/telegram.toml` with `urgent = ["watch", "market_state", "guard", "security", "crash"]`.
   - `service/telegram.flush` (`src/pflab/service/telegram.py:105`) sends only urgent kinds at once. Other rows stay
     queued with status `held`.
   - `hq/messenger.send_now` follows the same rule.
   - New `src/pflab/service/summary.py`: `morning(con, asof)` and `evening(con, asof)` build one message from code:
     - the portfolio change
     - the market state
     - watches near their levels
     - new suggestions with their ranges
     - the count of open Needs-from-you items
     - the held rows since the last summary
     - the brain's latest note (words only)

     They mark the included rows sent.
   - Jobs: `summary_morning` at `Daily(9, 0)` and `summary_evening` at `Daily(21, 45)`, trading days.
2. **News recency and the Tijori ask.**
   - New `hq/recency.py`: `stamp(items, kind)` adds `age_days` and `stale`, using the policy news 3 days, filings 30,
     results 100, web results 7, undated = "undated".
   - Apply it in every read tool that returns dated items (readings, notes, graph_timeline, research_flags,
     web_search, fetch_cited).
   - Fix `readers.recent` (`hq/readers.py:267`) to filter on `published_at`.
   - One sentence added to the brain's system prompt: a stale or undated item is never cited as a cause of today.
   - New `agents/needs.py` `ask_company_detail(con, isin, what)`. Each company is asked at most once a month, through
     `agents/questions.ask`, worded "Please drop the Tijori sheet for <symbol> (missing: <what>)".
   - Call it from `stocks.facts` and the results readers when there are fewer than 8 quarters, no results, or no data.
     This replaces the fall-only ask (`service/tasks.py:196`).
3. **Cause hypotheses in the graph.**
   - Brain tools `record_hypothesis` (journal: subject, cause, effect, evidence ids, check_by ≤ 90 days) and
     `hypotheses` (read).
   - Each hypothesis also writes a graph edge `seems_caused_by` with the hyp_id (`kg/graph.edge`).
   - The keeper (`hq/keeper.py`) checks hypotheses that are due:
     - Where the cause is a macro series (BRENT, USDINR, US_SP500), it tests by code: the rolling beta of the subject
       to the series over the window, significant with |t| ≥ 2 → confirmed, else refuted.
     - Otherwise it puts the hypothesis on the brain's next pass to decide, with the evidence.
     - Past check_by + 30 days → expired.
   - The graph edge is closed on refute or expiry.
4. **Theme exposure, the dip reserve, the opportunity pot.**
   - **Theme map.** `configs/themes.toml` maps each theme to sector-map codes plus named ISINs, starting with AI/IT
     from the IT sector codes. Additions the brain proposes go through `limit_proposals` as `theme_member`, applied
     after his yes.
   - **`risk/themes.py`:**
     - `exposure(con, asof)` measures exposure with fund look-through (reuse `risk/exposure.exposures`, `:42`).
     - `propose_limit(theme)` is code: the largest weight w for which w × the theme index's worst 12-month historical
       fall ≤ 10% of the portfolio, capped at his equity target. The evidence is stored.
   - **Dip reserve.** `plan/reserve.py` `propose(con, asof)`:
     - The amount is the smallest liquid amount that, deployed at a 20% Nifty fall, keeps equity within target plus
       band, with the 35% fall-limit probability from `risk/montecarlo` unchanged.
     - The sources are his monthly amount and the FD tranches (`plan/deploy.schedule`).
     - The trigger is the existing `guards.market_dip` plus the Hawkes state.
   - **Opportunity pot.** `plan/pot.py`:
     - The limit is proposed by code at 5% of equity, capped by the rest of the targets.
     - Ideas come from the brain via a tool `propose_pot_idea` (reason in words; buy_below, exit_above and stop_below
       computed by code from `plan/buyzone.zone` and the forecast ranges; amount ≤ room in the pot).
     - IPOs: new NSE listings enter as ideas after 20 sessions of prices.
     - Scored at the horizon by code: ret and ret_vs_market (CAPM).
   - **Theme baskets (the smallcase idea).**
     - Each theme is a basket of named ISINs in `theme_baskets`, weighted equal or by market value capped at 10%.
     - The basket's own history is built from its constituents' total returns in the panel, point in time. That gives
       every theme (AI, defence, EV, ...) a drawdown history even where NSE has no index, and `propose_limit` uses it.
     - When his holdings in a basket drift more than 5 points from the weights he approved, a line goes into the
       evening summary.
     - The opportunity pot is shown as a basket.
     - New baskets and members are proposals, applied after his yes.
   - **All three go through Needs from you.** Applied only after his yes. Then the guards check theme limits and the pot
     limit (`plan/guards.py` adds theme_over_limit and pot_over_limit), and the advisor never proposes past them.
5. **Every suggestion has numbers from code, a watch, and cash watching.**
   - `record_suggestion` (`hq/tools.py:415`): the model gives kind, symbol, text, reasoning and horizon only.
     `suggestions.record` (`hq/suggestions.py:62`) fills the price numbers by code:
     - price_low and price_high from `buyzone.zone` low and high
     - max_buy = min(zone high, forecast q50 at 21 sessions)
     - wrong_price = forecast q10 at 63 sessions, with wrong_if worded from it
     - amount from `hq/stocks.order_size`
   - It then calls `app/research.add_watch(kind="below", level=max_buy)` and stores the watch_id.
   - A watch hit's message includes the ready ticket text from `plan/trader` (a text ticket; a GTT is never placed).
   - Register `check_watches` (`app/research.py:172`) as a tick job `watches`: `Interval(15, 9, 16)` plus `Daily(16, 0)`.
   - New job `idle_cash`, `Daily(20, 30)`: Kite cash (`agents/tradecheck`) of Rs 10,000 or more unused for 7 days or
     more → a line in the evening summary (not urgent).
   - After he buys, the holding is watched by the existing guards and the brain's events.
6. **Scenario chains.**
   - `configs/scenarios.toml`: oil +30% (BRENT), rupee −10% (USDINR), US crash (US_SP500 −20% in a month), each with
     its path:
     - factor → each holding through its 60-month `shock_betas.rolling_betas`
     - US → Nifty 500 → holdings through CAPM beta
   - New `risk/scenarios.py` `run(con, root, asof, name)` gives the rupee impact per holding and in total, with a ±2 SE
     range.
   - Brain tool `scenario` (read), and a block on the dashboard Risk page.
   - Labelled "from historical betas; a description, not a forecast".
7. **F&O data as information.**
   - Extend the restored `data/fo_bhavcopy.py` to daily files (NSE's UDiFF F&O bhavcopy since July 2024; the old
     format before), as a `collect_daily.SOURCES` entry, not critical.
   - Derived daily values: Nifty put-call OI ratio, total OI change, annualised futures premium, and stock OI for his
     holdings.
   - **The Sensibull ideas**, computed by us from the options rows of the same file, in a new `quant/options.py`:
     - implied volatility per contract: Black-76 on the future, solved with scipy `brentq`, with the risk-free rate
       from 2a
     - at-the-money IV for Nifty and for each holding that has F&O, and its 1-year IV percentile
     - max pain per expiry
     - the OI build-up class per stock future: price up with OI up is long build-up, price down with OI up is short
       build-up, price up with OI down is short covering, price down with OI down is long unwinding
     - NSE's public participant-wise OI file (client, FII, DII, pro), daily, as a new source
     - one line in the summaries, e.g. "Nifty IV 14 (30th percentile), PCR 1.1"
   - Added to the brain's `market_context` tool and the dashboard market tile.
   - No signal unless a later registered test passes.
   - Backfill: `tools/backfill_fo.py --start 2024-01-01`. It takes more than 5 minutes, so it is the investor's.
8. **Replay bench (the loop engineering).**
   - `pflab hq replay <pass_id> [--model M]` re-runs a journaled pass with tools answered from its `tool_log_json`
     (a call not in the log gets "not in replay").
   - It prints old and new notes side by side, and the cost.
   - Rule: a change to the brain's prompt or tools is replayed on the last 5 passes before it is merged.
   - The real-path check is one replay of about Rs 9.
9. **Scanners (the Streak idea).**
   - A scan is a list of conditions from a closed set, evaluated by code over the holdings, his list or Nifty 500:
     - price versus its 20/50/200-day average, and crosses of them
     - RSI(14)
     - distance from the 52-week high or low
     - fall from the all-time high
     - a volume spike (more than 2× the 20-day average)
     - P/E versus its own 5-year median
     - the CAPM alpha sign
     - the OI build-up class
   - Indicators come from `quant/technicals.py` (S54c), extended where a condition is missing. New `quant/scan.py`
     holds `evaluate(conditions, universe, asof)`.
   - Job `scans` at `Daily(20, 40)`, after prices. Hits on holdings or his list go into the evening summary, never
     straight to Telegram. A hit can be turned into a price watch with one click.
   - He can make scans on the dashboard, and the brain can make them with a tool `make_scan` (journal kind;
     information only).
   - **The difference from Streak: backtests do not fool him.** A scan used as a buying rule is tested only through the
     learner: it becomes a claim on a new template `scan_rule` (conditions → next-month return in excess of Nifty 500
     after costs), registered first and counted by the counter.
   - The dashboard shows "tested: passed / failed / not tested" beside each scan. An untested scan is labelled
     "information, not evidence".
10. **The company page (the Tijori idea).** "Business at a glance" from our own data:
   - 12 quarters of revenue, profit and margins from the BSE integrated XBRL (`fundamentals.integrated`)
   - segment revenue where the XBRL carries segment tags
   - the shareholding trend (promoter, FII, DII, pledge)
   - deals and insider trades
   - the CAPM and process facts
   - a peer table of the same-sector names with P/E, 3-year growth and margin, each with its rank
   - concall and investor-presentation filings from the BSE announcements, linked as graph documents
   - Operating KPIs we cannot get (stores, volumes, order book) come from his Tijori sheet. The item-2 ask opens when
     a sheet is missing.
   - The brain's `stock_facts` gets a part `"business"` with the same facts.

Tests for each item. The real path for the phase: one morning summary and one evening summary built from the live
store with Telegram on (he receives two messages), one suggestion end to end with its watch, and one scenario run.
Expected spend under Rs 50.

## Phase 6: the US sleeve (full)
1. **Facts first, sourced and dated, never from memory.**
   - Look each fact up on official pages and record it with URL and access date in a new `configs/tax/foreign.toml`.
     Rows:
     - the LRS limit per financial year
     - TCS on LRS remittances for investment, with its threshold
     - India's tax on foreign shares (long-term holding period and rate, short-term at the slab rate)
     - US dividend withholding under the DTAA (W-8BEN)
     - the foreign tax credit (Form 67)
     - Schedule FA (calendar-year reporting)
     - US estate tax for non-resident aliens (the threshold)
     - the SBI TT buying rate rule for converting gains (Rule 115)
   - Sources: incometaxindia.gov.in, rbi.org.in, irs.gov, Zerodha's support pages for GIFT City.
   - A fact without an official source is marked "unconfirmed" and is never used in a figure.
2. **Identifiers.** US instruments use the real ISIN when a statement shows one. Otherwise they use a pseudo-ISIN,
   "ZZ" + the 10-digit SEC CIK (12 characters; "ZZ" is not an ISO country, so it never collides with a real ISIN).
   - Migration v38 `us_s64` adds:
     - `instruments.market` (default 'NSE') and `instruments.currency` (default 'INR')
     - `accounts.currency` (default 'INR')
     - the table `fx_rates(date, pair, rate, source)`
     - the table `instrument_alias(alias, isin, since)`, to map a ZZ key to the real ISIN later
   - Record the rule as an amendment to CLAUDE.md rule 4.
3. **Data.**
   - **New `src/pflab/data/us_prices.py`.** It uses the Yahoo chart request pattern already in
     `data/global_markets.py`, with Stooq daily CSV as the fallback. It writes `data/us/prices.parquet` in the
     `PANEL_COLUMNS` layout (`data/panel.py`). Its universe:
     - the S&P 500 current constituents (company list from SEC `company_tickers.json` plus a public constituent list),
       and the CIK
     - SPY, QQQ and the 11 SPDR sector ETFs
     - names he adds to his list
   - **New `data/sec_edgar.py`:**
     - `companyfacts` (XBRL fundamentals) and `submissions` (8-K/10-Q/10-K filings with timestamps), point in time by
       acceptance time
     - it sends a User-Agent "portfolio-lab <his GitHub noreply address from git config>" and stays under 10 requests a
       second
   - **FX.** USDINR daily from FRED (exists) into `fx_rates`. The RBI reference rate (FBIL) is used for the tax
     conversion where available, labelled "estimate" when it stands in for the SBI TT rate.
   - **`collect_daily.SOURCES` gets** `us_prices` and `sec_filings`, not critical.
   - **Backfill:** `tools/backfill_us.py --start 2005-01-01`. It takes more than 5 minutes, so it is the investor's.
4. **Calendar and the brain's US hours.**
   - New `configs/us_market_holidays.toml`, sourced from NYSE for 2026-2027.
   - `conductor/calendar.py` gets `us_session(dt)` using `zoneinfo("America/New_York")` (09:30-16:00 ET).
   - Job `us_collect` at `Daily(7, 15)` IST.
   - The brain's scheduled pass `us_open` runs once per US trading day, 20 minutes after the open in IST. It runs only
     when he has US holdings, US watches or a fresh US event. It is governed like the others.
   - US filings (8-K) for the list and holdings reach the readers like BSE announcements.
5. **Ledger and tax.**
   - Lots for US instruments are kept in USD, with the INR cost at the dated FX rate. Gains are computed in INR per the
     sourced rule; FX gains are included.
   - TCS paid is recorded as a tax credit.
   - `pflab pm tax --fy` shows foreign gains, the foreign tax credit, and a Schedule FA draft (estimates labelled).
   - With no statements yet, there is no parser. The system asks for the first GIFT City statement when the account
     shows money. Until then, the dashboard has a manual entry form for a US buy or sell (date, symbol, quantity, USD
     price, charges, FX rate source).
6. **Targets and the sleeve decision.**
   - `risk/exposure.BUCKETS` (`src/pflab/risk/exposure.py:17`) gets `intl_equity`. Instruments with market != NSE/BSE
     classify there. `plan/targets.py` accepts it; it is optional, default 0.
   - The sleeve study uses `risk/montecarlo`: the US share at 0/10/15/20% in rupees, a joint block bootstrap of Nifty
     500 TRI and S&P 500 TR × USDINR, against his 35% fall limit, with expected long-run growth.
   - The result goes to Needs from you as a proposal with the table. The share is his yes.
7. **Agents on the US.**
   - `stocks.facts`, `comove`, `capm` (against the S&P 500 TR, risk-free from FRED's 3-month T-bill `DTB3`, already
     reachable through `data/macro.py`), the forecast ranges, scenarios, and the learner's `calendar` template work on
     US instruments.
   - US learner tests run only on ETFs (no point-in-time S&P membership, so stock-level tests would carry survivorship
     bias).
   - The US universe is labelled in the brain's tools.
8. **Tests:** pseudo-ISIN round trip, USD lot to INR gain, the US calendar around a DST switch, an EDGAR acceptance
   time used as point in time, and the bucket.
9. **Real path:** fetch 5 US names and the ETFs for 1 month, one EDGAR filing, FX. Cost Rs 0 in API spend. Then give
   him the backfill command.

## Phase 7: the system onboards him by itself (restart readiness)
Gaps found:
- `sources.toml` is hand-written.
- Bank statements need a manual account and file-name hint.
- Bank labels have no UI.
- IPO and opening-cost entries are TOML.

Fixes:
1. **`pflab setup secrets`** (and a Settings form on the dashboard) writes Kite, Telegram, Anthropic and statement
   passwords into `%USERPROFILE%\.pflab\secrets.toml` through `getpass`. It never prints them. Check first whether a
   command for this exists (grep `secrets` in `src/pflab/cli.py`), and extend it if so.
2. **Setup page `/setup` on the dashboard.**
   - Steps: accounts (broker, DP, banks, FDs), start date.
   - It writes `PFLAB_PM_DIR/sources.toml` from his answers, using the schema `tools/build_pm_ledger.py`/
     `ingest/sources.py` expects.
   - It then lists the files the system needs ("CAS for DP x from <start>", "bank statement for <bank> from <start>"),
     which also appear as Needs-from-you items.
3. **Classify statements by content, not file name.** `app/inbox.classify` sniffs the first page (pypdf text, the
   openpyxl/xlrd header row) for the bank name, the account's last 4 digits, a CAS header, Zerodha headers, and maps
   them to a known account. Unknown → Needs from you: "which account is this file?"
4. **Bank labels by the system.**
   - New `ingest/bank_labels.py`:
     - it groups unmatched lines by counterparty
     - it auto-labels transfers between his own accounts (equal amounts on both sides within 2 days) and broker
       pay-ins (matched to Console)
     - each remaining group becomes one Needs-from-you question with choices (salary, own account, family, spend,
       refund, other)
   - His answer writes `bank_rules.local.toml`, and the ledger dry-run re-checks.
5. **IPO and opening-cost entries:** dashboard forms that write `sources.app.toml` (the overlay already exists).
6. **"Add to the ledger"** stays his press.
7. **"I'm investing 50k this month"** in the AI centre or the chat goes to the brain, which calls `prepare_plan(amount)`
   (`hq/tools.py:533`). Test this path end to end with a synthetic store.
8. **`pflab pm reset`.**
   - It refuses while the dashboard holds the store.
   - It moves `PFLAB_PM_DIR` contents (store, journal, memory, graph tables, his toml files, reports, workshop) to
     `PFLAB_PM_DIR\..\pm_old_<date>`, and leaves `data\` untouched.
   - It prints what it moved. The restart guide tells him to delete `pm_old_<date>` once the new ledger checks pass
     (his memory rule: personal inputs go after calibration).
9. **Tests:** content classification on synthetic PDF/xlsx text, the own-transfer matcher, the `sources.toml` writer
   round trip through `ingest/sources`, reset on a temp folder, and the 112A export on a synthetic lot set.
10. **The tax centre (the Quicko idea)**, built on `tax/` and the `tax_plan` tool.
   - **Every rule, rate, date and limit is sourced from incometax.gov.in** with URL and access date in `configs/tax/`.
   - Per financial year:
     - realised gains by schedule: short-term under 111A; long-term under 112A with the 31-Jan-2018 grandfathering;
       slab-rate items
     - dividends and FD interest
     - the foreign rows from Phase 6
   - **Schedule 112A as a CSV** in the column layout of the official ITR utility template. Fetch the template, record
     its URL and version, and test against it.
   - **Advance-tax reminders** on the sourced due dates, with an estimated amount from realised gains, labelled
     "estimate".
   - **Harvesting suggestions** from February to March: loss harvesting, and booking long-term gains up to the yearly
     exemption. Each is computed by code from the lots and shown as a text ticket; it never trades.
   - **Cross-check:** when he drops a Console or Quicko tax P&L export, the system reconciles it per ISIN. Differences
     above Rs 1 go to Needs from you.

## Phase 8: the clean (one repo, one product)
1. **Code prune.**
   - Write `tools/inventory.py` (deleted at the end of this phase). It lists every module under `src/pflab` and
     `tools/`, and whether it is reachable from a live entry point:
     - `service/tasks.py` jobs
     - `hq/tools.TOOLS`
     - `app/server.py` routes
     - `cli.py` commands
     - `collect_daily.SOURCES`
     - `tools/overnight.ps1`
     - `tools/register_tasks.ps1`
   - **Delete** every module that is not reachable, except the ones a fresh install needs.
   - **Always keep these, even though no live entry point reaches them:**
     - backfill_bhavcopy, backfill_bse, backfill_shareholding, backfill_consolidated
     - build_index_membership
     - the GDELT BigQuery SQL and ingest scripts
     - s48_collect (rename it to `backfill_deals.py`)
     - backfill_fo, backfill_us
     - kite_login, install_shortcut, register_tasks, set_address_words, ocr.ps1
   - **Also delete** the live features of failed studies, and one-offs: `make_app_icon.py` (keep the icon file),
     `kite_depth_record.py` if no caller, and `llm/` evaluation modules with no live caller (eval12 is imported by
     agents, so check before deleting).
   - **Keep:** the backtest engine and its protected tests (CLAUDE.md rule 7), and `quant/hawkes.py` (it passed and is
     live).
   - Move the backfills into `tools/backfill/`.
   - Put the delete list in the commit message body (a count plus a top-level summary).
   - Fix the 5 broken doc references in code: `backtest/engine.py:794`, `data/etf_events.py`, `eval/artifacts.py`,
     `configs/targets.toml`.
2. **Docs.** The end state is exactly README.md, CLAUDE.md, `docs/PLAN.md`, `docs/BUILT.md` and `docs/STUDIES.md`.
   - **`docs/BUILT.md`** (what is built): each package with its one-line role, every job with its time, every brain
     tool, every data source with its backfill command, the store tables, the Settings switches, and the costs. It
     replaces STATE, HANDOFF, COMPANION, BRAIN, SWITCH_ON, `docs/data/*`, `docs/llm/*` and principles. Keep only the
     facts code relies on (e.g. the adjustment method, index membership rules).
   - **`docs/STUDIES.md`:**
     - one table of every pre-registered test (claim, protocol commit, verdict, t's, live feature yes/no)
     - the learner protocol with its amendments in full
     - the two S64 protocols in full
     - a section "new protocols go here, committed before the run"
   - **`docs/PLAN.md`:** the investor's intent (his words from `docs/S64_KICKOFF_PROMPT.md`, his decisions list), the
     frame (targets, the 35% limit, the cap, what the system may not do), the amendments condensed to one line each,
     and what remains (only the restart steps and "after a month in sync").
   - **README.md:** the first-run guide from a fresh clone: install Python, `.venv`, `pip install -e .`, Docker Desktop,
     `docker build`, Ollama models, `pflab setup secrets`, every backfill command in order with its duration, the
     shortcut, the tick registration, Telegram.
   - **CLAUDE.md:** rewritten to under 90 lines.
     - Drop non-negotiable 1 (the archive), and renumber.
     - Keep the rules and the library pins, without TimesFM.
     - Add the features-fit-noise rule.
     - Add the line "Claude Code is for development only; the system runs, learns and asks by itself."
     - Point to BUILT.md for the layout.
   - **Delete:** `docs/CHANGELOG.md`, `docs/MIGRATED.md`, `docs/SESSION_TEMPLATE.md` (fold its useful lines into
     CLAUDE.md), the `S6*_KICKOFF_PROMPT.md` files, `docs/research/*`, `docs/llm/*`, `docs/data/*` (after folding),
     and `docs/S64_BUILD_PLAN.md` (its Progress section moves to PLAN.md).
   - Run `grep -rn "docs/" src tools configs tests` and point every reference at the new files or remove it.
     `tools/build_index_membership.py` writes `docs/data/index_name_unresolved.md`; change that to write under
     `PFLAB_DATA_DIR`.
3. **Git and archives** (authorised by the investor in writing, 2026-10-26):
   - Delete `.githooks/pre-merge-commit` and `.githooks/pre-rebase`. Keep `pre-push` (the privacy grep).
   - After the merge (step 4): delete the local branch `master` and all local `pm/*` branches with `git branch -D`. List
     them first in the commit message. Delete the local tags `lock/*` and `shelved/*`.
   - Delete `data\backups\portfolio_lab_full_history_2026-10-25.bundle` (Phase 0 rescued what was needed; confirm
     `src/pflab/data/fo_bhavcopy.py` exists first).
   - **ASK the investor to run** these two commands himself, because deleting a GitHub repo is irreversible and needs
     his login:
     `gh auth refresh -h github.com -s delete_repo` then `gh repo delete <account>/portfolio_system_archive --yes`
   - Update Claude's memory files: the build state, the TimesFM memory, the US sleeve, and reinstall-from-clone.
4. **Merge.** Merge `pm/s64-finish` into `main` with a fast-forward, run the privacy grep, push `main`, and delete the
   remote branch if it was pushed.

## Phase 9: the restart (the investor's steps, written into README's last section)
1. Close the dashboard, then run `.venv\Scripts\python -m pflab.cli pm reset`.
2. Start the "Portfolio Lab" shortcut. Docker Desktop starts with it.
3. On `/setup`: secrets, accounts, start date.
4. Drop statements into `D:\portfolio_lab\drop`, or use the dashboard's Inbox. Answer Needs from you (accounts, bank
   labels, IPOs). Press "Add to the ledger" when the checks are green.
5. Register the tick (`tools\register_tasks.ps1`) and turn on Telegram in Settings.
6. Then nothing more: it runs, learns and asks. He tells it his monthly amount when the money comes. After the new
   ledger checks pass, he deletes `pm_old_<date>`.

---

## Verification
- **After each phase:** `pytest -q` passes, and the phase's real-path check ran and is written in Progress with its cost.
- **End to end before Phase 9**, on a copy of the store (`PFLAB_PM_DIR` pointed at a temp copy):
  - The tick runs once with every job (`pflab conductor run`): no failures, summaries built, the forecast stored, the
    comove parquet written, the watches job ran.
  - The brain does one pass that uses `stock_facts` (capm, process, business), `comovement`, `scenario` and
    `record_hypothesis`.
  - One scan evaluates and shows "not tested".
  - The options line (IV, PCR, max pain) is computed for the latest day.
  - The 112A CSV opens against the official template's columns.
  - `grep -rn "sensibull\|streak\|smallcase\|tijori\|quicko" src` shows no network calls to their domains (ideas only;
    the Tijori sheet stays a file he drops).
  - One workshop calculation runs `contained: True`.
  - `pflab learner` status shows N and the bar.
- **The clean:**
  - `git ls-files docs` shows exactly the 3 files under `docs/`, plus README and CLAUDE.md at the root.
  - `git branch -a` shows `main` and `origin/main` only. `git tag` is empty.
  - `grep -rni "research-archive\|timesfm\|tfm2" src tools configs tests docs CLAUDE.md README.md` returns nothing.
- **The restart dry run:** `pflab pm reset` on a temp copy, then `/setup` with synthetic accounts, then a synthetic CAS
  and bank file classified by content, then the bank-label questions open.

## Progress (tick as phases finish; one line each)
- [x] Phase 0 set-up and rescue (2026-10-26: branch pm/s64-finish; data/fo_bhavcopy.py restored and imports, 225 month-end files present; pairs.py/pairs_study.py saved to scratchpad only; rescue ref deleted; 1757 tests pass; Rs 0). Docker ASK is open: investor to confirm `docker run --rm hello-world` works. Amendment 2026-10-26: pytest needs `--basetemp <scratchpad>` here (default temp folder is access-denied); pairs files were not deleted at the s62 tip, read directly from it.
- [x] Phase 1 test counter (2026-10-26: protocol Amendment 4 committed first; migration v35; `learner/counter.py`; wired into `claims.test/register`, `reregister_stale`, `redecide_passed`; status line in `run.status`, the `findings` tool and the Learner agent row. Real store (backed up first): seed added 22 rows (21 studies + claim #13), N=22, next bar t >= 2.85, no old passes to re-decide, no stale registered claims; Rs 0. 1765 tests pass.) Amendments 2026-10-26: the repo has no `/learn` board or `learner` CLI command, so the line is shown through `run.status`, the `findings` tool and the Learner row of the AI centre; split_study, maths_audit and brain_shadow have no results file with a verdict, so they are not seeded (N is therefore not overstated); `tests/test_pm_store.py` and one stub in `test_s62_learner.py` updated for v35 and the `threshold_dev` argument (not engine tests).
- [x] Phase 2 maths (2a-2f); studies handed to the investor (2026-10-26. TOOLS (code only): `data/riskfree.py`, `risk/capm.py`, `quant/process.py`, `quant/comove.py`, template `sector_reversion`. AGENTS read them: `stock_facts` parts capm/process, brain tool `comovement` (appended last), suggestions scored on return - beta x market. PLOTS: `/api/maths` and the "maths" block on the Research page (rolling beta, spread z, who it moves with). Real path: rf 204 of 225 month-ends estimated from futures carry (median 6.4%); CAPM/process on real stocks; weekly comove table written (13 names, 528 pairs, 0 significant after BH: consistent with S39); claims #16 sector_reversion and #17 short_term_reversal registered (protocol committed first); Rs 0. 1780 tests pass. Studies run: see Phase 3 line.) Amendments 2026-10-26: no `learner` CLI existed, added `pflab learner status|seed|reregister|register-s64|test --claim`; `comove` job is `Daily(10,0)` every day but skips while its table is under 6 days old (Daily has no weekday choice) and is registered before the conductor (which must stay last); rf "now" is the median of the last 3 month-ends (one month's basis swings 5-10%); the mechanics smoke of `sector_reversion` ran on 2012-H1 (6 months of development, values seen); after registration `templates.py` must not change (code hash).
- [x] Phase 3 forecasting; calibration test handed to the investor (2026-10-26. TimesFM removed: `tfm2*.py`, `vol_study.py`, 4 `timesfm2_*`/`tfm_live` tools, `s52_unattended`, `qlora_setup`, `gpu_log`, their 5 test files, and the data folders `forecasts\live`, `research\timesfm`, `research\timesfm2` (the fine-tuned weights); `bhav_files` moved to `data/bhavcopy.py`; `ewma` and the turnover/results baselines to `quant/baselines.py`. TOOLS: `quant/forecast.py` (baselines kept; NEW price ranges q10/q50/q90 at 21/63/252 sessions, stationary block bootstrap, EWMA-scaled or plain, CAPM centre; scored when due; rolling coverage), `quant/ranges_eval.py` (the registered test). AGENTS read it: trader tickets, researcher/thesis lines, brain `forecasts` tool (+ coverage), Forecaster row "statistics". PLOTS: `price_fan` in the maths block. Migration v36 renames `tfm_forecasts` to `forecasts`. Protocol `s64_ranges_protocol.md` committed before code. Real path on the live store (backed up first): 12 listed/held names x 3 horizons x 2 methods stored, labelled "not tested yet"; Rs 0. 1755 tests pass. Calibration test: run.) RESULTS 2026-10-26 (run by Claude at the investor's request): claims #16 and #17 FAIL (dev t +1.47 vs bar 2.87; reversal went the other way, t -2.07), no live feature; ranges: stats_plain passes coverage and serves, EWMA does not; see docs/research/s64_reversion_results.md and s64_ranges_results.md. Claims were re-registered once (code hash changed by line endings, no test run in between). Amendments 2026-10-26: v36 only renames; old rows keep their old `model` value (NULL or a TimesFM label) because the applied migration cannot be edited, and the readers use the `baseline` column and accept NULL; `.venv-train` is not in the plan's delete list, so it is left for the investor to delete; the counter's seed keys `timesfm:*`/`timesfm2:*` and the v23 migration comment keep the old names (history) and are renamed in Phase 8; the `forecast` job kept `Daily(21, 0)`; horizon 252 is stored and scored live but not tested (stated in the protocol).
- [x] Phase 4 Docker sandbox (2026-10-26. `sandbox/Dockerfile` + `.dockerignore`, image `pflab-sandbox:1` built (864 MB, python:3.13-slim, libraries pinned to the .venv); `agents/sandbox.py` (`Docker`, `Local`, `available`, `pick`); `workshop.run` uses it, `Run.contained` -> `meta.json`; statsmodels allowed; one Needs-from-you item a day when uncontained; `security.uncontained` counts such runs; the launcher starts Docker Desktop without waiting; PLAN A24. Real path: one workshop calculation (public Nifty 500 drawdown, Sonnet writer, Opus independent writing) ran `contained: True`, both agree; Rs 9.93, month to date Rs 1,407 of 2,500. 1765 tests pass, the `docker` test ran the real container: no network, read-only root.) Amendments 2026-10-26: image base is python:3.13-slim (the .venv is Python 3.13 and the pinned numpy/pandas/scipy need it) not 3.12; the build context is the repo root with `-f sandbox/Dockerfile .` and a .dockerignore (the runner lives outside `sandbox/`); `PFLAB_SANDBOX=local` forces the subprocess and is set by the test suite except for `docker` tests; the brain's `order_calculation` only posts to the board, so the check called `workshop.ask` (the board worker's path) directly.
- [~] Phase 5 companion gaps + replay bench (2026-10-27, branch pm/s64-finish). DONE and tested: 1 summaries (configs/telegram.toml urgent/direct kinds, others held; `service/summary.py`, jobs summary_morning/evening); 2 recency (`hq/recency.py`, `agents/needs.py`: Tijori ask once a company a month); 3 hypotheses (`kg/hypotheses.py`, tools record_hypothesis / hypotheses / decide_hypothesis, keeper tests macro causes by code); 4 limits (`risk/themes.py`, `plan/reserve.py`, `plan/pot.py`, `plan/companion.py`, job `companion`; every proposal waits for his yes); 5 suggestion numbers from code + price watch + ticket + `idle_cash` + `watches` jobs; 6 scenarios (`risk/scenarios.py`, tool, dashboard block); 7 F&O (`data/fo_daily.py`, `quant/options.py`, collect_daily source `fo`, `tools/backfill_fo.py`); 8 replay bench (`hq/replay.py`, `pflab hq replay`); 9 scanners (`quant/scan.py`, job `scans`, dashboard panel, tools); 10 business at a glance (`hq/business.py`). Also built on his steer 'think like a trader': `hq/valuation.py` (P/E vs own range and market, volatility, rules of thumb as untested flags) and `plan/nudges.py` (Kite-style pre-trade warnings). NOT DONE: the `scan_rule` learner template (scans stay 'not tested'); segment revenue and 3-year peer growth (data not on record); real-path run of the two Telegram summaries with sending on (built from the live store and read, not sent). Real store migrated to v37 (backup data\backups\ledger_before_v37_2026-10-27.duckdb); the `companion` job has not run on it. Amendments: dip reserve proposes nothing while equity is below its band floor (the schedule is the dip money); tools after the 20th are non-strict (API limit); tell_investor messages are held for the summary; web_search/fetch_cited carry a recency warning, not per-item stamps.)
  RESULTS 2026-10-27 (run by the investor): rule claims #18-#24, 1 passed (below the 200-day average, an avoid rule), 6 failed (P/E above 50 narrowly, development t -2.86 vs bar 2.89); docs/research/s64_rules_results.md.
  UPDATE 2026-10-27 (his steer: no survivorship, start testing, correct itself): theme history is now free of survivorship and hindsight (published index, else the point-in-time industry group with delisted names; a named basket is never the history; defence limit 24.7% -> 16.5%); the `scan_rule` idea became template `rule_filter` (docs/research/s64_rules_protocol.md committed first): seven rules (P/E above 50 and below 15, near the 52-week low, below the 200-day average, volume spike, 40% below the high, RSI below 30), point-in-time P/E from the filed history, registered as claims #18-#24 with `pflab learner register-rules` (tests run 25, bar t >= 2.89); the learner's nightly cycle tests 3 a night; scans, the P/E flag and the brain's `findings` show not tested / test pending / passed / failed from the learner's decision; an approved theme limit is re-proposed (his yes needed) when new history moves it more than 20%. Still open: alpha-sign, build-up and RICH rules (no testable history), segment revenue, 3-year peer growth.
  (earlier note: BRAINSTORM ANSWERS 2026-10-26, the investor's: 5.7 options = plan only (IV, IV percentile, PCR, max pain, OI build-up class, participant OI, one summary line; NO hedge-cost calculator, NO IV-around-results); 5.4 theme baskets seeded with AI/IT, Defence, EV and auto-tech, and the brain may propose more (each basket and member applies only after his yes); 5.9 scanners ship with starter scans on his list (near 52-week low, volume spike, below the 200-day average, falling alpha sign), information only, labelled 'not tested'; order: Phase 4 then Phase 5, done. Docker confirmed working; `.venv-train` deleted by him. Start Phase 5 at item 1 with migration v37 `companion_s64`; month API spend so far Rs 1,407 of 2,500.)
- [~] Phase 6 US sleeve (2026-10-27). DONE and tested: 1 sourced facts (`configs/tax/foreign.toml`, 14 rows, `tax/foreign.py`: TCS, 24-month rule, 12.5%, dividend withholding 25%, fx date rule, estate USD 60,000; all `secondary` = official wording seen in search results or Zerodha's guide, none primary-read; unverified rows refused); 2 schema v38 (`market`, `currency`, `fx_rates`, `instrument_alias`, `us_trades`, `us_remittances`), pseudo-ISIN `ZZ`+CIK (`ledger/foreign.py`), CLAUDE.md rule 4 amended, bucket `intl_equity`; 3 data (`data/us_prices.py` Yahoo, `data/sec_edgar.py` with point-in-time facts, collect_daily sources `us_prices`, `sec_filings`, `tools/backfill_us.py`, job `us_fx`); 4 calendar (`conductor/us_calendar.py`, NYSE 2026-27, DST-exact IST times, brain pass `us_open`); 5 ledger (dollar trades, FIFO lots, gains in rupees with the sourced tax, CLI `pflab us`, dashboard panel); 6 sleeve study (`risk/sleeve.py`, proposal to Needs from you, the share is his yes, targets.toml stays his); 7 agents read US closes, the picture has `us_sleeve`. NOT DONE / BLOCKED: SEC refused the request (403): it needs a real contact in the User-Agent and the investor chooses that contact (`[sec] user_agent` in secrets.toml); so no CIKs, no EDGAR filings and stocks are keyed `US:SYMBOL` until it is set. No statement parser (no GIFT City statement yet). Real path: Yahoo SPY, QQQ, XLK, AAPL, MSFT fetched, FX 13,482 rates into the live store (v38, backup data\\backups\\ledger_before_us_2026-10-27.duckdb). Sleeve study on the live target mix: a 10% sleeve moves the chance of a 35% fall from 20.5% to 18.1%.)
  (backfill handed to the investor: tools\\backfill_us.py)
  S65 UPDATE 2026-10-28 (Phase 6 finished as beta): `configs/features.toml` + `pflab/features.py` (beta feature `us_sleeve`: ON on channel `beta`, OFF on `stable` unless his Settings switch says so; settings key `features`, `/api/features`, a Beta features panel in Settings; the US panel, its entry forms (403 when off), the picture's `us_sleeve` (`beta_off`) and the brain's `us_open` pass follow it; data collection is not gated). The sleeve answer: `sleeve.parse_answer` reads 'yes 10 from February 2027', a yes without a share is asked once more, `sleeve.plan_now` spreads the amount over financial years under the TCS threshold (estimate, shown in the US panel and the picture). Dated Needs-from-you items (`agents/needs.deferred_items`, run by the `companion` job): foreign-tax primary check (2027-01-01 or the first remittance), SEC contact (2027-01-01 or a US stock by symbol), GIFT City statement parser (an inbox item of kind `gift_city`). SEC contact: his answer 2026-10-28 was "why do we need SEC?" -> not yet (funds need only Yahoo). Question #17 answered in the live store (backup data\backups\ledger_before_s65_2026-10-28.duckdb): the two unseen accounts are dormant, no FD or mandate on them. Rs 0 API spend. 1,919 tests pass.
- [ ] Phase 7 onboarding by the system
- [ ] Phase 8 clean, merge, archive deleted
- [ ] Phase 9 restart (the investor)
