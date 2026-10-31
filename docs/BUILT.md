# BUILT: what exists (as of S67, the completion cycle; the single reference for the system as built)

Rules and working style are in `CLAUDE.md`; intent and frame in `docs/PLAN.md`; every test and verdict in `docs/STUDIES.md`;
the first run in `README.md`. The job, tool and source lists below were generated from the code at the release.

## Two installations
| | APP (runs his money) | WORKSHOP (beta, development) |
|---|---|---|
| folder | its own (default `D:\PortfolioLabApp`: `app\` the clone, `data\`, `pm\`, `backups\`) | the repo checkout (`D:\portfolio_lab`) |
| code | a sparse clone at a release tag `vYYYY.MM.DD` (no `tests\`, no `docs\`) | any branch |
| `release.toml` | at the clone's root (gitignored): channel, tag, previous tag, backup, folder, data and pm paths; **wins over the environment** | none: that is what makes a checkout the workshop (channel `beta`) |
| sends | Telegram and paid calls inside his Rs 2,500 monthly cap, by his Settings | nothing, unless `pflab --live` / `pflab --paid` (paid counts against `dev_monthly_cap_rupees`, default 0); no tick registration |
| runs | the desktop shortcut, the scheduled tick, the overnight run | tests and the developer's commands |
| update | by itself at each start of the one desktop icon (`launcher.update_first` runs `pflab update`: store backed up first, newest tag, self-test, undone on failure); `--rollback`, `--check` | work on a branch (the beta); confirmed bug free: merge to `main`, run the suite, tag `vYYYY.MM.DD[.N]`, push |
Libraries: the app installs `requirements.lock` (the exact versions the tests passed on; a test keeps it equal to the workshop's .venv). The monthly API cap is one for both installations (the app carried the workshop's month). Beta features are listed in `configs/features.toml` (start: `us_sleeve`): off in the app unless his Settings switch turns them on, on in
the workshop; their data collection always runs. Code: `release.py`, `guard.py`, `features.py`, `update.py`; scripts `tools\install_app.ps1`,
`tools\seed_app.ps1`.

## Packages (`src/pflab/`)
| package | role |
|---|---|
| `data` | collectors and loaders: NSE/BSE bhavcopy, corporate actions, dividends, surveillance, indices, VIX, BSE announcements/shareholding/insider, GDELT, deals, FPI, macro, F&O (`fo_daily`), US prices (`us_prices`), SEC (`sec_edgar`), panel and calendar |
| `ledger`, `ingest` | event-sourced ledger (FIFO lots, income, fees), `foreign` (US dollar ledger); parsers: Console tradebook/ledger, contract notes, CAS, bank statements (spreadsheets, and PDFs in HDFC's layout checked against their own summary), SBI interest certificates, Kite (read-only); `sniff` (files by content, incl. deposit interest certificates and which saved password opened a file), `fd_summary` (a bank's fixed deposit summary: last four digits only); `pm/trace` (`pflab pm trace`, `GET /api/trace`: every balance with the file and date it comes from, fact or estimate, and the open differences); a day with no contract note takes its charges from Console's settlement (`contract_note.fees_from_settlements`, STT set apart at 0.1%); a Zerodha balance briefly below zero is carried to the next pay-in, never invented money; an IPO allotment is paid by the one bank debit of its amount (`ipo_payment_line`), a transfer, never spending; the knowledge graph holds his deposits (`kg.build.deposits`: one `deposit` node each, named by bank and maturity, never by number, `owns` from the term start) and what he owns is refreshed at once after the ledger or deposits job writes (`refresh_portfolio`), `setup_sources` (incl. `infer`: Setup proposed from the dropped files), `bank_labels`, `sources` (+ overlay); the inbox keeps files dropped before Setup and builds the ledger from all of them in one press (`inbox.apply_all`); `gmail` (read-only Gmail: statement attachments by content into the inbox, protected files opened in memory by saved password, an unopenable one asked about once); `mail_read` (what money emails SAY: the local model only, numbers kept only when the email states them, each fact checked by code against Kite and the record) |
| `tax` | rules (dated, sourced tables in `configs/tax/`), gains by schedule, income (both regimes), proposed sales, `foreign`, `quicko` (the pack: 112A CSV in the department's layout, reconcile) |
| `pm` | the store (DuckDB, schema v45), instruments, FDs (incl. `fd.entry`: a deposit from the Setup form, checked against the bank's maturity amount), bonds, gold, prices, today (net worth), `secrets` / `secrets_setup`, `reset` |
| `portfolio`, `risk`, `plan` | `prefs` (his preferences changed by the AI only when he asks, one exact edit, his yes, a backup); tax-aware sell-down; exposure, Monte Carlo, CAPM, themes, scenarios, sleeve study; targets, deploy, guards, safety, buy zone, ready plans, pot, reserve, nudges, trader tickets, advisor, `twin` (the scoreboard: four paper books with the same money) |
| `quant`, `fundamentals`, `monitor`, `signals`, `backtest`, `eval` | forecasts (price ranges, scored), Hawkes, options, scans, comove, process, event studies, `stress_hedge` (the stress gauge and forward test F5, paper only); BSE results, valuation; promoter/event monitors; the engine and its protected tests |
| `kg` | time-aware knowledge graph, hypotheses, memory/documents (the readers live in `hq/readers.py`) |
| `agents` | researcher, analyst (the only API doorbell), event, thesis, tradecheck, memory, questions, needs, inbox, workshop + sandbox (Docker: `network none`, read-only root, job folder read-only, a separate /out, capabilities dropped; **no fallback to the host**: with Docker missing a calculation waits; `probe()` proves containment; the uncontained `PFLAB_SANDBOX=local` is the workshop's and the suite's explicit setting and is refused in an installed app) |
| `hq` | the brain (tool loop, governor, egress gate, journal), `cases` (S67 investigations: question, evidence with times and stance, dependencies, calculations, decision, process review), `picture` (the one picture), reception, board (durable states: queued, running, waiting, retry, needs_approval, held, done, failed, dismissed; bounded attempts; held release/dismiss/expire), phone (Telegram), watcher, messenger, security, replay, valuation, plain words, models (the slider) |
| `learner` | sources, claims, templates, counter, rules, run, `forward` (live-only tests F1-F4, decided once at 24 months, `docs/protocols/s65_forward_protocol.md`): reads papers/blogs, registers tests, tests them, counts them |
| `verify` | `pflab verify`: the local acceptance of a candidate release (see `docs/PLAN.md`, S67) |
| `service`, `conductor` | jobs and the tick, Telegram outbox and bot, summaries, backup, health; the conductor (sync check, asks, closing notes; last in every tick) |
| `app` | the dashboard (FastAPI on 127.0.0.1): launcher, runtime, views, server, inbox, chat, research, sims, graph, settings, `static/`; `system` (the one picture: connectors coloured by their last real use, data freshness against the last session with failed refreshes shown as retained data, work in plain words, investigations, needs grouped, what changed since his last visit, readiness, where each thing is processed; `/api/system`, the assistant's `system_status` tool, the Command centre), `readiness` (what is reconciled and covered, known gaps, the resumable market-history backfill), `worker` (the same runtime and server with no window, for the verifier and tests of independent operation) |
| `llm` | local model client and registry, the guard, evaluation sets and adopted harness texts |

## Jobs (the tick runs what is due; the dashboard window runs them while open)
| job | when | what |
|---|---|---|
| collect | 19:30 weekdays | NSE bhavcopy, corporate actions, dividends |
| prices | 20:15 weekdays | collected bhavcopy into the store |
| nav | 22:45 weekdays | AMFI NAVs, IBJA gold |
| filings | every 15 min 08-22 weekdays | BSE filings for held and watched names; alerts |
| plans | 21:30 weekdays | ready plans for the next money (FD tranches, the monthly amount) |
| forecast | 21:00 weekdays | price ranges, turnover for tickets, results; scored when due |
| kg | 23:00 weekdays | knowledge graph: portfolio, filings, results, guards, GKG news, article text |
| analyst | 01:00 daily | API analyst: collect last night's batch, submit today's queue |
| research | 23:30 weekdays | material changes, briefs, digest |
| tradecheck | every 15 min 08-22 | Kite holdings, funds, today's trades: differences from the ledger asked |
| ledger | every 15 min, and a minute after a statement arrives; once after an update that changed the statement readers (every file read again) | his record builds itself: accounts set up from the files if nobody did, every statement read into one ledger and written; what does not match is a named difference with what closes it (2026-10-30) |
| deposits | every 15 min when his deposit file or a bank deposit summary changed; at start when his deposit file came back | his fixed deposits: the register rebuilt from `fd_holdings.toml` and every bank's FD summary (`ingest/fd_summary.py`, checked against its Total row); one deposit per bank and last four digits, a later term is a renewal; valued from the bank's value when read, else from its terms (an estimate); a matured deposit with no closing is left out of the total and asked about once (2026-10-31) |
| guards | 20:45 weekdays | surveillance and safety checks on the stock list; dip and FD alerts |
| outbox | every 15 min weekdays | deliver queued Telegram messages (held until he switches Telegram on) |
| backup | 23:30 daily | copy and verify the ledger |
| global | 07:30 daily | world markets, US VIX, commodities, dollar |
| us_fx | 07:25 daily | USDINR into the store (US sleeve) |
| comove | 10:00 daily (weekly work) | correlation and cointegration with peers and sectors |
| summary_morning / summary_evening | 09:00 / 21:45 trading days | the two Telegram summaries |
| watches / watches_close | every 15 min 09-16 / 16:00 | his price watches against the latest price |
| idle_cash | 20:30 weekdays | Kite cash unused for a week |
| mail | 21:15 daily (statements come monthly, contract notes in the evening); at once on Connect and on a new statement password | read-only Gmail (`ingest/gmail.py`): new statement attachments into the inbox (checked, then your press); the first look reads a year (cold start); locked files asked once per sender (a password slot named after it); one item to approve the accounts in Setup; asks once to be connected; the workshop never reads mail |
| twin | 20:55 weekdays | the scoreboard (`plan/twin.py`): your book, the brain's suggestions on paper, equal-weight Nifty 500 (the bar), Nifty 500; the same money on the same days; values only until 60 sessions |
| companion | 21:10 daily | theme baskets and limits, dip reserve, opportunity pot (proposals wait for his yes); bank-label answers to rules; deferred US items |
| scans | 20:40 weekdays | saved scans (information, labelled by what the learner tested) |
| learner | 22:00 daily | papers and blogs to registered tests; three tests a night |
| security | 21:15 daily | what left the PC, flows, privacy grep, tests; weekly code review |
| hq | every 15 min | orders, drop folder, reminders, readers, the brain, memory keeper |
| backfill | hourly, only while sessions are missing | market history since 2012 fills itself in 90-second steps (newest first); readiness and known gaps updated; a source that is down fails the job |
| sandbox | 06:40 daily (when Docker is installed) | the containment probe in a real container; its result is the sandbox's colour on the screen and a failed probe blocks generated code |
| conductor | every 15 min (last) | sync check, asks, wake and closing notes, fact sheet |
The `us_open` brain pass (20 minutes after the New York open, once per US trading day) runs only with the `us_sleeve` flag on and US holdings.

A job whose result carries a non-empty `failed` ({part: reason}) is a FAILED run (`service/jobs.py`): the hq job's parts, the mail job's reading step and the backfill's source.

## The brain's tools (`hq/tools.py`; read = by code, journal = records, action = capped a day and journaled)
- **read:** picture (called first every pass), portfolio, stocks_overview, stock_facts, tax_plan, measure, simulation, forecasts, readings,
  graph_timeline, notes, memory_recall, journal, ready_plans, research_flags, price_history, quant, who_is_buying, market_context, growth,
  findings (what the learner tested), comovement, ipo_plan, scans, scenario, hypotheses, themes, system_status, mail_facts, cases, experiments.
- **journal:** record_prediction, record_suggestion, save_state, make_scan, record_hypothesis, decide_hypothesis, propose_pot_idea, open_case, case_evidence, case_close, frame_objective, propose_software_change.
- **action:** ask_investor, tell_investor, order_research, order_calculation, prepare_plan, correct_memory, fetch_cited, web_search, request_report, case_calculate, register_experiment, resolve_task, change_preference
  (only when he asks: his targets, stock list or API cap, put to him as one exact edit; his yes applies it to his file after a backup, `plan/prefs.py`).
The ask centre has the same system and email facts as tools (`agents/tools.py`: `system`, `mail`), bound to the runtime of the question, so the dashboard and the background (Telegram, the tick) answer "is everything working?" from one source; the chat's last turns and the open investigations reach the brain as events of its pass.
It never trades, moves money or changes targets and limits. Spend is governed by `hq/governor.py` (slider modes off / economy / normal); what may
leave the PC is decided by `hq/egress.py`.

## Agents and models (generated from `hq/roster.py` and the slider `hq/models.py`; the Settings slider can change any model below)
**19 agents on the board** (`hq/roster.py`; ask any by name on the AI centre, in Telegram as `/name`, or let the receptionist route). The dashboard's AI centre also lists
the 17 job-level agents (collector, filings monitor, portfolio keeper, risk manager, simulator, forecaster, researcher, watch list, analyst, knowledge graph, trade check,
conductor, workshop, outbox, backup, learner, security) with their last runs; under both sit the code modules in `agents/`, `plan/`, `quant/`.
| agent | model (measured default) | does |
|---|---|---|
| receptionist | rules, no model | routes what he says or drops |
| ask centre | local qwen3 8B (guard-checked); then agents; then Sonnet or Opus | answers questions; his own data never leaves the PC |
| web | Opus 5.5 + web search | public questions, cited pages only |
| research | Sonnet 5.5 (the doorbell) | deep research on a company from public documents |
| file analyst | local model, then research | reads files he provides |
| calculation | reviewed measures first; Sonnet 5.5 writes code, Opus 5.5 writes it again independently; both must agree | new calculations, run in the Docker sandbox |
| simulation, quant, memory, cleanup, graph, messenger, watcher | code | Monte Carlo and stress; pre-registered studies; decisions and scoring; graph tidying; reminders; the drop folder |
| portfolio | code; the local model words it | the portfolio today |
| readers | Haiku 5.5 | read every public document: materiality, figures, summary. An email-kind document goes only with the mail reader's clearance (a hash of the text it checked), redacted and passing the full identity check again at send time (never by kind alone); one that carries his own details stays on the PC and is recorded as withheld |
| cited-page reader | Sonnet 5.5 + web fetch | reads a page the system already cites |
| brain | Opus 5.5 with tools (Sonnet 5.5 as its journal-only rival) | looks, decides what matters, asks and tells him; never trades |
| learner | local qwen3 8B reads (Haiku 5.5 if its reply does not parse); Sonnet 5.5 words proposals | papers and blogs to tested claims |
| security | code; Sonnet 5.5 reviews new code weekly | what left the PC, flows, privacy, tests |
Other jobs on the slider: routing, materiality, extraction, gatekeeper (Haiku 5.5), notes (Sonnet 5.5, batched), brain_web (Sonnet 5.5), learner_proposals, review.

**The local model** is `qwen3:8b-q8_0` through Ollama (`llm/registry.chosen("general")`, never deleted) and `nomic-embed-text` for embeddings. It is used, always with the guard
(`llm/guard.py`: a draft with a number it cannot find in the facts is dropped and the facts are shown instead), by: the ask centre (guarded answers on his own data; routing is
Haiku by default), the portfolio agent's wording, the nightly company briefs (`agents/brief.py`), the inbox agent and "Read it" summaries of screenshots and files, the file analyst,
the learner's screening and reading of papers, the workshop as its labelled fallback writer, and `analyst_compare`'s local prompt; `nomic-embed-text` serves memory retrieval
(`memory find`, hybrid with word matching). It never produces a number and never sees anything outside this PC. Everything paid goes through `hq/llm.py` or the doorbell
`agents/analyst.py`, priced first, behind `hq/egress.py`.

## Data sources and how to build their history (all long runs are his)
Daily, by the `collect` job or `python tools\collect_daily.py [--days N] [--sources ...]` (`panel` keeps `panel\prices.parquet`, the adjusted prices every long-history reader uses, current by itself: new sessions appended, rebuilt whole in about 4 minutes when corporate actions or a late dividend change the adjustment, or monthly): bhavcopy, corporate_actions, bse_bhavcopy, surveillance,
indices, vix, gkg, dividends, panel, bse, gdelt, insider, deals, fpi, macro, holders, fo, us_prices, sec_filings.
Backfills, in `tools\` (each is resumable; every one takes more than 5 minutes): `backfill_bhavcopy.py` (NSE from 2004; `--from` for a slice),
`backfill_bse.py START END LOG` (announcements), `backfill_shareholding.py` (2010 on), `backfill_consolidated.py` (integrated filings of the list),
`backfill_fo.py --start 2024-01-01` (futures and options, participant OI), `backfill_us.py` (13 US funds, S&P 500 members, his US names),
`build_index_membership.py --all` (point-in-time Nifty membership), `ingest_gdelt_backfill.py` and the `gdelt_*_bigquery.sql` queries (news history,
BigQuery free sandbox), `backfill_deals.py --source deals|institutions` (deals and institutional holdings). Kite each trading morning: `python tools\kite_login.py`
or the dashboard button (read-only).

## Investigations, work and recovery (S67)
An investigation (`hq_cases`) is one question with: evidence (`hq_case_evidence`: stance for / against / neutral / MISSING, source, the times it was published, happened and retrieved), assumptions, dependencies (`hq_case_deps`: a missing report is one named request and one question, resumed by `cases.sweep` when a document of that kind about that company, a file, an answer or the sandbox arrives), calculations kept with script, datasets, parameters and result (`hq_calcs`, reproducible), the decision, uncertainty and next review, a log of why it changed (`hq_case_log`) and a code-made process review (`hq_case_reviews`: stale inputs, failed tools, contradicted assumptions, unsupported confidence, uncontained or unconfirmed calculations, certainty wording, alerts for a decision of nothing). Missing evidence is never evidence against. States: queued, running, waiting_data, retry, awaiting_approval, done, failed; at most 4 case passes before a case that cannot settle closes as inconclusive; a closed case reopens on its review day. The brain wakes on a due case without the gatekeeper (the governor still counts); `cases.discover` opens cases from signals in the stores (a hypothesis to decide, a thesis ending, a prediction overdue, a material reading, an IPO allotment, a held task). Board tasks: bounded attempts (3), network and API errors retry with back-off and a bug does not, an interrupted task goes back to retry at the next start with its done effects remembered (`hq_effects`, `board.once`), waiting tasks resume on `board.wake`, a held task is released (runs once; what it hands on is held again), dismissed, or dismissed by the keeper after 3 days with the reason kept. After a sleep (`Runtime.beat`) work is recovered, arrivals swept and "catching up" shown until the closing prices are current; no brain pass and no recommendation prepared earlier is presented as current before that (`system.stale_prices`, `recommendations`). The app writes `pm/app/heartbeat.json` from its own `heart` thread every 30 s (last beat, last wake and what it recovered, then `settled_at` on current prices or `blocked_at`/`blocked_by` after 2 h; jobs that finished well and the jobs that failed in the last hour; whether paused) for `pflab verify --wake-check` and `--hour-check`. Pause (`settings.scheduler` false) holds every autonomous start (jobs, follow-ups, HQ readers/brain/keeper/cases/drop scan, agents' hand-offs, simulations, research, the tick); his own orders still run.

## Email: removed (2026-10-30)
No Gmail module, mail reader, job, connector, tool, command, screen or Google library: every file comes from his hand (Inbox and files, or the drop folder). Migration 50 drops `mail_seen`, `mail_facts`, `mail_scan` and adds `statement_periods`. Older sections below that describe the mail walk, `mail_facts` or Connect Gmail are history.

## The World (S67 local): the dashboard's new home
`app/world.py` + `GET /api/world` (read-only, nothing is written): one payload for the screen that answers "is everything running, and what is done?". Nodes: senses (job groups: market data, filings and news, Kite, mail, US), the agents around the brain (every `roster` agent), work (investigations, experiments, calculations, the board, routines), memory (ledger, graph, learned), guards (sandbox, spend, the picture of you, first launch, safety routines). States are computed from the store: working (running now), ok (done), late (due, not run), down (last run failed), waiting (for data, for you, for the first launch, or paused), idle. `checks` is the checklist (connections, data, today's rounds with done or not, agents, work, you); `feed` is the live activity; `looking_into` lists open investigations and experiments; `pulse` is the sentence at the top. One section failing is named under `errors` and the rest still show. `POST /api/world/pause {"paused": bool}` pauses or resumes the system's own routines (the `scheduler` setting; running work finishes). Front end: `static/world.js` + `world.css`; the map is built once and patched in place every 5 s (animations never restart); click a node for its inspector; the counters filter the checklist; the light theme and `prefers-reduced-motion` are honoured. "What to bring" (`onboarding.bring_list`, in the payload as `bring`): what he can give (Console tradebook, funds ledger, contract notes, CAS, bank statements, FD certificates, screenshots, GIFT City, FD and IPO forms, passwords, the Kite login, the first answers), each with why and where from, and have or missing computed from Inbox. Email is removed (2026-10-30): there is no Mail node. The old Agent HQ screen is gone: the World is the one place for the agents. Its controls sit under the map (`hqParts`/`hqWire` in `app.js`, still `GET /api/hq` and the `/api/hq/*` posts): order any agent (from the top box, a "To" list, or the agent's own panel), the board with answers, the brain (mode, Think now, journal, predictions), suggestions and readings, agents and spend against the limits, reminders. What is typed survives a refresh (`wset`). Tested in a real headless Edge (`tests/test_s67_world_ui.py`, marker `ui`).

## The research workspace (S67 local)
One set of tools and tables for chat and background work (`hq/tools.py`; chat reaches them through `agents/tools.py` `research`). `learner/experiments.py`: register (protocol file + hash of the evaluator), baseline, candidate script in the sandbox (walk-forward: `agents/workshop_runner.py` cuts the data at each decision date), trusted scoring (`score_period`, `decide`), counted in `learn_tests`, attempts in `learn_attempts`, outcome in `learned` kind `experiment`; the learner cycle runs one step per cycle; `reap` recovers a dead process's run. `hq/objectives.py`: a wish becomes a frame (objectives with a number, horizon and comparator; acceptable fall at most his limit; two competing explanations; what would change the view) or stays a draft with one grouped question. `ingest/coverage.py`: accounts from the statements (`account_candidates`), gaps (`known_gaps` keys `coverage:*`), `matrix`, `status` (nothing read yet | discovery in progress | partial | complete), `ask_inventory` (once, after the walk reached its horizon), `confirm_inventory` (his press only). `cases.reproduce(basis="original")` runs on the kept input snapshot (`hq_calc_inputs`). `propose_software_change` writes `hq_issues` rows only; no tool edits the application, grants a permission or changes a limit, and the Kite wrapper still refuses every order, GTT and SIP whatever the market.

## First launch, fresh start and the mailbox walk (S67 local)
`activation.py`: a new profile folder holds `activation.json` = pending; `run_job`, `gmail.session` and `kite.client` do nothing while it is pending; `launcher._run` (the icon) calls `activation.activate(pm, via="icon")`; nothing else can. No file = active. `pm/fresh.py` (`pflab pm fresh`, `pflab pm restore`): archive as opaque bytes with sha256 verification, sanitized manifest (salted-hash names, no file names; real names in `names.private.json` inside the archive), old profile moved aside, new empty migrated profile + `learn_tests` + reduced `api_calls` (no question or request text). `ingest/gmail.py`: `scan_ids` hands out the last `days` first, then walks back `WINDOW_DAYS` at a time to `HORIZON_DAYS`, saving the window in `mail_scan` per mailbox when it is finished; `coverage()` reports how far back and that link-only mail is not checked. Effects: `board.once` (marker `started`, then `done`), `once_db` (atomic with a store write), `uncertain`. `app/system.recommendations` judges each item on its own instruments.

## Store (`PFLAB_PM_DIR\ledger.duckdb`, schema v49; migrates itself; v44 `hq_effects.state`, v45 `mail_scan`, v46 `hq_calc_inputs` + `hq_calcs.versions_json`, v47 `learn_experiments` + `learn_attempts`, v48 `hq_objectives` + `hq_issues`, v49 `account_candidates`)
Ledger and tax: accounts, events, lots, cash_ledger, income, fees, carry_forward, tax_years, instruments, prices, navs, gold_rates, fds, fd_interest, bonds,
sgb_series, fund_holdings, ipo_applications, targets, us_trades, us_remittances, fx_rates, instrument_alias. Kite and checks: kite_snapshots, kite_trades,
live_quotes, recon_breaks, job_runs. Agents and the brain: questions, memory, decisions, briefs, theses, proposals, watches, ready_plans, scans, research_flags,
outbox, alerts_sent, api_calls, llm_runs, hq_passes, hq_tool_calls, hq_tasks, hq_predictions, hq_suggestions, hq_readings, hq_reminders, limit_proposals,
theme_baskets, pot_ideas, forecasts (renamed from tfm_forecasts in v36), twin_days and twin_trades (the scoreboard), hq_cases, hq_case_deps, hq_case_evidence, hq_case_log, hq_case_reviews, hq_calcs, hq_effects (v43), health_checks (the results of real operations, e.g. the sandbox probe), known_gaps (open gaps with attempts). Graph: kg_nodes, kg_edges, kg_docs, kg_aliases, kg_hypotheses. Learner: learn_sources,
learn_claims, learn_tests (the counter), learn_proposals, learned, forward_months (the forward tests). Dashboard: chats, chat_messages, app_notes, inbox_items, mail_seen (Gmail messages already looked at), mail_facts (what the emails said and how each checked). Take ids with `store.next_id`.

## Settings (Settings screen; `PFLAB_PM_DIR\app\settings.json`)
theme, privacy (hides rupee amounts), telegram_send (off until switch-on: held alerts stay held), scheduler, live_prices (Kite quotes in market hours),
preset (off / light / full / marathon), sims_hour, brain (off / economy / normal), drop_watch, models (the slider: job to model), features (beta switches),
plus the keys form (write-only), Setup (accounts and start date) and Connect Gmail (read-only; README step 5).

## Costs
Local models are free. API spend is priced before every call and refused above his monthly cap (Rs 2,500, `api_budget.toml`; the workshop has its own
`dev_monthly_cap_rupees`, default 0). A brain pass costs about Rs 10; deep research and web search are the dear items.

## Facts the code relies on
- **Adjustment.** NSE's bhavcopy `PREVCLOSE` is NOT adjusted on ex-dates (450 of 451 large down-gaps 2012-2020), so split and bonus factors come from
  the corporate-actions feed and are verified on known events (`tests/test_adjustment_known_events.py`); `adj_close` in the panel uses them.
- **Index membership is point-in-time or not used.** NSE's circular series covers Nifty 200 and 500 only in 2006-2008; membership tables are built
  from archived factsheet/change PDFs (`build_index_membership.py`); names it cannot resolve are written to `PFLAB_DATA_DIR\index_membership\unresolved.md`
  for him to check. Never use today's list over a past period (survivorship).
- **BSE results** come from the integrated XBRL filings (standalone and consolidated) dated by filing time; shareholding by filing date, never the quarter end.
- **Tax rules** are dated, sourced rows (`configs/tax/*.toml`); coverage of capital gains starts at transfer date 2024-07-23 and a lookup with no row raises
  (`RuleGap`), never a default. Foreign-tax rows are all `secondary` (official wording seen in search results) until a primary check (due 2027-01-01 or the
  first remittance). The new-regime slab table for the year ending 2026-03-31 is not read: regime tax raises for that year; the Quicko pack does not need it.
- **Schedule 112A layout** is the department's CSV instruction (`configs/forms/itr_112a_layout.toml`, read 2026-10-28); the template's own header row and a
  possible column 1b are checked at filing time. Quicko files his return; the system prepares and reconciles, it files nothing.
- **Small-numbers rule:** results under 20 observations carry their count and no conclusion; probabilities are shown with their error.
