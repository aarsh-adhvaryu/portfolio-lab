# E5-A A0 — development classification (DRAFT: numbers only)

**Draft, 2026-09-30.** Numbers and tables only. The conclusions are written
with Aarsh. Development only: no validation run exists and none was started.

**Change-log entries that apply** (E5-A §14): 2026-09-27 (rewrite: A0, the
families, purging, the windows, the fallback); 2026-09-28 (readiness
decisions D1 and D3–D9; A4 parked; A2's precondition); 2026-09-29 (D2: the
stack is E1 + E1d); 2026-09-29 session 6 (lock decisions: per-fit percentile
target, U(M) needs a row at M, a name that never opens again counts as −100%,
re-tuned to **7 / 200 / 0.02**); 2026-09-29 (A0 LOCKED at `lock/E5-A` →
`530a3d8`); 2026-09-30 (decision 3 confirmed). The A1 plan and §6(b) entries
dated 2026-09-30 do not touch A0. For the stack: E1 §15 and E1d §10.

## Runs

| role | directory | code | window |
|---|---|---|---|
| A0 (candidate) | `experiments/E5-A/sweeps/e5a_development-cedd1b289d7bb7aa` | `lock/E5-A` 530a3d8, `D:\pl_runs\E5-A` | 2011-01-01..2016-12-31 |
| STACK, E1 + E1d base | `experiments/E1d/regression/e5a_development-977f12d2dd395573` | 19ac284 (RUNNING job 7) | same |
| placebo (check i) | `experiments/E5-A/diagnostics/placebo-e5a_development-s20260930/sweep` | `lock/E5-A` worktree, `tools/e5a_placebo.py` | same |

§8 guard: the sweep's manifest names `e5a_development`, so it passes
(exploratory years are not read). A0 did not fall back at any decision:
0 of 72 month-ends, 0% of buy value, in every row.

## GATE (development), A0 against the stack

| | value | threshold | holds |
|---|---|---|---|
| G1 CAGR gap | +1.90 pp (12.59% vs 10.69%) | ≥ +0.5 pp, **or** DD ≥ 2 pp shallower | yes |
| G1/G2 MaxDD gap | −18.48 pp (14.46% vs 32.94%) | ≤ +2 pp | yes |
| G2 | CAGR gap ≥ −0.5 pp and DD gap ≤ +2 pp | | yes |
| G3 rows holding | 6 of 8 | ≥ 2/3 | yes |
| G4 turnover | 1.80 vs 1.95 /yr | ≤ 2× stack | yes |

## Sweep rows (each against the stack's base row)

| row | change | CAGR | MaxDD | Sharpe | turnover/yr | CAGR − stack (pp) | MaxDD − stack (pp) | GATE row | MANDATE §3 row |
|---|---|---|---|---|---|---|---|---|---|
| base | | 12.59% | 14.46% | 1.19 | 1.80 | +1.90 | −18.48 | yes | yes |
| S1 | h1 only | 13.21% | 16.15% | 1.20 | 3.21 | +2.53 | −16.80 | yes | yes |
| S2 | h3 only | 11.90% | 17.02% | 1.11 | 2.11 | +1.21 | −15.92 | yes | yes |
| S3 | h12 only | 9.09% | 19.12% | 0.91 | 1.76 | −1.59 | −13.82 | no | no |
| S4 | 15 / 500 / 0.03 | 10.13% | 14.84% | 1.03 | 2.30 | −0.55 | −18.10 | no | no |
| S5 | seed 20270927 | 10.91% | 16.00% | 1.03 | 1.84 | +0.22 | −16.94 | yes | no |
| S6 | monthly refit | 10.39% | 17.87% | 0.98 | 1.92 | −0.30 | −15.07 | yes | no |
| S7 | costs ×2 | 11.77% | 16.30% | 1.11 | 1.81 | +1.09 | −16.64 | yes | yes |

Stack base: 10.69% / 32.94%, Sharpe 0.74, turnover 1.95.

## MANDATE (development)

| | A0 | stack (for reference) | threshold |
|---|---|---|---|
| §3 MaxDD − B2 | −9.76 pp | +8.73 pp | ≤ +5 pp |
| §3 CAGR − B2 | +4.07 pp | +2.17 pp | ≥ +3 pp |
| §3 base row holds | yes | no | |
| §3 rows holding | 4 of 8 | 0 of 1 | ≥ 2/3 |
| **§3** | **no** | no | |
| **§5** CAGR − B5 | **−5.26 pp: no** | −7.17 pp | ≥ +2 pp |

Benchmarks, 2011–2016: B1 7.70% / 22.03%; B2 8.52% / 24.22%; B3 16.28% /
22.49%; B4 4.87% / 37.53%; B5 17.85% / 22.63%.

## Check (i): placebo (reported, not gating)

