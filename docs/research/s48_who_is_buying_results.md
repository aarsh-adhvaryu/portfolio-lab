# S48 "Who is buying": results

## Arm 1, promoters and insiders (run 2026-10-20, `tools/s48_study.py`, as registered in commit d165026)
Signal: net market buying by promoters, promoter group, directors, KMP and their relatives in the 90 days to the
month-end, at least 0.05% of market capitalisation (NSE insider-trading disclosures, point in time). Outcome: the next
63 sessions' return minus the Nifty 500 members' equal-weight average.

| period | mean 3-month excess | Newey-West t | one-sided p | months | median signal stocks |
|---|---|---|---|---|---|
| development 2016-06 to 2019-09 | +1.03% | 1.19 | 0.117 | 40 | 20 |
| validation 2019-12 to 2021-09 | +2.88% | 1.58 | 0.057 | 21 (1 skipped) | 14 |
| holdout 2026 (described) | -1.76% | -0.82 | | 5 | 11 |

**Fails** (validation p must be below 0.0125). The sign is positive in both registered periods but the evidence is
weak, and the 2026 months point the other way. Nothing live. Monthly rows: `PFLAB_DATA_DIR/research/s48_arm1_months.csv`.

## Arm 2, institutions quarterly (run 2026-10-22, as registered with amendment 1, commit 77e2283)
Signal: top decile (and positive) of the change in foreign + domestic institutional holding between the two latest
BSE shareholding filings usable at the month-end (854 scrips, 2015-12 to 2021-09 and 2025-09 to 2026-06).

| period | mean 3-month excess | Newey-West t | one-sided p | months | median signal stocks |
|---|---|---|---|---|---|
| development | -0.06% | -0.10 | 0.54 | 40 | 49 |
| validation | -0.44% | -0.42 | 0.66 | 22 | 46 |
| holdout 2026 (described) | -0.14% | -0.16 | | 5 | 49 |

**Fails.** No sign of an edge in any period. Nothing live.

## Arm 4, bulk and block deals (run 2026-10-22, as registered with amendment 1)
Signal: net buying by non-promoter parties in the 30 days to the month-end of at least 0.05% of market capitalisation.

| period | mean 3-month excess | Newey-West t | one-sided p | months (skipped) | median signal stocks |
|---|---|---|---|---|---|
| development | -4.43% | -2.84 | 1.00 | 29 (11) | 6 |
| validation | +0.11% | 0.06 | 0.47 | 14 (8) | 8 |
| holdout 2026 (described) | too few months | | | 2 (3) | 6 |

**Fails.** Few months reach five signal stocks. Development points the other way (big non-promoter buyers went on to
lag by about 4% a quarter in 2016-2019), but validation shows nothing, and a sell-side reading would need its own
registration. Known limit (amendment 1): NSE's 70-row cap cut 89 days of 2016-2021. Nothing live.

## Arm 3 and the arm as a whole
Arm 3 (mutual funds monthly) stays deferred: AMC monthly portfolios need a backfill from many fund houses in different
formats. **S48 closes with no live feature:** none of the three arms run beats the 0.0125 bar. Monthly rows:
`PFLAB_DATA_DIR/research/s48_arm{1,2,4}_months.csv`, summaries `s48_arm{1,2,4}.json`.
