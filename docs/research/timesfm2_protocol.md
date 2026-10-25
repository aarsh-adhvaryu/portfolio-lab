# TimesFM done properly (S52): pre-registered protocol

Registered 2026-10-20, committed before any forecast in this study was computed. The investor's decisions (2026-10-20):
use TimesFM wherever it can really help, configured to its full capability, with fine-tuning; 3.0's non-commercial
licence is acceptable for his personal use; build it as a live forecast service that scores itself and falls back to the
baseline. S50 (`timesfm_protocol.md`, `timesfm_results.md`) failed a narrow setup (zero-shot, raw r^2 input, median as
variance, no covariates); its result stands for that setup only. Changes after the first forecast need a dated amendment.

## What changes from S50, and why
| S50 | here | why |
|---|---|---|
| input r^2 or \|r\| | log of a daily variance proxy (Garman-Klass from OHLC; r^2 where OHLC is broken) | r^2 is mostly noise; log variance is smooth and persistent, the kind of series the model was trained on |
| point forecast (median) | the forecast distribution: E[variance] integrated over the quantile head | the median of a right-skewed quantity under-forecasts it |
| zero-shot only | zero-shot and LoRA fine-tuned (2.5), out of market and out of time | the model has seen little daily financial data |
| no covariates | VIX through a frozen combination model; calendar covariates (known ahead) through TimesFM's in-context regression | TimesFM's covariates need their future values; VIX's are unknown, a calendar's are known |
| Nifty only | ten foreign markets (their volatility never forecast-scored here), Nifty described, then live scoring | the Nifty's history is used up for this question |

## Models (all questions)
- **TimesFM 2.5** (`google/timesfm-2.5-200m-pytorch`, Apache 2.0) and **TimesFM 3.0** (`google/timesfm-3.0-pytorch`,
  non-commercial), package `timesfm` 3.0.2 in `.venv-train`. Quantile head on (deciles 0.1..0.9), `infer_is_positive`
  off for log inputs, `fix_quantile_crossing` on.
