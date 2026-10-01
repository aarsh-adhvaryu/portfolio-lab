# E5-A A3 (world exposure) — development classification

**2026-10-01.** Development only; the verdict needs validation (E5-A §10,
GATE). Every figure comes from `tools/e5a_family_period.py` (the
`classify.gate_rowwise`, `gate_for_period` and `mandate_for_period` that
`classify_e5a` is built from), saved at
`experiments/E5-A/A3/classify/development.json`, or from the sweep's
`summary.md`. Nothing is typed by hand.

**Change-log entries that apply** (E5-A §14): 2026-09-27 (rewrite);
2026-09-28 (D1, D3–D9, incl. D9: joins only if ADOPT against both A0 and the
stack); 2026-09-29 (D2: stack E1 + E1d; lock decisions; A0 LOCKED);
2026-09-30 (decision 3 confirmed); 2026-10-01 (family decision c: **A3
readings** — transforms, same transform for the 3-month change, FRED and
NSDL usable next calendar day, VIX and TRI same day, adjusted-close month-end
returns; hypotheses; **A3 LOCKED** at `6a29dde`; A0 store accepted at later
code). For the stack: E1 §15, E1d §10.

## Runs

| role | directory | code |
|---|---|---|
| A3 | `experiments/E5-A/A3/sweeps/e5a_development-09cc4b45c5116476` | `lock/E5-A-A3` → `6a29dde`, `D:\pl_runs\E5-A-A3\src`, clean (job 18) |
| A0 (incremental control) | `experiments/E5-A/sweeps/e5a_development-cedd1b289d7bb7aa` | `lock/E5-A` → `530a3d8`; A0-identical at `6a29dde` |
| STACK, E1 + E1d | `experiments/E1d/regression/e5a_development-977f12d2dd395573` | `19ac284` (job 7) |

Job check: 8 rows + B1–B5 persisted; log clean; manifest names
`e5a_development` (§8 guard passes). Fallback 0 of 72 month-ends in every row.

## Evidence window: the whole period

A3 activates at the **Dec 2010 refit**. Its holdings first differ from A0's
at **2011-04-29** and differ at **69 of 72** month-ends, in every row.

## Incremental (A3 against A0, row k vs row k)

| | value | threshold | holds |
|---|---|---|---|
| G1 CAGR gap | **+0.19 pp** (12.78% vs 12.59%) | ≥ +0.5 pp, or DD ≥ 2 pp shallower | **no** |
| G2 MaxDD gap | +0.22 pp (14.68% vs 14.46%) | ≤ +2 pp | yes |
| G3 rows holding | 6 of 8 | ≥ 2/3 | yes |
| G4 turnover | 2.20 vs 1.80 /yr | ≤ 2× | yes |

| row | A3 CAGR / MaxDD | A0 CAGR / MaxDD | CAGR gap | DD gap | holds |
|---|---|---|---:|---:|---|
| base | 12.78% / 14.68% | 12.59% / 14.46% | +0.19 | +0.22 | no |
| S1 h1 | 9.83% / 14.62% | 13.21% / 16.15% | −3.38 | −1.53 | no |
| S2 h3 | 13.52% / 12.87% | 11.90% / 17.02% | +1.62 | −4.15 | yes |
| S3 h12 | 10.13% / 17.11% | 9.09% / 19.12% | +1.04 | −2.01 | yes |
| S4 untuned | 11.12% / 15.04% | 10.13% / 14.84% | +0.98 | +0.20 | yes |
| S5 seed | 12.76% / 14.56% | 10.91% / 16.00% | +1.85 | −1.44 | yes |
| S6 monthly | 13.54% / 14.16% | 10.39% / 17.87% | +3.15 | −3.72 | yes |
| S7 costs ×2 | 12.39% / 14.73% | 11.77% / 16.30% | +0.61 | −1.57 | yes |

The base row is one of the two that fail. G3 compares rows only; G1 is the
base row's (GATE).

## Adoption (A3 against the stack, E1 + E1d)

| | value | threshold | holds |
|---|---|---|---|
| G1 CAGR gap | +2.09 pp (12.78% vs 10.69%) | ≥ +0.5 pp | yes |
| G2 MaxDD gap | −18.26 pp (14.68% vs 32.94%) | ≤ +2 pp | yes |
| G3 rows holding | 6 of 8 (S1, S3 fail) | ≥ 2/3 | yes |
| G4 turnover | 2.20 vs 1.95 /yr | ≤ 2× | yes |

## What development settles

By `gate_verdict`, ADOPT needs G1–G4 in both periods. **A3's incremental
verdict can no longer be ADOPT** (G1 fails here), so under D9 **A3 cannot
join the stack**, whatever validation shows. Validation decides between
**REJECT** (G1 fails there too) and **INCONCLUSIVE**. The adoption
computation holds in development.

## MANDATE (reported; ADVANCE is the adopted stack's)

§3: base holds (MaxDD −9.53 pp vs B2, CAGR +4.26 pp vs B2) but only 5 of 8
rows; **§3 fails in development**. §5: −5.07 pp vs B5 (12.78% vs 17.85%),
**fails**.

## §11 extras

Rank IC (base) 0.107 / 0.138 / 0.171 for h1 / h3 / h12, against A0's 0.102 /
0.130 / 0.126. Holdings overlap: 62.5% with A0, 9.1% with the stack (69
month-ends). A3's base drawdown runs 2016-10-06 → 2016-11-21. The §12 prior
said A3 is the least likely family to help.

## Conclusions

_For Aarsh._ Validation (job 26 onward) is written after this review is
committed.
