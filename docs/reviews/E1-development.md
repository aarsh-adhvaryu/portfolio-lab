# E1 — Development review (2007-01-01 .. 2016-12-31)

Written before the validation sweep. Contains no parameter proposals; the
charter is locked. Sweep id: see experiments/E1/sweeps/ manifest.
Reviewers: Aarsh (decision), Claude (analysis).

## Result against the charter (§13, development period)

| criterion | requirement | base row | status |
|---|---|---|---|
| C1 | CAGR(E1) − CAGR(B2) ≥ +2.0 pp | 9.34% − 8.07% = +1.27 pp | FAIL (short by 0.73) |
| C2 | CAGR(E1) − CAGR(B3) ≥ +2.0 pp | 9.34% − 13.48% = −4.14 pp | FAIL |
| C3 | MaxDD(E1) ≤ MaxDD(B2) + 5 pp | 55.4% vs 63.5% + 5 | PASS (by 13 pts) |
| C4 | C1–C3 hold in ≥ 6 of 9 sweep rows | C1 holds in S2 only | FAIL |

ADVANCE is not reachable. Validation determines INCONCLUSIVE vs REJECT and
runs regardless. Nothing in this review changes the charter.

## What the numbers say

E1 beat the primary benchmark after tax with lower drawdown, by less than the
bar. It lost by a wide margin to the momentum index fund. Its edge over
Nifty 500 did not survive small perturbations of its own settings.

## Findings, in order of importance

1. **The trend filter is the strategy.** S6 (filter off): 4.99% CAGR, 77.5%
   drawdown, against 9.34% / 55.4% for base. Worth 4.35 pp/yr and 22 points
   of drawdown in a window that contains 2008. Without it E1 trails Nifty 500.
2. **Delisting risk is as large as the crash rule.** S9 (held names that stop
   trading are worth zero): 5.02%. The 4.3 pp gap between "exit at last close"
   and "total loss" means E1 held names that later died, often. The true
   figure is between the two rows. This is the E2-A question.
3. **The universe drifts into thin names as capital grows.** 79 of 493 buys
   (16%) skipped on the liquidity guard, 27 in 2015 alone; worst case a
   ₹1.25 lakh buy into a name trading ₹3.7 lakh/day. Top-500-by-turnover
   includes names the momentum index (top 200 by market cap) never touches.
   Likely the largest part of the gap to B3.
4. **Sensitivity to N exceeds the edge.** N=20: 7.87%; N=25: 9.34%; N=35:
   7.67%. N was fixed blind, so this is not tuning, but the 1.27 pp edge over
   B2 is inside the range an arbitrary choice moves it.
5. **Turnover 1.70×/yr.** Nearly all realised gains were short-term (20%).
   Pre-tax CAGR and tax paid per row are requested below to size the drag.
6. **Selling into cash during RISK_OFF adds nothing.** S7: 9.23% / 53.3%
   with 40% more turnover than base. Holding and letting new cash wait
   performs the same.
7. **Costs are not the problem.** S5 (costs ×2): −0.30 pp. Cash rate matters
   more (S8, 4%: −1.14 pp), i.e. E1 spent a meaningful share of the window
   in cash.
8. **Lookback.** S1 (9-1): same CAGR, lower drawdown (50.1%). S2 (15-1):
   11.05% with 65.5% drawdown. More return, more risk; not promotable.

## Benchmarks

| | CAGR (liq, after tax) | MaxDD |
|---|---|---|
| B1 Nifty 50 TRI | 7.83% | 59.3% |
| B2 Nifty 500 TRI | 8.07% | 63.5% |
| B3 Nifty 200 Momentum 30 TRI (−0.30%) | 13.48% | 67.5% |
| B4 Equal-weight universe | 5.35% | 70.3% |

Caveat on B3: NSE launched the index in 2020 and backfilled its history.
Backfilled indices flatter themselves. It remains the benchmark because it
is what can be bought; the caveat is for interpretation, not for the gate.
B4 (5.35%, the universe itself equal-weighted) shows the universe is poor
material; E1's rules add about 4 pp over it.

## What surprised us

That the stock-selection rule is not where the value is. The crash rule and
the delisting assumption each move the result by more than the entire edge
over the index. That small caps, not costs or taxes, are the likely reason
for the gap to the momentum fund; this will be confirmed or refuted by the
requested extras.

## Requested extras (reporting only, no re-run of decisions)

Per row: pre-tax CAGR and total tax paid; count of held names that were
suspended or delisted and their contribution to return; months in RISK_OFF
and cash share over time; median turnover rank and market-cap proxy of
holdings by year.

## Implications for the E-series (recorded, not acted on)

E2-A (red flags) and E1-P (patience, tax) address findings 2 and 5
directly. E3 (defensive sleeve) addresses the cash share in finding 7. A
universe defined by market cap rather than turnover would be a new charter
(E1b), and can only be written after E1's verdict.

## Decision

Run the validation sweep and classify. Sealed period untouched.
