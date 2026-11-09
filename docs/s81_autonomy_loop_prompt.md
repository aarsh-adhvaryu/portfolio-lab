# S81 — The autonomous decision loop: core + satellite, selling, the knowledge graph, the US leg (overnight, unattended, must end GREEN)

You are the development session for `portfolio-lab` (package `pflab`), running **locally on his PC** in the workshop `D:\portfolio_lab` (Windows, PowerShell,
`.venv`, real Ollama, Docker, Kite). Read `CLAUDE.md`, the STATUS block at the top of `docs/PLAN.md` "What remains", `docs/KG_AUDIT_S80.md`,
`docs/CUT_PLAN_S80.md`, and only the parts of `docs/BUILT.md` you need. Branch `pm/s81-loop` from `main`.

I am asleep and will not answer anything. Do NOT stop to ask and do NOT wait for a "go". Decide on the defaults written here, record each decision as a dated
amendment, carry on. The session ends when everything is done or at the 8-hour hard stop.

## Why this session exists (read first)
v2 is wired but starts frozen. `baseline_v1` trades only the 8 names already held and, with no active allocation target, holds "the class mix the book has now";
nobody proposes an allocation any more; a lab policy can act only after 20 shadow sessions and a 2-point return-only index rule that rewards risk-taking; selling is
only band rebalancing; the knowledge graph is off; the US leg is data only. This session makes the system decide and act by itself every close, sensibly from day one,
with its active bets sized by earned evidence.

## 0. His decisions (2026-11-09): record as amendments A48–A55 in PLAN.md and rewrite the matching lines of CLAUDE.md (permanent, not a session exception)
- **A48 Core + satellite.** The book is a CORE (index ETFs such as Nifty 500 / Nifty 50, gold ETFs, international ETFs listed in India) plus SATELLITE sleeves:
  `longterm` (stock picks, months to years) and `swing` (days to weeks). **Intraday is dropped as a strategy** (no edge for a laptop on a retail feed after
  costs; no minute history to test). Minute data is kept only to time entries and exits of the other sleeves (avoid the opening spike, near VWAP, volume context).
- **A49 The strategist owns the system's allocation.** It proposes the target (asset classes, sectors, sleeve shares) with reasons through a lab tool; code checks
  it against the rails and the sleeve caps; the lab tests allocation variants like any policy, including "index only"; the same promotion rule adopts it; re-examined
  at every weekly session. His `targets.toml` stays his and is never changed.
