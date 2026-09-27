# E2-E — Retail crowding

Status: **DRAFT** 2026-09-27, written by Claude on Aarsh's instruction of
2026-09-26 (lane 6: "crowding, retail shareholder-count jumps, 2016
onward, windows as E2-A"). Not reviewed. Locks at its first development
run. Judged by `GATE.md` **and** a pre-registered event study (§8a), as
E2-A was.

**Every threshold here is proposed on priors, before any return has been
computed on this data, and is marked ◆. None is settled until Aarsh sets
it.**

## 1. Purpose
Test whether avoiding names that retail investors are crowding into —
measured by a jump in the number of public shareholders — improves E1's
after-tax return or drawdown. The idea is that a momentum book buys what
has been rising, and a surge of new small holders is a sign the rise is
late.

## 2. Hypothesis
A name whose public shareholder count has jumped far more than other
eligible names' over the latest reported quarter underperforms matched
names over the next 3–6 months, by enough that excluding it beats the
momentum signal's liking for it.

## 3. Rule (the one change)
- **Measure.** For each name with a usable filing, growth in
  `n_shareholders_public` between its two latest usable quarterly
  shareholding patterns as of M.
- **Flag.** ◆ A name is **crowded** at M if that growth is in the **top
  decile** of the eligible universe at M, among names with a usable
  measure. Cross-sectional on purpose: the number of demat accounts in
  India roughly doubled over 2020–2021, so an absolute threshold would flag
  most of the market in validation and almost none of it in development —
  E2-A's reversal between periods is the warning.
- **Crowded names are ineligible** at M. A **held** name that becomes
  crowded **exits at the next month-end** (not intra-month), the same
  treatment Aarsh set for E2-D on 2026-09-27.
- **Point-in-time.** A quarter is usable from its `filing_date`
  (`Fld_AuthoriseDate`; every row from the December 2015 quarter carries
  one). A name with fewer than two usable quarters has no measure and is
  not flagged.
- ◆ **Mechanical jumps are excluded**: a quarter in which the name had a
  merger or amalgamation, a demerger, or a rights issue or QIP (from the
  NSE corporate-actions feed and BSE announcements) gives no measure, since
  the count jumps for reasons that are not crowding. Splits and bonuses
  stay in — they change share count, not holder count.

## 4. Data
- `data/bse_shareholding/summary.parquet`, new era (from the December 2015
  quarter): `n_shareholders_public`, `filing_date`. About 2,000 scrips a
  quarter; 2016–2021 fully dated.
- **"Retail" is approximated by all public shareholders.** The collected
  table has no split of individuals holding up to ₹2 lakh — only the
  public category's total count. Institutions add hundreds of holders to
  counts in the tens of thousands, so the approximation is close, but it
  is declared.
- BSE scrip code → ISIN: `data/bse_scrip_isin/map.parquet`, as E2-D.
- Before the December 2015 quarter there are no shareholder counts at all
  (`docs/data/shareholding_finding.md` §2), so nothing before 2016 can be
  tested.

## 5. Window
As E2-A: development **2017-01-01 .. 2019-12-31**, validation
**2020-01-01 .. 2021-12-31**. E1 base re-run on both windows as STACK.
Sealed untouched. The first measure needs two usable quarters (December
2015 and March 2016, filed by about May 2016), so the whole window has
inputs.

**Declared limitation**, as E2-A: five years of a 25-name portfolio is a
low-power test, and a null result means *not shown*, not *no effect*.

## 6. Sweep
| row | change |
|---|---|
| S1 | ◆ top 5% instead of top decile |
| S2 | ◆ top 20% |
| S3 | growth over the latest **two** quarters |
| S4 | exclusion only: held names are not exited |
| S5 | mechanical-jump exclusion off |
| S6 | costs ×2 |

## 7. Reported extras (not gating)
Number of crowded names per month and how many E1 base held; the
cross-sectional growth threshold each month (so the demat boom is visible);
forward 3- and 6-month return of crowded names against matched names.

## 8a. Pre-registered event study — REQUIRED for ADOPT
Same design as E2-A §8a, written here before anything is computed:
- **Events.** A name's first crowded flag in any trailing 12 months,
  dated by `filing_date`, restricted to E1's eligible universe at that
  month-end.
- **Outcome.** Return from the next open over 1, 3 and 6 months minus the
  median of uncrowded eligible names in the same turnover-rank decile and
  the same 12-1 momentum quintile.
- **Pass.** Mean 6-month excess return across monthly cohorts negative
  with t below −2 (Newey-West, 5 lags) in 2017–2019, **and** negative in
  2020–2021 (sign only).
- Each period reads data only through its own end (`periods.truncate_end`);
  an event whose horizon ends after the period end is excluded.

## 9. Not claimed
Not a model of retail behaviour. A shareholder count is a quarterly,
lagged, coarse measure of who holds a stock.

## 10. What E2-A already taught, and why this is still worth a charter
E2-A found real information in its flags in development and the rule still
lost 2.75 pp: E1 holds 25 of about 500 names, so excluding one mostly
changes which unflagged name is bought instead. Crowding is aimed at the
names momentum *likes*, so it should intersect E1's holdings far more than
distress flags did — which §7's count of held names crowded will show
before any verdict is read.

## 11. Open before lock — every ◆
1. Top-decile cross-sectional threshold, and S1/S2's alternatives.
2. The mechanical-jump exclusion, and which corporate actions count.
3. Public shareholders as the retail measure (no ≤ ₹2 lakh split exists).

## 12. Change log
- 2026-09-27 — draft (Claude), on Aarsh's instruction of 2026-09-26. Not
  reviewed. No data beyond coverage counts was examined.
