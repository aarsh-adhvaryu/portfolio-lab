# Hawkes processes study: pre-registered protocol (S40)

Registered 2026-10-16, committed before any model was fitted to real data. Changes after the first run need a
dated amendment at the end; the first run's numbers stay in the report. Research and descriptions only.

## Questions
1. **Crash clustering (decides the live alert).** Do big down days of the whole market come in clusters, in a
   way that a model fitted on earlier years predicts better than "they arrive at random"?
2. **Stocks (descriptive).** The same for large stocks' own big down days, and how much a market fall raises
   the chance of a stock's fall (cross-excitation).
3. **Filings (descriptive).** Do a company's BSE filings come in bursts?

## Model and tools
Exponential Hawkes processes (`pflab.quant.hawkes`): univariate lambda(t) = mu + alpha beta sum exp(-beta (t -
t_i)), bivariate with one alpha and beta per pair of streams. Maximum likelihood (scipy L-BFGS-B, six starts).
Goodness of fit by time rescaling: compensator increments between events against Exp(1), Kolmogorov-Smirnov.
Baseline model: a homogeneous Poisson process (constant rate).

## Data and events
- **Market:** Nifty 500 TRI (`data/indices/NIFTY500_TRI.parquet`). Event: a session whose total return is -2.0%
  or worse. Time: session number plus a uniform position within the session (seed 20261016), so no two events
  tie.
- **Stocks:** Nifty 100 members on 2014-12-31 (`index_membership/NIFTY100.parquet`) with a total-return price on
  at least 95% of sessions from 2005-01 to 2019-12 (NSE panel, adjusted close and dividends). Event: a session
  return of -4.0% or worse. Same time convention. Bivariate: (market events, the stock's events).
- **Filings:** Nifty 100 members on 2019-12-31 mapped to BSE scrip codes (`bse_scrip_isin/map.parquet`);
  events are BSE announcement dissemination timestamps (`data/bse_announcements`), time in calendar days;
  filings with an identical timestamp count once. Companies with at least 100 filings in development.

## Periods
- Market and stocks: development 2005-01-01 to 2014-12-31 (fit); validation 2015-01-01 to 2019-12-31
  (scored with the development parameters, the intensity using every earlier event); 2020 onward described
  only, "not evidence" (2022-2025 is spent).
- Filings (the archive starts 2015-08-12): development 2015-08-12 to 2019-12-31; validation 2020-01-01 to
  2021-12-31; later years not used.

## Tests for each series
(a) in sample: likelihood-ratio test of Hawkes against Poisson, p < 0.01;
(b) out of sample: validation log-likelihood of the Hawkes fit above the Poisson fit's (both with development
    parameters);
(c) validation time-rescaling: KS p-value >= 0.05 for the Hawkes residuals.

## Pass rule (fixed now) and its use
The market series passes if (a), (b) and (c) all hold. Then, and only then:
- parameters are re-estimated once on 2005-01-01 to 2019-12-31 and frozen (no refit on spent years);
- **alert:** after a close where the market intensity is at least 3 times its baseline mu, one alert a week:
  the model's chance of another -2% session within the next 10 sessions, beside the constant-rate chance,
  labelled an estimate;
- **risk agent:** the same 10-session chance becomes a fact of the risk tool.
If the market series fails, no alert and no risk fact; the fits are reported only.
Stocks and filings are reported as shares of series meeting (a), (b), (c), with median branching ratio,
half-life and (stocks) median cross-excitation from the market; nothing live depends on them.

## Known simplifications
Constant baseline: seasonality (results seasons for filings, the weekday pattern of trading) is read as
excitation where it exists, which the time-rescaling test should expose. Daily data have no order within a
session, hence the uniform placement. Thresholds are fixed, not volatility-scaled.

## Amendment 1 (2026-10-16, AFTER the first run; the investor's decision): market state replaces the 3x alert
Why: the registered 3x-baseline trigger sits below the average intensity and would fire in about 40% of weeks,
even when the model's chance is below normal (results file). The investor asked for a fix that misses no clustering
episode (no false negatives), is not limited to major crashes, and works together with the dip rule and the
deployment plan. Fixed here before any of the numbers below were computed.

**Measure.** C(t) = the model's chance of at least one more -2% session within the next 10 sessions, at the close
of session t (exact, `hawkes.chance_within`).

**States.** calm: C < T1; elevated: T1 <= C < T2; high: C >= T2, with T2 = 0.80 (The investor).
T1 is chosen on development data only (2005-2014, development parameters): a "follow-on fall" is a -2% session
with another -2% session in the 10 sessions before it; recall(T) = share of follow-on falls whose previous close
had C >= T. T1 = the highest T on a 0.01 grid with recall >= 90%. Reported, not used to choose: recall and the
share of sessions in each state for validation (2015-2019) and 2020-2026, and recall of all -2% sessions (a first
fall after a calm spell cannot be foreseen by this model; the drawdown and dip rule cover slow declines).

**Messages.** One Telegram message when the state changes (calm to elevated, to high, back to calm), never
weekly repeats; the state is always shown in `pflab pm guards`, `pflab pm propose` and `pflab ask`.

**Link to investing (test, fixed now).** Regular monthly tranches never depend on the state. Question: when the
dip rule is active (Nifty 500 TRI >= 10% below its 252-session high), should the extra dip tranche wait while the
state is elevated or high? Month-ends 2008-2019 with the dip rule active, state from the development parameters
at that close; outcomes on the Nifty 500 TRI from that close: further fall (the minimum over the next 126 sessions
at least 10% below the close) and 12-month return. The wait rule is adopted only if, in BOTH development
(2008-2014) and validation (2015-2019), dip month-ends in elevated/high state had a HIGHER further-fall rate AND a
LOWER median 12-month return than dip month-ends in calm state, with at least 3 month-ends in each group. If it
passes: the extra tranche waits while the state is elevated or high and is bought at the first month-end when
the state is calm and the dip rule is still active. If it fails: the dip rule stays exactly as in S34 and the
state is information only.

## Amendment 2 (2026-10-18, registered before computing; the investor chose "keep it and re-study it")
Why: the S46 drift check flagged the market state (recall of follow-on falls 75% on 28 since 2020, floor 80%). The
cause found: amendment 1 chose T1 = 0.40 and measured every recall with the DEVELOPMENT fit (2005-2014: mu 0.0174),
but the live state and the drift check compute the chance with the FROZEN fit (2005-2019: mu 0.0125), whose chances
are lower. With the development fit, 2020 onward reads 82% (above the floor); with the frozen fit 75%, and even
2005-2014 reads 87% (below the 90% the rule asked for). The threshold was chosen on one model and used with another.

**Re-study (fixed now).** Same rule, same data, the model that runs live: T1' = the highest T on a 0.01 grid whose
recall of 2005-2014 follow-on falls is at least 90%, with C(t) from the FROZEN parameters (`configs/hawkes_market.toml`).
T2 stays 0.80 (The investor). Reported: recall and the share of sessions in each state for 2005-2014, 2015-2019 and 2020 on,
with T1'. The dip-tranche wait test is not re-run (it failed; the dip rule stays as in S34).

**Keep or retire (fixed now).** With T1', the S46 drift check is run as registered (2020 onward: KS p-value >= 0.01,
and recall >= 80% when there are at least 10 follow-on falls). Passes: T1' replaces t1 in the config and the state
stays as information. Fails: the market state is retired from guards, propose, ask and alerts (The investor: retire it if the
re-study fails). 2020 onward is not independent evidence (2022-2025 is spent); this checks the live rule is
consistent with how it was chosen, nothing more.
