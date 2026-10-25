# Early-warning study: pre-registered protocol

Registered 2026-10-16, committed before any result was computed. Changes after the first run need a dated
amendment; the first run's numbers stay in the report.

## Question
The market state (Hawkes) speaks once falls cluster but cannot foresee the FIRST fall after a calm spell, and the
"height" study found no warning in valuation, stretch or calm. Do outside signs (fear jumping in India or the US,
a big US fall overnight, foreign investors pulling money out) come shortly BEFORE first falls, often enough and
rarely enough otherwise to be a useful warning?

## Event
A **first fall**: a Nifty 500 TRI session of -2% or worse with no such session in the 20 sessions before it.

## Signals, known before the Indian open of session s (only data dated before s's date)
- **S1 India fear jump**: the latest India VIX close (`indices/INDIA_VIX.parquet`) at least 20% above its close
  5 sessions earlier.
- **S2 US fall overnight**: the latest S&P 500 session (`global/US_SP500.parquet`, adjusted close) down 2% or more.
  (The US close dated D is about 01:30-02:30 IST on D+1, before the Indian open.)
- **S3 foreign selling**: the sum of FPI equity net investment (`macro/FPI_DAILY.parquet`, asset Equity, route
  Sub-total) over the latest 5 report dates is in the lowest 10% of all such 5-date sums to date (at least one
  year of history). A report dated D is compiled at the end of D.
- **S4 US fear jump**: the latest US VIX close (`global/US_VIX.parquet`) at least 25% above its close 5 US sessions
  earlier.
- **Warning** = any of S1-S4.

## Measures (per period, over Indian sessions s)
Y(s) = a first fall happens in sessions s to s+4 (this week). Base rate P(Y); precision P(Y | warning);
**lift** = precision / base rate; **recall** = the share of first falls with a warning on at least one of the
sessions from 4 before it to the day itself; **frequency** = the share of sessions with a warning.

## Periods
Development 2010-01-01 to 2014-12-31 (all four inputs exist from 2010); validation 2015-01-01 to 2019-12-31;
2020-01-01 onward described only, "not evidence" (2022-2025 is spent).

## Pass rule (fixed now)
The combined warning passes only if, in BOTH development and validation: lift >= 2.0, recall >= 50%, frequency
<= 25% of sessions, and at least 8 first falls in the period. Each signal alone is reported, not used to decide.

## Use
If it passes: the market state gains an EARLY WARNING line (which signs fired) in guards, propose and ask, and one
Telegram message before the open when a warning starts; the daily collection adds the US index, US VIX and FPI
flows. Regular tranches and the dip rule do not change (a warning is a heads-up, not a trade). If it fails:
nothing is added.