- **A50 Promotion.** (a) The return-only "within 2 points a year of the Nifty 500" clause is replaced by a two-dimension rule against the index over the history
  window: pass if (return lag <= 2 points AND worst fall no deeper than the index's) OR (return lag <= 4 points AND worst fall at least one third smaller). Compare
  after tax and charges on BOTH sides (the index held as an ETF with its own charges and the tax of a buy-and-hold). (b) "Hold the index ETF" and the
  allocation-only variants are always lab candidates, so when nothing beats the index the system owns the index. (c) A **probation slice**: a variant that clears the
  history screen and the once-only 2018–2021 check trades a satellite slice of 5% of the book at once; the slice grows to 10% and then 20% while its live record is
  not worse than the champion's over 20 and 40 sessions, and is withdrawn automatically when it is worse. Shadow alone no longer blocks acting.
- **A51 Selling is code.** Every position carries an exit plan from its entry (target, stop, time stop, thesis break, tax boundary). Tax-and-risk selling in the
  core and long-term sleeves: book up to the yearly long-term exemption (Rs 1,25,000) of long-term gains and buy back (cost price reset); harvest losses to offset
  gains; do not sell a winner within the last weeks before 12 months unless a stop fires; trim names and sectors over the rails; sell on a thesis break. Every sale is
  scored after tax against holding the same money over the same days. Swing sales are scored the same way and the swing sleeve grows or shrinks by that score.
- **A52 Knowledge graph rebuilt on the agreed design** (`KG_AUDIT_S80.md`): three layers (facts by ISIN from structured sources; relations by a named rule;
  events attached only by a confident rule); nothing without an ISIN, a source and a date. Scope: his holdings, his list, the names the system finds itself, India and
  US; news back one year on D:; article text collected and read by the LOCAL model only; filings with no dissemination time are LEFT OUT. A **position layer** holds
  each holding's lots, cost, days to 12 months, unrealised gain, exemption used this financial year, exit plan and linked storylines. It switches ON only when its
  nightly audit passes, and must earn its place through a registered study (rule 10).
- **A53 The US leg.** Phase A now: international exposure through Indian-listed international ETFs inside the core, with a premium-to-NAV rail (these ETFs can
  trade well above their NAV when overseas limits bind; skip or trim above a set premium). Phase B: a paper US sub-book (USD, FX at the RBI/close rate, US
  calendar, US costs, Indian tax on foreign shares, US dividend withholding and its credit), with `market` passed through core, lab, rails and the close loop.
  Phase C (his real GIFT City money, Jan–Feb 2027) is NOT in this session. Tax rows for foreign assets: verify against primary sources in-session; until verified
  they are labelled estimates.
- **A54 It works during market hours, not only at the close.** Three rhythms per market: PRE-OPEN (read the US/global close, expected gap, the day's plan:
  conditional orders queued with their triggers); SESSION (a live loop every 5 minutes on Kite quotes and the day's minute bars: exit plans checked and executed
  at the live quote: stops, targets, thesis breaks from filings released during the session; swing entries when their trigger level is hit, timed by the minute
  data: never in the first 15 minutes, near VWAP, on volume; the circuit breaker; tactical views executed in session); POST-CLOSE (the full loop of B6: core and
  long-term rebalancing, allocation, scoring, learning) and DEEP (lab, strategist, KG, storylines). Session fills are paper fills at the live quote plus a spread
  and slippage model by liquidity, never better than the quote. **No same-day round trip in a name** (a buy and sell of the same shares on one day is taxed as
  speculative business income in India and is the dropped intraday strategy): an exit on the day of entry waits for the next session unless its stop fires.
  Without a Kite login the session loop says so on Today and Telegram, and only post-close work runs.
- **A55 Function first, cost later (his words, 2026-11-09).** Until the system is proved working, no internal spend throttle may stop a function: the
  strategist's "wasted session halves the budget" and "8 weeks without a win halves the budget" rules are recorded but NOT applied during the first 4 weeks after
  this release; the per-session cap is Rs 300; triggers are not rationed by spend. His monthly cap (Rs 2,500) stays the only hard limit, every call is still priced
  and logged, and the screens show spend by use, so cost and token work can be done later from real numbers.
Rules that STAY: point-in-time; 2022–2025 spent; ISIN key; no trading path (paper only, Kite read-only, no GTT); privacy; one store writer; engine tests unchanged;
his targets untouched; the kill switch; the rails (company 10%, sector 25%, ETF 35%, no F&O, no borrowing, no shorting); the turnover caps.

## 1. Time plan (hard limits; check the clock at every item)
- **0:00–0:20 Setup.** Cap the GPU clocks yourself (admin): `nvidia-smi -lgc 210,2100`, `nvidia-smi -lmc 405,9001`. No sleep on AC: `powercfg /change standby-timeout-ac 0`,
  `powercfg /change hibernate-timeout-ac 0`. Close the app; back up the app's store. **Start the long runs in the background now:** the one-year news backfill
  (article level, text kept, scope as A52) to D:, and the Kite minute-bar backfill for the held, listed and core-ETF names. Kite's token expires about 6:00 AM:
  every Kite step runs before 5:30 AM.
- **0:20 to at most 5:00 Build**, in this priority order (parallel subagents for independent items, each owning separate files and tests; you integrate; commit each):
  **B1 → B2 → B3 → B4 → B6 → B6b → B5 → B7 → B8 → B9.** At 5:00 stop building whatever the state; an unfinished item is switched OFF behind its config switch
  (nothing else may depend on it) and recorded in PLAN.md "What remains" with the reason.
- **5:00 to at most 7:15 Test, fix, clean run** (phase T below).
- **7:15 to at most 8:00 Release and leave it running**, then the morning report.

## 2. Build
**B1 Core + satellite baseline (`baseline_v2`).** Hold the active allocation target by class and sleeve; inside the core buy and hold the index, gold and
international ETFs; inside `longterm` keep the held names risk-sized as today; the fall gauge cuts equity as today. Unlike `baseline_v1`, it may BUY the core ETFs, so the
book acts sensibly from the first close. Until the strategist's first allocation is adopted, use a default in `configs/core.toml` (core 60%, longterm 35%, swing 5%,
gold inside core 10% of the book, international inside core 10%; his to change) and record it as the system's starting target.

**B2 Allocation owned by the strategist (A49).** A lab tool `propose_allocation` (classes, sectors, sleeve shares, reasons); code checks; allocation variants and
"index only" run in the lab; adoption by the A50 rule; weekly re-examination is part of the weekly session. Replace the dead `paper/allocation.propose_allocation` caller.

**B3 Promotion (A50).** The two-dimension index rule (both sides after tax and charges); index-only candidates seeded in the lab; the probation slice (5% → 10% →
20%, automatic withdrawal); the screen on Today shows each challenger's slice and why.

