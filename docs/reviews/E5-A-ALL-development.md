# E5-A-ALL (A0 + A1 + A2 + A3) — development classification

**2026-10-01.** Development only; the verdict needs validation (E5-A §10,
GATE). Every figure comes from `tools/e5a_family_period.py` (the
`classify.gate_rowwise`, `gate_for_period` and `mandate_for_period` that
`classify_e5a` is built from), saved at
`experiments/E5-A/ALL/classify/development.json`, or from the sweep's
`summary.md` and `manifest.json`. Nothing is typed by hand.

> **Evidence.** In this window A1's and A2's columns have only **2015–2016**
> to act in (both switch on at the Dec 2014 refit in the base row). From
> 2011 to 2014 ALL tests **A3's columns alone**. Any development verdict on
> ALL is therefore mostly a verdict on A3 plus two years of A1 and A2.

**Change-log entries that apply** (E5-A §14): every entry that applies to
A1, A2 and A3 (see their reviews), and 2026-10-01: **hypotheses** (ALL
registered as one fixed candidate, amending §3's "never combined");
**ALL activation** (each member from its own activation refit, NaN before;
A0's model until the first member is active); **A2 dating amendment**;
**ALL LOCKED** at `31a4b7c`.

## Runs

| role | directory | code |
|---|---|---|
| ALL | `experiments/E5-A/ALL/sweeps/e5a_development-de36b811a670c8c1` | `lock/E5-A-ALL` → `31a4b7c`, `D:\pl_runs\E5-A-ALL\src`, clean (job 25) |
| A0 (incremental control) | `experiments/E5-A/sweeps/e5a_development-cedd1b289d7bb7aa` | `lock/E5-A` → `530a3d8`; A0-identical at `31a4b7c` |
| STACK, E1 + E1d | `experiments/E1d/regression/e5a_development-977f12d2dd395573` | `19ac284` (job 7) |

Job check: 8 rows + B1–B5 persisted; log clean; §8 guard passes. Fallback
0 of 72 month-ends in every row. Every model file carries all 108 columns
(inactive members NaN by design), and the run does not record which members
were active at each refit. The member windows above therefore follow from the
locked rule and from the standalone runs (A1 and A2 base rows active from
2015-01-30; A3 throughout). ALL is active, through A3, at all 72 month-ends
in every row, and its holdings differ from A0's from 2011-04-29 (69 of 72).

## Incremental (ALL against A0, row k vs row k)

| | value | threshold | holds |
|---|---|---|---|
| G1 CAGR gap | **+0.05 pp** (12.64% vs 12.59%) | ≥ +0.5 pp, or DD ≥ 2 pp shallower | **no** |
| G2 MaxDD gap | +1.18 pp (15.64% vs 14.46%) | ≤ +2 pp | yes |
| G3 rows holding | 6 of 8 | ≥ 2/3 | yes |
| G4 turnover | 2.47 vs 1.80 /yr | ≤ 2× | yes |

| row | ALL CAGR / MaxDD | A0 CAGR / MaxDD | CAGR gap | DD gap | holds |
|---|---|---|---:|---:|---|
| base | 12.64% / 15.64% | 12.59% / 14.46% | +0.05 | +1.18 | no |
| S1 h1 | 9.46% / 14.97% | 13.21% / 16.15% | −3.76 | −1.18 | no |
| S2 h3 | 12.56% / 14.33% | 11.90% / 17.02% | +0.66 | −2.69 | yes |
| S3 h12 | 10.53% / 16.06% | 9.09% / 19.12% | +1.44 | −3.06 | yes |
| S4 untuned | 11.34% / 15.66% | 10.13% / 14.84% | +1.21 | +0.82 | yes |
| S5 seed | 12.19% / 14.19% | 10.91% / 16.00% | +1.28 | −1.82 | yes |
| S6 monthly | 13.65% / 14.50% | 10.39% / 17.87% | +3.26 | −3.37 | yes |
| S7 costs ×2 | 12.34% / 15.69% | 11.77% / 16.30% | +0.57 | −0.61 | yes |

ALL's base drawdown runs 2016-10-26 → 2016-11-21.

## Adoption (ALL against the stack, E1 + E1d)

| | value | threshold | holds |
|---|---|---|---|
| G1 CAGR gap | +1.95 pp (12.64% vs 10.69%) | ≥ +0.5 pp | yes |
| G2 MaxDD gap | −17.30 pp (15.64% vs 32.94%) | ≤ +2 pp | yes |
| G3 rows holding | 7 of 8 (S1 fails) | ≥ 2/3 | yes |
| G4 turnover | 2.47 vs 1.95 /yr | ≤ 2× | yes |

## What development settles

**ALL's incremental verdict can no longer be ADOPT** (G1 fails), so under
D9 **ALL cannot join the stack**. Validation decides REJECT (G1 fails there
too) or INCONCLUSIVE. ALL's base row (12.64% / 15.64%) sits below A3 alone
(12.78% / 14.68%) on the same window: adding A1 and A2 for 2015–2016 did not
raise the base row.

## MANDATE (reported)

§3: base holds (MaxDD −8.57 pp vs B2, CAGR +4.12 pp vs B2) but 5 of 8 rows;
**fails**. §5: −5.21 pp vs B5 (12.64% vs 17.85%), **fails**.

## §11 extras

Rank IC (base) 0.106 / 0.138 / 0.173 against A0's 0.102 / 0.130 / 0.126
(A3's: 0.107 / 0.138 / 0.171). Holdings overlap: 61.8% with A0, 8.8% with
the stack (69 month-ends).

## Conclusions

_For Aarsh._ Validation is written after this review is committed.
