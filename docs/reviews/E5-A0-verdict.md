# E5-A A0 — verdict: INCONCLUSIVE (GATE vs E1 + E1d)

**2026-09-30.** Computed by `classify_e5a` (both periods), never typed; saved
as `experiments/E5-A/verdict_A0.json`. Development detail:
`docs/reviews/E5-A0-development.md`.

**Change-log entries that apply** (E5-A §14): 2026-09-27 (rewrite);
2026-09-28 (readiness decisions D1, D3–D9); 2026-09-29 (D2: stack E1 + E1d);
2026-09-29 session 6 (lock decisions, re-tuned 7 / 200 / 0.02); 2026-09-29
(A0 LOCKED, `lock/E5-A` → 530a3d8, span re-verified 2026-09-30);
2026-09-30 (decision 3 confirmed); 2026-09-30 session 8 (placebo PASS). For
the stack: E1 §15, E1d §10.

## Runs

| | directory | code |
|---|---|---|
| A0 development | `E5-A/sweeps/e5a_development-cedd1b289d7bb7aa` | `lock/E5-A`, `D:\pl_runs\E5-A` |
| A0 validation | `E5-A/sweeps/validation-c6564e07b9148590` | same |
| STACK development | `E1d/regression/e5a_development-977f12d2dd395573` | 19ac284 |
| STACK validation | `E1d/regression/validation-a6256fbb0ba71a8f` | at `lock/E5-A` (RUNNING job 10) |

## GATE

| | development 2011–16 | validation 2017–21 |
|---|---|---|
| A0 base | 12.59% / 14.46% | **7.51% / 26.69%** |
| stack base | 10.69% / 32.94% | 26.21% / 42.96% |
| CAGR gap | +1.90 pp | **−18.70 pp** |
| MaxDD gap | −18.48 pp | −16.27 pp |
| G1 | yes | yes (on drawdown) |
| G2 | yes | **no** (CAGR) |
| G3 | yes, 6 / 8 | **no, 0 / 8** |
| G4 | yes (1.80 vs 1.95) | yes (2.67 vs 1.78) |

Verdict rule: ADOPT needs G1–G4 in both periods; REJECT needs G1 to fail in
both or G2 to fail in both. Neither holds → **INCONCLUSIVE**.

Validation rows, each against the stack's base row (26.21% / 42.96%):

| row | CAGR | MaxDD | Sharpe | turnover |
|---|---|---|---|---|
| base | 7.51% | 26.69% | 0.65 | 2.67 |
| S1 h1 only | 11.31% | 25.70% | 0.95 | 3.47 |
| S2 h3 only | 10.90% | 28.37% | 0.92 | 3.06 |
| S3 h12 only | 6.86% | 25.16% | 0.62 | 2.06 |
| S4 15/500/0.03 | 8.23% | 26.06% | 0.74 | 3.08 |
| S5 seed | 7.52% | 29.25% | 0.64 | 2.65 |
| S6 monthly refit | 8.13% | 26.19% | 0.71 | 2.55 |
| S7 costs ×2 | 6.95% | 27.30% | 0.61 | 2.68 |

## MANDATE: not met

| | development | validation |
|---|---|---|
| §3 MaxDD − B2 / CAGR − B2 | −9.76 / +4.07 pp | −11.25 / −7.26 pp |
| §3 rows holding | 4 / 8 | 0 / 8 |
| §5 CAGR − B5 | −5.26 pp | −14.93 pp |

Validation benchmarks: B1 14.88% / 38.06%; B2 14.77% / 37.94%; B3 20.16% /
33.92%; B4 8.67% / 57.18%; B5 22.44% / 38.14%.

## §11 extras, validation (base row)

| | A0 | stack |
|---|---|---|
| holdings overlap with stack | 12.5% (59 month-ends) | — |
| fallback share, decisions / buy value | 0% / 0% | — |
| mean trailing vol_63 of holdings | 28.6% | 45.2% (U(M) 41.3%) |
| mean names held | 18.2 | 21.7 |
| mean equity share of NAV | 64.5% | 78.8% |
| NAV return 2018 / 2019 / 2020 / 2021 | −8.7 / −1.7 / +13.2 / +26.9% | −15.9 / +0.2 / +47.0 / +77.0% |

Rank IC (mean monthly Spearman), base:

| | 2017 | 2018 | 2019 | 2020 | 2021 |
|---|---|---|---|---|---|
| h1 | +0.083 | +0.161 | +0.125 | +0.048 | +0.080 |
| h3 | +0.125 | +0.217 | +0.259 | −0.031 | +0.137 |
| h12 | +0.191 | +0.373 | +0.268 | −0.130 | — |

## Against the prediction recorded before validation (2026-09-30)

The prediction: A0 passes validation only if its selection adds return, not
just safety. In validation A0's CAGR was 18.70 pp below the stack's and its
drawdown 16.27 pp shallower; G2 failed. Its holdings' volatility was 28.6%
against 45.2%, as in development (27.9% vs 44.9%). Unlike development, its
equity share was lower than the stack's (64.5% vs 78.8%).

## Decisions needed (Aarsh)

1. Record the verdict: STATE (7 experiments with a verdict; INCONCLUSIVE 4),
   ROADMAP.
2. E5-A §3 and §10: A1–A3 are judged incrementally against A0, and adoption
   against the stack. With A0 INCONCLUSIVE, does the A1 build go ahead as
   planned?
