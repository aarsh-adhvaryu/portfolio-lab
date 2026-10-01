# E5-A A2 (positioning) — development classification

**2026-10-01.** Development only; the verdict needs validation (E5-A §10,
GATE). Every figure comes from `tools/e5a_family_period.py` (the
`classify.gate_rowwise`, `gate_for_period` and `mandate_for_period` that
`classify_e5a` is built from), saved at
`experiments/E5-A/A2/classify/development.json`, or from the sweep's
`summary.md` and `manifest.json`. Nothing is typed by hand.

**Change-log entries that apply** (E5-A §14): 2026-09-27 (rewrite);
2026-09-28 (D1, D3–D9, incl. D7: promoter shares only; D9; **A2
precondition**: shares and percent changes plus the unexplained share-count
change, nothing thresholded); 2026-09-29 (D2; lock decisions; A0 LOCKED);
2026-09-30 (decision 3); 2026-10-01 (**§6(c) amended**: pledge invocations
dropped, pledged % of promoter holding and its changes added; hypotheses;
**A2 readings approved** with pledge condition (ii); **A2 dating
amendment**: later of the announcement and quarter end + 21 days, undated by
E2-D1's rule, replacing condition (i); **A2 LOCKED** at `31a4b7c`).

## Runs

| role | directory | code |
|---|---|---|
| A2 | `experiments/E5-A/A2/sweeps/e5a_development-5355d1e6aa97ba7f` | `lock/E5-A-A2` → `31a4b7c`, `D:\pl_runs\E5-A-A2\src`, clean (job 24) |
| A0 (incremental control) | `experiments/E5-A/sweeps/e5a_development-cedd1b289d7bb7aa` | `lock/E5-A` → `530a3d8`; A0-identical at `31a4b7c` |
| STACK, E1 + E1d | `experiments/E1d/regression/e5a_development-977f12d2dd395573` | `19ac284` (job 7) |

Job check: 8 rows + B1–B5 persisted; log clean; §8 guard passes. Fallback
0 of 72 month-ends in every row.

## Evidence window: 2015–2016 (base row)

Active month-ends per row (the run's own `family_active_months`):

| rows | active from | active decisions |
|---|---|---|
| base, S3, S4, S5, S7 | 2015-01-30 (Dec 2014 refit) | 24 of 72 |
| S1 (h1 only), S2 (h3 only) | 2014-01-31 (Dec 2013 refit) | 36 |
| S6 (monthly refit) | 2014-06-30 | 31 |

§6 [D 6] activates a family when **every horizon of the row** has 36
covered cross-sections; a one-horizon row or a monthly refit reaches that
sooner. That is the locked rule as written, not a deviation; it means G3
compares rows with 24 to 36 active months. Holdings first differ from A0's
at 2015-02-28 in the base row (2014-02-28 in S1 and S2, 2014-07-31 in S6).

## Incremental (A2 against A0, row k vs row k)

| | value | threshold | holds |
|---|---|---|---|
| G1 CAGR gap | **−1.40 pp** (11.19% vs 12.59%) | ≥ +0.5 pp, or DD ≥ 2 pp shallower | **no** |
| G2 MaxDD gap | **+6.33 pp** (20.79% vs 14.46%) | ≤ +2 pp | **no** |
| G3 rows holding | **0 of 8** | ≥ 2/3 | **no** |
| G4 turnover | 1.82 vs 1.80 /yr | ≤ 2× | yes |

| row | A2 CAGR / MaxDD | A0 CAGR / MaxDD | CAGR gap | DD gap |
|---|---|---|---:|---:|
| base | 11.19% / 20.79% | 12.59% / 14.46% | −1.40 | +6.33 |
| S1 h1 | 12.28% / 13.14% | 13.21% / 16.15% | −0.94 | −3.01 |
| S2 h3 | 9.91% / 21.48% | 11.90% / 17.02% | −1.99 | +4.46 |
| S3 h12 | 8.14% / 25.55% | 9.09% / 19.12% | −0.96 | +6.43 |
| S4 untuned | 8.90% / 21.06% | 10.13% / 14.84% | −1.23 | +6.22 |
| S5 seed | 9.53% / 21.42% | 10.91% / 16.00% | −1.38 | +5.41 |
| S6 monthly | 9.45% / 22.90% | 10.39% / 17.87% | −0.94 | +5.03 |
| S7 costs ×2 | 10.74% / 21.00% | 11.77% / 16.30% | −1.04 | +4.70 |

Every row returns less than A0's. A2's base drawdown runs 2015-03-05 →
2016-12-26, inside its active window.

## Adoption (A2 against the stack, E1 + E1d)

| | value | threshold | holds |
|---|---|---|---|
| G1 CAGR gap | +0.51 pp (11.19% vs 10.69%) | ≥ +0.5 pp, or DD ≥ 2 pp shallower | yes |
| G2 MaxDD gap | −12.16 pp (20.79% vs 32.94%) | ≤ +2 pp | yes |
| G3 rows holding | **3 of 8** (base, S1, S7) | ≥ 2/3 | **no** |
| G4 turnover | 1.82 vs 1.95 /yr | ≤ 2× | yes |

## What development settles

**A2's incremental verdict can no longer be ADOPT** (G1, G2, G3 fail), and
nor can its adoption verdict (G3). It cannot join the stack. Since G1 and G2
both fail here, `gate_verdict` gives **REJECT** if either fails again in
validation, INCONCLUSIVE otherwise.

## MANDATE (reported)

§3: base fails (MaxDD −3.43 pp vs B2, CAGR **+2.68 pp** vs B2 < 3), 1 of 8
rows; **fails**. §5: −6.66 pp vs B5 (11.19% vs 17.85%), **fails**.

## §11 extras

Rank IC (base) 0.101 / 0.131 / 0.130 against A0's 0.102 / 0.130 / 0.126.
Holdings overlap: 90.4% with A0, 8.8% with the stack (69 month-ends).

## Conclusions

_For Aarsh._ Validation is written after this review is committed.
