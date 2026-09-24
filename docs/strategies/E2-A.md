# E2-A — Firm-level red flags

Status: DRAFT. Locks at its first development run. Judged by `GATE.md`.

## 1. Purpose
Test whether excluding and exiting names with a recent distress-type
announcement improves E1's after-tax return or drawdown. This is the
"scams and frauds" question in a form that can be measured.

## 2. Hypothesis
Names with a red-flag announcement in the trailing 12 months underperform
after costs by enough that avoiding them beats the momentum signal's occasional
liking for them.

## 3. Rule (the one change)
- A name with any frozen red flag disseminated in the trailing 12 months is
  ineligible on month-end M.
- A held name receives a new flag between month-ends → sold at the open of the
  next session after dissemination (not waiting for month-end). This is the
  only intra-month action in the stack.
- Point-in-time key: BSE `DissemDT` **where present, `NEWS_DT` otherwise**,
  declared per row. The after-15:30 rule applies to **either**: an
  announcement whose key timestamp falls after 15:30 is usable from the
  next session. (Draft amendment 2026-09-24; see §10.)

## 4. Flags (frozen; the rules in `pflab/data/red_flags.py` as of the freeze commit)
AUDITOR_RESIGNATION, REGULATORY_ACTION (SEBI/SAT/ED/CBI enforcement),
INSOLVENCY (CIRP/IBC, schemes excluded), PROMOTER_ENCUMBRANCE (≥50%/≥20%
threshold disclosures only), RATING_DOWNGRADE, RESULTS_DELAY, FORENSIC_AUDIT,
DEFAULT, FRAUD. Changing a rule after the first run invalidates the results.

## 5. Data
- BSE announcements, backfilled from 2010-01-01, daily job thereafter.
- NSE announcements added only if BSE coverage of NSE-listed names is below
  95% on a 200-name sample (checked before the first run, recorded in the
  manifest).
- BSE scrip code → ISIN map from the BSE equity master.

## 6. Window
Development 2010-01-01 .. 2016-12-31. Validation 2017-01-01 .. 2021-12-31.
E1 stack re-run on this window for the comparison. Sealed untouched.

## 7. Sweep
| row | change |
|---|---|
| S1 | window 6 months |
| S2 | window 24 months |
| S3 | exclusion only, no intra-month exit |
| S4–S12 | each flag type removed one at a time (nine rows) |
| S13 | **2016 onward only** — the years in which `DissemDT` exists, so the rule runs on the exchange's own dissemination timestamp with no substitution. E1 base is re-run on the same window as its stack. (Draft amendment 2026-09-24.) |

## 8. Reported extras (not gating)
Number of flagged names per month; how many E1 base holdings would have been
excluded; the 12-month forward return of flagged names vs the universe (the
raw evidence for §2, reported even if the gate fails).

## 9. Not claimed
No prediction of fraud. No reading of attachments (that is a later
extraction experiment; if adopted it is E2-A2 with its own charter).

## 10. Change log
- 2026-09-16 — draft.
- 2026-09-24 — **draft amendment, not locked.** §3's point-in-time key was
  `DissemDT` alone. BSE's API returns `DissemDT` as **null for every
  announcement before 2016** — confirmed against the raw API, not a
  collector artefact — which is 2010-01-01 to 2015-12-31, six of the seven
  years of this charter's own development window (§6). The key is now
  `DissemDT` where present and `NEWS_DT` otherwise, declared per row, with
  the after-15:30 rule applying to whichever is used.

  The substitution is measured, not assumed. Over 222,419 announcements in
  the 2016–2022 overlap where both timestamps exist, `DissemDT − NEWS_DT`
  has a **median of 5.1 seconds** (p75 6.8 s, p90 8.2 s, p99 10.3 s);
  99.77% are within five minutes and **0.009% cross a session boundary**,
  which is the only difference that can change a decision. So the
  substitution misdates roughly one announcement in 11,000 by one session,
  in the years where it is used at all.

  **S13 exists so the substitution can be priced.** It restricts the
  experiment to 2016 onward, where no substitution happens, and re-runs E1
  base on the same window; the gap between the full-window verdict and
  S13's is the measured cost of the earlier years. Evidence:
  `docs/data/insider_finding.md` §3.
