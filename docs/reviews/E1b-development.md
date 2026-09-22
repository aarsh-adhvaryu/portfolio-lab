# E1b — Development review (2007-01-01 .. 2016-12-31)

Written before the validation sweep. No parameter proposals; the charter is
locked.

**Sweep re-run 2026-09-19** with the corrected equity/cash decomposition
(version 3) and per-row equity curves and trade ledgers persisted:
`experiments/E1b/sweeps/development-1996387124c166df/`. The original sweep
(`development-26b23d4fbc273fea`) is untouched and still on disk. **Every one
of the fourteen rows reproduced its CAGR and max drawdown to within 1e-12**,
so nothing below about the verdict changes; only the decomposition table in
"Requested extras" is new, and it replaces a table that was wrong.

## Against the gate (development only; verdict needs both periods)

| test | requirement | E1b vs E1 base | status |
|---|---|---|---|
| G1 | CAGR +0.5 pp or MaxDD −2 pp | +0.13 pp / −0.70 pp | not met |
| G2 | other metric within tolerance | met | met |
| G3 | G1–G2 in ≥ two thirds of rows | 5 of 14 | not met |
| G4 | turnover ≤ 2× | 1.16 vs 1.70 | met |

Against E1 §13, development: C1 +1.40 pp over B2 (needs 2), C2 −4.01 pp vs
B3, C3 met, C4 not met.

## What the numbers say

The universe change did what §3 intended and did not change the result.
Median turnover rank of holdings 82–146 (E1: 172–340); ADV skips 3.6% (E1:
16.0%); turnover 1.16 (1.70); tax drag 0.73 pp (1.34); short-term share of
gains 32.8% (66.2%). After-tax CAGR 9.47% vs 9.34%. Gap to the momentum
index −4.01 pp vs −4.14 pp.

Conclusion the hypothesis allowed for: E1's gap to the momentum fund is
not the universe. It is the rules.

## Findings

1. **Cash carry.** 40 of 156 months RISK_OFF, mean cash share 22.4% at 6%
   against a benchmark compounding at 13.5%. Rough attribution: ~1.7 pp of
   the 4 pp gap. The seat belt's price in a decade that recovered.
2. **Signal.** S1 (9-1 lookback) 11.86% / 48.3%; S7 (sell-to-cash) 11.24% /
   49.2%. Same names, different rules, different money. S1 was flat in E1's
   sweep, so the evidence is inconsistent across universes; not promotable,
   but sufficient to charter a signal experiment after the verdict. The
   benchmark uses 6- and 12-month volatility-scaled momentum, 30 names,
   semi-annual rebalance.
3. **Measurement resolution.** S12 (latest-possible inclusion) 11.61% vs
   base 9.47%: a 2.14 pp bracket from membership timing alone, wider than
   any effect in this sweep. In 2007–2011 E1b cannot distinguish "no better
   than E1" from "2 pp better." S13 (published Nifty 200 only, 2012–2016):
   E1b 12.77% / 20.7% vs E1 base 11.40% / 30.5% on the same window, +1.37 pp
   and −9.8 pp drawdown. The clean years favour E1b; the proxy years blur it.
4. **Trend filter** worth +1.1 pp and 17 drawdown points here (S6: 8.33% /
   71.9%), less than in E1 (+4.3 pp) because large caps fell less in 2008.
5. **Thinning at the end of the window persists**: 14.8 names held in 2016
   with zero ADV skips that year, so the cause is not liquidity. Recorded.
6. **S10 (Nifty 500 index members) 3.91%** with 104 skips, turnover 2.0,
   76.5% short-term gains, against 9.34% for E1's own 500-name universe.
   Not credible without a data check on the Nifty 500 membership table
   (largest guessed-window share, one exact-list miss).
7. **B4 recomputed on the E1b universe: 8.54%** (E1 universe: 5.35%). The
   large/mid universe equal-weighted earns 3 pp more than the 500-name
   universe did; E1b's rules add ~1 pp over that.

## Defects to fix before any verdict

- ~~E1's stored criteria.json predates `turnover_annual`; G4 currently passes
  by default.~~ **Fixed.** E1's sweeps now carry it (development 1.6952,
  validation 1.3131), and G4 is decided on real numbers in the verdict.
- Data check on S10's Nifty 500 membership table. **Still open.** S10's
  3.91% is the row that leans hardest on the weakest table (56% of Nifty 500
  names carry a guessed window; one exact-list miss). It did not affect the
  verdict, which rests on the base row, but any future row that leans on
  Nifty 500 membership should be read with that in mind.

## Requested extras before validation

Return of the invested (equity) portion alone, per row, to separate cash
carry from signal. B3 and E1 base on the 2012–2016 window for S13's
comparison to the benchmark.

### Where the return came from, per row (decomposition v3, 2026-09-19)

**This replaces the "Invested equity alone" table in the original summary,
which was version 2 and was wrong.** Versions 1 and 2 both failed the
property that makes the question answerable: version 1 returned NaN whenever
the sleeve emptied, and version 2 was time-weighted, which gives every
session equal weight regardless of how much capital was at risk — on the base
row, 162 sessions sat below 25% equity weight and 115 below 10%, and one
2009-02-02 session moved 21% on a base of ₹4,239 and counted as much as a
fully invested day. It reported "days invested 100%" for every row, which was
the tell.

