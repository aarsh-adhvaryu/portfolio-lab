# TimesFM done properly (S52): results

Run 2026-10-21 (log `PFLAB_PM_DIR\reports\s52_2026-10-21.log`, every step ok, FINISHED 22:19). Checked 2026-10-22
against the files, not the notice: `data/research/timesfm2/results.json` (the registered rules,
`quant/tfm2_eval.py` as committed with the protocol on 2026-10-20), six `ft/*/meta.json` (q1, q6 ln_revenue, q6 margin;
folds A and B), all forecast sets. Described-only numbers: `timesfm2_study.py describe` -> `describe.json` (no rule).
Protocol: `timesfm2_protocol.md`, amendments 1-5, all before any forecast was scored.

**Decisions.** Q1 fail, Q2 fail, Q3 fail (every h), Q3b fail, Q4 fail: no live feature for any of them (risk tool,
Monte Carlo, volatility chance and the 1-year view stay as they are). **Q5 passes: T30C goes live** (turnover for the
trader's tickets). **Q6 passes: F25 for revenue, T25 for net margin go live** (results ranges for the thesis tracker
and the researcher). Both with the registered scoreboard and fallback.

## Q1. Volatility over the next 10 sessions (fail)
Rule: pooled QLIKE below THE baseline on validation (2015-2019), DM p < 0.01 (five candidates), breadth 7 of 10 markets
(F25, C: 4 of 5 in each fold), holdout ratio <= 1.00. THE baseline (development): HAR on ln v (0.221; HAR on r^2
0.254, EWMA 0.264). Validation baseline QLIKE 0.290.

| candidate | config | val QLIKE | DM p | markets better | holdout ratio (1,691 rows) |
|---|---|---|---|---|---|
| T25 | log, 1024 | 0.298 | 0.91 | 5/10 | 0.92 |
| T30 | log, 1024 | 0.299 | 0.92 | 4/10 | 0.93 |
| T30X (US VIX) | log, 1024 | 0.290 | 0.47 | 5/10 | 0.90 |
| F25 (fine-tuned) | log, 1024 | 0.313 | 0.99 | A 0/5, B 3/5 | 1.04 |
| C (combination) | - | 0.286 | 0.20 | A 2/5, B 4/5 | 1.09 |

No candidate beats HAR on the same log-variance input on validation. Fine-tuning made it worse out of market (F25 has
the best development QLIKE, 0.224, and the worst validation). The zero-shot models do better on the 2026 holdout
(0.90-0.93), but the holdout is a condition, not a test.

## Q2. Chance of a -2% session within 10 sessions (fail)
Rule: pooled validation AUC above the live EWMA chance, block-bootstrap p < 0.01, breadth as Q1, holdout not below.

| candidate | AUC diff | p | markets better | holdout AUC (rival 0.725) | Brier |
|---|---|---|---|---|---|
| T25 | +0.010 | 0.069 | 7/10 | 0.728 | 0.163 |
| T30 | +0.011 | 0.045 | 7/10 | 0.731 | 0.164 |
| T30X | +0.013 | 0.027 | 6/10 | 0.736 | 0.163 |
| F25 | -0.000 | 0.49 | A 2/5, B 4/5 | 0.723 | 0.169 |
| C | +0.015 | 0.005 | A 3/5, B 4/5 | 0.731 | 0.162 |

**C, recorded as a registration discrepancy.** The protocol's Q2 text says "at least 7 of 10 markets" (C has 7); the
rule code committed with it (48113c9, 2026-10-20, before any forecast) applies Q1's per-fold breadth to F25 and C (C has
3 of 5 in fold A). Decided 2026-10-22: **the stricter reading stands, C fails.** Reasons: the registration (text plus
code, committed together) must be passed as a whole; the per-fold rule exists because these models are out of market
per fold, which holds for Q2 as for Q1; and C has no defined live form for the Nifty (it needs an F25 from the other
fold, and the Nifty is in neither). The safe side is the live EWMA chance, 0.015 AUC behind. A later attempt needs its
own registration.

## Q3. Ranges over 3, 6 and 12 months (fail); Q3b (fail); Q4 (fail)
Rule: pooled pinball loss below THE baseline, DM p < 0.025, 10-90 coverage in [0.70, 0.90]. Baselines chosen on
development: bootstrap at 63 sessions, normal with EWMA sd at 126 and 252.

| h | baseline val | T25 val (p, coverage) | T30 val (p, coverage) |
|---|---|---|---|
| 63 | 0.0245 | 0.0253 (1.00, 0.75) | 0.0261 (1.00, 0.71) |
| 126 | 0.0325 | 0.0343 (1.00, 0.72) | 0.0364 (1.00, 0.69) |
| 252 | 0.0441 | 0.0469 (0.87, 0.72) | 0.0507 (1.00, 0.64) |

Q3b (does the volatility-aware normal beat the bootstrap at one year, p < 0.05): p 0.15, fails: the Monte Carlo keeps
its unscaled bootstrap. Q4 (T25 chosen on development): out-of-sample R^2 on validation -0.095 (development -0.080),
Clark-West p 0.19, fails: no return forecast anywhere; the 1-year view keeps its labelled assumption. No 126- or
252-session holdout has matured.

## Q5. Turnover over the next 5 sessions (passes: T30C)
Rule: pooled MSE below THE baseline, DM p < 0.0167, lower loss for at least 60% of stocks, holdout ratio <= 1.00.
200 stocks; THE baseline: HAR on ln turnover with calendar dummies (development MSE 0.493; 20-session mean 0.682).
Validation baseline MSE 0.439. Holdout: 6,080 rows on 38 dates to 2026-10-05.

