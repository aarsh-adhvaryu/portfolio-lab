# Roadmap — E1 to the final system

Where this file lives in the repo: `docs/ROADMAP.md`. It is the map, not a
charter. Each experiment gets its own charter in `docs/strategies/` before it
runs; this file only says what the experiments are, in what order, what each
must prove, and what the finished system looks like.

**Forward order (2026-10-01, session 13): the gap ladder (diagnostic)
decides between one final stack experiment and the fallback build
(`docs/reviews/gap-ladder.md` §2). Still listed, none before the ladder is
read: E2-D1, E2-D2 (parked until E2-D1), E6-V.** Done: E1
(INCONCLUSIVE), E1b (INCONCLUSIVE), E1-P (INCONCLUSIVE), E1c (REJECT), E1d
(ADOPT), E2-A (REJECT) — final, re-classified 2026-09-29 after the full
regression; **E5-A A0 (INCONCLUSIVE) and E3-R (REJECT), 2026-09-30**
(`docs/reviews/E5-A0-verdict.md`, `E3-R-verdict.md`).
**Adopted stack: E1 + E1d (2026-09-29).** Closed, not run: E2-C. Off the list:
E4, any stop-loss, and E3-R (REJECT 2026-09-30) (E1-P's N1 failed validation). Nothing skips the gate.
The gate's arithmetic lives in `docs/strategies/GATE.md`; each experiment
has its own charter in `docs/strategies/`.

**Two decisions, two documents.** `GATE.md` decides **adoption** — whether a
change joins the stack. From **2026-09-21**, `docs/MANDATE.md` §3 and §5
decide **ADVANCE** — the sealed reveal, the live paper year, real money —
in place of E1 §13's C1–C4. Recorded verdicts are unchanged.

---

## Decisions, 2026-10-01 (session 13) — E5-A closed; four cut

**E5-A closed** (Aarsh): verdicts accepted, no new families, A4 not pursued
(E5-A §14). **E2-B, E1-S, E2-E and E3 are removed from the forward list.**
The gap diagnosis's "selection" row is relabelled "picks, frictionless and
fully invested". Next is the **gap ladder** (diagnostic, not an experiment):
if trend brake plus six-buy cap explain at least 60% of E1d's 5.67 pp
development gap to B5, Aarsh may register one final stack experiment on that
component; otherwise research ends and the fallback (`docs/plans/fallback.md`)
is built.

---

## Verdicts, 2026-09-30 — A0 INCONCLUSIVE, E3-R REJECT

**E5-A A0: INCONCLUSIVE** against E1 + E1d. Development (2011–16) holds
G1–G4 (+1.90 pp CAGR, 18.48 pp shallower); validation fails G2 (−18.70 pp
CAGR for 16.27 pp shallower) and G3 (0 / 8). Mandate not met. **E3-R:
REJECT** — G1 and G2 fail in both periods (−1.24 / −6.59 pp CAGR). E3-R
leaves the forward list. The E5-A families proceed against the frozen A0
(E5-A §3, §10): A1 and A3 to ready-to-lock, A2 readiness only.

---

## Order change, 2026-09-28 — E5-A next

On Aarsh's instruction (E5-A readiness §4 D1, following the audit). E5-A
tests information families one at a time against a price/volume control
(A0), so it answers the question every later event experiment asks, once,
under one procedure. A4 (company news) is **parked, not dropped**: GDELT GKG
starts 2015, after the development window opens. Everything else keeps its
relative order.

## Order change, 2026-09-25 — E2-A before E3-R, on what E1d showed

On Aarsh's instruction, after E1d's INCONCLUSIVE verdict
(`docs/reviews/E1d-verdict.md`).

**The reason, recorded before either runs.** E1d changed nothing but the
price signal, and what it bought was a shallower drawdown paid for with
return — the same trade in both periods, with only the sign of the bargain
set by the decade. Development's crashes made the purchase cheap (+2.58 pp);
2017–2021 punished being out of the way (−3.09 pp for 3.10 pp of fall), and
G2's asymmetric tolerance refuses a one-for-one trade of that kind.

**E3-R is a drawdown device too**, and a more direct one: its cautious gear
takes equity down toward half. It will meet exactly the same G2 arithmetic,
and on the same validation years that just refused E1d's version of the
trade. That does not make E3-R wrong — its high gear is supposed to pay for
the cautious gear — but it does mean E3-R is now the harder question, not
the easier one.

**E2-A is the different kind of change.** It removes *names* rather than
*exposure*: a company with a distress flag leaves the universe, and the
capital goes to another holding rather than to cash. So it is not the
return-for-drawdown trade E1d and E3-R both make, and it is the one
remaining route to MANDATE §2's "no meaningful chance of permanent loss"
that does not cost market exposure to get there.

Two further reasons it should go first: **its hypothesis was not formed on
the test years** — unlike E1d's, which came from E1c's S6 on 2007–2021, so
§7 applies to E1d and not to E2-A — and **its data is complete**: BSE
announcements 2010-01-01 → 2026-09-22, 6,109 of 6,109 days count-verified.

---

## Order change, 2026-09-22 — E1d first, while the BSE backfill runs

On Aarsh's instruction. E2-A, the permanent-loss guard, needs BSE
announcements from 2010; only 2026 had been collected, and the backfill
(started 2026-09-22, four idempotent workers, ~20–22 h) is the long pole.
Rather than wait on it, **E1d** (`docs/strategies/E1d.md`: E1c's
volatility-scaled score as E1's ranking signal) and **E3-R** (the risk
gears), which need no new data, go first. **E2-A runs as soon as its data
is complete**, then the rest as before.

## Order change, 2026-09-21 — the mandate takes effect

On Aarsh's instruction, with MANDATE §3 confirmed the same day. The order
follows MANDATE §4 (the permanent-loss guard, E2-A, first after E1c,
because the universe is the whole Nifty 500) and §9 (the risk gears, E3-R,
next), then the rest:

| # | experiment | what it is | charter |
|---|---|---|---|
| 1 | **E1c** | the momentum fund's own construction, through this engine | `E1c.md`, LOCKED |
| 2 | **E2-A** | firm-level red flags: the permanent-loss guard | `E2-A.md`, draft |
| 3 | **E3-R** | risk gears: cautious / normal / high equity exposure | `E3-R.md`, draft |
| 4 | **E2-B** | shock-exposure graph | `E2-B.md`, draft |
| 5 | **E1-S** | sector-trend cap (MANDATE §7): a sector below its 10-month average is capped at half weight | to be written |
| 6 | **E2-C** | event-intensity regime input | `E2-C.md`, draft |
| 7 | **E2-D** | positioning: bulk deals, insiders, promoters | `E2-D.md`, draft |
| 8 | **E2-E** | *named in the order; no charter or description exists yet* | — |
| 9 | **E3** | defensive sleeve during RISK_OFF | `E3.md`, draft |
| 10 | **E6-V** | value: operating cash flow yield — not chartered; **blocked on a historical fundamentals source.** Exchange XBRL resolves from 2018, operating cash flow half-yearly from 2020, no balance sheet. Routes: BSE XBRL probe for 2011-2017 (queued after the shareholding backfill); a licensed database such as CMIE Prowess, pending a point-in-time check. | to be written |
| 11 | **E5-A** | LightGBM on the cross-section | `E5.md`, draft |

**Off the list:** **E4** (IPO listing gains), and **any stop-loss**. E1-P's
N1 control beat the base row only in the period containing 2008 and cost
4.7 pp a year in validation, where the names it sold rose 9.5% afterwards.
E1-P itself was REJECTED on 2026-09-21.

## Order change, 2026-09-19 — E1c runs after E1-P

**Aarsh's instruction, 2026-09-19: E1c is slotted immediately after E1-P and
before E2-A.** Forward order is therefore E1-P, then E1c, then E2-A onward.

The reasoning that makes the slot coherent, recorded so the next session does
not have to re-derive it: E1c calibrates B3. Every experiment is judged partly
against B3 through E1 §13's C2, and E1c §6 is the one sanctioned route by
which C2 may be restated — downward, toward a number that can actually be
bought. A bar that may move should move before the experiments that are
measured against it, which argues for E1c early. It goes after E1-P rather
than before it because E1-P is already most of the way built, needs no new
data, and runs on E1 base either way; E1c's verdict cannot change E1-P's
comparison, only the B3 column both of them report.

E1c is a candidate base like E1b, so if it is ADOPTED, the re-run rule below
applies to it too: E1-P's verdict against E1 base stands as evidence and is
labelled as such.

## Order change, 2026-09-18

**E1-P runs now, against E1 base. E1b continues in parallel.**

E1-P needs no new data: its rule attaches to the `defer_exit` hook that is
already in the engine, and its window is E1's. E1b needs a point-in-time
index membership table, which is a data build with its own failure modes and
its own timetable. Blocking a ready experiment on an unready dataset buys
nothing.

If E1b is later ADOPTED, **E1-P is re-run on the E1b base before its verdict
is final**, because a verdict is a property of the stack it was measured
against, not of the experiment alone. E1-P's result against E1 base stands as
evidence in the meantime and is labelled as such.

E1b's membership build is time-boxed to three working days from 2026-09-18
(to **2026-09-23**) for the listing cap and the Internet Archive captures. If
the check has not closed by then, the fallback is to take the first year it
passes as the development start, re-run E1 base on that window, and record
both in §4 and §15.

## The gate (applies to every experiment after E1)

The gate decides adoption only. ADVANCE is decided by `docs/MANDATE.md` §3
and §5 from 2026-09-21 (see `GATE.md`).

An experiment is one change on top of the current adopted stack. It is
tested under the same periods, the same nine-row sweep, the same after-tax
liquidation-adjusted metrics and the same verdict arithmetic as E1. It is
adopted only if, in **both** development and validation, it improves
after-tax CAGR or max drawdown without worsening the other, and the
improvement survives at least six of the nine sweep rows. Adopted changes
stack in adoption order. The sealed period is never used to choose.

Every experiment gets a charter before its first run: rules, data, sweep,
success criteria, what it does not claim, change log. After the first run,
only the change log moves.

---

## E1 — Momentum SIP baseline (the thing everything must beat)

**Status:** VERDICT INCONCLUSIVE (2026-09-17). See `docs/notes/E1-diagnostic.md`.
**Charter:** `docs/strategies/E1.md`

- Universe: NSE stocks (instrument type STK, series EQ), top 500 by traded
  value, listed 12+ months, price above ₹10, keyed by ISIN, survivorship-free.
- Signal: 12-1 momentum. Hold 25, exit below rank 50.
- Cash: ₹50,000 a month into the largest shortfalls, at most six names, no
  selling to rebalance. Uninvested cash accrues 6%.
- Crash rule: Nifty 50 below its 10-month average → new cash waits, nothing sold.
- Costs: Zerodha delivery, STT both sides. Taxes: FIFO lots, 20% short,
  12.5% long above ₹1.25 lakh, cess, set-off and carry-forward, settled from
  the portfolio each April. Today's regime for every year.
- Benchmarks through the same engine: Nifty 50 TRI, Nifty 500 TRI (primary),
  Nifty 200 Momentum 30 TRI with 0.30% drag (the do-nothing alternative),
  equal-weight universe.
- Periods: development 2007–2016, validation 2017–2021, sealed 2022–2025,
  live paper from October 2026.
- Verdict: ADVANCE if 2 points a year over both Nifty 500 TRI and the
  momentum index fund, with drawdown no worse than Nifty 500 + 5 points, in
  both periods and six of nine sweep rows. REJECT if it fails Nifty 500 in
  both. INCONCLUSIVE otherwise.

**What E1 proves:** whether a simple, tax-aware stock rule beats what you
could buy in one click. If it does not, the rest of the roadmap becomes
research around an index fund, which is a legitimate and cheaper project.

**Remaining work:** rename verification and two §9 decisions (factor
handling on held lots, dividend double-count), engine + benchmarks +
artifacts + lookahead tests + random-walk control + sweep + classify, lock
the charter, development sweep, written review, validation sweep, verdict.

---

## E1b — E1's rules on the momentum index's universe

**Status:** **VERDICT REJECT (2026-09-18).** Complete; not in the forward
order. Verdict at
`experiments/E1b/sweeps/validation-4eaf560fb1319d16/verdict.json`, review at
`docs/reviews/E1b-development.md`. The membership build it was blocked on
finished and passes its exact-list check
(`docs/data/index_membership_finding.md`).
**Charter:** `docs/strategies/E1b.md` (LOCKED 2026-09-18)

- GATE G1 failed in both periods and G2 was violated in validation, where
  confining E1's rules to the Nifty 200 cost **10.73 pp** of CAGR. E1's
  2017–21 return came from small caps outside the Nifty 200; the universe
  drift the E1 diagnostic flagged was where the money came from, not a defect.
- E1 base therefore remains the stack, and E1-P is measured against it.
- Rule: E1's rules unchanged, on Nifty 200 constituents point-in-time, taken
  from NSE's inclusion/exclusion history. No turnover ranking.
- Judged by `GATE.md` against STACK = E1 base, and additionally reported
  against E1 §13 (C1–C4) because E1b is a candidate base.
- What it tests: whether E1's development gap to the momentum index fund came
  from the universe rather than the rules. E1 drifted to a median holding at
  turnover rank 340; the index draws from Nifty 200.

## E1-P — Patience

**Status:** **VERDICT REJECT (2026-09-21).** G1 failed in both periods and G2
was violated in validation (−1.04 pp CAGR, +3.02 pp drawdown). Verdict note
`docs/reviews/E1-P-verdict.md`. The tax saving was small and unstable; the
return cost of deferring was not. N1 (stop-loss) failed validation; N2
(profit-take) was expensive in both periods.

- Rule: a band exit is deferred when the lot is 9–12 months old and the
  name has only slipped to rank 51–100, so the sale crosses into long-term
  tax. Two negative controls (20% stop-loss, 50% profit-taking) measure what
  impatience costs. The live ledger records every override you were tempted
  to make.
- Judged by `GATE.md` against STACK = E1 base. Not a candidate base, so no
  C1–C4 half — the GATE verdict is the whole verdict.
- **The per-lot question was settled at the lock** (§3): the base rule and
  S4 use the OLDEST lot, because FIFO makes it the lot a sale realises; S5's
  minimum hold uses the YOUNGEST; partial-position exits are out of scope.

## E1c — The momentum fund's own construction, through this engine

**Status:** **VERDICT REJECT (2026-09-21)** — GATE G2 violated in both
periods. Note `docs/reviews/E1c-verdict.md`. The replication keeps about
half of B3 in development and nearly all of it in validation; C2 was not
restated.

- Rule: replicate the Nifty 200 Momentum 30 construction on E1b's universe —
  volatility-scaled 6+12-month momentum clipped at ±3, top 30,
  score-proportional weights capped at 5%, semi-annual rebalance with a
  one-month lag — carrying E1's SIP, costs, tax and cash sleeve.
- Judged by `GATE.md` against STACK = E1 base, and reported against E1 §13
  C1–C4 because it is a candidate base.
- **§6 no longer lets it move E1's bar** (amended 2026-09-19). E1c reports
  its gap to B3 and attributes what it can, but **may not restate E1 §13's
  C2**: free float exists in no dataset here, so the gap contains an
  unmeasurable weighting artefact, and a bar must not move on one. C2 moves
  only on a replication with real free-float weights. §6 now also requires
  base vs S1 (equal weight) as the bound on how much weighting matters.
  **No experiment may now change E1 after its lock.**
- **Declared data gap (§3):** free-float shares outstanding are not in the
  panel, so the fund's free-float tilt cannot be reproduced; weights are
  score-proportional instead, and S1 tests equal weight as the sensitivity.

## E1d — E1 with the fund's volatility-scaled score

**Status:** charter DRAFT (`docs/strategies/E1d.md`, Aarsh, 2026-09-21);
first in the order. Readiness: `docs/notes/E1d-readiness.md` — four small
pieces of code before its first run, no new data.

- Rule: E1c's score (6- and 12-month returns over their own volatility,
  z-scored within the universe, ±3 clip) replaces E1's raw 12-1 momentum,
  for ranking only. Everything else is E1.
