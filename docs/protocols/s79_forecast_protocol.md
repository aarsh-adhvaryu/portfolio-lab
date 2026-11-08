# S79 predict, score, correct: protocol (2026-11-05, committed before any run)

The system forecasts the benchmark index of each market (and the held and watched names) every session, scores each forecast
when it matures, and re-weights its own forecasters, all by code. This protocol fixes what counts as success before a single
forecast is scored. Nothing below changes after the first run; a change is an amendment with its date and reason. Code:
`src/pflab/fcast/` (rule in `score.verdict`). Registered in the learner's counter (`learn_tests`, notes `forecast_s79:IN` and
`forecast_s79:US`, one test per market, family "all"); the protocol file's SHA-256 is stored with the registration and the
verdict refuses to run if the file changed since.

## What is forecast
- **Subjects:** the market's index (IN: NIFTY 50 price index; US: S&P 500 price index) and every held or listed name.
- **Horizons:** 1, 5 and 20 SESSIONS on the market's own calendar (`markets.get(m).session_after`), never calendar days.
  A forecast made at the close of session s (data up to and including s) matures at `session_after(s, h)`.
- **Output:** quantiles at levels 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95 of the simple return from the close of s to the
  close at maturity. Quantiles are non-decreasing in the level.

## The forecasters (all code, point in time; constants fixed here)
Daily log returns r. sigma250 = standard deviation of the last 250 returns (at least 120). ewma = EWMA variance (lambda 0.94).
All quantiles are normal: simple return q = exp(mu + z_level * sigma_h) - 1.
- **naive** (the benchmark): mu = 0, sigma_h = sigma250 * sqrt(h).
- **volatility:** mu = 0, sigma_h = sqrt(h * (w * ewma + (1 - w) * sigma250^2)), w = h^-0.5.
- **momentum:** volatility's sigma_h; mu = +0.1 * sigma_h * tanh(z), z = (sum of the last 126 returns) / (sigma250 * sqrt(126)).
- **reversion:** volatility's sigma_h; mu = -0.1 * sigma_h * tanh(z), z = (log P - its 50-day mean) / (sigma250 * sqrt(50)).
- **overnight** (IN index only): mu = beta * (log return of the last US S&P 500 session dated strictly before the target
  session), beta from a rolling 500-session least-squares fit (at least 250 pairs) of India's daily return on the latest US
  return dated strictly before that Indian session; sigma_h = volatility's sigma_h * sqrt(1 - corr^2) for the first day,
  volatility's sigma_h beyond. It is made when the US close is known (before the Indian open), so it is a pre-open forecast.
  The hook `fcast.forecasters.EXTERNAL_GAP` records `quant.transmission.expected_open_gap` beside it but does not use it:
  a second transmission model would enter only through its own registered comparison.
- **hedge** (the combined forecast): the weight-averaged quantiles (Vincentisation) of the forecasters above.

## Correction by code only: Hedge on pinball loss
Each matured forecast gets the pinball loss at each level, averaged over the seven levels. The loss of a forecaster for the
weight update is relative to the benchmark: l_i = L_i / (L_i + L_naive), in [0, 1]. Weights per market and horizon:
w_i <- w_i * exp(-eta_h * l_i), then normalised, eta_h = 1 / h (a slow rate; overlapping horizons count less per day), then mixed with a
floor: a weight under 0.03 is lifted to 0.03 and the others scaled down to sum to 1, so no forecaster is ever below 3%. Weights start uniform (live: from the
last replay weights if a replay exists). The index forecasts drive the weights; names use the same weights over the forecasters
they have. No model sets a weight or a number.

## Success (decided per market, per horizon; rule in `score.verdict`)
The claim: the hedge forecast beats the naive forecast on LIVE sessions.
1. **Pinball loss.** d_t = L_naive,t - L_hedge,t (pinball loss averaged over the seven levels, same outcomes). Diebold-Mariano
   statistic: t = mean(d) / HAC standard error (Bartlett kernel, lags max(1, h - 1), as the forecasts overlap),
   one-sided. PASS needs t >= `counter.t_needed(N)`, N the number of tests in the family "all" at the time of the verdict
   (the bar rises with N), and a positive mean difference.
2. **Coverage.** The 80% range (10th to 90th quantile) covers between 75% and 85% of the live outcomes of that horizon.
3. **Sample.** At least 60 live sessions (60 scored forecasts, h = 1: 60 sessions; h = 5, 20: 60 origin sessions) per market
   and horizon before any verdict. **A verdict before the data exists is forbidden: below 60 the code returns "not enough
   data (n of 60)" and no pass or fail.** A market's overall verdict waits for all three horizons.
A pass wires the hedge forecast into the agents as the system's forecast; a fail leaves the forecasts shown as "not better
than the naive range" and the naive range serves.

## fall_risk (a probability, never a date)
- **Definition of a fall:** the benchmark's close, at any session within the next H = 20 sessions, is at least X = 5% below
  its close on the forecast date (the date's close is the level the fall is measured from; see Amendment 1).
- **Raw probability:** zero-drift reflection formula p = min(1, 2 * Phi(-d / sigma_20)) where d = ln(1 / 0.95) and
  sigma_20 is the volatility forecaster's 20-session sigma.
- **Calibration:** a logit shift a such that the mean calibrated probability equals the observed fall rate over the outcomes
  resolved up to the date (replay outcomes of 2012-2021 count as the prior, live outcomes added). Below 20 resolved outcomes
  the output shows the raw probability, n and "no conclusion".
- **Scoring:** Brier score of the probability against the realised 0/1, compared with the climatology Brier (the past fall rate
  as a constant). Verdict: Brier skill > 0 with the Diebold-Mariano rule above on the squared-error difference, at least 60
  live resolved forecasts; before that, refused.

## Amendment 1 (2026-11-05, before any live forecast was made or any claim registered)
Two corrections found by the first development replay (2012-2021; a development read, no live row existed). (a) The fall was first
defined from the 60-session high; states already 5% under that high made the event nearly certain (a fall rate of 46% in India)
and the Brier skill came from that, not from foresight; the fall is now measured from the forecast date's close. (b) The Hedge
floor was first a mixing floor applied at every step, which pulled all weights back to uniform and cancelled the learning; the
floor is now a lift: a weight under 3% is raised to 3% and the others scaled down to sum to 1. The success rules are unchanged.

## History replay (S79 item 9)
The forecasters, scoring and Hedge run day by day over 2012-01-01 to 2021-12-31 on the real index series to warm the weights and
test the loop on thousands of days. Sessions are the days the index traded. **Any date in 2022-2025 is refused in code
(2022-2025 is spent).** Replay rows carry `source = 'replay'`, are kept apart from live rows in every table, and are never
counted in the 60 live sessions or in any verdict. News and model-read features are forward-only: none enters the replay.
Replay numbers are a development read, not evidence of anything out-of-sample.

## Not decided here
Model-read news features, other horizons, other subjects and any second transmission model are new registered comparisons.