| candidate | val MSE | t (p) | stocks better | holdout ratio | passes |
|---|---|---|---|---|---|
| T25 | 0.405 | 9.7 (<1e-6) | 72% | 0.72 | yes |
| T30 | 0.401 | 11.3 (<1e-6) | 73% | 0.71 | yes |
| T30C (3.0 + calendar) | **0.398** | 13.3 (<1e-6) | 79% | 0.71 | yes |

Adopted: T30C (lowest validation MSE). About 9% lower squared error than the best baseline on validation, 29% on 2026.

## Q6. Next quarter's results (passes: revenue F25, margin T25)
Rule (per target): one-sided t across companies on the mean validation (2018-2019) loss difference, p < 0.0167, lower
loss for at least 55% of companies, holdout not worse. 980 companies on validation.

| target, baseline | candidate | val MAE (baseline) | t (p) | companies better | passes |
|---|---|---|---|---|---|
| ln revenue, last year x trailing growth | T25 | 0.207 (0.284) | 12.5 (<1e-6) | 78% | yes |
| | T30 | 0.204 | 13.4 (<1e-6) | 79% | yes |
| | **F25** | **0.197** | 14.7 (<1e-6) | 81% | yes |
| net margin, same quarter last year | **T25** | **1.097** (1.296) | 2.79 (0.003) | 75% | yes |
| | T30 | 1.150 | 1.89 (0.030) | 75% | no (p) |
| | F25 | 1.100 | 2.26 (0.012) | 74% | yes |

Margin errors are in margin units (0.01 = one point); the mean is driven by tiny-revenue quarters (amendment 5 notes
margins of thousands of sd); the median tells the typical case (2020-2021: 0.042 for T25 vs 0.058). **Holdout: none.**
`data/bse_results` ends at quarters of 2021-12-31, so no 2026 quarter is in the study's data; under amendment 2 the
holdout condition passes to the live scoreboard, which scores the 2026 quarters from the PM store's results as they
come. Described 2020-2021 (6,963 rows): revenue MAE 0.303 (F25) vs 0.484; margin 4.11 (T25) vs 6.03.

## Described only (no rule)
**Nifty 50** (frozen configs and scales; HAR on ln v and EWMA fitted on the Nifty's development; F25 and C not defined):
QLIKE ratio to HAR on ln v, and fall-chance AUC (EWMA chance in brackets).

| period | rows | T25 | T30 | T30X (India VIX) | AUC T30X (EWMA) |
|---|---|---|---|---|---|
| 2005-2014 | 2,225 | 1.03 | 1.03 | 1.03 | 0.78 (0.77) |
| 2015-2019 | 1,234 | 1.03 | 1.04 | 1.01 | 0.73 (0.68) |
| 2020-2021 | 500 | 1.05 | 1.00 | 0.87 | 0.62 (0.68) |
| 2026 | 186 | 1.29 | 1.30 | 1.02 | 0.73 (0.69) |

The Nifty looks like the ten markets: no gain on the level of volatility; a small, unsteady edge in ranking falls.
2020-2021, ten markets: QLIKE ratio T30X 0.96, T25 1.05, F25 1.40; fall-chance AUC 0.67-0.70 vs EWMA 0.685.

## What goes live (as registered)
- **Q5:** a forecast step writes ln turnover over the next 5 sessions for the stocks on the list and held (T30C,
  3.0 with day of week, month end, expiry week); the trader's tickets check size against it (an ESTIMATE).
- **Q6:** before each result, the revenue range (F25, the model trained on the company's other scrip-parity fold, as
  validated) and the margin range (T25), labelled; after it, the surprise against the range, in the thesis tracker and
  the researcher's flags.
- **Scoreboard:** every forecast stored with as-of date, inputs' last date, model version and the baseline's forecast.
  Q5 over the last 60 matured dates, Q6 over the last two quarters' companies: loss ratio above 1.05 with at least half
  the window matured -> the baseline (HAR + calendar; last year x trailing growth / same quarter last year) and the
  morning report says so; TimesFM resumes at <= 1.00 over a full window.

## Built 2026-10-22 (`quant/tfm2_live.py`, `tools/tfm_live_forecast.py`, store v23, `pflab forecast run|show`)
Nightly: the `forecast` job (21:00) and the night run's step after the jobs. TimesFM runs in `.venv-train` on the CPU
with the study's own wrappers and options (19 s for 12 stocks and 9 companies on 2026-10-22); the GPU stays free.
Consumers: the advisor's tickets (a size line), the researcher (`results_range` before a result, `results_surprise`
after it), the thesis tracker (its matched holdings' lines), the morning report (`forecast show`). Live forms, decided
2026-10-22 (the study's frozen fits have no live equivalent): the turnover baseline is refitted nightly on the stock's
last ~1,500 sessions with matured targets (point in time; a stock too new for it gets the 20-session mean, labelled);
results history joins `data/bse_results` with the store's standalone quarters, and a company needs 8 consecutive
quarters as in the study (on 2026-10-22: 9 qualify; the rest hold 6-7: a results pull of older quarters closes it); the
scoreboard windows count matured forecasts only (Q5: the last 60 forecast dates with matured targets; Q6: the last two
quarters with results in). TimesFM keeps forecasting while its baseline serves, so the scoreboard can resume it. A night
TimesFM cannot run, the baseline serves, labelled, and the step reports the failure.
