# Pairs trading study: results (S39)

Run 2026-10-16 with `tools/pairs_study.py`, as registered in `pairs_protocol.md` (commit 76549d2; amendment 1,
commit 925900d, added before the full run). A reporting bug in the tool's first full run (each period's
returns ran to the end of the data) was fixed and the run repeated; trade counts were unaffected. 36
formations (Dec 2008 to Jun 2026), 10 pairs each; universe 132-224 F&O-eligible Nifty 500 members per
formation. Figures are excess over the cash rate (market futures carry, median 6.4% a year), on a Rs 50 lakh
book of 10 slots, after Zerodha charges, slippage, rolls and margin.

## Primary rule (entry |z| 2, exit at 0, stop at 4, 63-session cap)
| period | months | net excess / yr | Newey-West t | max drawdown | gross / yr | trades | winners |
|---|---|---|---|---|---|---|---|
| development 2009-14 | 72 | +4.5% | 1.82 | 11.5% | +6.2% | 165 | 53% |
| validation 2015-19 | 60 | +1.1% | 0.71 | 7.2% | +2.7% | 132 | 53% |
| 2020-26 (not evidence) | 81 | -1.7% | -0.66 | 23.2% | -0.1% | 181 | 48% |

**Verdict: FAILS the registered pass rule** (needs t >= 2.0 in both periods; development 1.82, validation
0.71). Answer, as registered: no pairs strategy.

## Why it fails
- **Cointegration does not last.** Only 9% of the selected pairs were still cointegrated (Engle-Granger
  p < 0.05) on their own six-month trading data. A third of all trades ended because the month-end test
  showed the relation had broken ("breakdown": 53 of 165 in development, 44 of 132 in validation); 9-17%
  were stopped at |z| 4.
- **The edge shrinks over time.** Gross excess fell from 6.2% a year (2009-14) to 2.7% (2015-19) to about 0
  (2020-26), the pattern expected as more traders run the same textbook rule.
- **Costs take most of what is left.** Charges, slippage and monthly rolls cost about 1.6-1.7 points a year;
  with costs doubled, validation is negative (-0.5%).

## Sensitivity (reported, not used to decide)
| variant | dev net / t | val net / t | 2020-26 net |
|---|---|---|---|
| entry 1.5 | +4.7% / 1.63 | +3.1% / 1.42 | -4.6% |
| entry 2.5 | +3.1% / 1.64 | +0.9% / 0.49 | -1.1% |
| costs and slippage x2 | +2.8% / 1.13 | -0.5% / -0.29 | -3.2% |
No variant reaches t = 2 in both periods; all lose money in 2020-26.

## Portfolio use
None. The descriptive `pflab pm pair` command built with the study was removed on 2026-10-16 at the investor's request
(only what passes is wired into the agents). The backtester and `tools/pairs_study.py` remain so this result can
be reproduced.