Version 3 is capital-weighted: each day's equity P&L and cash P&L are
expressed as a share of the whole portfolio and chained, so the two **add up
to the portfolio's own pre-tax return**. That reconciliation is the property
the first two lacked.

| row | from equity pp | from cash pp | sum | pre-tax CAGR | mean equity weight |
|---|---|---|---|---|---|
| base | 8.67 | 1.38 | 10.05 | 10.20% | 79% |
| S1 | 10.73 | 1.69 | 12.42 | 12.67% | 72% |
| S2 | 9.81 | 1.32 | 11.14 | 11.23% | 81% |
| S3 | 7.19 | 1.39 | 8.58 | 8.70% | 79% |
| S4 | 7.17 | 1.56 | 8.73 | 8.69% | 78% |
| S5 | 7.89 | 1.44 | 9.34 | 9.44% | 78% |
| S6 | 8.81 | 0.41 | 9.22 | 9.18% | 96% |
| S7 | 9.13 | 2.29 | 11.42 | 12.06% | 56% |
| S8 | 8.99 | 0.93 | 9.92 | 10.06% | 78% |
| S9 | 8.38 | 1.41 | 9.78 | 9.89% | 79% |
| S10 | 2.64 | 1.63 | 4.27 | 4.60% | 70% |
| S11 | 7.05 | 1.28 | 8.33 | 8.55% | 78% |
| S12 | 11.03 | 1.24 | 12.27 | 12.52% | 79% |
| S13 | 12.39 | 1.41 | 13.80 | 13.46% | 81% |

The sum sits within about 0.15 pp of the pre-tax CAGR (base: 10.05 vs 10.20);
the residual is the compounding cross-term between the two sleeves, not an
unexplained gap.

**What it says about finding 1.** The base row ran at a 79% mean equity
weight; the cash sleeve contributed **+1.38 pp/yr** of the 10.05 pp pre-tax
total, and the equity the strategy actually picked contributed **8.67 pp/yr**
— against B3's 13.48%.

Finding 1 called the cash carry worth "~1.7 pp of the 4 pp gap", which was a
rough attribution made on the version-2 numbers. It should be read against
S6, which measures the same thing directly rather than by attribution: with
the trend filter off, mean equity weight rises to 96% and cash contribution
falls to 0.41 pp, and the **total falls** to 9.22 pp pre-tax (8.33% after
tax) from base's 10.05 (9.47%). Holding more equity and less cash made the
result *worse*, not better.

So the seat belt was not a drag on this universe over this decade — finding 4
already says it was worth about +1.1 pp — and "cash carry costs 1.7 pp of the
gap" cannot be sustained as a counterfactual, because the row that actually
removes the cash carry loses money rather than gaining it. What is left is
the conclusion the review already drew, now with the arithmetic behind it:
the gap to the momentum fund is in the stock selection, not the universe and
not the cash sleeve.

### The same table on validation (for the record)

The validation sweep was re-run the same way
(`experiments/E1b/sweeps/validation-14c240592c8fc806/`); all fourteen rows
and all four benchmarks reproduced to within 1e-12, so the REJECT stands
untouched there too.

| row | from equity pp | from cash pp | sum | pre-tax CAGR | mean equity weight |
|---|---|---|---|---|---|
| base | 16.50 | 1.28 | 17.78 | 17.38% | 88% |
| S6 (filter off) | 20.19 | 0.99 | 21.18 | 20.70% | 93% |
| S7 (sell-to-cash) | 14.82 | 2.77 | 17.60 | 17.52% | 61% |

Validation reverses development's reading of the seat belt, which is worth
recording because it is the same rule on the same universe. Here the trend
filter **cost** money: turning it off (S6) earns 20.19 pp of equity
contribution against base's 16.50, at a 93% mean equity weight against 88%.
2017–2021 had no 2008 in it, and a rule that pays for itself in a crash
charges rent in a decade that only rises. Neither period is evidence about
the other; both are in the sweep because that is what a sweep is for.

### Persistence (2026-09-19)

Every row's equity curve and trade ledger, and the four benchmarks', are now
written into the sweep directory under `rows/<row>/`. No future extra needs a
re-run to recover a curve the run already had — three sweeps were lost to
exactly that on 2026-09-18. Decision records began being persisted alongside
them later the same day, so these two E1b directories carry curves and
ledgers but not `decisions.json`; nothing E1b still needs reads it.

## Implications (recorded, not acted on)

E3 (defensive sleeve) addresses finding 1 directly. A signal charter
(candidate: the benchmark's own construction, 6+12-month volatility-scaled
momentum, 30 names, semi-annual rebalance, run on E1b's universe through
this engine with SIP, costs and tax) would test finding 2 and, as a side
effect, measure how much of B3's 13.48% survives real trading and real tax.
Neither starts before E1b's verdict.

## Decision

Fix the two defects, add the extras, run validation, classify. Sealed
untouched.