- Why: E1c's S6 found, in both periods, that E1's raw signal earns about
  5 pp a year less than the volatility-scaled score on the fund's cadence.
  §7 records honestly that the hypothesis came from those same years.

## E2 — Event layer (four separate experiments)

**Status:** data collection running daily; charters written after E1's verdict
**Pre-definition:** `docs/strategies/E2.md`

Events move markets, but by month-end the move is in the price. The three
uses of event data below are the ones that can still add value at a monthly
horizon. None is a forecast.

### E2-A Firm-level red flags
- Rule: names with a red-flag announcement in the trailing 12 months are
  ineligible; a held name is sold at the next open on a new flag.
- Flags (frozen, corpus-tested): auditor resignation, enforcement action
  (SEBI/SAT/ED/CBI), insolvency (CIRP/IBC, schemes excluded), distress-level
  promoter encumbrance, rating downgrade, results delay, forensic audit,
  default, fraud.
- Data: BSE announcements from 2010 (dissemination timestamp as the key),
  NSE announcements added here.
- Testable on the full backfill immediately: thousands of events.

### E2-B Shock-exposure graph
- Nodes: companies, sectors, shock factors (Brent, USDINR, US 10-year, FII
  flows, India VIX, GDELT geopolitical intensity). Edges: rolling 36-month
  betas, estimated point-in-time.
