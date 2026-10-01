# E5-A families A1, A3, A2, E5-A-ALL — verdicts (both periods)

**2026-10-01.** Computed by `classify.classify_e5a` through
`tools/e5a_verdict.py`; full output `experiments/E5-A/<fam>/classify/verdict.json`.
Nothing is typed by hand. Development figures: the four development reviews.

**Change-log entries that apply** (E5-A §14): as listed in each family's
development review (A1: §6(b) amended, reader decisions, RESULTS_DELAY with
K; A2: §6(c) amended, dating amendment; A3: readings c; ALL: registration
and activation), and the four lock entries (2026-10-01).

**STACK, validation:** `E1d/regression/validation-a6256fbb0ba71a8f` (run at
`530a3d8`), reproduced **IDENTICAL** at `6a29dde` and `31a4b7c` (jobs 30–31,
pflab from each worktree), so it is every family's validation STACK (§8).
A0, validation: `E5-A/sweeps/validation-c6564e07b9148590` (7.51% / 26.69%).

## Verdicts

| family | incremental (vs A0) = the family's evidence | adoption (vs E1 + E1d) | joins stack | mandate |
|---|---|---|---|---|
| **A1** issuer events | **REJECT** (G2 fails both periods) | INCONCLUSIVE | no | not met |
| **A3** world exposure | **INCONCLUSIVE** (G1 fails dev, holds val) | INCONCLUSIVE | no | not met |
| **A2** positioning | **REJECT** (G2 fails both periods) | INCONCLUSIVE | no | not met |
| **E5-A-ALL** | **INCONCLUSIVE** (G1 fails dev, holds val) | INCONCLUSIVE | no | not met |

Adoption is INCONCLUSIVE for all four: G1–G4 hold in development (A2: G3
fails), and in validation every family is 12.9–18.4 pp below the stack's
26.21% (G2 fails).

## Validation (2017–2021), base rows

| family | CAGR / MaxDD | vs A0: CAGR / DD (pp) | rows vs A0 | vs stack: CAGR / DD (pp) | §5 vs B5 |
|---|---|---|---|---|---|
| A1 | 7.80% / 29.54% | +0.29 / +2.85 | 4 of 8 | −18.41 / −13.42 | −14.64 |
| A3 | 11.37% / 19.61% | **+3.86 / −7.08** | **8 of 8** | −14.84 / −23.34 | −11.07 |
| A2 | 13.35% / 30.62% | +5.84 / +3.93 | 3 of 8 | −12.86 / −12.34 | −9.09 |
| ALL | 11.48% / 23.17% | **+3.97 / −3.52** | **8 of 8** | −14.72 / −19.79 | −10.95 |

MANDATE §3: 0 of 8 rows for every family in validation.

## Evidence windows

A1 and A2: 2015–2016 in development, all of validation. A3: both periods
whole. **ALL:** in development A1's and A2's columns act only in 2015–2016,
and 2011–2014 tests A3's columns alone; ALL's validation result (+3.97 pp vs
A0) sits beside A3 alone (+3.86 pp), so this verdict cannot separate ALL from
A3.

## Reading (numbers only; conclusions are Aarsh's)

- A3 and ALL pass every incremental gate in validation (8 of 8 rows) and
  fail only development G1 (+0.19 and +0.05 pp). Under GATE that is
  INCONCLUSIVE, and GATE allows no retry with new numbers.
- No family closes A0's validation gap to the stack: the best (A2, 13.35%)
  is 12.86 pp short.

STATE count: 12 experiments with a computed verdict (A1, A2 REJECT; A3, ALL
INCONCLUSIVE). A5: development only.
