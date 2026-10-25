# HANDOFF — 2026-10-25

## Start here
**S63 DONE in the repo 2026-10-25 (branch `pm/s63-clean`, PLAN A23; STATE).** Waiting on the investor for the two GitHub
steps (rename the old repo, create the new one), then the push of the single first commit and the old repo's branches
deleted (archive and tags kept). **Next: S64 finish (seven gaps, then switch-on), from `docs/S64_KICKOFF_PROMPT.md`** (his own words,
his answers, the design in `docs/COMPANION.md`). The first run from a clone (his requirement in PLAN A23) and the final
clean moved to the very end, after a month in sync; the items below are for that last session. Known S64 items: a TimesFM-only `.venv-train`
setup (today `qlora_setup.ps1` installs torch but not `timesfm`, and downloads Qwen files nobody needs) with the weights
download; the fine-tuned revenue weights rebuilt by `s52_unattended.ps1` on a fresh install (the forecast job asks);
backfill commands for every collector (`backfill_*`, `s48_collect`, `build_index_membership`, the panel, GDELT BigQuery
in its free sandbox); keys and passwords by a `pflab` command; Gmail read-only (free API, `gmail.readonly`); bank money
movements labelled by the system (`bank_rules.local.toml` was hand-made in chat), asking only where needed; then his data
rebuilt through those commands once he says yes to erasing (he said "not yet" in S63). S63 review notes still open: the
egress gate's year exemption (bare 1900-2100 numbers) and the trial paths' default approval.
**The investor's target (2026-10-20, memory `autonomous-loop-vision`):** the system complete in November, working on its own
(wake, sync check, ask for files, ready plans, escalate to Opus, weekend notes), him in the loop when he wants. The
sessions to switch-on, then filing and the US sleeve: **PLAN amendment A8** (S54 dashboard and Streak-style watches,
S55 ready plans, S56 escalation chain with the Tijori check first, S57 KG cleanup + Graphify, S58 restart drills,
switch-on, S59 Quicko filing pack, S60 US sleeve; its research and Monte Carlo may start early).

