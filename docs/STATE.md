# STATE — 2026-10-25

**S64 Phase 5 (2026-10-27, branch `pm/s64-finish`):** the companion's gaps wired on the real path, 1,827 tests pass. Telegram only when it matters plus 09:00 and 21:45 summaries; news recency and the Tijori ask; cause hypotheses in the graph; theme limits, dip reserve and opportunity pot (all proposals wait for his yes); every suggestion with a price range, highest buy, amount, wrong-if, a price watch and a ticket with Kite-style nudges; scenario chains (oil, rupee, US crash); F&O daily data with IV, PCR, premium, max pain and build-up (information only); the replay bench; scanners (starter scans, labelled not tested); business at a glance; valuation facts and rules of thumb for the brain. Open: `scan_rule` template, segment revenue, 3-year peer growth, Telegram real-path with sending on, the F&O backfill (his: `tools\backfill_fo.py --start 2024-01-01`), docs of the new tables in PLAN.

**S63 the clean (2026-10-25, branch `pm/s63-clean` from `pm/s62-learner`, PLAN A23):** the delete list shown first,
removals only per the investor's answers. 8,400+ lines removed (study runners, QLoRA/harness, OKF, order stubs, old
runner, whatif, theses lock, fo_bhavcopy, corporate_actions, issuer_events); tests trimmed to match; every CLI command,
the dashboard's and jobs' imports checked. Corrected from the first list after his questions: TimesFM 2 and its refresh
path kept; collectors kept and wired. His name: 0 in the repo (code, prose, the analyst's gate from his file; stored ids
renamed on this PC). His list: names, symbols, ISINs, BSE codes replaced by invented ones; privacy grep 0 lines;
pre-push hook. Wired and run on the real path: collect's new sources (deals 144 this month, FPI to 23 Oct with history
kept, macro 23 series, holdings for 12 names incl. Sep 2026; NSE insider feed stopped in May, BSE's comes with the
announcements); graph docs (46 deals, 604 holdings, idempotent); brain tools `who_is_buying`, `market_context`, `growth`
(31 tools, 19 strict); Portfolio growth split; `holder_event` template (events per kind found in both periods, no result
read); TimesFM refresh check (nothing due on this PC). Full history bundled: `data\backups\portfolio_lab_full_history_
2026-10-25.bundle` (verified). `pytest -q`: 1757 passed. His data not erased ("not yet").

