# E2-D — Positioning (bulk deals, insiders, promoters)

Status: DRAFT. Locks at its first development run. Judged by `GATE.md`.

## 1. Purpose
The Indian-equity analogue of on-chain "whale" tracking: exchanges publish
who bought and sold in size, and insiders and promoters must disclose their
trades. Test whether net selling by the people who know the company predicts
underperformance.

## 2. Hypothesis
Names where promoters and insiders were net sellers of more than 1% of shares
outstanding in the trailing two quarters underperform the universe after
costs; excluding them improves E1.

## 3. Rule (the one change)
On month-end M, a name is ineligible if, over the trailing two reported
quarters (as of their disclosure dates ≤ M), promoter holding fell by more
than 1.0 percentage point of shares outstanding **or** net insider
transactions (PIT disclosures, sells minus buys, by value / market cap) exceed
1.0% of market cap. Held names that trip the rule exit at the next month-end
(not intra-month; disclosures are lagged anyway).

## 4. Data
- Quarterly shareholding patterns (NSE/BSE), promoter holding %, with filing
  date as the point-in-time key. Available from ~2009.
- PIT (insider trading) disclosures from NSE, with disclosure date. Structured
  from ~2015; earlier from BSE.
- Bulk and block deals (NSE daily) — stored, reported in §7, not in the rule.
- Shares outstanding from the shareholding pattern.

## 5. Window
Development 2010-01-01 .. 2016-12-31. Validation 2017-01-01 .. 2021-12-31.
Stack re-run on the same window.

## 6. Sweep
| row | change |
|---|---|
| S1 | threshold 0.5% |
| S2 | threshold 2.0% |
| S3 | promoter holding change only (no PIT) |
| S4 | PIT only (no shareholding pattern) |
| S5 | insider net **buying** > 1% as a tiebreak among entry candidates (additive, reported separately) |

## 7. Reported extras
Bulk/block-deal buyers by category (FII, DII, promoter, other) for held names;
forward 6-month return of excluded names vs universe.

## 8. Not claimed
No tracking of specific investors. No copying of any fund's trades.

## 9. Change log
- 2026-09-16 — draft.
