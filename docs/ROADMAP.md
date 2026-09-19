# Roadmap — E1 to the final system

Where this file lives in the repo: `docs/ROADMAP.md`. It is the map, not a
charter. Each experiment gets its own charter in `docs/strategies/` before it
runs; this file only says what the experiments are, in what order, what each
must prove, and what the finished system looks like.

Order is sequential: E1, E1-P, E1b, E2-A, E2-B, E2-C, E2-D, E3, E4, E5.
(E1-P and E1b swapped 2026-09-18; see the order change below.) Nothing skips
the gate. The gate's arithmetic lives in `docs/strategies/GATE.md`; each
experiment has its own charter in `docs/strategies/`.

---

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

**Status:** VERDICT INCONCLUSIVE (2026-09-17). See `docs/reviews/E1-diagnostic.md`.
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

**Status:** charter written; code ready; **BLOCKED on data** — see
`docs/data/index_membership_finding.md`. NSE publishes its
constituent-change circulars as PDFs from 2010 onward (68 of 98) and
names companies rather than symbols in them, so the point-in-time table
cannot be built until a PDF reader is sanctioned (CLAUDE.md 7) and a
company-name key is decided. Runs after E1's verdict, before E1-P.
**Charter:** `docs/strategies/E1b.md`

- Slotted ahead of E1-P because a universe change alters the base that every
  later experiment is measured against. E1-P's preparation stands and runs on
  whichever base survives E1b.
- Rule: E1's rules unchanged, on Nifty 200 constituents point-in-time, taken
  from NSE's inclusion/exclusion history. No turnover ranking.
- Judged by `GATE.md` against STACK = E1 base, and additionally reported
  against E1 §13 (C1–C4) because E1b is a candidate base.
- What it tests: whether E1's development gap to the momentum index fund came
  from the universe rather than the rules. E1 drifted to a median holding at
  turnover rank 340; the index draws from Nifty 200.

## E1-P — Patience

**Status:** charter written; runs right after E1's verdict, no new data

- Rule: a band exit is deferred when the lot is 9–12 months old and the
  name has only slipped to rank 51–100, so the sale crosses into long-term
  tax. Two negative controls (20% stop-loss, 50% profit-taking) measure what
  impatience costs. The live ledger records every override you were tempted
  to make.

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

**Status:** idea parked; charter only after E3; runs on its own capital sleeve

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