**S62 the learner, the brain's web search, own-data insight to the brain, the security agent (2026-10-25, branch
`pm/s62-learner` from `pm/s61-slider`, PLAN A22):** The investor's answers first: sources both ways, everything inside the
Rs 2,500 cap, local wherever it can, limits Claude's. Store v34.
- `learner/` (job `learner` 22:00, board `/learn`): free sources (arXiv, OpenAlex, 6 blog feeds, `drop\learn`); the local
  model screens and reads (Haiku when its reply does not parse); a claim must quote its source and fit a coded template
  (cross-section price signals, filing event study, calendar) by its own words, and claim an effect exists; protocol file
  + hashes before the test; one rule (`docs/research/learner_protocol.md`, committed before any run; amendments 1-2 the
  same day before any test). Passes go live (`learned` findings: the brain's cached part, the `findings` tool with
  today's quintiles); fails get none. Record half: code rules at n >= 20 (Wilson, bootstrap Brier), lessons live, limits /
  dearer model / model-worded instructions asked under Needs from you; his yes applies.
- Own-data judgement ("should I", "too heavy in", "what next") -> the brain from Auto mode and Telegram, no rival; facts
  stay local then Haiku. Brain tool `web_search` (3 a day, slider `brain_web` = Sonnet, 2 searches).
- `hq/security.py` (each HQ round + job `security` 21:15, board `/security`): egress re-check, flows, privacy grep, tests,
  Sunday code review (slider `review`, Sonnet, his name and PANs redacted from the diff first). Reports only.
- Real checks (2026-10-25, ~Rs 49 in all; month Rs 1,398 of 2,500): 195 sources free in 72 s; 13 papers screened and 6
  read locally (~16-25 s each); the local model mapped claims at random -> amendments 1-2; claim #13 tested in 8 s on the
  panel (96 + 48 months): FAIL, no live feature. Insight question -> brain pass #15 (Rs 8.79, portfolio and ready-plans
  tools). Web tool: Opus Rs 23.65, Sonnet Rs 4.50 (both cited). Review Rs 11.08: 4 findings; the researcher's market
  series was not cut to asof in replays (fixed); the egress gate's year exemption (1900-2100 bare numbers) and the trial
  paths' default approval are for S63. **The security agent's first look back found real leaks** (his name in the
  answers' system prompt, 7 calls; the brain repeating his name from its tool names, 1 call; FD numbers in 6 Telegram
  alerts): fixed (prompt, tool names, name scrub, FD alerts by bank and amount, `llm.body_check` on the whole request);
  re-check after: 0 hits. `pytest -q`: 1820 passed. Privacy grep: his first name in 650+ doc/code lines (the repo's convention), 23 stock-list names
  in old tests/docs: S63's clean decides. 10 open reconciliation breaks reported.

**S61 the model slider (started 2026-10-25, branch `pm/s61-slider`, PLAN A19):** protocol
`docs/llm/s61_slider_protocol.md` committed before any run (amendment 1: the web set topped up to 6, found by the smoke
check). `hq/models.py`: 11 jobs, each with its choices, a measured default (`configs/models.toml`, written by the
scoring) and his Settings choice (new Models panel); every Claude model on the governed road. Wired: the ask centre
(routing on Haiku per step 1; answers drafted along the chain, local then Haiku by default, `Answer.answered_by`), the
analyst's research / web / workshop models, company notes, the brain and its rival (`brain.pair`), the gatekeeper,
fetch, and readers' materiality (a second verdict when moved off Haiku). Governor: `router` limits, `wording` raised.
Runner `tools/s61_slider.py` (live, materiality, web, notes, workshop, score, estimate). Smoke on the real path ₹8.5:
every arm ran; the ask centre answered through the Haiku router and the local model, checked. `pytest -q`: 1784
passed. **S61 DONE 2026-10-25:** The investor ran the registered runs; results `docs/llm/s61_slider_results.md`, defaults in
`configs/models.toml`: live answers local (22 of 38; cascade 23, Haiku 12, Sonnet 3), materiality Haiku (86.5% vs
87.0%, bar 90%), research notes Sonnet (55% share, half the cost), workshop Sonnet (10 of 10; its second writing is now
always the other model), web Opus (amendment 2: two attempts stopped at a budget I set too low, ~₹600 lost; the runner
had not recorded its spend: recorded and fixed). `model_compare.py` crashed on the unnumbered set (found by running Q1
first; fixed). Month spend ₹1,349 of ₹2,500. `pytest -q`: 1784 passed.
**Then (The investor, PLAN A20):** `answers = cascade` set in his Settings; Claude prompts carry the ledger's ids as letter
tokens (`hq/models.tokens` / `restore`): the run's blocked FD questions now reach Haiku (one checked on the real ledger,
₹0.06). Kickoff for the next session: `docs/S62_KICKOFF_PROMPT.md`.

**S60 the brain with tools (2026-10-25, branch `pm/s60-one-brain` from `pm/s59-agents-hq`, PLAN A18):** built and
checked on the real path. Store v33 (`api_calls.turn`, `hq_tool_calls`, `hq_suggestions`).
- `hq/tools.py`: 26 tools (16 read, 3 journal, 7 action), strict schemas (the API takes at most 20 strict tools: the 17
  with required inputs), checked again locally; results redacted (ids, name, PAN, e-mail, phone, UPI, IFSC) and passed
  through egress (the bare word "address" not read: filings name their offices); every call logged.