- Rule: no shock factor's portfolio beta may exceed 1.5× the Nifty 500's;
  a buy that would breach it is skipped for the next candidate.
- What it tests: diversification across what can hurt you, not just across
  sectors. Judged on 2008, 2013, 2020, 2022 drawdowns.
- This is the knowledge-graph idea in its measurable form. The graph is also
  the explanation layer for the monthly memo.

### E2-D Positioning (bulk deals, insiders, promoters)
- Rule: names with net promoter/insider selling above 1% of shares
  outstanding in the trailing two quarters are ineligible.
- The Indian-equity analogue of on-chain whale tracking: exchange-published
  bulk/block deals, PIT disclosures, shareholding patterns.

### E2-C Event-intensity regime input
- Rule: GDELT tone and count plus India VIX replace the plain SMA-10 as the
  RISK_OFF trigger.
- Declared limit: eleven years of GDELT contain about four stress episodes.
  If adopted, it is adopted as a risk rule held on priors and reported as
  such, never as an alpha claim. Whipsaw guard: no more than one extra
  switch a year.

---

## E3 — Defensive sleeve (asset-class trend during RISK_OFF)

**Status:** data ready (ETFs typed in the panel by INF-prefix ISIN); charter after E2-A

- Rule: when RISK_OFF, the SIP goes to whichever of {liquid ETF, gold ETF,
  Nifty ETF} has the strongest 10-month trend, instead of always to cash.
