# S64 reversion studies: results (run 2026-10-26)

Run as registered in `s64_reversion_protocol.md` (commit a1ae419, before any run), through the learner's rule with the
test counter (`learner_protocol.md`, amendment 4). Claims were re-registered once before running because the line endings
of `templates.py` changed (code hash), with no test run in between. Mechanics-only smoke test beforehand: 2012-H1 of the
development period (6 months) was looked at.

| claim | development (2010-2017) | validation (2018-2021) | bar | result |
|---|---|---|---|---|
| #16 `sector_reversion`, bottom quintile of z, next-month excess over the sector, after charges | mean +0.99% a month, NW t +1.47, 96 months | +0.55%, t +0.74, 48 months | t >= 2.87 (N = 24 tests) | **FAIL** (also under the old bar of 2.0) |
| #17 `short_term_reversal`, last month's losers, next month vs all members | mean -0.53%, t -2.07, 96 months | -0.10%, t -0.25, 48 months | t >= 2.88 (N = 25) | **FAIL**: the effect went the other way |

Reading: being cheap against a cointegrated sector index did not earn a reliable excess; the sign is positive in both
periods but the evidence is weak. In this market last month's losers did not rebound; if anything they lagged (t -2.07 in
development, nothing in validation), which is the opposite of the claim and is not a registered finding.

Live consequence (CLAUDE.md 12): no "cheap vs sector" line in the buy zone or the ready plans, no live finding.
`quant/comove.py` stays a description. The deflated Sharpe ratios (0.98 and 0.04) are recorded and do not decide.