- `hq/stocks.py`: per stock drift (the advisor's own per-name share, cap, bands, trend), odds (10% moves with
  independent n; bootstrap touch chances of 5/10/20% falls at 20,000 paths; the zone) and edge (excess over the Nifty 500
  TRI after round-trip charges, n, t, `worth_a_study`, never a signal). Real ledger: 15 read tools in ~2 s, none withheld.
- `hq/brain.py`: manual tool loop, at most 8 turns, the governor before each turn (passes a day count first turns,
  `governor.check(turn=)`), last turn without tools, hand-off near 70% of the per-call input limit (state saved as memory
  kind `state`, superseding; code writes one if the brain does not), the next pass reads it. The single-call JSON path,
  `clean()` and `agents_view` are gone; `check_prediction` kept. Protocol amendment 1 (dated) records the change.
- `hq/suggestions.py` + keeper: ledger, quality by code at the time, answers (dashboard buttons; a trade seen in the
  portfolio counts as taken), scored at the horizon against the Nifty 500 TRI (declined on paper), record by kind with n,
  lessons in the brain's cached part. Keeper writes decisions' 30-day outcomes back to memory. `memory.correct` keeps the
  old row and the reason.
- `hq/redact.py`: tokens for identity and banking details, multi-line address blocks; `for_api` must pass egress. His real
  statements on this PC: 25 of 26 readable files pass after redaction, no ledger id left (one workbook unreadable by
  openpyxl). 45 kept lines share rare words with some redacted address line (likely the broker's and banks' offices, not
  provable): his address words in `api_budget.toml [egress] address` close it (the gate then replaces and blocks them).
  No S60 path sends statement text yet.
- `hq/fetch.py` (+ roster agent `fetch`): web fetch (`web_fetch_20250910`, one fetch, that host) of a cited URL only;
  BSE refuses Anthropic's fetcher (`url_not_accessible`), so BSE filings are read from the readers' local copy.
- Changed in place: `governor` (turns, `fetch` limits), `llm` (turn, `extra_in`), `egress` (`skip`, address words),
  `memory` (`state`, `correct`), `keeper` (suggestions, outcomes, root), `service` (keeper root), `roster` (`fetch`,
  brain wording), `views` + `server` + `app.js` (suggestions panel and answers, tool calls per pass), `plan/buyzone`
  (headline says "below its zone" under the bottom; verdict unchanged).
- Real checks (2026-10-25, trigger `check`, ₹28.57 in all): passes #12-#13 Opus 4 turns each, ₹10.67 and ₹7.87, 20-54 s;
  Sonnet rival #14 3 turns ₹3.41; cache reads working. The brain found two tool faults, both fixed: the overview's fall
  chance at 5,000 paths failed the small-numbers bar; a price under its zone read "in the zone". Fetch: a news page by web
  fetch ₹2.85, a BSE filing from the local copy ₹1.79. The Brain view rendered from real data in headless Edge.
`pytest -q`: 1775 passed (2026-10-25; the S60 and HQ tests re-run after the last fetch change).
**Then (The investor, same day):** no 14-day trial: `brain.SHADOW = False` (protocol amendment 2), actions capped a day
(`tools.DAILY`), the rival journal-only. Filings: nothing had run since 24 Oct 19:30 because the scheduled tick
"PFLab Tick" was never registered (the system ran only with the dashboard open); of his names' 256 filings in 60 days
only 16 had their attachment text kept (the readers look 3 days back). New free HQ part `texts` (`readers.keep_texts`):
every filing of a held or listed name keeps its text, 25 a round, 120 days back. Address words found by code from his
statements (`tools/set_address_words.py`, `redact.address_from`); the investor then gave his address and the words were set by
hand in `api_budget.toml [egress] address` (generic words, his city and a common first name left out): none left in any
of his 25 readable statements after redaction; the 15 read tools pass. The tick stays unregistered: The investor switches the
system on when the build is done. `pytest -q`: 1778 passed.