- Requires an asset-class-aware tax module: gold and silver ETF short-term
  gains at slab, different STT, liquid ETF dividends at slab. This module is
  needed for live trading anyway, since the real cash sleeve will be a
  liquid ETF.
- Judged on drawdown and after-tax CAGR against E1 base (plus whatever E2
  adopted). This is the "opportunistic in a crash" goal in testable form.
- REITs and InvITs: parked. Few names, yield instruments, distribution tax
  needs attachment-level data.

---

## E4 — IPO listing gains with GMP

**Status:** **off the list (2026-09-21)**, on Aarsh's instruction. Kept here
as a record of the idea, not as planned work.

- Rule: apply at the retail cutoff to every mainboard IPO whose grey-market
  premium over issue price exceeds a pre-registered threshold on the last
  bidding day; sell at the listing-day close. No SME IPOs.
- Data: historical GMP snapshots (fragile, roughly 2019 onward), exchange
  subscription figures, listing prices from the bhavcopy.
- Metric: post-tax return on capital committed, counting lock-in days,
  against the same cash in the liquid sleeve.
- Honest prior: a small positive edge bounded by allotment probability, not
  by signal. Its value is being uncorrelated with E1.

---

## E5 — Learned signals (cross-section ML, then graph models)

**Status:** last; only after E1–E3 have verdicts