- **Fine-tuned 2.5:** LoRA (`peft` 0.21.2) on the attention and feed-forward projections of the transformer, rank r in
  {8, 16}, alpha 2r, dropout 0.05, AdamW lr 1e-4, batch 64, steps in {1000, 3000}; loss: mean pinball loss over the nine
  deciles plus squared error of the mean, on the forecast horizon. The four (r, steps) settings are chosen on an inner
  validation (the training fold's 2013-2014); the base weights are frozen. Seed 20261020.
- **Batches never mix forecast dates** where a model fits anything across the batch (the in-context regression): one
  date per batch. Without covariates, batching is safe (each series is forecast on its own).

## Tests
One-sided, family alpha 0.05 per question, split equally over that question's candidates (Bonferroni): the threshold
is written with each rule. A candidate that cannot run as written (an API limit found in the smoke test) is dropped
by a dated amendment before any forecast is scored, never after.

## Periods
Development 2005-01-01 to 2014-12-31 (context may start in 2000). Validation 2015-01-01 to 2019-12-31, judged once.
2020-2021 described only; 2022-2025 spent (CLAUDE.md rule 2), not scored. Holdout 2026-01-01 to the last date with a
full horizon after it: descriptive, not tested (too short). A forecast at the close of t uses only data up to t.

## Markets and folds
Ten indices from `data/global` (Yahoo, daily OHLC): fold A = US_SP500, DE_DAX, JP_NIKKEI225, HK_HANGSENG, AU_ASX200;
fold B = UK_FTSE100, KR_KOSPI, TW_TAIEX, CN_SHANGHAI, BR_BOVESPA. A model fine-tuned on fold A's 2000-2014 is scored on
fold B's validation and holdout, and the other way round: every fine-tuned score is out of market and out of time.
Zero-shot models and baselines are scored on all ten. Nifty 50 (`indices/NIFTY50_PRICE.parquet`, OHLC) with India VIX:
described only (S50 used the Nifty), then judged live by the scoreboard.

Daily variance proxy v_t: Garman-Klass 0.5 ln(H/L)^2 - (2 ln 2 - 1) ln(C/O)^2 plus the overnight term ln(O_t/C_{t-1})^2,
where H > L, H >= max(O, C), L <= min(O, C); else r_t^2. Input x_t = ln(max(v_t, 1e-8)).

## Q1. Volatility over the next 10 sessions (use 1: risk agent and Monte Carlo)
Target RV_t = mean of r^2 over t+1..t+10 (close to close, as S50). Loss QLIKE = RV/F - ln(RV/F) - 1.
- Candidates: T25 (2.5 zero-shot), T30 (3.0 zero-shot), F25 (2.5 fine-tuned, by fold), C (combination: per market, OLS
  of ln RV on the HAR terms of ln v and ln F25, where F25 is the model trained on the OTHER fold, plus ln VIX where the
  market has one in our data (US_SP500: US_VIX, same close); fitted on that market's development, frozen).
- Configurations, chosen per candidate on development by QLIKE over its scored markets: context {512, 1024}; input
  {x_t; 5-session trailing mean of v, logged}.
- Forecast F = mean over h=1..10 of the average over the nine deciles of exp(Q_q,h), times a scale fitted on development
  per candidate (QLIKE-optimal: the mean of RV/F) to map the proxy's level to close-to-close variance.
- Baselines: EWMA of r^2 (0.94); HAR on r^2 (S50); HAR on ln v (the same information TimesFM gets), each fitted per
  market on development; the baseline with the lowest development QLIKE over all ten markets is THE baseline. Any
  regression in logs (HAR on ln v, C) is back-transformed as exp(fit + s^2/2), s^2 its development residual variance.
- **Pass:** on validation, the candidate's QLIKE is below the baseline's, pooled over its markets: d_t = mean over the
  markets open on date t of the loss difference; one-sided Diebold-Mariano on d_t, Newey-West lag 9, p < 0.0125
  (four candidates: Bonferroni) AND lower QLIKE in at least 7 of 10 markets (4 of 5 for F25 and C, per fold, both
  folds) AND on the holdout the pooled QLIKE ratio to the baseline is <= 1.00. Of the passing candidates the lowest
  validation QLIKE is used.

## Q2. Chance of a -2% session within 10 sessions (use 1b: beside the Hawkes market state)
Event E_t: some session in t+1..t+10 at -2% or worse. Score from each Q1 candidate's variance path s_h^2:
P = 1 - prod_h (1 - Phi(-0.02 / s_h)). Rival: the EWMA volatility chance live now (S51 amendment 3, `guards.vol_chance`
logic, each market's own fit). AUC pooled over markets on validation; one-sided p from a moving-block bootstrap of the
AUC difference within each market (blocks 20, 2,000 replications, seed 20261020).
**Pass:** p < 0.0125 AND higher AUC in at least 7 of 10 markets AND not below the rival on the holdout. Brier score and
a reliability table reported. Known limit: S51 saw the EWMA chance's validation AUC on these markets (not TimesFM's).

## Q3. Ranges over 3, 6 and 12 months (use 1c: the 1-year view and the Monte Carlo's width)
Target R_t(h) = ln(C_{t+h} / C_t), h in {63, 126, 252} sessions; forecast dates every 5th session.
- Candidates: TimesFM 2.5 and 3.0 zero-shot on the log close (context 1024 sessions, horizon h, deciles of
  ln C_{t+h} - ln C_t).
- Baselines: (a) bootstrap of the market's own past h-session log returns up to t (the Monte Carlo's way);
  (b) normal, mean = the market's expanding mean daily log return x h, sd = EWMA (0.94) daily sd x sqrt(h);
  (c) normal with the expanding sd. THE baseline: lowest development loss.
- Loss: mean pinball loss over the nine deciles (approximates CRPS). Coverage of the 10-90 band reported.
- **Pass (decided per h, two versions):** pooled validation loss below the baseline's, DM on the per-date mean
  difference with Newey-West lag h/5 (the 5-session spacing), p < 0.025, AND 10-90 coverage between 0.70 and 0.90.
- **Q3b (registered now, for the Monte Carlo):** does baseline (b), the volatility-aware range, beat (a) at h = 252?
  Same test, p < 0.05. If yes, the Monte Carlo scales its bootstrap draws to the current EWMA volatility (the mean
  unchanged), decaying to 1 as below.

## Q4. The 12-month return itself (The investor's question; expected to fail)
Point forecast: the median of the Q3 TimesFM range at h = 252. Rival: the market's expanding mean (the "historical
average"). Out-of-sample R^2 = 1 - sum (R - f)^2 / sum (R - hist)^2, pooled over markets on validation; Clark-West test,
Newey-West lag 50 (252/5), p < 0.05 (one version, chosen on development). **Pass:** OOS R^2 > 0 and p < 0.025 and
OOS R^2 > 0 on the holdout. Fails: no return forecast anywhere; the 1-year view keeps the labelled assumption.

## Q5. Turnover over the next 5 sessions (use 2: the trader's tickets)
Stocks: 200 drawn (seed 20261020) from NIFTY 500 members on 2015-01-01 (`index_membership`, point-in-time) with
turnover on at least 90% of sessions 2008-2019. Target: ln of mean daily turnover (bhavcopy) over t+1..t+5; forecast
dates every 5th session; development 2008-2014. Candidates: TimesFM 2.5 and 3.0 zero-shot on ln turnover, with and
without calendar covariates (day of week, month end, monthly F&O expiry week: all known ahead) through
`forecast_with_covariates` (mode "xreg + timesfm", one date per batch). Baselines: 20-session mean of ln turnover; HAR on
ln turnover with the same calendar dummies. Loss: squared error. **Pass:** pooled DM (per-date mean over stocks,
Newey-West lag 1), p < 0.0125 (four candidates), lower loss for at least 60% of stocks, holdout ratio <= 1.00.

## Q6. Next quarter's results (use 3: thesis tracker and results ranges)
Companies with at least 24 quarters in `bse_results` (standalone revenue and net profit). A forecast for quarter q is
made when q-1's result is usable: quarter end + 60 days (later than SEBI's deadlines, so point-in-time without
dissemination dates). Targets: ln revenue(q); net margin(q) = net profit / revenue. Development: quarters ending
2013-2017; validation: 2018-2019; holdout: quarters ending in 2026. Candidates: TimesFM 2.5 and 3.0 zero-shot (context
all quarters available, horizon 1), F25 fine-tuned by company fold (companies split by scrip code parity, trained on
2017 and earlier). Baselines: same quarter last year; same quarter last year x trailing four-quarter YoY growth;
the baseline with the lower development loss. Loss: absolute error. **Pass (per target):** per company the mean
validation loss difference; one-sided t across companies p < 0.0167 (three candidates), and lower loss for at least 55%
of companies, and holdout not worse (pooled).

