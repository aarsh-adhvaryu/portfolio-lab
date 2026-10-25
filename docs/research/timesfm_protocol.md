# TimesFM for market risk: pre-registered protocol (S50)

Registered 2026-10-20, committed before any forecast was computed. The investor's decision (memory #45): TimesFM may go live
if it passes; test version 2.5 as well as 3.0. Code: `tools/timesfm_study.py` (prepare and evaluate, main venv),
`tools/timesfm_forecast.py` (forecasts, `.venv-train`). Changes after the first run need a dated amendment.

## Questions
1. **Volatility (decides the live risk fact).** Does TimesFM forecast the Nifty 500's realised variance over the next
   10 sessions better than the standard simple forecasts?
2. **Fall risk (decides a second market-state estimate).** Does TimesFM's volatility forecast rank the sessions
   before a -2% fall better than the live Hawkes chance does?

## Models
- **TimesFM 2.5** (`google/timesfm-2.5-200m-pytorch`, Apache 2.0, released 2025-09-15) and **TimesFM 3.0**
  (`google/timesfm-3.0-pytorch`, non-commercial licence, released August 2026); package `timesfm` 3.0.2 in
  `.venv-train`; zero-shot (no fine-tuning), point forecast, univariate, GPU.
- Configurations per version (6): input transform {squared returns r^2; absolute returns |r|} x context length
  {256, 512, 1024} sessions (shorter where less history exists). Forecast horizon 10. RV forecast = mean of the 10
  forecast values for r^2; for |r|, (mean of the 10 forecasts)^2 x pi/2 (the normal relation between E|r| and sigma).
  Negative forecasts are floored at 1e-10.
- **Baselines** (main venv): (a) trailing 22-session mean of r^2; (b) EWMA of r^2, lambda 0.94 (RiskMetrics); (c) HAR:
  OLS of the next-10-session RV on the trailing 1-, 5- and 22-session mean r^2, fitted on development only and frozen.
- **Hawkes chance** for question 2: the live frozen fit (`configs/hawkes_market.toml`, 2005-2019), computed as in
  `quant.drift.chances`. It was fitted on data that includes validation, which favours it (conservative for TimesFM).

## Data and periods
Nifty 500 TRI daily returns (`data/indices/NIFTY500_TRI.parquet`), 2004-01-02 on. A forecast made at the close of
session t uses only returns up to t (point in time) and is scored against sessions t+1..t+10.
- Development 2005-01-01 to 2014-12-31: choose each version's configuration and the best baseline; fit HAR.
- Validation 2015-01-01 to 2019-12-31: judged once.
- 2020-2025: described only (2022-2025 is spent).
- Clean holdout 2026-01-01 to the last session with 10 sessions after it: unseen by both models' training data
  (their listed sources end 2022-2023) and by every baseline fit.

## Measures and rules (fixed now)
- **Q1:** loss QLIKE = RV/F - ln(RV/F) - 1 per forecast date (RV the realised mean r^2 over t+1..t+10, F the
  forecast), mean over the period; MSE of ln F reported. Diebold-Mariano test on the QLIKE differences with Newey-West
  standard errors (lag 9, overlapping horizons). On development, each TimesFM version's configuration with the lowest
  QLIKE is chosen, and the baseline with the lowest QLIKE. **A version passes Q1** if on validation its mean QLIKE is
  below the chosen baseline's with one-sided DM p < 0.025 (two versions: Bonferroni), AND on the 2026 holdout its mean
  QLIKE is not above the baseline's (ratio <= 1.00; descriptive, no test: about 190 sessions).
- **Q2:** event E_t = at least one session of -2% or worse in t+1..t+10. Score: the version's chosen RV forecast; rival:
  the Hawkes chance. AUC on validation; one-sided p from a moving-block bootstrap of the AUC difference (blocks of 20
  sessions, 2,000 replications, seed 20261020). **A version passes Q2** if its AUC exceeds the Hawkes AUC with p < 0.025
  AND it is not below the Hawkes AUC on the 2026 holdout (descriptive).
- If both versions pass a question, the one with the better validation measure is used (The investor accepts the 3.0 licence
  for personal, non-commercial use).

## Use, fixed now
- Q1 passes: the risk tool and the morning report carry "expected Nifty 500 volatility over the next 10 sessions" from
  that version, labelled an ESTIMATE, refreshed by a nightly forecast step in `.venv-train`.
- Q2 passes: a TimesFM fall chance (logistic map of ln F to E, fitted on development, frozen) is shown beside the
  Hawkes market state in guards, propose and ask, as information; the dip rule and tranches do not change.
- Fails: nothing live; results reported in `docs/research/timesfm_results.md`.

## Known limits
Pretraining corpora (GiftEvalPretrain, Wikipedia pageviews, Google Trends, synthetic) are not listed as containing
Indian market series, but that cannot be excluded for 2005-2019; the 2026 holdout guards against it. Daily close data
only; no intraday realised variance. One index, so cross-sectional power is nil.
