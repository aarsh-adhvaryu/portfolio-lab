# Financial results in XBRL — what the exchanges actually carry

Probed 2026-09-23/24 against NSE's `corporates-financial-results` API and
the XBRL documents it links. **Nothing has been bulk-collected.** This note
is the "report before collecting everything" step the investor asked for.

## 1. The headline answers

| question | answer |
|---|---|
| does XBRL go back to 2011? | **no.** Metadata rows exist from 2012, but the XBRL *documents* only resolve from **2018**. Every sampled link for 2012–2017 returns a stable HTTP 404. |
| which fields does it carry? | 280 distinct tags across a 119-document census of 2022; **46 appear in every document** and cover the whole P&L. Full list in §4. |
| **is operating cash flow quarterly, half-yearly or annual?** | **Half-yearly.** Never quarterly. |

## 2. Operating cash flow — the decisive measurement

`CashFlowsFromUsedInOperatingActivities`, by which quarter the filing
reports (2022, 30 documents sampled per quarter):

| filing reports | documents | carry operating cash flow |
|---|---|---|
| Q1 (June) | 30 | **0** |
| Q2 (September) | 30 | **30** |
| Q3 (December) | 29 | **0** |
| Q4 (March, annual) | 30 | **30** |

The same 0/30/0/30 pattern holds for investing activities, financing
activities and closing cash. This is SEBI LODR Reg 33: a cash flow
statement is required for the half-year and the full year, not per
quarter. An independent sample of FY2024-25 filings reproduced it
(September 14/14, June 0/14, December 0/14).

**Consequence for any charter that wants cash flow:** the series is
semi-annual with a ~45-day filing lag, so at a monthly decision date the
freshest operating cash flow is between 1.5 and 7.5 months old, and
changes twice a year. A rule that assumes a quarterly cash-flow series
cannot be written against this data.

## 3. Coverage by year — and where it stops

Six documents sampled per year from the November (half-year) window:

| year | links live | median tags | operating cash flow |
|---|---|---|---|
| 2012–2017 | **0 / 6** — all HTTP 404 | — | — |
| 2018 | 6 / 6 | 65 | 0 / 6 |
| 2019 | 6 / 6 | 53 | 0 / 6 |
| 2020 | 6 / 6 | 145 | **6 / 6** |
| 2021 | 6 / 6 | 148 | **6 / 6** |
| 2022 | 6 / 6 | 214 | **6 / 6** |
| 2023 | 6 / 6 | 211 | **6 / 6** |
| 2024 | 6 / 6 | 219 | **6 / 6** |
| 2025 | 1 / 6 | 218 | 1 / 1 |
| 2026 | 2 / 6 | 212 | 1 / 2 |

Three distinct regimes, and only the middle one is usable:

- **2012–2017: documents gone.** The API still returns the metadata row
  (symbol, ISIN, `filingDate`, `broadCastDate`, a link), so a naive
  collector would record thousands of "results" with no content. The links
  404 on every retry, so this is deletion, not throttling.
- **2018–2019: thin.** ~53–65 tags, P&L only, **no cash flow at all**.
- **2020–2024: full.** ~145–219 tags including the cash-flow block.
- **2025–2026: mostly 404 again**, and the API windows themselves go
  sparse (November 2025 returned 31 filings against 2,450 for November
  2022). Four retries with backoff returned an identical 404 each time, so
  again not a throttle. The same tail decay affects NSE's insider feed
  (`docs/data/insider_finding.md` §2), which suggests something structural
  on NSE's archive rather than anything specific to results.

**So the honest usable span is 2018–2024 for documents, and 2020–2024 if
cash flow is required** — not "2011 onward". Against E2-D's window
(development 2010–2016, validation 2017–2021) that leaves development with
no XBRL at all and validation with two of five years.

## 4. The field list

From 119 documents sampled across the four 2022 filing windows, 280
distinct tags. Percentages are the share of documents carrying the tag.

**Present in 100% of documents (46) — the reliable core.**

*Identity and period (11):* `Symbol`, `ReportingQuarter`,
`DateOfStartOfReportingPeriod`, `DateOfEndOfReportingPeriod`,
`DateOfStartOfFinancialYear`, `DateOfEndOfFinancialYear`,
`NatureOfReportStandaloneConsolidated`, `WhetherResultsAreAuditedOrUnaudited`,
`LevelOfRoundingUsedInFinancialStatements`, `DescriptionOfPresentationCurrency`,
`IsCompanyReportingMultisegmentOrSingleSegment`