**B4 The exit manager and tax selling (A51)** (`core/exits.py`). Exit plans stored per position at entry; daily checks at the close; tax rules (exemption harvesting
in the last quarter of the financial year and whenever the plan allows, loss harvesting, the 12-month guard, rail trims, thesis break); every sale scored after tax vs
holding; the reasons written by code. The exemption and rates come from the tax engine (dated rows), never typed into the policy.

**B5 The lab for swing (A48).** A daily step (not only month-ends); stop, target and time-exit orders; per-sleeve accounting and tax category (short-term 20%,
long-term 12.5% above the exemption, as the tax engine says); a slippage model by liquidity; each sleeve benchmarked against holding the index or cash over the same days.
Seed three registered swing variants (momentum continuation, pullback within an uptrend, post-results drift) as lab candidates only; the strategist may write more.
Pre-register `docs/protocols/s81_selling_swing_protocol.md` before any run (counts in the learner): does the swing sleeve beat holding after tax and charges over
2005–2017, with the shuffled-signal luck measure, and does exemption harvesting add after-tax return vs no harvesting.

**B6 The autonomous decision loop.** Wire every close, in code, in this order: events (KG, filings, news) → storylines → features per stock → each sleeve's policy
(champion, plus probation slices) → the exit manager → tactical views → construct and rails → the big-trade check → orders → scoring. New strategist triggers: a
thesis-break event on a held name, the harvesting window opening, a probation slice to grow or withdraw, an allocation drift beyond its band. **The chat can start a
strategist session** ("look into X"), inside the strategist's budget, replacing the lost background investigation; its note comes back into the chat.

**B6b The market-hours rhythms (A54).** `core/session.py`: the pre-open plan (conditional orders with triggers, from the policies, the exit plans and the views); the
5-minute session loop on live quotes (exits, swing entries with minute-data timing, thesis breaks from in-session filings, the breaker, views); fills at the live quote
with the spread and slippage model; the no-same-day-round-trip guard; every check and fill recorded with code-written reasons and shown live on Today. The post-close
loop (B6) then sees what happened in the session. A replay mode feeds recorded minute bars through the same code for tests and drills.

**B7 Knowledge graph (A52).** Build the three layers and the position layer on the agreed design and scope; the nightly audit as code (every node has an ISIN, a source
and a date; zero point-in-time violations; at least 95% of events for held and listed names linked to an ISIN; duplicates under 1%; a rebuild from the raw files is
byte-identical; a sample file for hand-checking). The graph's switch turns ON only if the audit passes; otherwise it stays OFF and the morning report says which check
failed. Events on a held ISIN feed B4's thesis-break check and the storylines. Register the "graph earns its place" study (storyline evidence attached correctly and
storyline predictions holding more often with graph facts than without); it is judged later on live data.

**B8 US leg (A53).** Phase A: the international core ETFs, their premium-to-NAV series and rail. Phase B: the paper US sub-book with `market` through core, lab, rails and
the close loop, on the US close (IST morning), FX, costs, foreign-asset tax rows verified from primary sources (labelled estimates until verified), dividend
withholding and its credit. If phase B is not green by 5:00, it ships OFF.