- E5-A: LightGBM on the cross-section predicting 1/3/12-month excess
  returns from point-in-time features (price, volume, factor exposures,
  E2 features), purged and embargoed cross-validation, replacing the
  momentum rank. Must beat the adopted stack under the gate.
- E5-B: Kronos (finance-native, MIT-licensed K-line foundation model):
  zero-shot row reported with a contamination caveat; retrained-from-scratch
  row with yearly cutoffs is the adoptable one.
- E5-C: TimesFM-3 zero-shot, research-only. E5-D: graph model over E2-B.
- LLMs: extraction and explanation only. Anything an LLM produces that
  feeds a decision is a timestamped feature, and the model's training
  cutoff is recorded so the lookahead tests can reason about it.
- Expected outcome, stated now: modest or no improvement over the factor
  baseline. That result is publishable and still counts.

---

## Live paper year (October 2026 → September 2027)

Runs in parallel with E2–E5 research. The month-end job produces the order
list from the adopted stack, places after-market orders via Kite Connect
Personal in paper mode, and reconciles intended fills against the next open.
The daily collectors keep running so the live window has full event data.

What the year proves: the machine works, slippage matches assumptions,
nothing peeked. What it cannot prove: alpha. Twelve observations do not.

---

## The final system

A private, monthly, tax-aware portfolio engine over Indian equities, running
against a Zerodha account, in which every component earned its place under
the gate.

