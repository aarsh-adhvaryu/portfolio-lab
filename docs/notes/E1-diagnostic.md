# E1 — Diagnostic note (verdict: INCONCLUSIVE)

Required by E1 §13 for a non-ADVANCE verdict. No parameter is changed here.
Sealed period untouched. No live trading is unlocked.

## Verdict arithmetic (from `pflab classify`)

| criterion | development | validation |
|---|---|---|
| C1 vs Nifty 500 TRI (≥ +2.0 pp) | FAIL, +1.27 | PASS, +11.32 |
| C2 vs Nifty 200 Momentum 30 TRI (≥ +2.0 pp) | FAIL, −4.14 | PASS, +5.87 |
| C3 drawdown (≤ B2 + 5 pp) | PASS | PASS |
| C4 sweep stability | FAIL, 0/10 | PASS, 7/10 |

Not REJECT (C1 passed one period). Not ADVANCE (all four must hold in both).

## Why the periods disagree

1. **Regime.** Development contains 2008 and the 2011–2013 small-cap bear.
   Validation ends at the December 2021 small-cap peak. E1's holdings are
   small-cap by construction (see 3), so the two windows are the two faces
   of one exposure.
2. **The trend filter is insurance, not alpha.** S6 (filter off) is the worst
   development row (4.99% vs 9.34%) and the best validation row (29.34% vs
   26.12%). It pays in prolonged bears and costs in V-shaped crashes (2020).
   Its value cannot be judged from either period alone.
3. **Universe drift into thin, small names.** Median turnover rank of holdings
   fell from 172 (2007) to 340 (2016); names held fell from 23 to 13; 16% of
   development buys were skipped on the liquidity guard, 27 in 2015 alone.
   In validation the market was deep enough that the guard never fired, but
   the small-cap exposure remained. The momentum index draws from the top
   200 by market cap; E1 draws from the top 500 by traded value and buys
   whatever the shortfall rule points at.
4. **Tax is real but secondary.** Pre-tax 10.68% vs after-tax 9.34% in
   development (1.34 pp); 66% of realised gains short-term. Smaller than the
   gap to the momentum fund. E1-P addresses it.
5. **Delisting risk is smaller than S9 suggested.** 12 names, all exited, net
   +₹227,780. S9 (−100%) is a stress row, not an estimate.
6. **Concentration.** 13 names held in 2016 means the shortfall-plus-skips
   buy rule under-diversifies as capital grows. Recorded; not addressed in E1.

## Caveats on the validation result

Five years ending at a small-cap peak flatters a small-cap strategy. The
sealed period (2022–2025) contains the 2022 correction and the 2024–25
small-cap fall and is the honest test. It is not opened by this verdict.

## What this verdict unlocks

The next experiment in sequence. Nothing else. Order decision recorded
below.

## Order decision

E1b (universe: Nifty 200 constituents, point-in-time) is chartered and
slotted before E1-P, because a universe change would alter the base every
later experiment is measured against. E1-P's preparation stands and runs on
whichever base survives E1b.

## Corrections

2026-09-17 correction: finding 6 (under-diversification as capital grows)
not supported by validation extras; names held 17.7–29.2 in 2017–2021.
Finding 3 (universe rank 240–340 in both periods) stands.
