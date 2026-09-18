# E1b — Development review (2007-01-01 .. 2016-12-31)

Written before the validation sweep. No parameter proposals; the charter is
locked. Sweep: experiments/E1b/sweeps/development-26b23d4fbc273fea/.

## Against the gate (development only; verdict needs both periods)

| test | requirement | E1b vs E1 base | status |
|---|---|---|---|
| G1 | CAGR +0.5 pp or MaxDD −2 pp | +0.13 pp / −0.70 pp | not met |
| G2 | other metric within tolerance | met | met |
| G3 | G1–G2 in ≥ two thirds of rows | 5 of 14 | not met |
| G4 | turnover ≤ 2× | 1.16 vs 1.70 | met (E1 criteria.json to be regenerated; see defects) |

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

- E1's stored criteria.json predates `turnover_annual`; G4 currently passes
  by default. Regenerate by re-running E1 base on both periods under the
  current engine and assert the metrics reproduce byte-identically (a
  regression check on every engine change since).
- Data check on S10's Nifty 500 membership table.

## Requested extras before validation

Return of the invested (equity) portion alone, per row, to separate cash
carry from signal. B3 and E1 base on the 2012–2016 window for S13's
comparison to the benchmark.

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
