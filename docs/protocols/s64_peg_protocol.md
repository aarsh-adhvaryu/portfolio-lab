# S64 PEG and the multibagger claim: protocol (2026-10-27, committed before any code or run)

The investor's rule of thumb: "a stock bought at a PEG below 1 is a multibagger". It is a claim about years, so the one-month
`rule_filter` template cannot test it (the mistake of the P/E-above-50 test). This is a separate study with a five-year horizon,
counted as one test in the family "all" (`counter.record`). Nothing below changes after the first run; a change is an amendment
with its date and reason.

## Definitions (fixed here)
- **P/E:** the traded close over the trailing-twelve-month basic EPS, point in time (`templates.eps_ttm_frame`: four consecutive
  filed quarters, usable 60 days after the quarter ends; undefined when the EPS is older than 15 months or a split or bonus has
  moved the adjustment factor more than 2%).
- **Growth:** TTM EPS now over TTM EPS one year (252 sessions) earlier, minus 1. Both must be above zero, and the adjustment
  factor must not have moved more than 2% between the two dates (a split would mix units).
- **PEG:** P/E divided by growth in percent. Defined only for growth above zero.
- **Multibagger:** the stock's total return (dividends in; a name that stops trading keeps its last value, so delisted losers
  count against) reaches 3 times within 1,260 sessions (5 years) of the month-end.

## The study
- **Universe, each month end:** the Nifty 500 members of that day (delisted included) with a close on at least 200 of the last
  252 sessions and a defined PEG; fewer than 50: the month is skipped.
- **Groups:** A = PEG below 1 (and above 0); B = every other name in the universe with a defined PEG.
- **Formation months:** 2010-01 to 2016-12 (84 months). Their five-year windows end by 2021-12, so the spent years 2022-2025 are
  not used. Later formation months are not used: their windows would reach into them.
- **Measure:** per formation year, the average over its months of the share of group A that became multibaggers, and of group B.
  A year counts for A when its rate exceeds B's.

## Decision rule (fixed)
The claim passes only if ALL of:
1. A's rate exceeds B's in at least 5 of the 7 formation years;
2. the pooled ratio of A's rate to B's is at least 1.5;
3. the fifth percentile of that ratio, resampling the 7 formation years with replacement 5,000 times (seed 20261027), is above 1.
Otherwise it fails. A pass is also reported with its power: seven formation years, windows overlapping inside each year, so the
independent evidence is a handful of five-year periods; a pass says "consistent with", a fail says "not supported on this data".
The counter's Bonferroni bar is not applied to this rule (it is a count-and-ratio rule, not a t-test); it is recorded in the
counter as one more test so the other bars rise honestly.

## Use of the result
A pass: the brain's valuation facts show PEG with "tested: passed (consistent with, weak power)". A fail: "tested: failed", and
PEG stays context. Either way the result goes into `docs/research/s64_peg_results.md`.

## Run
`.venv\Scripts\python -m pflab.quant.peg_study` (about a minute).
