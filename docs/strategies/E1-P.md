# E1-P — Patience (holding-period rules on E1's exits)

Status: DRAFT. Runs immediately after E1's verdict, before E2-A. Needs no
new data. Judged by `GATE.md`.

## 1. Purpose
Test whether E1 is more or less patient than it should be. "Patient" here
means: a name is not sold because of its own recent loss or gain, and a
band exit can wait if waiting is cheap and the tax saving is large. The
experiment has one candidate rule and two deliberately impatient rows that
serve as negative controls, so the cost of impatience is measured, not
assumed.

## 2. Hypothesis
Most of E1's sells are band exits within 12 months, taxed at 20%. Deferring
an exit to cross the 12-month line when the name has only slipped modestly
in rank saves tax without giving back return. Reacting to a position's own
loss or gain (stop-loss, profit-taking) hurts a momentum strategy after
costs and tax.

## 3. Rule (the one change) — tax-aware patience
A band exit (rank > 50 on month-end M) for a held lot is **deferred** if all
three hold:
- the lot is between 9 and 12 months old (within 3 months of long-term),
- the name's rank on M is ≤ 100 (slipped, not broken),
- the name is still eligible and has no red flag (once E2-A exists).
The deferred lot is re-checked each month-end; it is sold at the first
month-end after it turns long-term if rank is still > 50, or immediately if
rank exceeds 100 or eligibility fails. Delisting, suspension and red-flag
exits are never deferred.

## 4. Negative controls (run alongside, never adoptable)
- **N1 Stop-loss**: sell any position at the next open when it is down 20%
  from its cost basis. Everything else as E1.
- **N2 Profit-taking**: sell any position at the next open when it is up
  50% from its cost basis. Everything else as E1.
Both are reported with the same metrics. Their purpose is to put a number on
what impatience costs (or, if one helps, to say so honestly and charter it
separately; there is published evidence that a stop-loss can tame momentum
crashes, and this is where that claim gets tested on Indian data).

## 5. Window
E1's full window. Development 2007–2016, validation 2017–2021.

## 6. Sweep (for the candidate rule)
| row | change |
|---|---|
| S1 | defer window 6 months (lots 6–12 months old) |
| S2 | rank ceiling 75 |
| S3 | rank ceiling 150 |
| S4 | defer only if the lot has an unrealised gain (a loss is sold; STCL is worth harvesting) |
| S5 | minimum hold of 6 months on every lot regardless of rank (pure patience, tax-blind) |

## 7. Reported extras
Share of E1 sells that were short-term; tax paid by STACK vs CAND; the
forward 3-month return of deferred lots vs the lots E1 would have sold; for
N1/N2, how many sells they triggered and what those names did over the
following 6 months.

## 8. The trader's patience (live year)
The system's patience is in the rules. Yours is measured too: the live ledger
carries an `override` field. Every month-end where you wanted to deviate
from the order list gets a one-line note, whether or not you acted. The
target for the live year is zero overrides; the notes are the data if it is
not zero.

## 9. Not claimed
No prediction of when a position will recover. Patience is a policy, not a
forecast.

## 10. Change log
- 2026-09-16 — draft.