**S59 agent HQ (2026-10-24, branch `pm/s59-agents-hq`, PLAN A16):** `pflab.hq` built and checked on the real path.
Egress list (identity and banking never; portfolio may go), spend governor (4 limits per call, `over_limit` logged,
Settings brain off / economy / normal), 16 agents on one board (receptionist rules, orders from the dashboard's new
Agent HQ tab and Telegram: /calc /sim /web /research ..., 3-hop cap then the brain), Haiku readers (BSE attachments read
by page; figures kept only when their quote and number are in the document, page set by code), Sonnet for company notes
(batched) and the workshop's second writing, drop folder `D:\portfolio_lab\drop` -> inbox, reminders, the brain in
shadow (protocol `docs/research/brain_shadow_protocol.md`, committed before its first pass), memory keeper (predictions
scored vs base rates, decisions followed up). Store v32. Changed in place: `analyst` (named insert; batch priced at the
call's model), `researcher.deep_queue` (Sonnet), `workshop` (Sonnet second writing), `runtime` (hq and phone threads),
`tasks` (`hq` job), `settings`, `server`, `app.js`. Real checks: 6 Haiku readings ~₹0.4; one ordered brain pass
Opus ₹2.12 + Sonnet ₹1.13 in 19 s; 7 free orders through the board. Not yet real: Telegram polling inside the
dashboard, the drop folder with a real file, a gatekeeper-woken pass, the reflection.
`pytest -q`: 1755 passed (2026-10-24).
**Then (same day, the investor: the office look, a thorough paid check):** Agent HQ opens on an Office view (rooms of agents
around the brain, isometric SVG, live from /api/hq; no API cost) beside Tasks / Brain / Agents and spend. Every agent
ordered once on the live system. Fixed from that test: a NIFTY 50 question answered on the S&P 500 by a "reviewed"
measure (world series now checked against a named NSE index); web search returned no citations under the
dynamic-filtering tool, so every figure was dropped (basic `web_search_20250305` now; dates no longer count as figures);
a large company's ~2,000 articles crowded every filing out of research (`analyst.balanced`: filings, results, one
article per story); readers skip bare headlines and repeated stories; Portfolio answers worded by Haiku when the local
draft fails (numbers checked). Launcher: 10 s without a window before stopping (was 3), page reconnects in 1 s; no
self-restart while an agent works. Day's API spend ~Rs 89 (web 51, calc/research 14, Sonnet notes 11 real vs 62
estimated, reflection 6, brain 6, readers 1.4 for 52 documents). `pytest -q`: 1759 passed.
**Then (PLAN A17):** step 1 of the one-brain program measured (`docs/llm/haiku_vs_local_results.md`): Haiku takes
routing, guarded answers and extraction; materiality undecided (86% vs 79%, bar 90%); live answers local 8 of 12,
Haiku 7 of 12 (local stays first; the cascade answers 10 of 12). Next: S60 (`docs/S60_KICKOFF_PROMPT.md`).

**Portfolio Manager with the A7 agent team.** Research closed; archived on `research-archive`.
`pytest -q`: 1657 passed (2026-10-23). Nothing running (first overnight run finished 2026-10-18 01:14, all steps ok; reviewed
2026-10-18, fixes on `pm/s49-review-fixes`). Sealed 2022–2025 period is spent
(live use loads it). Last research verdicts live only in the archive's
`docs/STATE.md`; they are not rules here.

