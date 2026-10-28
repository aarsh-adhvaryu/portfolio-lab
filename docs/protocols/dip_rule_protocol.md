# Dip-buy rule study: pre-registered protocol (S34)

Registered 2026-10-15, committed before any result was computed. Changing anything below after the first run
needs a dated amendment at the end of this file that says what changed and why; the first run's numbers stay
in the report.

## Question
The investor deploys each FD batch over 10 monthly tranches and wants an extra buy (at most a quarter of a tranche,
from the same pot) when something on his list falls. Two questions, in this order:
1. **Safety.** Which filters keep a dip buy away from companies that keep falling or collapse ("bought it low,
   then it went bankrupt")?
2. **Value.** Does buying on a dip signal (with those filters) do better than buying at an ordinary month-end?

No rule gives certainty that a price will rise. The study measures how often each rule bought into further
falls or ruin, and keeps only rules that are no worse than ordinary buying on both counts.

## Data (on disk, no network)
- NSE panel `data/panel/prices.parquet`: split-adjusted closes and dividends; total return = adjusted price change
  times (1 + dividend / close) on the ex-date.
- Universe: Nifty 500 members on each signal date (`data/index_membership/NIFTY500.parquet`, point-in-time).
- Benchmark: `data/indices/NIFTY500_TRI.parquet`.
- Fundamentals: BSE quarterly results (`data/bse_results`, standalone, Rs mn), each quarter usable from quarter
  end + 90 days (`fundamentals.pit` rule `unmatched_90`, the conservative date). ISIN by
  `data/bse_scrip_isin/map.parquet`.

## Periods
- Development: signals 2008-01 to 2014-12.
- Validation: signals 2015-01 to 2019-12 (24-month outcomes end by 2021-12).
- 2020-2026 signals: reported descriptively only, marked "not evidence" (2022-2025 is spent: CLAUDE.md rule 2).

## Signal dates and events
Month-ends (the allocator decides monthly). A stock-month is an event for a trigger if the trigger holds at that
month-end and did not hold for that stock in the previous 3 month-ends (one event per episode).

## Triggers (computed only from data dated on or before the signal date)
- `T0` baseline: every stock-month in the universe (an ordinary month-end buy).
- `T1(p)`: close at least p below its 252-session high; p in {10%, 15%, 20%, 30%}.
- `T2(k)`: drawdown from the 252-session high of at least k times the stock's 63-session volatility
  (daily return std x sqrt(63)); k in {1, 1.5, 2, 3}.
- `T3(r)`: 63-session return at least r below the Nifty 500 TRI's (a company-specific fall); r in {10%, 20%}.
- `T4`: the Nifty 500 TRI at least 10% below its 252-session high (market-wide dip), applied to all members.

## Safety filters (falling-knife guards; point-in-time)
- `F1 profitable`: trailing four quarters' net profit > 0.
- `F2 no collapse`: trailing net profit at least 50% of the trailing net profit a year earlier.
- `F3 can pay interest`: trailing (PBT + finance costs) / finance costs >= 2, or no finance costs.
- `F4 not a crash`: drawdown from the 252-session high no deeper than 50%.
- `Fsafe` = F1 and F2 and F3 and F4. Each trigger is evaluated with no filter, each filter alone, and Fsafe.
A stock with no usable results on the signal date fails F1-F3 (unknown is not safe).

## Outcomes (from the signal-date close)
- `R12x`: 12-month total return minus the Nifty 500 TRI's (and `R6x` for 6 months).
- `knife`: within 6 months the price falls a further 20% or more below the entry close.
- `ruin`: within 24 months the price falls 70% or more below entry, or trading stops after a fall of 50% or
  more (delisting and insolvency proxy).

## Pass rule (fixed now)
A trigger+filter combination passes only if, in BOTH development and validation:
1. its ruin rate is no higher than the baseline's (T0 with no filter);
2. its knife rate is no more than 5 points above the baseline's;
3. its median R12x is no lower than the baseline's.
Among passing combinations the rule chosen is the one with the lowest development ruin rate (ties: higher
development median R12x). Uncertainty is shown as a 95% interval for the median R12x difference to baseline from
a bootstrap over signal months (500 draws). If nothing passes, the answer is: no dip rule; the plain 10-month
schedule, with the safety filters still applied to every buy.

## What the live rule adds that history cannot test
Exchange surveillance (ASM, GSM, ESM, T2T, IBC), pending suspension, illiquidity and corporate-action price
breaks are checked live before any buy is proposed; there is no point-in-time history of those lists on disk,
so they are guards, not part of the test.

## Amendment 1 (2026-10-15, after the run): F3 does not apply to financial companies
Found when a bank (HDFC Bank) was added live and failed F3 (interest cover 1.32): for banks, NBFCs and insurers
interest expense is the business, not debt service, so "interest cover" does not measure solvency. The live
guard (`plan.safety`) skips F3 for companies whose sector is financial; F1, F2 and F4 still apply. The study's
numbers above are unchanged and still include financials under F3 (which excluded most of them from Fsafe);
re-running the study with this rule is listed in PLAN (S39 prerequisite) and its result will be reported here.

### Amendment 1, how the re-run applies it (registered 2026-10-16, before the re-run)
- A stock-month is financial when its sector label as of the signal date (`data.sector_map.sector_at`,
  `allow_later=False`: the latest NSE constituent-list capture on or before the date, ISIN then issuer match)
  satisfies `plan.safety.is_financial`. That test now also covers the pre-2014 label "FINANCIAL INSTITUTION"
  (PFC, REC, IFCI, IDFC), which it missed before; banks, finance, housing finance, financial services were
  already covered.
- For a financial stock-month F3 passes (F1, F2 and F4 still apply; no usable results still fails F1-F3).
- A stock-month with no label on or before the date counts as non-financial, so F3 applies as in the first run
  (about 2-20% of members per date have no point-in-time label).
- Sensitivity, reported beside it and not used for the choice: labels allowed from the first later capture
  (`allow_later=True`), which covers 97-100% of members.
- Everything else is unchanged: universe, periods, triggers, outcomes, pass rule, selection rule, seed. The
  first run's numbers stay in the results file; the re-run is a dated addendum there.

## Amendment 2 (2026-10-18, live guard only): F1-F3 on consolidated results where eight quarters exist
Found in live use (`docs/data/bse_results_finding.md` §7): standalone results misread group companies. One list
company that moved a business into subsidiaries shows standalone trailing profit down by two thirds (F2 fails) while
its consolidated profit is steady; another fails F3 standalone and passes it consolidated. Investors and lenders
judge a group on its consolidated accounts.

**Rule (fixed now, before any consolidated verdict is computed).** For each company the live guard uses the
consolidated quarters when the newest eight quarters are consecutive consolidated filings (BSE integrated filings,
dated by their filing time) and the newest of them is not older than the newest standalone quarter; otherwise the
standalone quarters exactly as before. F1-F3, the financial-company exemption from F3 and "unknown is not safe" are
unchanged; a failing reason names the basis when it is consolidated. Consolidated filings start with the March 2025
quarter, so the switch happens by itself once the December 2026 quarter is filed (about February 2027).

**Scope.** The study above was run on standalone history (2010-2021; consolidated data do not exist there in this
source) and is not re-run: this is a data-basis change of the live guard, recorded before it can change a verdict.
Fallback: standalone, as validated.