A0 was refitted at `lock/E5-A` with every label's return shuffled within its
own (month-end, horizon) cross-section (seed 20260930). Kind, interval and
observability stay with the row, so each fit uses the same rows at the same
dates. IC is scored against the **true** labels. Everything else is as
locked. The IC took 10 s and the base row 269 s.

| | A0 | placebo | stack |
|---|---|---|---|
| mean rank IC, h1 (70 months) | +0.1017 | −0.0196 | |
| mean rank IC, h3 (68 months) | +0.1298 | −0.0416 | |
| mean rank IC, h12 (59 months) | +0.1261 | +0.0090 | |
| CAGR | 12.59% | **2.41%** | 10.69% |
| MaxDD | 14.46% | 26.45% | 32.94% |
| turnover /yr | 1.80 | 6.89 | 1.95 |
| mean equity share of NAV | 63.4% | **24.9%** | 64.3% |
| month-ends holding anything | 69 | 56 | 69 |
| mean names held (when holding) | 18.3 | 8.3 | 18.3 |
| GATE vs stack | G1–G4 hold | G1 yes (DD), G2 no, G3 0/1, G4 no | |

The placebo's IC is near zero. Its CAGR is 8.28 pp below the stack's. Its
drawdown is 6.50 pp shallower, but it held about a quarter of NAV in equity.

## Check (ii): rank IC per year and horizon (mean monthly Spearman)

| horizon | year | months | A0 | placebo |
|---|---|---|---|---|
| h1 | 2011 | 12 | +0.1085 | −0.0313 |
| h1 | 2012 | 12 | +0.1220 | −0.0227 |
| h1 | 2013 | 12 | +0.1349 | −0.0168 |
| h1 | 2014 | 12 | +0.0833 | −0.0168 |
| h1 | 2015 | 12 | +0.0810 | −0.0050 |
| h1 | 2016 | 10 | +0.0761 | −0.0262 |
| h3 | 2011 | 12 | +0.1140 | −0.0404 |
| h3 | 2012 | 12 | +0.1931 | −0.0523 |
| h3 | 2013 | 12 | +0.1476 | +0.0047 |
| h3 | 2014 | 12 | +0.1225 | −0.0675 |
| h3 | 2015 | 12 | +0.1022 | −0.0697 |
| h3 | 2016 | 8 | +0.0842 | −0.0159 |
| h12 | 2011 | 12 | +0.0088 | −0.0567 |
| h12 | 2012 | 12 | +0.3224 | +0.0433 |
| h12 | 2013 | 12 | −0.0151 | +0.0195 |
| h12 | 2014 | 12 | +0.1779 | +0.0390 |
| h12 | 2015 | 11 | +0.1375 | −0.0007 |

A later month has fewer observable labels (up to 2016-12-31): h1 has no
label for Nov–Dec 2016, h3 none for Sep–Dec 2016, h12 none for 2016 or
Dec 2015. For reference, §5's tuning IC on 2007–2010 (exploratory) at the
locked point was +0.0052.

## Check (iii): holdings and risk

| | A0 | stack | placebo | U(M), all names |
|---|---|---|---|---|
| holdings overlap with stack (share of A0's month-end names) | 9.05% (69 month-ends) | — | 1.71% (56) | |
| turnover /yr | 1.80 | 1.95 | 6.89 | |
| fallback share, decisions / buy value | 0% / 0% | — | 0% | |
| mean trailing vol_21 of holdings (annualised) | 27.4% | 42.7% | 34.9% | 39.1% |
| mean trailing vol_63 | 27.9% | 44.9% | 36.7% | 40.8% |
| mean trailing vol_252 | 31.0% | 47.6% | 36.2% | 41.8% |
| name-months without vol_63 | 25 of 1,260 | 55 of 1,263 | 15 of 467 | |

The vol figures come from the E5-A feature store's `vol_*` columns at each
month-end M, using rows up to and including M. For each month-end we take
the equal-weighted mean over the names in `decisions.json` `held`, then
average across month-ends.

Other §11 extras for A0's base row: tax drag 1.72 pp; 58% of realised gains
short-term; risk-off 40 of 156 months (the trend filter is shared with the
stack); mean cash share 36.6%; 1 name written off.

## Reproduce

```
cd D:\pl_runs\E5-A; $env:PYTHONPATH='D:\pl_runs\E5-A\src'; $env:PFLAB_EXPERIMENTS_DIR='D:\portfolio_lab\experiments'; D:\portfolio_lab\.venv\Scripts\python.exe -u D:\portfolio_lab\tools\e5a_placebo.py
```
The GATE, MANDATE, overlap and vol figures come from `pflab.eval.classify`
(`gate_for_period`, `mandate_for_period`, `_holdings_overlap`) on the
criteria.json files above. `classify_e5a` itself needs the validation sweeps,
so it was not called.
