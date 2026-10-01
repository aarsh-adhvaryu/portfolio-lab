# E5-A A1 (issuer events) — development classification

**2026-10-01.** Development only; the verdict needs validation (E5-A §10,
GATE). Every figure comes from `tools/e5a_family_period.py` (the
`classify.gate_rowwise`, `gate_for_period` and `mandate_for_period` that
`classify_e5a` is built from), saved at
`experiments/E5-A/A1/classify/development.json`, or from the sweep's
`summary.md`. Nothing is typed by hand.

**Change-log entries that apply** (E5-A §14): 2026-09-27 (rewrite);
2026-09-28 (D1, D3–D9, incl. D9: joins only if ADOPT against both A0 and the
stack); 2026-09-29 (D2: stack E1 + E1d; lock decisions; A0 LOCKED);
2026-09-30 (decision 3 confirmed; A1 reader plan; **§6(b) amended**: per flag
× subtype, NOT_EVENT excluded; reader decisions: L reads DEFAULT,
FORENSIC_AUDIT, REGULATORY_ACTION, K's events UNCLEAR); 2026-10-01 (family
decisions a–b: RESULTS_DELAY with K, A1 readings; hypotheses; **A1 LOCKED**
at `6a29dde`; A0 store accepted at later code). For the stack: E1 §15, E1d §10.

## Runs

| role | directory | code |
|---|---|---|
| A1 | `experiments/E5-A/A1/sweeps/e5a_development-56d82ba9a55f41e0` | `lock/E5-A-A1` → `6a29dde`, `D:\pl_runs\E5-A-A1\src`, clean (job 17) |
| A0 (incremental control) | `experiments/E5-A/sweeps/e5a_development-cedd1b289d7bb7aa` | `lock/E5-A` → `530a3d8`; A0-identical at `6a29dde` |
| STACK, E1 + E1d | `experiments/E1d/regression/e5a_development-977f12d2dd395573` | `19ac284` (job 7) |

Job check: 8 rows + B1–B5 persisted; log clean; manifest names
`e5a_development` (§8 guard passes). Fallback 0 of 72 month-ends in every row.

## Evidence window: February 2015 – December 2016

A1 activates at the **Dec 2014 refit** (§6 [D 6]: 36 covered cross-sections
from the 2010 feed start). Its month-end holdings equal A0's at every
month-end through **2015-01-30** and first differ at **2015-02-28**, in every
row; they differ at **23 of 72** month-ends. 2011–2014 is A0 exactly, so the
whole-period differences below come from about 23 months.

## Incremental (A1 against A0, row k vs row k)

| | value | threshold | holds |
|---|---|---|---|
| G1 CAGR gap | +1.15 pp (13.74% vs 12.59%) | ≥ +0.5 pp, or DD ≥ 2 pp shallower | yes |
| G2 MaxDD gap | **+3.06 pp** (17.52% vs 14.46%) | ≤ +2 pp | **no** |
| G3 rows holding | **5 of 8** | ≥ 2/3 | **no** |
| G4 turnover | 2.12 vs 1.80 /yr | ≤ 2× | yes |

| row | A1 CAGR / MaxDD | A0 CAGR / MaxDD | CAGR gap | DD gap | holds |
|---|---|---|---:|---:|---|
| base | 13.74% / 17.52% | 12.59% / 14.46% | +1.15 | +3.06 | no |
| S1 h1 | 11.94% / 21.27% | 13.21% / 16.15% | −1.28 | +5.12 | no |
| S2 h3 | 13.35% / 14.23% | 11.90% / 17.02% | +1.45 | −2.79 | yes |
| S3 h12 | 10.23% / 19.21% | 9.09% / 19.12% | +1.13 | +0.09 | yes |
| S4 untuned | 11.72% / 17.87% | 10.13% / 14.84% | +1.59 | +3.03 | no |
| S5 seed | 12.31% / 16.00% | 10.91% / 16.00% | +1.40 | 0.00 | yes |
| S6 monthly | 11.78% / 15.14% | 10.39% / 17.87% | +1.39 | −2.73 | yes |
| S7 costs ×2 | 13.22% / 17.61% | 11.77% / 16.30% | +1.44 | +1.31 | yes |

A1's base drawdown runs 2016-10-19 → 2016-12-26, inside the active window
(A0's: 2015-03-05 → 2016-12-26).

## Adoption (A1 against the stack, E1 + E1d)

| | value | threshold | holds |
|---|---|---|---|
| G1 CAGR gap | +3.05 pp (13.74% vs 10.69%) | ≥ +0.5 pp | yes |
| G2 MaxDD gap | −15.42 pp (17.52% vs 32.94%) | ≤ +2 pp | yes |
| G3 rows holding | 8 of 8 | ≥ 2/3 | yes |
| G4 turnover | 2.12 vs 1.95 /yr | ≤ 2× | yes |

## What development settles

By `gate_verdict`, ADOPT needs G1–G4 in both periods. **A1's incremental
verdict can no longer be ADOPT** (G2 and G3 fail here), so under D9 **A1
cannot join the stack**, whatever validation shows. Validation decides
between **REJECT** (G2 fails there too) and **INCONCLUSIVE**. The adoption
computation holds in development; it is A0's advantage over the stack
carried through, since A1 is A0 until 2015.

## MANDATE (reported; ADVANCE is the adopted stack's)

§3: base holds (MaxDD −6.70 pp vs B2, CAGR +5.22 pp vs B2), 7 of 8 rows;
**§3 holds in development**. §5: −4.11 pp vs B5 (13.74% vs 17.85%), **fails**.

## §11 extras

Rank IC (whole period, base) 0.097 / 0.120 / 0.116 for h1 / h3 / h12, against
A0's 0.102 / 0.130 / 0.126. Holdings overlap: 86.8% with A0, 10.5% with the
stack (69 month-ends). ADV skips 9 of 255 buys (3.5%).

## Conclusions

_For Aarsh._ Validation (job 26 onward) is written after this review is
committed.
