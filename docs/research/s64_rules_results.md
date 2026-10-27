# S64 rule tests: results (run by the investor, 2026-10-27; protocol `s64_rules_protocol.md`, committed before any run)

Seven pre-registered claims, `rule_filter` template, development 2010-2017 and validation 2018-2021, the group that meets the
rule against all Nifty 500 members over the next month. The development bar rose with each test (N 25 to 31): 2.89 to 2.96.
Means are monthly excess returns of the group; for "under" claims the claim is that the mean is negative.

| # | rule | claim | development | validation | result |
|---|---|---|---|---|---|
| 18 | P/E above 50 | earns less | mean -0.50%, t -2.86, n 95 | mean +0.11%, t +0.40, n 48 | **fail**: development 2.86 under the 2.89 bar; validation the other way |
| 19 | P/E below 15 | earns more | +0.23%, t +1.56, n 96 | -0.18%, t -0.55, n 48 | **fail**: t 1.56 under 2.90 |
| 20 | within 5% of the 52-week low | earns more | -1.03%, t -3.37, n 87 | -0.25%, t -0.51, n 33 | **fail**: the other way |
| 21 | below the 200-day average | earns less | **-0.59%, t -3.64, n 96** | **-0.75%, t -2.65, n 48** | **PASS**: both periods in the claimed direction |
| 22 | volume spike (over 2x) | earns more | -0.61%, t -2.91, n 95 | -0.76%, t -2.52, n 48 | **fail**: the other way in both periods |
| 23 | 40% or more below the high | earns more | -0.61%, t -2.41, n 96 | -0.61%, t -1.53, n 48 | **fail**: the other way |
| 24 | RSI below 30 | earns more | -0.16%, t -0.25, n 56 | +1.67%, t +1.75, n 26 | **fail**: development the other way |

## What it means
- **Passed (#21):** Nifty 500 stocks below their 200-day average earned about 0.6% to 0.75% a month less than the others, in both
  periods (about 7-9% a year). It is an *avoid* rule: it costs nothing to apply (not buying a name is not a trade), and it is wired
  into the brain as a tested finding (`learned`, shown by `findings` with the names of the investor's list that meet it today). It
  is a description of 2010-2021, not a forecast, and the Nifty 500's cheap dips did not pay.
- **The investor's P/E-above-50 rule did not hold up** as a rule for the next month: a small underperformance in 2010-2017
  (t -2.86, just under the corrected bar) and none in 2018-2021. P/E stays in the brain's view as context with the label "tested:
  failed". This does not say a high P/E is harmless for a particular company; it says the single cut-off at 50 had no reliable
  edge on the Nifty 500 over a month.
- **Cheap (P/E below 15) did not beat the market** either; its development t was 1.56.
- **Buying weakness did not pay:** stocks near their 52-week low, with a volume spike, or far below their high all did worse than
  the others, mostly in both periods. The tests were of the buy-the-dip side; the opposite sides (these names keep falling) are
  leads, not findings. They are NOT tested here: the same data has been seen, and a reversed claim registered now would be a
  hypothesis chosen after the result. If the system is to test them it must be on data it has not seen, which is the live record
  from 2026 on; they are listed for that.
- The starter scans: "Below its 200-day average" is labelled tested: passed (as an avoid rule); "Near its 52-week low" and
  "Volume spike" tested: failed as buy rules; "Alpha turned negative" is still not tested.

## Consequences in the system
- `learned` has one finding (claim #21). The failed rules have no live feature.
- The scan labels, the P/E flag and `findings` follow `learn_claims` (never a model).
- Open for fresh data: the reversed sides of #20, #22, #23 (underperformance after a volume spike, near the low, far below the
  high), the alpha-sign and build-up scans, and the P/E cut-offs at other levels. None is registered.
