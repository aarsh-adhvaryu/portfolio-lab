# E5-A A5 (valuation) — development classification

**2026-10-01.** Development only; the verdict needs validation (E5-A §10,
GATE). Every figure comes from `tools/e5a_family_period.py` (saved at
`experiments/E5-A/A5/classify/development.json`) or from the sweep's
`summary.md` and `extras.json`. Nothing is typed by hand.

**Change-log entries that apply** (E5-A §14): 2026-09-27; 2026-09-28 (D9);
2026-09-29 (D2; lock decisions; A0 LOCKED); 2026-09-30 (decision 3);
2026-10-01 (**A5 hypothesis**; **A5 dating rule and dividend NaN window**; A0
store accepted); session 12 (**§6(f)**: 8 columns, sources, dividend yield
also NaN through 2007-12-31, non-payers 0, D6 as written; **A5 LOCKED** at
`655aae0`).

## Runs

| role | directory | code |
|---|---|---|
| A5 | `experiments/E5-A/A5/sweeps/e5a_development-37cd18619cd4815a` | `lock/E5-A-A5` → `655aae0`, clean (job 32) |
| A0 | `experiments/E5-A/sweeps/e5a_development-cedd1b289d7bb7aa` | A0-identical at `655aae0` |
| STACK | `experiments/E1d/regression/e5a_development-977f12d2dd395573` | `19ac284` |

Job check: queue marker done, log clean, 8 rows + B1–B5, §8 guard passes,
fallback 0 of 72.

## Evidence window: 2013–2016 (base row)

Active from the **Dec 2012 refit**: 48 of 72 decisions in base, S3, S4, S5,
S7; 60 in S1, S2 (from 2012-01); 59 in S6 (from 2012-02). Holdings first
differ from A0's at 2013-02-28 (base; 46 month-ends differ).

## Incremental (A5 against A0, row k vs row k)

| | value | threshold | holds |
|---|---|---|---|
| G1 CAGR gap | **+0.15 pp** (12.74% vs 12.59%) | ≥ +0.5 pp, or DD ≥ 2 pp shallower | **no** |
| G2 MaxDD gap | **+3.56 pp** (18.02% vs 14.46%) | ≤ +2 pp | **no** |
| G3 rows holding | 6 of 8 (base, S7 fail) | ≥ 2/3 | yes |
| G4 turnover | 2.25 vs 1.80 /yr | ≤ 2× | yes |

| row | A5 CAGR / MaxDD | CAGR gap vs A0 | DD gap | holds |
|---|---|---:|---:|---|
| base | 12.74% / 18.02% | +0.15 | +3.56 | no |
| S1 h1 | 13.86% / 16.32% | +0.65 | +0.17 | yes |
| S2 h3 | 13.25% / 16.30% | +1.35 | −0.72 | yes |
| S3 h12 | 13.22% / 17.22% | +4.12 | −1.91 | yes |
| S4 untuned | 14.77% / 16.80% | +4.64 | +1.96 | yes |
| S5 seed | 12.92% / 16.48% | +2.01 | +0.48 | yes |
| S6 monthly | 14.62% / 14.46% | +4.23 | −3.42 | yes |
| S7 costs ×2 | 12.36% / 18.45% | +0.58 | +2.15 | no |

Base drawdown 2015-03-05 → 2016-11-21, inside the active window.

## Adoption (A5 against the stack)

G1 +2.05 pp (12.74% vs 10.69%), G2 −14.92 pp, G3 8 of 8, G4 2.25 vs 1.95:
**all hold**.

## What development settles

**A5's incremental verdict can no longer be ADOPT** (G1 and G2 fail in the
base row), so under D9 **A5 cannot join the stack**. Validation decides
REJECT (G1 or G2 fails again) or INCONCLUSIVE. Six of eight rows beat A0;
the base row is one of the two that do not.

## MANDATE (reported)

§3 holds (MaxDD −6.20 pp vs B2, CAGR +4.23 pp, 8 of 8 rows); §5 −5.11 pp vs
B5, **fails**.

## §11 extras

Rank IC (base) 0.103 / 0.127 / 0.133 against A0's 0.102 / 0.130 / 0.126.
Holdings overlap 67.8% with A0, 10.5% with the stack. Buy value without A5
coverage on active months: 0%.

## Conclusions

_For Aarsh._ Validation command (job 33) is written after this review is
committed.
