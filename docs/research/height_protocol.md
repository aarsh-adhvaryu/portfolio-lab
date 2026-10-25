# "Height of the ride" study: pre-registered protocol

Registered 2026-10-16, committed before any result was computed. Changes after the first run need a dated
amendment; the first run's numbers stay in the report.

## Question
The Hawkes market state cannot foresee the first fall after a calm spell. The investor's framing: on a roller coaster
you cannot time the drop, but you can see how high you have climbed. Were big market falls within the following
year MORE COMMON when the market was "high" (expensive, stretched above its trend, unusually calm) than at other
times? This is about conditions, not timing. If yes, the system shows the height so a fall never comes in the dark.

## Measures at each month-end (point-in-time: each uses only data dated on or before that month-end)
- **Valuation**: Nifty 500 P/E (`indices/NIFTY500_VALUATION.parquet`) as a percentile of its own history to date.
  NSE changed the P/E method on 2021-03-31 (a 17% drop on a flat day): the percentile compares a value only with
  values from the same method period, and needs 3 years of that period (so it is missing from 2021-04 to 2024-03).
- **Stretch**: Nifty 500 TRI over its 200-session average, minus 1, as a percentile of its history to date (at
  least 3 years).
- **Calm**: India VIX 60-session average (`indices/INDIA_VIX.parquet`) as a percentile of its history to date (at
  least 1 year); LOW VIX counts as high on the ride, so the measure is 1 minus that percentile.
- **Height score** = the average of the measures available that month (0 to 1). **High** = score >= 0.80.

## Outcome
**Big fall**: within the 252 sessions after the month-end, the Nifty 500 TRI falls at least 15% below the
highest close reached since that month-end. Also reported: 12-month return.

## Periods
Development: month-ends 2009-03 to 2014-12. Validation: 2015-01 to 2019-12. 2020-01 to 2025-09 (the last month with
a full year after it): described only, "not evidence" (2022-2025 is spent).

## Pass rule (fixed now)
In BOTH development and validation: the big-fall rate after High months is at least 1.5 times the rate after the
other months AND at least 10 percentage points higher, with at least 6 months in each group.
Reported, not used to decide: each measure alone (its top fifth against the rest), and 12-month returns.

## Use
If it passes: the market state gains a height line (LOW below 0.50, NORMAL, HIGH at 0.80 or more) in guards,
propose and ask, and one Telegram message when the height turns HIGH. It is information: the plan's protection
for an unforeseeable fall stays the mix (debt, gold, the cash floor) and the 10-month staging; regular tranches
do not change. If it fails: nothing is added.

## Known limits
Month-ends overlap (a 12-month window spans 12 month-ends), so the real number of independent episodes is small
(a handful of big falls per period); the result is evidence, not proof.
