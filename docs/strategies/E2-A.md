# E2-A — Firm-level red flags

Status: **LOCKED** 2026-09-25 (see §10). Changes go only through §10.
Judged by `GATE.md` **and** §8a: ADOPT requires both.

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
Development **2017-01-01 .. 2019-12-31**. Validation **2020-01-01 ..
2021-12-31**. E1 stack re-run on both windows for the comparison. Sealed
untouched. (Amended 2026-09-25, before lock; see §10.)

**Why this window, recorded before any return was computed.** The window is
set by when the rule's inputs exist, not by what they pay: the Insolvency
and Bankruptcy Code came into force in December 2016, and SEBI's
encumbrance and default disclosure regimes date from 2019. Choosing a
window from input availability is not choosing it from results.

**Declared limitation.** Five years of a 25-name portfolio, split three and
two, is a **low-power test**. A null result here means *not shown*, not
*no effect*. Nothing in this charter may be read as evidence that red flags
do not matter; the most it can show is that this rule, on this universe,
over these five years, did not move the metrics enough to detect.

## 7. Sweep
| row | change |
|---|---|
| S1 | window 6 months |
| S2 | window 24 months |
| S3 | exclusion only, no intra-month exit |
| S4–S12 | each flag type removed one at a time (nine rows) |

**S13 removed, 2026-09-25.** It restricted the run to 2016 onward so the
rule would use `DissemDT` with no substitution. §6's window now begins in
2017, so the whole experiment is already inside the `DissemDT` era and
S13 would be a duplicate of the base row — which `GATE.md`'s convention of
2026-09-25 forbids running. The `NEWS_DT` fallback in §3 stays in the
charter because the collector and the flag table still implement it; it
simply never fires on this window.

## 8. Reported extras (not gating)
Number of flagged names per month; how many E1 base holdings would have been
excluded; the 12-month forward return of flagged names vs the universe (the
raw evidence for §2, reported even if the gate fails).

**Added 2026-09-25:** for every name E1 base held that was later suspended
or delisted, **whether a flag preceded it and by how long.** This is the
permanent-loss question in its most direct form — the rule's purpose is to
be early, and a flag that arrives after the exit is worth nothing. Reported
as a list with the lead time in months, and as a count of exits with no
preceding flag.

## 8a. Pre-registered event study — REQUIRED for ADOPT

**Added 2026-09-25, before lock and before anything was computed.** GATE
alone cannot separate "flags carry no information" from "five years of a
25-name portfolio could not detect it" (§6's declared limitation). This
section tests the information directly, on every flagged name rather than
on the handful the portfolio happened to hold, and **its pass condition is
written here before the study is run.**

**ADOPT requires GATE *and* §8a. Either alone is not enough.**

- **Events.** A name's **first flag in any trailing 12 months**, dated by
  `usable_from` (§3's key, including the after-15:30 rule), restricted to
  names in E1's eligible universe at that month-end. All nine flags are
  **pooled** for the test; each flag is also reported separately.
- **Outcome.** Return from the next open over 1, 3 and 6 months, minus the
  median return over the same horizon of **unflagged eligible names in the
  same turnover-rank decile and the same 12-1 momentum quintile at that
  month-end.** Matching on both is deliberate: a flagged name is typically
  thinner and already falling, and without the match the study would
  measure size and momentum rather than the flag.
- **Pass condition.** The mean 6-month excess return across **monthly event
  cohorts** is negative with **t below −2** (Newey-West, 5 lags, for the
  overlapping horizon) in **2017–2019**, *and* negative in **2020–2021**.
  The second period is a sign test only — two years of cohorts cannot
  support a t-statistic.
- **Reported, not gating.** The same study on **2010–2016** for the flags
  that existed then. Those years are outside §6's window precisely because
  the inputs are thin, so the result is evidence about the flags, never
  about the rule.
- **No flag is ever dropped or weighted on the basis of this study.** It
  decides whether the rule is tested further, not what the rule is. A flag
  whose individual result looks poor stays in §4.
- **Truncation (added 2026-09-25).** Each period's event study reads data
  only through that period's end, via `periods.truncate_end`. An event
  whose 1-, 3- or 6-month horizon ends after the period end is **excluded
  from that horizon and counted in the report**. No forward return may read
  a price after 2021-12-31.

## 9. Not claimed
No prediction of fraud. No reading of attachments (that is a later
extraction experiment; if adopted it is E2-A2 with its own charter).

## 10. Change log
- 2026-09-16 — draft.
- 2026-09-25 — **§6 window moved to development 2017–2019, validation
  2020–2021**, on Aarsh's decision, before lock. The readiness note
  (`docs/notes/E2A-readiness.md`) measured that the old 2010–2016
  development window would have made between **0.8% and 5.9%** of the
  universe ineligible — twelve names in 2010 — because three of the nine
  frozen flags did not exist as disclosures for most of it: INSOLVENCY is
  near-zero before the IBC took force in December 2016,
  PROMOTER_ENCUMBRANCE is **exactly zero until 2019**, and DEFAULT is
  negligible until 2019. A rule touching one name in 120 cannot move a
  25-name portfolio, so the gate would have read "no effect" where the
  honest reading is "no data". The window is set by input availability and
  the reason is recorded before any return on it was computed. The
  low-power limitation is declared in §6 rather than discovered later.
- 2026-09-25 — **S13 removed.** §6 now begins inside the `DissemDT` era, so
  S13 would duplicate the base row, which `GATE.md`'s convention of the
  same date forbids.
- 2026-09-25 — **§8a added: a pre-registered event study, required for
  ADOPT alongside GATE**, with its pass condition written before the study
  was run. GATE on a five-year, 25-name portfolio cannot distinguish an
  uninformative flag from an undetectable one; §8a tests the information on
  every flagged name, matched on turnover-rank decile and momentum
  quintile. No flag may be dropped or weighted on its result.
- 2026-09-25 — **§8 extra added**: for every E1 base holding later
  suspended or delisted, whether a flag preceded it and by how long.
- 2026-09-25 — **§8a truncation declared**: "Each period's event study reads
  data only through that period's end, via `periods.truncate_end`. An event
  whose 1-, 3- or 6-month horizon ends after the period end is excluded from
  that horizon and counted in the report. No forward return may read a price
  after 2021-12-31." Without this a six-month horizon opened in late 2019
  would reach into 2020 — data the development period has not been shown —
  and the last months of validation would read into the sealed period. The
  exclusion is counted rather than silent, because a horizon that quietly
  drops its most recent cohorts is a different study from the one
  chartered.
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
- 2026-09-25 — **LOCKED. No changes to §3–§8a after this line.**