*Revenue and expense (11):* `RevenueFromOperations`, `OtherIncome`, `Income`,
`CostOfMaterialsConsumed`, `PurchasesOfStockInTrade`,
`ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade`,
`EmployeeBenefitExpense`, `FinanceCosts`,
`DepreciationDepletionAndAmortisationExpense`, `OtherExpenses`, `Expenses`

*Profit (11):* `ProfitBeforeExceptionalItemsAndTax`, `ExceptionalItemsBeforeTax`,
`ProfitBeforeTax`, `ProfitLossForPeriodFromContinuingOperations`,
`ProfitLossFromDiscontinuedOperationsBeforeTax`,
`ProfitLossFromDiscontinuedOperationsAfterTax`, `ProfitLossForPeriod`,
`OtherComprehensiveIncomeNetOfTaxes`, `ComprehensiveIncomeForThePeriod`,
`ComprehensiveIncomeForThePeriodAttributableToOwnersOfParent`,
`ComprehensiveIncomeForThePeriodAttributableToOwnersOfParentNonControllingInterests`

*Tax (4):* `CurrentTax`, `DeferredTax`, `TaxExpense`,
`TaxExpenseOfDiscontinuedOperations`

*Per share and capital (8):* basic and diluted EPS in three variants each
(continuing, discontinued, combined), `PaidUpValueOfEquityShareCapital`,
`FaceValueOfEquityShareCapital`

**Half-yearly only (~50%) — the cash-flow block (7):**
`CashFlowsFromUsedInOperatingActivities`, `CashFlowsFromUsedInOperations`,
`CashFlowsFromUsedInInvestingActivities`, `CashFlowsFromUsedInFinancingActivities`,
`CashAndCashEquivalentsCashFlowStatement`, plus two subsidiary-control lines.
Around 60 further cash-flow detail tags (purchases of intangibles, proceeds
from borrowings, lease payments, taxes paid by activity) sit at the same 50%.

**Conditional:** `SegmentRevenue`, `SegmentAssets`, `SegmentLiabilities`,
`SegmentProfitBeforeTax` at 45% (only multi-segment filers);
`ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod`
98%; `NameOfTheCompany` 50%; `DateOfBoardMeetingWhenFinancialResultsWereApproved` 50%.

**What is NOT there.** No balance sheet. There is no total assets, no total
equity, no borrowings, no inventory, no receivables — `EquityShareCapital`
appears in 25% of documents and is paid-up capital, not net worth. Balance
sheet items appear only as cash-flow *movements*. So book value, debt/equity
and return on equity **cannot be computed from this source**; it supports
earnings, margins, EPS and (half-yearly) cash flow only.

**ISIN is in only 49% of the XBRL documents**, but the API metadata row
carries `isin` for every result, so the security key comes from the metadata,
not the document.

## 5. Filing date

The metadata row carries three timestamps, and they are not the same thing:

- `filingDate` — when the company filed.
- `broadCastDate` — when NSE broadcast it. **This is the point-in-time key.**
- `exchdisstime` — dissemination, null for older rows.

A sampled row: `filingDate` 12-Jan-2026 16:54, `broadCastDate` 12-Jan-2026
16:54:53, `exchdisstime` 16:55:46. Sub-minute apart in the modern era, but
`exchdisstime` was null in the 2012 sample, so `broadCastDate` is the one to
key on.

## 6. What I recommend, and what I have not done

I have **not** collected a year, because the census changed the question.
Collecting 2022 in full (~9,450 filings, ~1.5 hours) would produce a good
dataset for a year that is inside E2-D's *validation* window and outside its
development window entirely, and I do not think that is worth doing before
The investor decides what the data is for.

The decision the investor owns:

1. **Accept a 2018-onward (or 2020-onward for cash flow) window** and write
   whichever charter uses fundamentals around it, as E2-E can declare a
   2016-onward window for shareholding. This is the honest option and needs
   no new source.
2. **Find another source for 2011–2017.** BSE serves its own XBRL for
   results and may have retained the older documents; I have not probed it,
   because the shareholding backfill was already using BSE's API and I did
   not want to compete with it. That is the obvious next probe if the early
   years matter.
3. **Drop fundamentals before 2018** and let E2-D rely on shareholding and
   insider data, which do reach back further.

No charter should be written against "XBRL from 2011" — that window does
not exist in this source.
