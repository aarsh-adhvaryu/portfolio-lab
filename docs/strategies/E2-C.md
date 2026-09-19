# E2-C — Event-intensity regime input

Status: DRAFT. Locks at its first development run. Judged by `GATE.md`
**with one declared exception (§6)**.

## 1. Purpose
Test whether a composite of event intensity and volatility gives a better
RISK_OFF trigger than E1's plain 10-month trend rule.

## 2. Hypothesis
Stress shows up in news tone and implied volatility before the 10-month
average is broken; adding those inputs cuts exposure earlier without adding
whipsaw.

## 3. Rule (the one change)
RISK_OFF(M) if E1's SMA-10 rule fires, OR both of:
- India VIX at M above its trailing 3-year 90th percentile, and
- 20-session mean GDELT India tone at M below its trailing 3-year 10th
  percentile.
RISK_OFF behaviour is unchanged (new cash waits, nothing sold).

## 4. Data
GDELT 2.0 India-filtered daily aggregate (BigQuery backfill from 2015-02-18,
daily job after). India VIX from NSE.

## 5. Window
Development 2015-03-01 .. 2019-12-31. Validation 2020-01-01 .. 2021-12-31.
Declared before the run: this contains roughly four stress episodes and
cannot support a statistical claim.

## 6. Verdict rule (exception to the gate)
This is a **risk rule held on priors**. It is adopted only if:
- MaxDD improves in both periods (G1 on drawdown),
- CAGR does not fall more than 0.5 pp in either period,
- the number of RISK_OFF switches per year rises by at most one on average
  (whipsaw guard),
- and Aarsh writes one paragraph stating he would hold this rule through a
  false alarm. If that paragraph cannot be written, the rule is not adopted
  regardless of numbers. If adopted, every report labels it "on priors".

## 7. Sweep
| row | change |
|---|---|
| S1 | percentiles 85/15 |
| S2 | percentiles 95/5 |
| S3 | VIX-only composite (tone removed) |
| S4 | tone-only composite (VIX removed) |
| S5 | 10-session tone window |

## 8. Not claimed
No prediction of crashes. Four episodes are anecdotes.

## 9. Change log
- 2026-09-16 — draft.