## Use, fixed now (only what passes goes live; what fails has no live feature)
- Q1: a nightly forecast step in `.venv-train` writes `PFLAB_DATA_DIR/forecasts/vol/<date>.parquet` (Nifty 50; the mix's
  markets where data exist): "expected volatility over the next 10 sessions", an ESTIMATE, in the risk tool, the fact
  sheet and the morning report; the Monte Carlo scales its draws by forecast / long-run volatility, the ratio decaying
  to 1 at the half-life of an AR(1) on monthly ln RV of the Nifty 50, 2005-2014 (fitted once, frozen).
- Q2: the TimesFM chance replaces the EWMA chance shown beside the Hawkes state; Hawkes keeps the state and its alerts.
- Q3: the 1-year view shows the passing range; Q3b alone: the Monte Carlo's vol scaling as above.
- Q4: a central 12-month estimate beside the assumption, labelled. Q5: tickets check size against forecast turnover.
- Q6: before each result, the range for revenue and margin (labelled); after it, the surprise against the range, in
  the thesis tracker and the researcher's flags.

## Live scoreboard and fallback (fixed now)
Every live forecast is stored with its as-of date, inputs' last date, model version and the baseline's forecast for the
same target. Each night, forecasts whose targets have matured are scored. Per use, over the last N matured forecasts
(Q1/Q2: 120 sessions; Q3: 26 dates per horizon; Q5: 60 dates; Q6: the last two quarters' companies), if the loss ratio
to the baseline is above 1.05 (Q2: AUC below the rival's by 0.03) with at least half of N matured, the agents switch to
the baseline and the morning report says so; TimesFM resumes for that use when the ratio is <= 1.00 over a full window.

## Compute and dependencies
GPU work runs only after S47 pass 3 finishes (one GPU job at a time), probed on the worst case first, checkpointed,
logged with `tools/gpu_log.ps1`. Q5's covariates need `timesfm[xreg]`: jax (CPU build; CUDA jax is not supported on
Windows) and scikit-learn, pinned in `.venv-train` and recorded in CLAUDE.md when installed.

## Amendment 1 (2026-10-20, before any forecast; from reading the installed timesfm3 API)
TimesFM 3.0's `predict_batch` takes covariates natively and per series (cross-variate attention, no fit across the
batch): `past_only_covariates` (values up to t only) and `past_future_covariates` (values known over the horizon too).
So:
- **Q1 and Q2 gain a fifth candidate, T30X:** 3.0 with past-only covariate ln US_VIX, aligned point in time (same
  session's close for US_SP500 and BR_BOVESPA, which close with or after New York; the previous US session for the
  others), the global fear gauge every market can use. Thresholds become p < 0.01 (five candidates).
- **Q5's covariate candidate uses 3.0's native past-future covariates** (day of week, month end, F&O expiry week)
  instead of 2.5's in-context regression; the 2.5-with-covariates candidate is dropped. Candidates: T25, T30, T30C;
  threshold p < 0.0167. `timesfm[xreg]` (jax, scikit-learn) is no longer needed: no new dependency.