| layer | what it is | comes from |
|---|---|---|
| Data | survivorship-free adjusted panel, corporate actions, dividends, announcements, GDELT, macro; daily collectors | Phase 1 |
| Graph | companies, sectors, shock factors, events; betas and flags as edges; also the explanation layer | E2-B, E2-A |
| Signals | momentum baseline; learned signals only if E5 earns them | E1, E5 |
| Constraints | red-flag exclusions, shock-beta caps, liquidity and position caps | E2-A, E2-B |
| Regime | SMA trend rule, or the E2-C composite if adopted | E1, E2-C |
| Defensive sleeve | trend-selected ETF during RISK_OFF | E3 |
| Portfolio construction | shortfall buys, band exits, no rebalancing sells, FIFO lots, tax in the objective | E1 |
| Side sleeve | IPO module on its own capital, if E4 earns it | E4 |
| Harness | sealed periods, sweeps, computed verdicts, content-addressed artifacts | Phase 0–2 |
| Execution | month-end order list, Kite after-market orders, ledger, monthly memo | Phase 4–5 |

Real-money decision: after the live year, using the sealed-history verdicts
and the live year's operational record, not the live year's return.

The two honest endings, both counted as success:

- **Top:** a measured, modest after-tax edge over the index with a smaller
  drawdown, run on your own money from late 2027.
- **Bottom:** proof that the momentum index fund plus a defensive sleeve is
  the best you can do, which stops you running code against your savings
  for no edge.

---

## Standing rules

1. The charter is law; changes go through the change log with a date.
2. Sweeps are stability checks, never menus.
3. Verdicts are computed, never typed.
4. One sealed reveal, in writing, journaled.
5. LLMs (including Claude Code) implement, test and report. They do not
   pick parameters.
6. A new idea mid-experiment goes into a new charter file, not into the
   running work.
