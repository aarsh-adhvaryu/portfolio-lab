# S64 price ranges from calibrated statistics: protocol (2026-10-26, committed before any run)

TimesFM is removed (S52 Q1-Q4 failed). Price ranges for each holding and each name on the stock list come from the
stock's own history. This protocol decides which method may serve, by coverage on unseen data. Nothing below changes
after the first run; a change is an amendment with its date and reason. This is S64 Phase 3c of `docs/S64_BUILD_PLAN.md`.

## The two methods (`quant/forecast.py`)
Both draw 10,000 paths of daily log returns for h sessions from a stationary block bootstrap (Politis-Romano, mean block
length 10) of the stock's own daily log returns over the last 750 sessions, take the price quantiles q10, q50, q90 at h,
and use the CAPM expected return (`risk/capm.py`; never momentum) as the centre: each draw's sample mean is removed and
the daily drift ln(1 + E[r]) / 252 is added.
- **stats_plain:** the draws as they are.
- **stats_ewma:** the draws are rescaled by the ratio of today's EWMA volatility (lambda 0.94, `baselines.ewma`) to the
  sample volatility of the 750 sessions.

## The test
- **Origins:** every month end; each origin uses a seeded random sample of 100 point-in-time Nifty 500 members with at
  least 750 sessions of history and a CAPM fit (60 months; 36 at least); the same sample for both methods.
- **Horizons:** 21 and 63 sessions. **Periods:** development 2010-2017, validation 2018-2021 (2022-2025 is spent).
- **Point in time:** returns up to the origin; the CAPM beta from the 60 months ended at the origin; the market premium
  is the expanding mean of the Nifty 500 TRI excess return over cash up to the origin (not the fixed 2005-2021 premium
  the live label uses, which would look ahead); cash is the futures-carry rate known at the origin (`data/riskfree.py`).
- **Realised:** the total-return index of the stock h sessions after the origin against the price at the origin.
- **Scores:** coverage of the 80% interval (share of outcomes between q10 and q90), and the pinball loss averaged over
  the three quantiles (0.1, 0.5, 0.9).

## Decisions (rule in code: `quant/ranges_eval.py`)
1. A method **passes coverage** if its 80% interval covers between 75% and 85% of outcomes in **both** periods, at both
   horizons.
2. `stats_ewma` **replaces** `stats_plain` only if its pinball loss is lower by a Diebold-Mariano test (one-sided, Newey-West
   HAC on the monthly mean loss differences, lags h/21 + 1) with t >= `counter.t_needed(N)` in development (this counts
   as one test in the family "all"), t >= 1.65 in validation, and it passes coverage.
3. **Serving:** the method that passes serves (if both pass and the replacement test fails, `stats_plain`). If neither
   passes, ranges are still shown, labelled "not calibrated: covered x% in testing" with the lowest-covering period's
   figure. Until this test has run, ranges are labelled "not tested yet".
4. **Live scoring:** each stored range is scored when due (inside or outside, pinball loss); the rolling coverage of the
   last 60 scored ranges per method and horizon is shown beside the range and in the brain's `forecasts` tool.

## Not decided here
A return forecast (a centre other than the CAPM expected return) would be a new registered study. The horizon of 252
sessions is served and scored live but not tested here (too few independent origins to test coverage in 2010-2021 with a
monthly step; its label says so).

## Run
`.venv\Scripts\python -m pflab.cli forecast test` (more than 5 minutes: the investor's). Result file:
`PFLAB_DATA_DIR\research\s64_ranges.json`, written to `docs/research/s64_ranges_results.md` after.
