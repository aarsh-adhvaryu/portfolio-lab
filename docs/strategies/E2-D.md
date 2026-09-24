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
(Draft amendment 2026-09-24; see §9.)

- **Promoter holding and pledge from the BSE shareholding backfill, 2010
  onward** (`pflab/data/bse_shareholding.py`). Point-in-time key is the
  filing date: `Fld_AuthoriseDate`, which exists for the SEBI-format era
  (December 2015 quarter onward) and lands about three weeks after quarter
  end.
- **A quarter with no traceable filing date is usable from the second
  month-end after its quarter end** — a month past the 21-day filing
  deadline. Declared per row. This covers 2010 to September 2015, where no
  filing timestamp exists in any structured source. The quarter end itself
  is never used as the key; that would let the engine see three weeks into
  the future.
- **Category-wise holding and shareholder counts exist only from December
  2015** and are recorded explicitly unavailable before it, never zero.
  Nothing in §3 depends on them.
- **The PIT limb applies from 2016-01-01.** NSE's structured feed begins
  2015-11-19 and is the only source carrying quantities, values and
  before/after holding, which is what §3's 1.0%-of-market-cap test needs.
  BSE's insider/SAST announcements cover 2010 onward but carry a headline
  and no parsed quantity, so they cannot support the limb and are not
  substituted for it.
- Bulk and block deals (NSE daily) — stored, reported in §7, not in the rule.
- Shares outstanding from the shareholding pattern: `reported` from the
  SEBI-format era, `derived` (promoter shares ÷ promoter %) before it, kept
  in separate columns with the derivation and its implied rounding error
  stored. Undefined when promoter holding is zero.

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
| S6 | **dated quarters only** — quarters carrying a real filing date, dropping those that rely on §4's second-month-end convention (draft amendment 2026-09-24) |
| S7 | **2016 onward only** — both the shareholding schema and the PIT feed change there, so this is the window on which the whole rule runs on its intended data. E1 base re-run on the same window as its stack |
| S8 | **S4 (PIT only) on 2016–2021**, E1 base re-run on the same window as its stack — the PIT limb measured alone on the years it actually applies to |

## 7. Reported extras
Bulk/block-deal buyers by category (FII, DII, promoter, other) for held names;
forward 6-month return of excluded names vs universe.

## 8. Not claimed
No tracking of specific investors. No copying of any fund's trades.

## 9. Change log
- 2026-09-16 — draft.
- 2026-09-24 — **draft amendments, not locked.** §4 rewritten around what
  the collected data turned out to be, and three sweep rows added.

  **Promoter holding and pledge are available 2010 onward**, from the BSE
  backfill. Two eras with different schemas: the SEBI format (category-wise
  holding, shareholder counts, `Fld_AuthoriseDate`) begins with the
  **December 2015** quarter; before it only promoter entities, shares,
  percent and pledged shares exist. §3's rule reads promoter holding and
  pledge only, so it is supported across the whole window.

  **Filing dates do not exist before 2016.** `Fld_AuthoriseDate` covers the
  SEBI era; nothing covers 2010–2015, and the announcement feed cannot fill
  it (its "Shareholding" subcategory exists only 2014–2022, and pre-2016
  announcements carry no dissemination timestamp at all). Rather than date
  those quarters by their quarter end — which would be lookahead of about
  three weeks — a quarter with no traceable filing date is **usable from
  the second month-end after its quarter end**, one month past the 21-day
  deadline. The data itself keeps `filing_date = NaT` and
  `filing_date_source = "unresolved"`; this convention is the charter's,
  not the collector's, so the raw record stays honest.

  **The PIT limb applies from 2016-01-01**, because NSE's structured feed
  starts 2015-11-19 and BSE's insider announcements carry no quantities.
  The two sources agree on which companies have insider activity (92.2% of
  NSE's securities appear in BSE's feed) but not on when (15.7% same-day),
  so BSE is not a substitute. NSE's feed also **stops on 2026-05-02**,
  which is outside this charter's windows but matters for any live use.

  **S6, S7 and S8 exist so each of those three compromises can be priced**
  rather than assumed harmless: S6 drops the undated quarters, S7 runs the
  whole rule only where both data sources are native, and S8 isolates the
  PIT limb on 2016–2021. Each re-runs E1 base on its own window as its
  stack. Evidence: `docs/data/shareholding_finding.md`,
  `docs/data/insider_finding.md`.