- Options for every 3.0 call: quantiles returned, symmetric averaging on, `make_positive` off for log inputs (on for
  turnover in levels, not used here), quantiles sorted; 2.5: continuous quantile head, flip invariance, quantile
  crossing fixed, `infer_is_positive` off. Both forecast functions' "point" output is the median; it is not used.

## Amendment 2 (2026-10-20, before any forecast; fixing what the code needs)
- **F25's input (Q1)** is the input T25 prefers on development (`timesfm2_study.py dev-choice`, written to
  choices.json before fine-tuning); F25 is trained on contexts drawn from {512, 1024}, and its context is then chosen on
  development like the other candidates'.
- **Fine-tuning schedule:** one run per rank with a constant learning rate, adapters kept at 1000 and 3000 steps (equal
  to separate runs of those lengths). Inner split: Q1 trains on targets ending by 2012-12-31 and selects on forecast
  dates in 2013-2014; Q6 trains on quarters ending by 2015-12-31 and selects on 2016-2017. Selection metric: mean
  pinball loss of the deciles on the series itself (flip-averaged, as at inference). The chosen adapter is merged and
  used as trained (no refit). Before any training, `timesfm2_finetune.py check` must show the training forward equals
  the library's forecast (max difference <= 1e-3); otherwise F25 and C are dropped.
- **Holdout conditions** apply only where at least 20 holdout forecast dates have matured. At 126 and 252 sessions
  (Q3) and for Q4 none have yet (2026 + one year has not happened): those conditions pass to the live scoreboard.
- **The Nifty (described only)** uses India VIX as T30X's covariate (its own fear gauge, same close).
- **Q2's Brier score** uses each market's logistic map of the score to the event, fitted on development.
- **Q5 development** is 2008-2014 (forecast dates before 2008 are not scored).

## Amendment 3 (2026-10-21, before any fine-tuning step and before any forecast was scored)
- **One LoRA rank (r = 16)** instead of {8, 16}: the fine-tuning grid becomes r 16 at 1000 or 3000 steps (chosen on the
  inner validation as before). Reason: run time on the laptop (about 3-4 h saved; the investor may need to pause the run);
  rank rarely decides a LoRA result. Nothing else changes.
- **Pace only, results unchanged** (recorded, not a change of method): after the GPU dropped off the bus on 2026-10-21
  04:29, forecasting runs in batches of 32 (was 128) and every GPU loop pauses at 83 C until 72 C (`tools/gpu_guard.py`).
  Each series is forecast on its own, so batch size and pauses do not change a forecast; the one TimesFM 3.0 file
  written at batch 128 was deleted so that all 3.0 files share one setting.

## Amendment 4 (2026-10-21, before any fine-tuning step and before any forecast was scored; the investor's call on run time)
- **Fine-tuning steps {500, 1500}** instead of {1000, 3000} (rank 16, chosen on the inner validation as before):
  1500 steps of 64 windows is about 96,000 training windows per fold.
- **The temperature guard is removed and forecasting is back to batches of 128.** The laptop crashed again at 16:23
  with the guard on; the telemetry shows the guard's 5-second pauses made the GPU swing from idle to full boost dozens
  of times, the kind of load step that upsets it. A steady full load is the better of the two. Of the TimesFM 3.0
  files, 13 were written at batch 32 and the rest at 128; each series is forecast on its own, so this changes no
  forecast beyond float rounding.

## Amendment 5 (2026-10-21, before any fine-tuning step and before any forecast was scored; the investor: run the full one overnight)
- **The registered fine-tuning grid is restored** (amendments 3-4 withdrawn): ranks {8, 16} x {1000, 3000} steps.
  Measured on the capped GPU: 0.13-0.20 s per step, so the full grid takes about 1.5 h.
- **Training sees windows exactly as forecasting does:** the library's own cleaning (leading NaNs dropped, inner NaNs
  interpolated) instead of masking, and a window with fewer than 8 known values is skipped (as in forecasting).
- **Training targets are clipped at +-10 sd of their own window** (loss and inner selection only): net margins in the
  training years reach 2,332 sd (a loss of 19,000x revenue), which would swamp the squared-error term. Scoring is
  unchanged (absolute error on the raw margin, as registered).
- **Forecasting:** a context with fewer than 8 known values gets no forecast (1,506 Q5 dates in 40 stocks, mostly
  before listing; 1 Q6 margin row); Q5 compares candidate and baseline on the same dates.

## Known limits
Yahoo is not an official source; 2000-2014 OHLC of some indices is patchy (Nikkei, ASX, DAX early years: the r^2 fallback).
TimesFM's pretraining corpus may include some of these markets' public series before 2023; the fine-tuned scores are
out of market for our fine-tuning but cannot be out of Google's pretraining. The 2026 holdouts are short. One forecast
date per market per session, so markets, not dates, carry most of the power.