| area | state |
|---|---|
| Panel (8.03M rows, 4,380 securities, to 2026-09-16) | built, gitignored `data/` |
| BSE announcements 2010 → 2026-09-22 | complete, count-verified |
| Tax lots, costs, corporate actions | implemented, tested |
| Live collectors (`tools/collect_daily.py`) | exist; the investor schedules |
| Kite (`ingest/kite.py`, read-only allowlist) | built ahead (S4), fake SDK; no key; paper execution stays a stub. Console tradebook import reads .xlsx (2026-10-14), real tradebooks parse; IPO allotment rows set aside; contract-note parser (`ingest/contract_note.py`) built on a real note, levies attach to trades by trade_id; ledger lots now exclude STT from cost (s.48) |
| PM store (`D:\portfolio_lab\pm\ledger.duckdb`, migration 1) | done (S1): 22,146 instruments, 14,356 AMFI schemes |
| Secrets loader | done (S1); no secrets file yet |
| Tax rule tables (`configs/tax/`, `pflab.tax.rules`) | done (S2): 25 rows, coverage 2024-07-23 →; open items in PLAN §6 |
| Ledger core (`pflab.ledger`: events, FIFO lots, cash, replay) | done (S3), synthetic only |
| Prices/NAV/gold (`pflab pm prices --refresh`) | built (S8), real load ok to 2026-09-16; acceptance pending |
| Corporate actions on lots (`ledger/corporate_actions.py`) | built (S11), synthetic; acceptance pending |
| Bonds, SGB, physical gold, Estimate type (`pm/bonds.py`, `gold.py`, `estimate.py`) | done (S10), synthetic; no real bond/SGB rows loaded |
| Calculations (`pflab.calc`: valuation, returns, growth, whatif) | built (S14), synthetic; acceptance pending |
| Risk (`pflab.risk`: exposure, stats, report; `pflab pm risk`) | built (S15), synthetic; acceptance pending |
| Realised gains (`pflab.tax.gains`) | built (S12), synthetic + engine parity; acceptance pending |
| Income tax both regimes, advance tax, proposed sale by lot (`tax/income.py`, `proposed.py`, `pflab pm tax`) | done (S13): 25 tests, rows verified against Act text |
| MF look-through (`pm/lookthrough.py`, `pflab pm lookthrough`, openpyxl 3.1.5) | built (S16), synthetic workbooks; acceptance pending |
| Fundamentals PIT (`fundamentals/pit.py`, `pflab pm results`) | built (S24); live BSE pull verified on an unheld company; acceptance pending |
| IPO ledger (`ledger/ipo.py`: block, allot, release, list; blocked funds) | built (S19), synthetic; acceptance pending |
| Targets, steering, sale options, proposal log (`pflab.plan`, `pflab pm propose`) | built (S17) on synthetic targets; committed targets.toml has NO values; acceptance pending |
| Filings monitor and falls (`monitor/filings.py`, `falls.py`, `event_reaction.py`) | done (S20); alerts OFF until a watchlist exists |
| Service (`pflab.service`, `pflab service ...`, `tools/register_tasks.ps1`) | built (S9), mocked Telegram; nothing registered with Task Scheduler; acceptance pending |
| CAS import (`ingest/cas.py`, casparser 1.4.1) | built ahead (S5) on synthetic models; no real CAS yet; acceptance pending |
| Bank statement import (`ingest/bank.py`, `configs/bank_rules.toml`) | S6: reads SBI encrypted .xlsx and HDFC .xls; rules calibrated 2026-10-14 on real HDFC/SBI exports (own-name rules in `pm/bank_rules.local.toml`); acceptance waits on SBI Apr 2026-today |
| Fixed deposits (`pm/fd.py`, `ingest/sbi_interest_cert.py`, migration 14) | S33 DONE 2026-10-15: real deposits and FY2024-25/25-26 certificates loaded into the PM store; FD interest + TDS in `pflab pm tax`; `pflab pm fd show` ladder and renewal warnings |
| Dip-rule study and live safety (`docs/research/dip_rule_*`, `plan/safety.py`) | S34 DONE: pre-registered, chosen rule market-wide 10% dip + Fsafe; amendment 1 re-run 2026-10-16 keeps the rule (safety robust, return edge fragile) |
| Guards, surveillance, alerts (`plan/guards.py`, `data/nse_surveillance.py`) | S35 built: NSE ASM/GSM/ESM/IBC snapshots, indices updates, outbox alerts; Telegram configured; runner not registered |
| Monte Carlo and frontier (`risk/montecarlo.py`) | S36 DONE: block bootstrap + GBM, 5,000-mix frontier page, `pflab pm simulate`. S43 audit 2026-10-17 (`docs/research/maths_audit_s43.md`): falls measured on any day as well as month-ends, circular blocks, funds mapped by name |
| Agents S43 (`agents/tradecheck.py`, `memory.py`, `questions.py`, `service/bot.py`, migration 17) | built 2026-10-17, synthetic tests: trade check (Kite trades staged until the rebuild, holdings vs ledger, questions), memory (dated, superseded not edited), two-way bot (`pflab bot run`, the investor's chat only, read-only, never flushes held alerts); `tradecheck` job at 16:00 when Kite is logged in; nothing registered or started |
| Researcher S44 (`agents/researcher.py`, migration 18, job `research` 23:30) | built 2026-10-17: per list/held company, flags found and measured in code (material filings by BSE subcategory, frozen red-flag rules, results vs a year earlier, guard changes, news spikes), briefs rewritten when flagged or 30 days old, one digest; `pflab research run|show`, bot `/research`; filings alerts now include the stock list |
| API analyst S44 (`agents/analyst.py`, `analyst_compare.py`, migration 19, anthropic 1.15.0) | built 2026-10-17, OFF: doorbell (reuse a recent note, public graph documents only, egress gate on the question, priced before sending against the investor's cap, live for his questions, overnight batch otherwise, cited notes kept in the graph and memory); adopted only if the pre-registered blind comparison passes (`docs/research/analyst_comparison_protocol.md`); needs an API key |
| Model (`configs/llm_models.toml`) | 2026-10-17: qwen3:8b-q8_0 adopted for routing and guarded answers (amendment, `docs/llm/model_decision_2026-10-17.md`); guard bug fixed; round 3 (answers, production guard) registered for the investor to run; not downloaded yet, so ask answers facts-only until then |
| Maths audit (`tests/test_maths_audit.py`) | S43 2026-10-17: every number-producing agent recomputed a second way (closed forms, a deterministic drawdown chain, hand-worked portfolios, numerical integration); 5 findings fixed |
| Ask centre (`agents/`) | S37 DONE: bounded routing, read-only tools, S21 guard (opt-in cited-source numbers, strict dates) |
| Knowledge graph (`kg/`, `data/gdelt_gkg.py`) | S38 DONE: time-aware edges, filings, results, guards, GKG news, article text, 3D view, Obsidian vault, `pflab list add` |
| Pairs trading (`quant/pairs.py`, `data/fo_bhavcopy.py`, `tools/pairs_study.py`) | S39 DONE 2026-10-16: pre-registered study FAILS (t 1.82 dev, 0.71 val; 9% of pairs stay cointegrated); not used anywhere (pair command removed at the investor's request), code kept to reproduce the result; month-end F&O futures 2007-12 to 2026-08 on disk; statsmodels 0.14.6 |
| Hawkes processes (`quant/hawkes.py`, `tools/hawkes_study.py`, `configs/hawkes_market.toml`) | S40 DONE 2026-10-16: market crash clustering passes the registered test; market state calm/elevated/high (amendment 1, the investor) in guards, propose and ask, one message per state change (held); dip rule unchanged (wait test failed) |
| Order book simulator (`quant/lob.py`, `ingest/kite_depth.py`, `tools/kite_depth_record.py`, `pflab pm impact`) | S41 built 2026-10-16: engine, Hawkes flow, depth recorder (quote(), read-only), measured impact; no depth recorded yet |
| Model evaluation for the 12 GB GPU (`llm/eval12.py`, `docs/llm/model_eval_12gb_protocol.md`), list-add brief (`agents/brief.py`) | S42: round 1 run 2026-10-16/17, no model passed (recorded "not chosen"; best qwen3:8b q4); tool menu and deploy facts fixed; round 2 run 2026-10-17 (`model_eval_12gb_round2_results.md`): no model passed, recorded "not chosen"; `pflab ask` facts-only; the gap goes to S47 |
| Height-of-the-ride study (`tools/height_study.py`, `docs/research/height_*.md`) | 2026-10-16: pre-registered; FAILS (big falls were less common after expensive/stretched/calm months); nothing added live |
| Early-warning study (`tools/early_warning_study.py`, `docs/research/early_warning_*.md`) | 2026-10-16: pre-registered; FAILS (India VIX, US overnight fall, FPI selling, US VIX together gave no warning of first falls); US VIX jump alone consistent but found after the fact, not adopted |
| LLM infrastructure (`pflab.llm` guard/registry/budget/graphs/evalset, `pflab.knowledge`; PyYAML, langgraph, langchain-ollama pinned) | built (S21); 9B smoke passed; 27B registered, not pulled; acceptance pending |
| Results fixes and integrated filings (`fundamentals/integrated.py`, `tools/reparse_results.py`) | 2026-10-18: bottom-line net profit fixed (13 stored quarters re-parsed); NBFC/bank/new-listing results from BSE's integrated XBRL filings, dated by filing time; consolidated basis decided for when 8 quarters exist (`docs/data/bse_results_finding.md` §7) |
| S47 pass 1 / S49 adopted (`docs/llm/tuning_s47_results.md`, `docs/research/memory_compare_results.md`) | 2026-10-18: materiality v2 tags unmapped filings in the researcher; hybrid look-up in the ask centre's context tool; nightly tuning/S49 steps off |
| S47 pass 2, QLoRA (`llm/qlora.py`, `tools/qlora_train.py`, `tools/qlora_gguf.ps1`, `tools/s47_unattended.ps1`) | 2026-10-20: run complete, **NOT ADOPTED** (writing tied base at 0.78 < 0.85; research 0.57 < base 0.63); ~0.1 is noise at this size (`docs/llm/qlora_s47_pass2_results.md`); agents unchanged; S47 closed |
| Consolidated basis, safety amendment 2 (schema v22) | 2026-10-18: built; consolidated quarters stored for the list (6-7 each); verdicts stay standalone until 8 consolidated quarters (~Feb 2027) |
| Market state amendment 2 | 2026-10-18: drift traced to T1 chosen on the development fit; re-chosen on the frozen fit, KEEP, t1 0.37 |
| TimesFM study S50 (`quant/vol_study.py`, `tools/timesfm_*.py`) | 2026-10-20: registered and run; **FAILS** both questions for 2.5 and 3.0 (volatility worse than EWMA; fall ranking not significantly above Hawkes); nothing live. Exploratory: plain volatility ranks falls better than the Hawkes chance (2026: 0.63-0.66 vs 0.47) (`docs/research/timesfm_results.md`) |
| S51 market state vs plain volatility (`tools/market_state_vol_study.py`, `configs/market_state.toml`) | 2026-10-20: volatility WINS the ranking test on ten foreign indices (p 0.011, 8 of 10) but warns before fewer 2020-26 follow-on falls (68% vs 82%); the investor: Hawkes keeps the state, volatility chance shown beside it |
| S47 pass 3 harness search (`llm/harness.py`, `llm/adopted.py`) | 2026-10-20 run, results doc 2026-10-22 (`docs/llm/harness_s47_pass3_results.md`): research harness **ADOPTED** (0.745 vs live 0.097, n 165) and live in the doorbell's local-first answer (`analyst.local_answer`: `/deep`, `pflab analyst ask` when Opus is not rung); writing **not adopted** (0.765 < 0.85) |
| S52 TimesFM done properly (`quant/tfm2*.py`, `tools/timesfm2_*.py`, `tools/tfm_live_forecast.py`) | Run complete 2026-10-21; results 2026-10-22 (`docs/research/timesfm2_results.md`): Q5 turnover **T30C** and Q6 results **F25 revenue / T25 margin** pass, Q1-Q4 fail (nothing live). Live (store v23, `pflab forecast run|show`, job `forecast` 21:00): tickets' size line, researcher range/surprise flags, thesis lines, registered scoreboard + fallback; checked on the ledger (12 stocks, 9 companies, CPU 19 s) |
| S48 who is buying (`tools/s48_study.py`) | CLOSED 2026-10-22: arm 1 fails (2026-10-20); arms 2 (institutions) and 4 (deals) run after amendment 1, both fail; arm 3 deferred; nothing live (`docs/research/s48_who_is_buying_results.md`) |
| S53 conductor (`conductor/`, `agents/workshop.py`, `configs/market_holidays.toml`) | 2026-10-20: BUILT. Conductor job every 15 min (mode, wake-up sync check, asks as questions + one message, wake/closing notes, fact sheet `reports/situation.json/.md`), NSE 2026 holidays (past dates checked against our bhavcopy), daily `global` job (a download can no longer shrink a series). Calculation workshop: a model writes the maths as code (local model first, Opus through `analyst.write_calculation` if adopted), static checks, isolated sandbox, the writer's test case must pass, a second method must agree, kept beside the result as "not reviewed" until promoted. Real-ledger smoke test and a real local-model try wait for the GPU and ledger to be free |
| Workshop with Opus, gate fix, roster (A9) | 2026-10-22: Opus writes first (local = labelled fallback); egress gate no longer blocks years, dates, window lengths; acceptance 10/10 (~Rs 51, `docs/llm/workshop_acceptance_results.md`); PLAN A9 agent roster, autonomy, small-numbers rule |
| S54 dashboard (`pflab.app`, desktop shortcut "Portfolio Lab", store v24-v28) | 2026-10-23: DONE in five parts: command centre, portfolio, watch list with buy zones v1, AI centre (Ask / Web / Deep / Calculate), inbox and files (statements dry-run checked before the ledger is written, Windows OCR for screenshots), research and plans, simulations (to 100,000 paths, stress, frontier), knowledge-graph view, schedule presets and checklists, settings; all checked on real data |
| S55 ready plans (`plan/ready.py`, store v29, job `plans` 21:30) | 2026-10-23: DONE: the next FD tranche and the monthly amount (asked once) each have a plan kept current (versions, what changed, held message 7 days before), price ranges from the buy zones, reasons, tickets; the outer ring shown as an idea with its numbers |
| S56 escalation chain (`agents/escalate.py`, PLAN A10) | 2026-10-23: DONE: Auto mode local -> agents -> Opus with reasons; own data stops locally; live fall flags (S20 classifier); Tijori checked (`docs/data/tijori_check.md`), its exports local by default |
| S57 knowledge-graph cleanup (`kg/clean.py`, store v30, PLAN A11) | 2026-10-23: DONE: names merged by exact rules (asked when unsure), syndicated copies set aside, older analyst notes ended; nightly in the `kg` job; Graphify not adopted |
| S58 restart drills (`docs/research/s58_restart_drills.md`) | 2026-10-23: drill 1 7/10, four findings fixed, re-run pending; drill 2 (power cut) fixed and passes; 3 covered; 4 (full disk) fixed; 2026-10-24: Run now for every job, Opus notes submitted right after research while the app is open; re-run: two misses (news gap, no fresh note) fixed |
| S58b portfolio today and maths (PLAN A14) | 2026-10-24: Kite snapshots (v31) make the portfolio today; login and statements asked; reviewed measures first; new code needs an independent second writing; first real Kite snapshot to check |
| Buy-zone wait study (`docs/research/buyzone_wait_*.md`) | 2026-10-23: NOT ADOPTED (PLAN A12); the zone never says wait |
| Reusable calculations, Sonnet comparison (PLAN A13) | 2026-10-23: library live in the workshop; comparison protocol and runner ready, runs pending (The investor) |
| Switch-on (`docs/SWITCH_ON.md`) | checklist written; nothing switched on |
| Article relevance for the analyst and briefs (`kg.build.is_about`) | 2026-10-18: headline must name the company in its first 8 words; analyst gets the newest quarter and its year-ago per basis; brief results point in time |
| Backup of `PFLAB_PM_DIR` | **none** — job built (S9), disabled until a target is set |
| Portfolio Manager features (holdings import, NAV, tax report) | not started |

Plan: `docs/PLAN.md` (S0–S32). S0, S1, S2 done.
