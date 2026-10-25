# TimesFM for market risk: results (S50, 2026-10-20)

Run as registered in `timesfm_protocol.md` (commit 814fb23, before any forecast). TimesFM 2.5 and 3.0 (timesfm
3.0.2), zero-shot, 6 configurations each, 5,405 forecast dates each (2005-01-03 to 2026-10-16); 6 min of GPU in all.
Numbers: `PFLAB_DATA_DIR/research/timesfm/results.json`.

## Q1, volatility over the next 10 sessions (QLIKE, lower is better)
| | development 2005-14 | validation 2015-19 | holdout 2026 |
|---|---|---|---|
| EWMA 0.94 (chosen baseline) | 0.309 | 0.299 | 0.421 |
| TimesFM 2.5 (abs, 256) | | 0.459 (DM t -3.54) | 1.72 x baseline |
| TimesFM 3.0 (abs, 256) | | 0.431 (DM t -3.17) | 1.59 x baseline |

**Fails for both versions:** significantly worse than the RiskMetrics EWMA. Zero-shot, TimesFM does not capture
volatility clustering on this series.

## Q2, ranking the sessions before a -2% fall (AUC)
| | validation 2015-19 | holdout 2026 |
|---|---|---|
| Hawkes chance (live) | 0.557 | 0.467 |
| TimesFM 2.5 | 0.629 (vs Hawkes p 0.142) | 0.677 |
| TimesFM 3.0 | 0.608 (vs Hawkes p 0.220) | 0.679 |

**Fails for both versions:** higher than Hawkes but not significantly (p must be < 0.025).

**Decision: nothing live.** `.venv-train` keeps timesfm 3.0.2; no nightly step, no risk fact.

## Exploratory, not registered (computed after the results; a lead, not evidence)
The simple baselines rank falls about as well as TimesFM and better than the live Hawkes chance in every period:
AUC development 0.767 / 0.756 (EWMA / trailing 22) vs Hawkes 0.745; validation 0.612 / 0.637 vs 0.557; 2020-25
0.658 / 0.654 vs 0.635; 2026 holdout 0.630 / 0.660 vs 0.467 (47 fall windows of 186). The Hawkes market state passed
its own drift check (recall of follow-on falls, amendment 2) but ranks 2026 falls no better than chance. A registered
study "market state: Hawkes vs plain volatility" is the next step if the investor wants the market state kept useful.