**S54 dashboard, in parts (branch `pm/s54-dashboard`).** Design approved by the investor: the mock at
https://claude.ai/artifact/GNjKTyBVDTsRNGFiLbndDr (10 screens, sample data). **54a DONE 2026-10-22:** `pflab.app`
(launcher, runtime, views, server, static UI; fastapi + uvicorn pinned; store v24 `app_notes`); desktop shortcut
"Portfolio Lab" (`tools\install_shortcut.ps1`, icon `tools\make_app_icon.py`): double-click starts the screen, the jobs
(scheduler every minute; the outbox only when Telegram is switched on in Settings, so held alerts stay held), live Kite
prices in market hours and the Monte Carlo cache in one process; closing the window stops it (checked: stops within 2 s
of Edge closing; a second double-click only reopens the window). Real screens: Command centre, Portfolio (buckets,
sectors, stocks, lots, FDs, tax so far), Schedule (jobs), Settings (theme, privacy mode, scheduler, live prices,
Telegram). Decisions: Opus writes the research briefs and runs web search / deep research (The investor: "most tasks need
Opus", within the cap). **54b DONE 2026-10-22:** AI centre: chats (store v25; new, delete, tidied into memory after
30 days) with modes Ask (local tools + guard), Web search (Opus `web_search_20260209`, gated, priced first incl.
$0.01/search, uncited figures dropped), Deep research (doorbell, note kept and openable), Calculate (workshop); route shown
per answer; agents roster with last runs; questions answered on screen. Real check: Ask answered in 24 s, guard-checked.
**54c DONE 2026-10-22:** watch list with buy zones v1 (`plan/buyzone.py`: zone = 20th-40th percentile of a year's closes;
valuation is a separate check, WAIT when the price assumes >10 points more growth than the company's own; touch chance by
100,000 bootstrapped paths with its error; guard NO), add / remove names, price watches (store v26; a hit is a held message
and a notification), check my idea, nudges on the Command centre; research and plans (the tested S45 plan with what the zone
says beside each ticket, guard NO vs zone WAIT shown apart, results ranges, flags, Opus notes, technicals). The nightly
research job now queues Opus notes for changed names (batch, within the cap). Real check: 13 names in 23-44 s, plan 19 s.
**Decision 2026-10-22:** the zone does not change the plan (CLAUDE.md 12): a pre-registered study must first show that
waiting for the zone beats buying at once (data 2016-2021, Nifty 500, the S45 design); it is queued for after S54.
**54d DONE 2026-10-23:** Inbox and files (store v27): drop, paste (Ctrl+V) or attach in a chat. Ledger documents go to
`new/` and `pm\sources.app.toml` (his `sources.toml` is never rewritten); each is checked by a dry-run rebuild and written
only on "Add to the ledger" with every check passing, in one transaction. Overlapping downloads: repeated fills and
contract notes count once (real ledger unchanged: same events, 13/13 checks). A file already in `new/` is never deleted.
Screenshots read by Windows' own OCR (`tools\ocr.ps1`, chosen: built in, nothing to download, 0.5 s); image deleted after
7 days, text kept; "Read it" (guarded local summary) / "Research it" (deep research of the text, egress gate). Market
exports into the graph. Needs-from-you = open questions. **54e DONE 2026-10-23:** Simulations (`app/sims.py`): current,
target and a what-if mix, 10,000 or 100,000 paths (100,000 in ~20 s), fan chart, fall chance under the small-numbers
rule, medians with batch errors, seven dated stress episodes and each mix's own worst fall, the frontier. Presets
Off / Light / Full / Marathon (Light = data and checks only; nightly simulation 10,000 Full, 100,000 Marathon, after
22:00), catch-up shown, checklists from four templates (store v28). Knowledge graph view (`app/graph.py`): companies
with sectors, verdicts and what their documents name at least twice, time slider by document date, click for documents.
All screens checked on real data in privacy mode. KG cleanup itself is S57.
**After S54 (2026-10-23):** the desktop shortcut's start died silently (a held ledger, no console under pythonw): the
window now opens at once, a failure is shown in a message box, job subprocesses end with the system (Windows job
object) and the Edge window closes; checked with the shortcut's own command (window in 1.1 s, nothing left after stop).
Simulations now carry "your stocks" (today's names and weights, their own total returns; the equal-weight Nifty 500
before a name listed; the share of own history is shown) beside the equal-weight Nifty 500 (The investor's ask).
**S55 DONE 2026-10-23 (branch `pm/s55-ready-plans`):** `plan/ready.py`, store v29 `ready_plans`, job `plans` 21:30
(Light preset too). The next FD tranche always has a plan however far off (his rule: 10 monthly tranches; the 54c card
wrongly used the whole payout), others within 60 days; the monthly amount is asked once (a question; "25,000 from
January" sets amount and start). Each plan: bucket split, funds/ETF with a price range (gold ETF's zone), stocks with
qty, "buy around" range (the zone, a description), why (share of its target, guards) and tickets; versions kept only
when the plan changes, with what changed; a held message and a notification 7 days before. The outer ring (idea, not a
rule): the same stock money into list names not held, no top-ups, with names, the largest name's share and the sleeve's
1-year fall chance for both (same random draws; on the real ledger the ring lowered concentration but raised the
fall chance, so it is shown as a trade-off). Privacy mode
masks rupees in tickets. Waiting on the investor: his answer to the monthly-amount question.
**S56 DONE 2026-10-23 (branch `pm/s56-escalation`, PLAN A10):** `agents/escalate.py`: local -> agents -> Opus, each
step's reason shown as the answer's route; the AI centre's default mode "Auto". Kinds by fixed word rules: own (stops
at the local facts; his data never leaves), calc (workshop, Opus writes code), company (a reused note, else Opus deep
research), outside (Opus web search). Real check: a portfolio question answered locally and checked (28 s); a company
question went to Opus (cited note, ~Rs 9). Falls: `researcher.fall_flags` runs the S20 classifier live (5 and 20
sessions); a company-specific fall is a flag (-> the night's Opus note; a Tijori ask once he has Tijori). Briefs: no
second paid writer (the flagged name's Opus note sits beside a failed brief). Tijori check (`docs/data/tijori_check.md`):
Monthly Rs 330, Yearly Rs 3,500; downloads for paid users (format not stated); the terms allow personal use and forbid
transmitting its contents; the investor's decision: the exports are public company data and go to the analyst.
**Then (The investor 2026-10-23):** Tijori exports are public company data, not his: they go to the analyst (default on).
**S57 DONE 2026-10-23 (branch `pm/s57-kg-cleanup`, PLAN A11):** `kg/clean.py` in the nightly `kg` job, logged on the
Inbox screen: exact name matches merge (legal endings; into his companies' nodes), unsure ones asked once (store v30
`kg_aliases`), syndicated copies point at the original (`dup_of`; counts, news spikes and the analyst use originals),
the newest analyst note per company is current. Real graph: 85 names, 393 copies, 21 notes; second run a no-op.
Graphify not adopted (a Claude Code skill; sends documents to Claude). Waiting on the investor: one "same company?" question and the
monthly amount (both under Needs from you).
**S58 drill 1 run 2026-10-23 (branch `pm/s58-restart-drills`, `docs/research/s58_restart_drills.md`):** five days
offline, three jobs killed mid-run, no Kite login. 7 of 10 expectations passed (reaping, catch-up of prices and
indices, Kite off without blocking, held messages held, conductor, clean stop). Fixed: the news step opened the ledger
the dashboard holds and collect hid the failure; settings saves raced; job finish times; a material change now buys a
fresh Opus note instead of reusing the last. **Then (same day):** drills 2-4 (`s58_restart_drills.md`): a power cut
mid-rebuild left 100 of 1,383 events (no transaction on the command line): every delete-then-insert write is now
all-or-nothing (`store.transaction`), the same cut leaves the ledger intact; low disk is asked about and stops
downloads. Buy-zone wait study NOT ADOPTED (PLAN A12: waiting lost in every period); WAIT became ABOVE ZONE / RICH.
Reusable calculations (A13). Sonnet vs Opus comparison ready (runs are the investor's). **2026-10-24 (The investor: the schedule is
for when the system is not in use):** every job has "Run now" on the Schedule screen (queued, run next on the scheduler
thread, one at a time; the held outbox stays refused), with its last run, status and duration; in the app, notes research
queues for Opus are submitted straight after it and a submitted batch is collected every 30 min (1 AM stays for
unattended nights). **Drill 1 re-run 2026-10-24:** all jobs ran once with real durations; two misses fixed (news days
missed by a failed run: 14-day look-back; no fresh Opus note: research checks the last 2 days' flags, never buys a
note in flight). Open: a workshop calculation marked checked is wrong (one-day fall for "fall from a peak": a
model-written test agreed with the model's code); the ledger's documents end 13 Oct (Kite only checks, never writes).
**S58b 2026-10-24 (branch `pm/s58b-portfolio-math`, PLAN A14):** the portfolio today from Kite between statements
(`pm/today.py`, store v31 `kite_snapshots`; login and monthly statements asked for); reviewed measures answer first
(`calc/measures.py`), new code needs an independent second writing. Real checks: Nifty 2020 fall from a peak 38.44%
(14 Jan-23 Mar) by the measure in 6 s; the wrong 22 Oct calculation withdrawn. Not yet seen on real Kite data
(positions and Coin funds shapes are from Kite's documentation): check the first snapshot after the investor's next login.
**Then (same day):** first real Kite snapshot checked (14:03, straight after the login: one holding differs from the
statements, a buy since 13 Oct; cash moved to SBI estimated). Tax planner (`tax/plan.py`, PLAN A14 (4)): per holding a
FIFO ladder of sales replayed by the tax engine (both regimes), long-term dates from each lot's rule, what waiting
saves, the 112A exemption left and the gains that fit in it (replay-checked), sales that lower this year's tax; on the
Portfolio screen, `pflab pm taxplan`, the Ask tool `taxplan`, /taxplan, and the workshop's `tax_plan` measure; 0.4-1 s
on the real ledger. Fixed: the shared DuckDB connection across threads (the Monte Carlo loop failed at start), the
Schedule screen's login check. **Switch-on prepared (2026-10-24):** `docs/SWITCH_ON.md` rewritten for the dashboard
era; the scheduled tick stands aside while the dashboard is open and obeys its Settings (preset; Telegram held until
switched on); the task runs pythonw (no window; `pm\reports\tick.log`); `pflab pm alerts --drop-before DATE` drops
stale held messages. Checked: the tick with the dashboard open, under pythonw; `register_tasks.ps1 -WhatIf`. The investor's
answers of 24 Oct (Gadget Co name, monthly amount) apply at the next `kg` and `plans` runs.
**Switched on 2026-10-24 (The investor):** Telegram configured and sending; dashboard restarted. **Decision (The investor,
2026-10-24): no backup target** ("if I need one I will tell you"): `configs/service.toml [backup] declined`; shown as
off, never asked. Then (The investor: real time, autonomous): new data starts the jobs that use it (`jobs.FOLLOWS`: collect ->
prices -> guards, plans; nav -> plans; a material filing -> research -> analyst), window open or not; filings and the
Kite snapshot every 15 min; the dashboard sees new code and offers "Update ready: restart", restarting itself after 30
min untouched with nothing running (checked on a throwaway instance: back in 4 s). Fixed: a slow screen load drew over
the next screen (Settings "popped back", reproduced in headless Edge, fixed, checked); the window's cached old app.js;
"same" read as a no for merging names, and an unreadable monthly amount dropped silently (both now read or asked again).
**Next:** The investor restarts once more (onto the self-update); the Tijori session; XIRR and the FY return as reviewed
measures; queued: Sonnet vs Opus.
**S59 DONE 2026-10-24 (branch `pm/s59-agents-hq` from `pm/s58b-portfolio-math`, PLAN A16; details in STATE):** the
agent HQ (`pflab.hq`) and the brain in shadow mode. The investor's answers: drop folder local (`D:\portfolio_lab\drop`, Google
Drive later), laptop on = system on. Cap set to ₹2,500 in `api_budget.toml`; his name for the egress list in its
`[egress] names`. The shadow trial runs 14 days from 2026-10-24 (judgement by the committed protocol; he marks passes
"Mattered / Did not" on the Agent HQ tab). **Next:** first dashboard start on this branch: check Telegram orders end to
end, a file in the drop folder, the Monday morning review; open items: the researcher's local materiality tagger is
not yet replaced by the readers; the brain acts only after the trial and his yes.
**Then (same day):** the Office view, a paid check of every agent and its fixes (STATE). Open: web search costs ~Rs 25
on Opus (Sonnet would halve it: a measured choice, not made); the AI centre's Auto mode still words own-portfolio
answers locally (A10); filing attachments reach research only once the readers have fetched them.
**Then (same day, PLAN A17):** the one-brain program decided with the investor. Step 1 done (Haiku vs local, results in
`docs/llm/haiku_vs_local_results.md`).
**S60 DONE 2026-10-25 (branch `pm/s60-one-brain`, PLAN A18; details in STATE):** the brain is one model with 26 tools
(`hq/tools.py`) in a governed loop of at most 8 turns, shadow kept; per-stock drift / odds / edge (`hq/stocks.py`); the
suggestion ledger scored by the keeper and shown on the Brain view with Taken / Declined; context hand-off to memory;
memory corrections and outcomes; `redact()` (checked on his real statements); cited-page fetch (BSE from the local copy).
Shadow protocol amendment 1: the trial's 14 days restart at the first non-check S60 pass. **For the investor:** optionally add his
address words to `pm\api_budget.toml [egress] address` (done 2026-10-25 from his own words). Then the same day: no
shadow wait (the brain acts, capped), every filing's text kept, the tick left unregistered until he switches on.
**S61 DONE 2026-10-25 (branch `pm/s61-slider`, PLAN A19; STATE):** the slider is built, wired and measured: live
answers local, materiality Haiku, research notes and the workshop Sonnet, web Opus, routing Haiku
(`docs/llm/s61_slider_results.md`). The local model keeps live answers, so the GPU stays in use for now.
**Then (The investor, same day, PLAN A20):** answers divided (local for basic, Haiku when it fails: his setting; insight
questions to the brain, to wire in S62); every model sees the same facts, ids as letter tokens restored on this PC
(an FD question Haiku could not see in the run now passes). **Next: a new session from `docs/S62_KICKOFF_PROMPT.md`** (S62 learner + web-search tool + security agent; S63 clean; S64 first run with Gmail, PLAN A21)
(S62 the learner, then S63 the repo clean, history rewrite and his data plan).
**Then:** S62 the learner; S63 the repo clean with the git-history rewrite (The investor asked for it 2026-10-25: "proper
cleaning, all engineered, all wired, no random things"; show him the delete list first; `research-archive` untouched).
**S62 DONE 2026-10-25 (branch `pm/s62-learner`, PLAN A22; STATE):** the learner (free sources, quoted claims, coded
tests registered first; first real test failed and has no live feature), own-data judgement to the brain, the brain's
`web_search` (Sonnet), the security agent (its first look back found and we fixed three small leaks of his name and FD
numbers; `llm.body_check` now guards every request). **Next: S63 the clean** on `pm/s63-clean`. The investor's answers of
2026-10-25 for S63: the old history goes completely; he offered to delete the GitHub repo, but `research-archive` lives
only there (non-negotiable 1), so the proposal is a fresh repo for the cleaned tree with the old one kept for the archive
only (his yes needed); GitHub Actions only if worth it (pytest on push is cheap; the privacy grep must stay local, a
pre-push hook). S63 inputs found in S62: his first name in 650+ doc/code lines, 23 list names in old tests/docs, the
egress year exemption, the trial paths' default approval. S64 Gmail: the free Gmail API (`gmail.readonly`).

**Done 2026-10-22 (The investor's steps 1-4, each on its branch, merged):**
1. Results, checked against logs and files: `docs/research/timesfm2_results.md` (Q5 T30C and Q6 F25 revenue / T25
   margin pass; Q1-Q4 fail; Nifty and 2020-21 described by `timesfm2_study.py describe`) and
   `docs/llm/harness_s47_pass3_results.md` (research adopted, writing not). Decided: Q2's candidate C passes the
   protocol text's 7-of-10 breadth but fails the per-fold breadth in the rule code committed with it; the stricter
   reading stands (C fails). Q6 has no holdout: `data/bse_results` ends at 2021-12, so it passes to the scoreboard.
2. S48 arms 2 (institutions) and 4 (deals) run after amendment 1 (holdings outside 0-100% dropped; NSE's 70-row deal
   cap recorded): both fail; S48 closes with nothing live. (The arm numbers are the protocol's: 2 institutions, 4
   deals.)
3. S47 research harness live: `llm/adopted.py`; `/deep` and `pflab analyst ask` give the local guarded answer when
   Opus is not rung. Studies keep their registered prompt.
4. S52 live (`quant/tfm2_live.py`, `tools/tfm_live_forecast.py`, store v23, `pflab forecast run|show`, job
   `forecast` 21:00, a night-run step, a morning-report section): tickets' size line, researcher `results_range` /
   `results_surprise`, thesis lines, the registered scoreboard and fallback. Checked on the ledger 2026-10-22: 12
   stocks, 9 companies, TimesFM on the CPU in 19 s.

**Step 5, S53 checks on real data (The investor, 2026-10-22):** `conductor status` as expected before switch-on (jobs never
run by the service, 12 held messages, no backup target); "market market" now reads "market open"; the night run now
runs the `global` job (foreign markets were 30 days old). `workshop ask --writer local` ("the Nifty 50's largest fall
from a peak in 2020") gave a WRONG answer marked checked: 916.7 is the largest one-day RISE in all the data (12 May
2025); the answer is -38.4% (12,362.3 on 14 Jan to 7,610.25 on 23 Mar 2020). Its own test case was wrong in the same
way, and its "second method" was a copy. Fixed: a copied second method is refused, the writer is told to apply every
condition of the question and work the test out from the question, the result line no longer says more than the checks
show. The label "not reviewed" held: nothing reads it. Finding: the local writer cannot be trusted on its own; the
workshop stays out of `pflab ask` and the bot (S56 decides whether Opus writes calculations, priced by the doorbell).
**Then, same day (The investor's decisions):** the workshop writes with Opus first (the local model only as a labelled
fallback); the egress gate no longer reads years, dates or window lengths as ledger numbers (it had blocked every
workshop question) and gates only the question, not the code-made rows; acceptance test PASSES 10/10, ~Rs 51
(`docs/llm/workshop_acceptance_results.md`). No larger local model and no Perplexity for now (The investor). **PLAN
amendment A9:** the agent roster (duty, schedule, model, test, autonomy), the investor's autonomy grants and the
small-numbers rule. After the build: a final session removes Claude Code's traces (local files, memory, sessions;
git history only with the investor's yes). **Next: S54** (dashboard, live portfolio keeper, watches; the small-numbers helper).

**Open for the investor:** switch-on (`docs/SWITCH_ON.md`, held alerts first); trade-check gaps (Console tradebook, funds
ledger, bank statement into `sources.toml`); Kite depth recordings for `pflab pm impact`; at switch-on, older
quarters for the list companies the forecast skips (6-7 quarters on record, 8 needed):
`pflab pm results --scrip <code> --pull --quarters 12` (the skipped codes: `data/forecasts/live/inputs_<date>.json`).

## History (2026-10-21)
**The investor's target (2026-10-20, memory `autonomous-loop-vision`):** the system complete in November, working on its own
(wake, sync check, ask for files, ready plans, escalate to Opus, weekend notes), him in the loop when he wants. Order:
S53 conductor + S52 TimesFM side by side, then S54 dashboard (no email: Telegram + dashboard inbox), S55 ready plans
(the "outer ring" is an idea to show, not a rule), S56 escalation chain (Tijori last; he has not bought it), S57 KG
cleanup + Graphify trial (needs his OK to install), S58 restart drills, then switch-on.

**S52 RUN COMPLETE 2026-10-21 22:19** (log `PFLAB_PM_DIR\reports\s52_2026-10-21.log`, every step ok; `results.json`,
six `ft/*/meta.json`, all forecast sets on disk). RESULT lines: Q1 adopt None | Q2 adopt None; Q3 h=63/126/252 fail
for T25 and T30; Q3b (vol-aware Monte Carlo) fail; Q4 fail; **Q5 adopt T30C** (turnover, 3.0 + calendar);
**Q6 adopt ln_revenue F25, margin T25**. Write the results doc from results.json, then build only Q5 and Q6.
**S52 TimesFM done properly: the overnight run of 2026-10-21 finished it.** Protocol
`docs/research/timesfm2_protocol.md` with amendments 1-5, all committed before any forecast was scored. Code:
`quant/tfm2.py` (proxy, baselines, losses, pooled tests), `quant/tfm2_prep.py`, `quant/tfm2_eval.py` (the rules),
`tools/timesfm2_study.py` (prepare, dev-choice, evaluate), `tools/timesfm2_forecast.py` and `tools/timesfm2_finetune.py`
(.venv-train), `tools/s52_unattended.ps1` (the run). Kept from earlier runs: Q1 forecasts (132 files: T25, T30, T30X x 4
configurations x 11 series), Q3 (20), Q5 T25 for 5 stocks, `choices.json` (F25 input `log`, dev only). First thing in the
new session: check the run against the process table and the files, not the notice: log
`PFLAB_PM_DIR\reports\s52_2026-10-2x.log` ends with FINISHED and RESULT lines; `data/research/timesfm2/results.json`
exists; `ft/<task>_<fold>/meta.json` for q1_A, q1_B, q6_ln_revenue_A/B, q6_margin_A/B. If it stopped, rerun the same
command (it resumes; GPU lost -> Restart, caps again). Then write `docs/research/timesfm2_results.md` (each question,
its rule, pass or fail; Nifty described; 2026 holdouts where matured), and build only what passed (forecast service,
live scoreboard and fallback exactly as registered); what fails gets no live feature.

**S53 conductor + calculation workshop: BUILT and merged.** `pflab conductor status|run|sheet`; the `conductor` job runs
last in every tick (registered with the others: nothing runs until the investor switches on). `pflab workshop ask|list|show|
promote|rerun`: a model writes a calculation as code; it runs in an isolated sandbox on the real rows, must pass its own
test case (and agree with a second method when given), and is kept beside its code as "not reviewed" until promoted.
Not yet wired into `pflab ask` or the bot: adding a tool changes the routing menu that S42/S47 measured, so it waits for
the routing re-check. Still to see on real data (after the GPU runs): `pflab conductor status` on the ledger and one
`pflab workshop ask` with the local model (The investor runs these as step 5 below).

**State on 2026-10-21 evening.** Done: S47 pass 3 (research harness ADOPTED, final 0.745 vs live 0.097, McNemar p
~0; writing NOT adopted), S48 deals (144 files) and institutions (23,912 pairs). S52: Q1 and Q3 forecasts complete;
The investor runs the rest overnight (`powershell -ExecutionPolicy Bypass -File tools\s52_unattended.ps1` from an
Administrator PowerShell, which sets the GPU clock caps; ~3 h; it resumes). The laptop GPU dropped off the bus three
times at its top boost (14 GHz memory); capping core 2100 / memory 9001 MHz held (`nvidia-smi -lgc 210,2100`,
`-lmc 405,9001`; a reboot clears them). Protocol amendments 1-5; the full fine-tuning grid is restored (amendment 5).

**Next session, the investor's order (no reruns planned):** 1. results: S52 (`data/research/timesfm2/results.json` ->
`docs/research/timesfm2_results.md`, decisions by the registered rules) and S47 pass 3 (write the results doc). 2. data:
the S48 studies, `tools\s48_study.py --arm 2` (deals) and `--arm 4` (institutions). 3. S47: wire the adopted research
harness into the agents (writing keeps the live one). 4. S52: build only what passed (forecast service, live scoreboard,
fallback, as registered). 5. S53: The investor's checks, `pflab conductor status` and one `pflab workshop ask --writer local`.
Then S54 dashboard.

**New, from the investor 2026-10-21: a US-stocks sleeve** (Zerodha has approved his international account through GIFT City;
IFSCA, not SEBI; money out under RBI's LRS). Diversification only: the PhD plan stays as is, and he expects to hold a
small amount (the rupee cost of dollars). It is its own research and planning, a new session after the queue above;
steps 1-2 may start early as they depend on nothing else:
1. Facts, sourced and dated (as the tax tables; Opus through the doorbell, all public): IFSCA framework and the
   broker's terms, LRS limit, TCS on investment remittances, Indian tax on foreign shares (holding period, rates),
   US dividend withholding and the India-US treaty credit (Form 67), Schedule FA reporting, US estate tax on US-situs
   assets of non-US persons (no India-US estate treaty: decides how to hold it), all costs (brokerage, FX markup,
   remittance). Nothing from memory is used until a source confirms it.
2. Numbers: the Monte Carlo with a US sleeve in rupees (S&P 500 total return x USD/INR) at 0/10/15/20% of the
   investable mix against his 35% fall limit, labelled estimates. The share is the investor's decision; the system shows it.
3. Plumbing: a USD account in the ledger (lots at the dated FX rate, the 24-month rule, foreign tax credit, Schedule FA
   report), US prices and USD/INR data, SEC filings for research.
4. Agents: tickets for the sleeve, guards and research for US names.

**Also from the investor 2026-10-21 (Zerodha ecosystem; official routes only, never reverse-engineered private APIs):**
- **Quicko replaces a CA** for his filing (free self-filing or the expert plan). Build a "filing pack" from our tax
  engine (capital gains by schedule, interest, TDS, both regimes) and a side-by-side check against Quicko's figures
  each year; the year-round real-time view stays ours (tax so far, advance-tax dates, LTCG exemption headroom shown,
  never acted on). Check whether Quicko covers Schedule FA and foreign tax credit (for the US sleeve).
- **Tijori: he plans to buy.** Before he does, check its plans and terms: Excel export in Premium, and use of the
  data with an AI; exports then go into `pm\inbox\market\` (the inbox already reads them).
- **Ideas from Streak for S54/S55** (ideas, not code): plain-words conditions watched in market hours through the Kite
  live poller, alerting on Telegram and the dashboard (never an order); a technicals view per stock. An alert is a
  watch; a rule that claims an edge needs its pre-registered study.
- **Coin:** no mutual funds or SIPs now; reading them through Kite Connect's mutual-fund API (read-only) is a small add
  when he starts. smallcase, Sensibull: out of the system.

**Open for the investor:** switch-on (`docs/SWITCH_ON.md`, held alerts first); trade-check gaps (Console tradebook, funds
ledger, bank statement into `sources.toml`); Kite depth recordings for `pflab pm impact`.

## History (2026-10-18 to 2026-10-20)
**2026-10-20 (later):** S52 registered (protocol + 2 amendments before any forecast) and built; S53 built (conductor,
calculation workshop); `.gitignore` had hidden `src/pflab/pm/secrets.py` (code only) from git since S1: now tracked.
**2026-10-20:** S47 pass 2 (QLoRA) NOT ADOPTED (`docs/llm/qlora_s47_pass2_results.md`). S50 TimesFM FAILS as configured.
S51: plain volatility WINS the fall-ranking test on ten foreign indices but warns before fewer follow-on falls; the investor:
Hawkes keeps the market state, the volatility chance is shown beside it. S47 pass 3 (own harness search, after Google's
Harness2: Linux/Vertex only, unsandboxed, so only its method) registered and built. S48: the research archive (read with
The investor's OK, nothing copied) never tested a buyer signal; arm 1 (insiders) FAILS (val +2.9%, p 0.057 vs 0.0125); arms 2
and 4 collectors built (NSE caps deal answers at 70 rows: day by day; BSE Table III for institutions); arm 3 deferred.
`master` pushed (private repo). A real balance used as an example in CLAUDE.md was replaced; it remains in pushed
history (commit acfd8e3): removing it needs a history rewrite, the investor's call.
**Session of 2026-10-18: the first overnight run reviewed and its findings fixed** (branch `pm/s49-review-fixes`,
off `pm/s44-researcher`; neither merged to master). The Opus batch had arrived (13 notes, well inside the month's cap).
Fixed: results bottom line and NBFC/new-listing results (`docs/data/bse_results_finding.md` §7); analyst told the
results' basis and dating; a note whose company had no name in the master read "For None"; report showed every note and brief twice and garbled the
rupee sign (`overnight.ps1` read UTF-8 as ANSI). Wired in: S47 materiality v2, S49 hybrid look-up. Nightly S47/S49
steps off (decided). Then, the same day: The investor's answers recorded (memory #40-43: market state kept and
re-studied, amendment 2 KEEP with t1 0.37; API cap stays; Tijori not yet, he is weighing the paid plan; backup target
at switch-on); consolidated basis built (safety amendment 2, schema v22; switches by itself at 8 quarters, ~Feb 2027);
analyst and brief context take articles only when the headline names the company, results point in time;
S47 pass 2 (QLoRA) registered (`docs/llm/qlora_s47_pass2_protocol.md`), 2 of 966 training tasks done.
Read PLAN section 9 and amendment A7 first.

**Steps as listed on 2026-10-18 (all done or superseded; kept for the record):**
1. **S47 pass 2 is the investor's to run, in one go:** `powershell -ExecutionPolicy Bypass -File tools\s47_unattended.ps1`
   (online ~1 h: night-run data/jobs/research/Opus submit, `.venv-train` + base weights ~20 GB, Opus collect; offline
   ~9-10 h: the rest of the 966 data tasks (175 done 2026-10-18), base evaluation, Ollama unloaded from the GPU, smoke,
   training, merge, import, tuned evaluation, decision, morning report). Log `PFLAB_PM_DIR\reports\s47_<date>.log`
   ends with FINISHED and a RESULT line; a re-run skips what is done. Then read the DECIDE line and wire in what passed.
   **2026-10-18/19 run:** data done (966 tasks, 680 kept), base evaluation done, smoke ok; the laptop lost power 9 min
   into training (23:06; Modern Standby with the screen off under full GPU load; no bugcheck). Fixed: the run keeps
   the screen on, training checkpoints every 20 steps and resumes. Resume: `tools\s47_unattended.ps1 -SkipOnline`.
   **2026-10-19 later:** the real cause was GPU memory (fp32 vocabulary tables, full-sequence logits); fixed, trained
   in 38 min (8.2 GB peak). Import: Ollama refused q8_0 and int8 on Windows; amendment 1b converts with llama.cpp to
   GGUF Q8_0; `pflab-qwen3-8b-s47` is in Ollama. **2026-10-20 RESULT: NOT ADOPTED** (writing 0.778 = base, research
   0.567 < base 0.633; the converted-base check shows ~0.1 is noise on 30-36 tasks): `docs/llm/qlora_s47_pass2_results.md`.
   Agents unchanged. S47 is closed; a third attempt needs its own registration (larger evaluation, better targets).
2. After tonight's run: check the analyst notes read better (no "For None", no passing-mention articles, results with
   their basis and dating), and that consolidated result documents are in the graph.
3. Then S45/S46 acceptance on real use (advise before the Feb 2027 tranche; `pflab event` on a real news item).

**State of things (2026-10-17):**
- **Model:** qwen3:8b-q8_0 for routing and guarded answers (round 3: 100%; `docs/llm/model_decision_2026-10-17.md`),
  `nomic-embed-text` for S49. Both on disk; the overnight run pulls a model only if missing.
- **Analyst:** Claude Opus 5.5, ADOPTED by its registered comparison (0.70 at the bar, Rs 132; it won where the local
  model gave no answer), live only behind `only_sourced_numbers`. The investor: all analysis and research on Opus, qwen
  for the agents. Market-data exports (inbox/market, Tijori/Screener) go to it; portfolios and personal files never.
- **Maths audit** (`docs/research/maths_audit_s43.md`): falls measured on any day; the investor kept the target mix.
- **S45 split study RUN:** no plan adopted (limits below market cost 45-60 bps on validation, t about -3): tickets
  say buy at once with a limit at the last price.
- **Built:** S43 trade check, memory, questions, two-way bot (round trip works; never flushes held alerts); S44
  researcher + analyst doorbell; S45 advisor + trader; S46 drift, event study, quant researcher, event research,
  thesis tracker; S49 harness; inbox (any dropped file into the graph, migration 21). Store at schema v21.
- **Trade check gaps** answered by the investor (a T1 buy; unused Zerodha cash paid back to the bank): they close when that
  day's Console tradebook, funds ledger and the bank statement are added to `sources.toml` and the ledger rebuilt
  (`tools\build_pm_ledger.py` reads statement passwords from secrets `[passwords]`, the investor's choice).
- **Git history** rewritten 2026-10-17 (list names and figures removed from every branch; research-archive link
  03f756e intact); the pre-rewrite bundle is deleted.
- **Depth recordings** for `pflab pm impact` (S41) still to do: after `tools\kite_login.py`,
  `.venv\Scripts\python tools\kite_depth_record.py --wait-open --minutes 60` on a weekday before 09:15.
- **Switch-on** (The investor's call, after the build): task registration, the always-on bot, the 10 held alerts, backup
  target. Remaining A7 sessions: S47 pass 2 if needed, S48 "who is buying" study.

**Overnight run** (unattended, network-tolerant): `powershell -ExecutionPolicy Bypass -File tools\overnight.ps1
-DeepAll` (every list name gets a deep note; without it only names with changes). About 3.5 hours on 2026-10-17.

Built and accepted on the investor's real data: S4 (Kite + Console), S5 (CAS), S6 (bank statements), S8 (prices,
NSE + BSE), S12 (gains = Console), S14 (net worth), S19 (IPO), S33 (FDs), S34 (dip-rule study + live safety
checks), S35 (guards, surveillance, alerts; built, runner not registered), S36 (Monte Carlo + frontier),
S37 (`pflab ask` centre), S38 (knowledge graph, 3D view, Obsidian vault, `pflab list add`). Telegram works
(token and chat id in secrets; one test message sent); 10 alerts sit in the outbox, held at the investor's request.

**2026-10-16: S39 done** (branch `pm/s39-pairs-trading`). Crash-risk choice settled by the investor (local session
notes; targets.toml updated, simulate and deploy re-run). Dip-rule amendment 1 re-run: same rule, return edge
fragile (addendum in `docs/research/dip_rule_results.md`). Pairs study (`docs/research/pairs_*.md`): FAILS its
pre-registered rule; unused (the pair command was removed, the investor 2026-10-16). Month-end F&O futures are on disk
(`data/fo_bhavcopy`, 225 files). **S40 done** (`docs/research/hawkes_*.md`): market falls cluster (passes);
market state (calm/elevated/high, amendment 1) in guards, propose and ask; one message per state change.
**S41 built** (`docs/research/lob_simulator.md`): engine, Hawkes-driven flow, Kite depth recorder,
`pflab pm impact` (measured from recordings; none recorded yet: The investor runs `tools/kite_depth_record.py`).
**S42 built, evaluation pending** (`docs/llm/model_eval_12gb_protocol.md`): 6 candidates + Laya registered;
routing, guarded answers, extraction, materiality, latency; `pflab llm eval12 | decide12`; `pflab list add`
prints a research brief (facts-only until a model is chosen).

2026-10-15 later: all local models deleted at the investor's request (PLAN A6); `pflab ask` is facts-only until
S42's pre-registered evaluation picks a model for the 12 GB GPU. Raw files in `new/` stay LOCAL for now (his
decision; gitignored, never pushed).

**Read also (local, personal, never committed): `PFLAB_PM_DIR/session_notes_2026-10-15.md`**: decisions made,
the model plan as discussed, and the pending crash-risk choice with its alternatives table.

Open decisions for the investor (ask, do not assume):
- Models: none on the PC (Ollama empty; D:/hf-cache confirmed gone 2026-10-15). S42 picks and the investor downloads.
- Target risk: settled 2026-10-16 (his choice is in the local session notes, not here).
- Data gaps: three list names' results are not in BSE's results feed (lenders, new listing): safety shows
  "unknown"; a lender-format source is needed.
- When he switches the system on (only after everything is built, his choice): `.\tools\register_tasks.ps1 -WhatIf`, then without `-WhatIf`; the model(s) chosen by the S42 evaluation (no model is installed now); GKG backfill
  `.venv\Scripts\python tools\collect_daily.py --days 7 --sources gkg` then `pflab kg build --gkg-since <date>`.

## The investor's input list (grows as sessions are built)
- Backup target (external drive or Google Drive folder): needed by S9's backup job
  (built disabled).
- `python tools/collect_daily.py --days 25` from `D:\portfolio_lab` (prices stale
  since 2026-09-16).
- Decisions on SGB premature redemption: settled by the investor 2026-10-06 (stays taxable).
- S8 acceptance (every held ISIN priced <= 1 session): needs your holdings (S4/S5 imports) and a fresh `python tools/collect_daily.py --days 25`; then `pflab pm prices --refresh`.
- S11 acceptance (ledger qty = Kite qty across every action since May 2026): needs S4's Kite holdings/tradebook; until then actions are tested on synthetic histories and the real KOTAKBANK 2026-01-14 ISIN change/5:1 split.
- S10 (optional): physical gold holdings (weight, purity, purchase date, price, making charges) if any; SGB/bond holdings need their terms entered (SGB issue price/dates from RBI; bond coupon, frequency, day count from the issue document).
- S14 acceptance (matches a spreadsheet check on real data): needs the real ledger (S4/S5 imports) and a spreadsheet of your holdings to compare.
- S12 acceptance (FY2026-27-to-date gains = Zerodha Console tax P&L and the CAMS capital-gains statement): Console tax P&L (and tradebook) since May 2026, CAMS capital-gains statement; also any capital losses carried forward from your filed returns, and 31-Jan-2018 FMVs only if you hold pre-2018 equity.
- S13: your other income (if any) and age bracket for the tax estimate; old-regime deductions only if you want a fair old-vs-new comparison (80C, 80D etc.). Regime choice stays yours.
- S16 acceptance (look-through for every held fund, or category-only with a reason): the AMC monthly portfolio .xlsx for each mutual fund/ETF you hold (download from the AMC site; load with `pflab pm lookthrough --fund <ISIN> --file <xlsx> [--sheet ..] [--as-of ..]`), once the holdings are known (S4/S5).
- S24 acceptance (a held company's last 8 quarters load): needs your holdings (S4/S5); then `python -m pflab.cli pm results --scrip <BSE code> --pull` per company (live pull works; tested on an unheld company).
- S19 acceptance (a past IPO application replays): your past IPO applications, if any (IPO name, bid lots and price, date, UPI/ASBA bank account, allotted quantity and amount, listing date), or say there are none.
- S17: set your target allocation and bands in configs/targets.toml (target weights per bucket summing to 1, soft and hard bands, and which ISIN each bucket's new money buys, e.g. the Momentum 50 index fund for equity_fund). Until you do, `pflab pm propose` refuses. Also tell me your monthly contribution if not Rs 50,000.
- S20: a watchlist of names to watch for filings alerts, in configs/watchlist.toml (alerts are off until it, or your holdings, name something).
- S9 (acceptance: a test alert arrives; a missed day is caught up): (1) create a Telegram bot with @BotFather, send it a message, then put token and chat id in %USERPROFILE%\.pflab\secrets.toml under [telegram] token = "..." and chat_id = "..."; test with `python -m pflab.cli service test-alert`. (2) review then run from D:\portfolio_lab: `.\tools\register_tasks.ps1 -WhatIf` and then `.\tools\register_tasks.ps1` (registers one task 'PFLab Tick': every 15 min, at logon and at wake; remove with Unregister-ScheduledTask -TaskName 'PFLab Tick'). (3) set the backup target: `setx PFLAB_BACKUP_DIR <folder>` (external drive or Google Drive folder, outside D:\portfolio_lab\pm) or edit configs/service.toml. Check with `python -m pflab.cli service status`.
- S4 (acceptance: holdings from Kite equal ledger holdings): Kite Connect app key and secret (Rs 500 plan; redirect http://127.0.0.1:<port>/kite/callback; put in secrets.toml under [kite] api_key, api_secret); Console tradebook CSV and tax P&L since May 2026; contract-note PDFs/XMLs (PAN password) so charges can be loaded; a daily Kite login (dashboard button, S30). Contract-note parser is deferred: no public sample exists to build it against.
- S5 (acceptance: MF holdings equal CAMS closing units; dormant demat appears as an account): the latest CDSL CAS and the CAMS/KFintech DETAILED statement since inception (manual PDF downloads) plus their passwords; tell me which demat is the old dormant one (its DP/client id) and any cost/purchase dates you have for holdings that have no history.
- S6 (acceptance: every credit since May 2026 classified or listed): your SBI statement export since May 2026 (CSV or XLSX from net banking, with the Txn Date / Description / Debit / Credit / Balance table); the bank rules in configs/bank_rules.toml are starting patterns that need tuning on it.
- S21: pull the 27B research model so its smoke test can run (17 GB download, about 30+ minutes, your job): `ollama pull qwen3.5:27b`; then `python -m pflab.cli llm smoke --model qwen3.5:27b` (needs about 2 tokens/s or more). Then the pre-registered evaluation (LONG, run overnight; protocol in docs/llm/model_pick_protocol.md): `python -m pflab.cli llm evaluate --role classify --model qwen3.5-9b-16k` then `python -m pflab.cli llm evaluate --role research --model qwen3.5:27b`; I record the decision with the rule fixed beforehand. Graphify trial: say yes only if you want a Claude Code skill installed (deferred).

## State
- Old research project: only on GitHub (`origin/research-archive`, tags `lock/*`, `shelved/2026-10-01`).
  Rules: CLAUDE.md #1; hooks in `.githooks/`. Nothing was copied out of it in this build (S0 only).
- Built (13 migrations in `pm/store.py`): `pflab.pm` (store, secrets, instruments, prices, bonds, gold,
  estimate, lookthrough, costs), `pflab.ledger` (events, lots, cash, book, corporate_actions, ipo,
  reconcile), `pflab.tax` (rules, gains, income, proposed, report), `pflab.calc`, `pflab.risk`,
  `pflab.plan` (targets, rebalance, monthly, journal), `pflab.monitor` (event_reaction, falls, filings),
  `pflab.fundamentals.pit`, `pflab.ingest` (kite read-only, tradebook, cas, bank), `pflab.service`
  (jobs, telegram, backup, health), `pflab.llm` (client, guard, registry, budget, graphs, evalset, smoke),
  `pflab.knowledge` (okf, attest). CLI: `pflab pm init|instruments|prices|risk|tax|results|lookthrough|
  propose`, `pflab service tick|run|plan|status|test-alert|backup`, `pflab llm models|smoke|evaluate`,
  `pflab knowledge <dir>`.
- Ledger db: `D:\portfolio_lab\pm\ledger.duckdb` (instruments and AMFI schemes, prices to 2026-09-16,
  NAVs, gold rates; no events yet: no real holdings imported).
- Not done on purpose: no Task Scheduler entry registered (`tools/register_tasks.ps1` is for the investor); backup
  job disabled until a target is set; no secrets file; contract-note parser deferred (no public sample);
  Graphify trial deferred; the 27B model is registered but not pulled.
- Open tax items: PLAN §6 (S12/S13 resolved most against the Acts' gazette text).
- Not decided: whether `backtest/` retires into a `legacy/` package; GitHub branch protection (unavailable on
  a free private repo).
- Dead code awaiting the investor's OK to delete: `tools/reconcile_events.py` and `pflab.data.experiments_dir`;
  empty `src/pflab/ranker/`, `readers/` folders.
- Still migrated-but-unrunnable: `tools/a1_read_events.py` (S22), `tools/probe_a5_valuation.py`,
  `tools/probe_bse_results.py` (S24 uses its endpoint through `fundamentals/pit.py`), `theses/lock.py`
  (rewrite in S25).
