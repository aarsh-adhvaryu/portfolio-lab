# "Height of the ride" study: results

Run 2026-10-16 with `tools/height_study.py`, as registered in `height_protocol.md` (commit 9b18489, before the
run). No amendment. Big fall = the Nifty 500 TRI at least 15% below its highest close within the next 12 months.

| period | big fall after HIGH months (score >= 0.80) | after other months | median 12-month return, HIGH / other |
|---|---|---|---|
| development 2009-14 | 17% (12 months) | 48% (58) | +3.7% / +10.1% |
| validation 2015-19 | 37% (19) | 56% (41) | +10.5% / +6.5% |
| 2020-25 (not evidence) | 44% (9) | 27% (60) | +9.2% / +13.1% |

**FAILS**: in both test periods big falls were LESS common after "high" months, not more. Each measure alone
(top fifth against the rest) gave no consistent warning either: stretch 0% vs 54% (2009-14) and 33% vs 54%
(2015-19); valuation 36% vs 45% and 50% vs 50%; calm 57% vs 41% and 25% vs 56%.

## Reading
- In this market, being expensive, stretched or calm did not tell when a big fall was coming; falls often came
  from ordinary or already-nervous levels.
- A 15% fall within a year happened after about half of all month-ends in 2009-2019 (43% and 50%): it is a
  normal part of the ride, not a rare event.
- So the protection against a fall that cannot be seen coming stays what the plan already has: the mix (debt,
  gold), the cash floor, staging each FD batch over 10 months, the safety filters, and the dip rule that buys more
  after a fall. Nothing is added to the live system; the measures stay in the study tool only.