**B9 Clean-up.** Delete the writer-less code (provenance credit, the keeper's predictions, the proposals' scorecard claims, the learner's suggestion rules) and any of
`hq/cases`, `hq/board`, `hq/roster`, `hq/scorecard`, `hq/keeper` that nothing reads (check the readers first). Re-write tests for behaviour that still exists and
lost its tests in the cut (the circuit breaker cases, the daily look, the budget reset). Fix the Research overview text so it describes v2 (the full UI redesign is his,
later). The five protected engine suites stay unchanged.

**Parked for his UI redesign (do not build):** Telegram as a full personal agent (conversation, PDFs, links, voice notes, forwarded alerts) and the Tijori
cross-check. The existing Telegram messages and questions stay as they are. Record this in PLAN.md "What remains".

## 3. Phase T — test everything once, fix everything once, run clean
- **Step A, test all, no fixing:** the full suite; privacy grep; drills on a synthetic profile with an injectable clock (kill -9 mid-close, off Friday→Monday, off 10
  days, network down, Ollama down, Docker down, Kite logged out, budget exhausted, a failing champion falls back to the baseline, a probation slice withdrawn); an
  accelerated run of 10 sessions with a weekend (allocation proposed and adopted, core ETFs bought, an exit plan firing, a harvesting sale and buy-back, a swing
  trade opened and closed and scored vs holding, a thesis-break sale from a KG event, a US sub-book close if B8 phase B is on); a **replayed market day** of
  recorded minute bars through the session loop (a stop hit mid-session and filled at the replayed quote plus slippage, a swing entry on its trigger after the
  first 15 minutes, a same-day exit held to the next session, a filing released mid-session breaking a thesis, the Kite login lost mid-session); every B item's
  real path once on this PC.
  Every problem goes into `docs/s81_test_findings.md`.
- **Step B, fix all in one pass** (root causes, a test each). **Step C, run clean once**; repeat C only for what is still open, inside the time.
- **Green means:** suite passing (only documented environmental failures); engine tests unchanged; privacy clean; drills pass; accelerated run clean; every switched-ON
  item passed its real path. Anything not green is switched OFF, never released half-working. Never weaken, skip or stub a test. If `main` cannot be green by 8:00, do
  not merge: the app stays on the last good tag.

## 4. Release and leave it running
Merge to `main`, tag, start the app from its icon so it takes the tag; run `pflab verify --app D:\PortfolioLabApp --wake-check` and `--hour-check`; confirm the next close
will run the loop (the phase 1 gate of 5 real closes under 2 minutes counts from tomorrow; the app reports it on Telegram after the fifth). **The first live
market day checks itself:** at 15:45 IST the app sends him on Telegram what the pre-open plan was, how many session checks ran, what fired and filled (with the quote
and the slippage charged), and what the post-close loop did; anything that did not run is named with its reason. Paid calls tonight at most Rs 1,000 (A55: function
first; record each). If the GPU drops off the bus: fall back, mark GPU checks unverified, continue, report it first.

**The autonomy check (code, on Today and on Telegram after the fifth real close, then weekly).** It measures autonomy instead of claiming it, over the period, with
no human action counted: closes run by the loop and their outcome (traded or held, each with code-written reasons); allocation proposals made and adopted;
strategist sessions that started on their own triggers, with lab runs, challengers, probation slices granted, grown or withdrawn; exit-manager actions by kind
(target, stop, time, thesis break, harvesting, trim) each scored after tax vs holding; storylines opened, updated, confirmed or broken; views issued and scored;
questions sent to him and answered or defaulted; rupees spent per lab run and per promoted change. A week with no AI-started session, no adopted change and only
"held" closes is flagged as NOT AUTONOMOUS with the reason (no trigger fired, budget, a gate, a failure), so a frozen system can never look busy.

## 5. Morning report (Telegram AND the top of PLAN.md "What remains"; 15 lines or fewer, plain words)
Green or not and the tag; what the book will do in tomorrow's session and at the close (the starting allocation, what it will buy or sell and why); what was built and what is OFF and
why; the KG audit result; the swing and harvesting study status; the US leg state; paid spend; GPU; the one thing I must do (Kite login), if any.

---
## Appendix: his answers and the clock (2026-11-09 night, before the unattended run; they override the text above where they differ)
- **Time:** he gave until 06:00 IST on 2026-11-10 (not 8 hours). Kite's token expires 06:00: every Kite step ends before 05:30. Plan: setup 22:45-23:15; build until 03:15; test, fix, clean run 03:15-05:00; merge, tag, release, morning report 05:00-05:45. Anything not green is switched OFF, never released half-working; incomplete items are covered in a later session.
- **Path to the core (A48):** gradual and tax-aware: new cash (top-ups up to Rs 50,000 a month) and any sale proceeds go to the core ETFs first; stocks are sold only for the A51 reasons (tax harvesting, rails, stop, thesis break). No forced taxable sell-down to reach 60/35/5.
- **Sleeve caps (A49), enforced by code on every proposed allocation:** swing at most 20%, longterm at most 60%, core at least 30% of the book. The company 10%, sector 25%, single-ETF 35% rails stay.
- **Scope:** nothing is dropped up front. The US sub-book (B8 phase B) is a necessity; if it cannot be finished and green, ship it OFF and leave accurate, primary-source-checked research on the US leg (`docs/US_LEG_S81.md`) so it can be finished properly later.
- **News (A52):** capped text collection: about 150 names (held, listed, core ETFs, names the system finds itself), at most 20 GB on D:, polite rate limits, robots.txt respected, a page that refuses is skipped and counted; text stays on this PC and is read by the local model only.
- **Facts about tonight:** tomorrow Tue 2026-11-10 is an NSE holiday; the first live market day is Wed 2026-11-11 and needs a fresh Kite login that morning. The app is closed; the live store is backed up at `D:\PortfolioLabApp\backups\ledger_before_s81_20261109_2252.duckdb`. The installed app is on v2026.11.09.2. Real-path runs use a COPY of the store, never the live one. The shell is Administrator (GPU clocks capped, no sleep on AC set). A minute-bar top-up from Kite is already running in the background (log `D:\s81_scratch\kite\backfill.log`); minute bars for 461 NSE names and indices already exist from 2015 to 2026-11-06 under `D:\PortfolioLabApp\data\bars_1m\IN` (core ETFs are not among them).
- **`pflab verify --wake-check` and `--hour-check` cannot be done unattended** (they need the laptop to sleep and Claude Code to be closed): they stay his; record that.
