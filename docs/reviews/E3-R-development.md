# E3-R — development classification

**2026-09-30.** The numbers below are from the draft
(`E3-R-development-draft.md`); the conclusions at the end are Aarsh's.
Development only.

**Change-log entries that apply** (E3-R §11): 2026-09-25 (prediction,
declared before any run); 2026-09-27 (Aarsh's four decisions: undefined
means not firing, the sell-down ranks by FIFO tax cost, the high gear holds
NIFTYBEES, and its disposal and interruption); 2026-09-27 (e) (the high
gear's NIFTYBEES buy is split across sessions); 2026-09-29 (the stack is
E1 + E1d); 2026-09-29 (LOCKED at `lock/E3-R` → `c06c6af`, including the
NIFTYBEES split/ISIN data fix); 2026-09-30 (STACK source: the c6ef67e E1d
sweeps, if they are reproduced exactly at the tag). For the stack: E1 §15 and
E1d §10.

## Runs

| role | directory | code | window |
|---|---|---|---|
| E3-R | `experiments/E3-R/sweeps/development-7abfb3d39c34e018` | `lock/E3-R` c06c6af | 2007-01-01..2016-12-31 |
| STACK, E1 + E1d | `experiments/E1d/sweeps/development-924cec1bb3dd9ff9` (base row) | c6ef67e; reproduced **IDENTICAL** at `lock/E3-R` (RUNNING job 12, `experiments/_identity/e1d_e3r_*.log`) | same |

## GATE (development), E3-R against the stack

| | value | threshold | holds |
|---|---|---|---|
| G1 CAGR gap | −1.24 pp (6.82% vs 8.06%) | ≥ +0.5 pp, **or** DD ≥ 2 pp shallower | no |
| G1/G2 MaxDD gap | −0.58 pp (54.16% vs 54.74%) | ≤ +2 pp | |
| G2 | CAGR gap ≥ −0.5 pp and DD gap ≤ +2 pp | | no (CAGR) |
| G3 rows holding | 1 of 11 | ≥ 2/3 | no |
| G4 turnover | 1.93 vs 1.82 /yr | ≤ 2× stack | yes |

## Sweep rows (each against the stack's base row)

| row | change | CAGR | MaxDD | Sharpe | turnover/yr | CAGR − stack (pp) | MaxDD − stack (pp) | GATE row | MANDATE §3 row |
|---|---|---|---|---|---|---|---|---|---|
| base | | 6.82% | 54.16% | 0.41 | 1.93 | −1.24 | −0.58 | no | no |
| S1 | cautious target 30% | 7.09% | 54.16% | 0.42 | 2.01 | −0.97 | −0.58 | no | no |
| S2 | cautious target 70% | 6.79% | 56.14% | 0.40 | 1.85 | −1.27 | +1.40 | no | no |
| S3 | no selling in cautious | 6.80% | 54.74% | 0.40 | 1.85 | −1.26 | +0.00 | no | no |
| S4 | V only | 7.34% | 64.43% | 0.41 | 1.86 | −0.72 | +9.69 | no | no |
| S5 | B only | 7.19% | 54.16% | 0.41 | 1.96 | −0.87 | −0.58 | no | no |
| S6 | two gears | 7.55% | 54.16% | 0.43 | 1.93 | −0.51 | −0.58 | no | no |
| S7 | high gear into stack names | 9.95% | 54.16% | 0.52 | 1.94 | +1.90 | −0.58 | yes | no |
| S8 | India VIX trigger | 6.97% | 54.16% | 0.40 | 1.99 | −1.09 | −0.58 | no | no |
| S9 | costs ×2 | 6.86% | 54.15% | 0.41 | 1.89 | −1.20 | −0.59 | no | no |
| S10 | sell-down all at once | 7.27% | 54.16% | 0.43 | 1.99 | −0.79 | −0.58 | no | no |

Stack base: 8.06% / 54.74%, Sharpe 0.45, turnover 1.82.

## MANDATE (development)

| | E3-R | stack (for reference) | threshold |
|---|---|---|---|
| §3 MaxDD − B2 | −9.37 pp | −8.79 pp | ≤ +5 pp |
| §3 CAGR − B2 | −1.24 pp | −0.00 pp | ≥ +3 pp |
| §3 base row holds | no | no | |
| §3 rows holding | 0 of 11 | 2 of 12 | ≥ 2/3 |
| **§3** | **no** | no | |
| **§5** CAGR − B5 | **−6.92 pp: no** | −5.68 pp | ≥ +2 pp |

Benchmarks, 2007–2016: B1 7.84% / 59.22%; B2 8.06% / 63.53%; B3 13.22% /
67.53%; B4 3.26% / 73.92%; B5 13.73% / 70.15%.

## §8 extras (base row)

Months in each gear, and mean equity share of NAV (equity value ÷ total,
daily mean; the same formula for both):

| year | cautious | normal | high | E3-R equity share | stack equity share |
|---|---|---|---|---|---|
| 2007 | 0 | 12 | 0 | 64.3% | 64.3% |
| 2008 | 10 | 2 | 0 | 46.9% | 51.5% |
| 2009 | 3 | 8 | 1 | 40.8% | 48.7% |
| 2010 | 0 | 12 | 0 | 97.1% | 97.7% |
| 2011 | 10 | 1 | 1 | 47.9% | 64.0% |
| 2012 | 1 | 10 | 1 | 62.3% | 69.2% |
| 2013 | 3 | 8 | 1 | 82.1% | 90.7% |
| 2014 | 0 | 12 | 0 | 96.1% | 97.4% |
| 2015 | 7 | 5 | 0 | 72.0% | 77.6% |
| 2016 | 4 | 7 | 1 | 38.2% | 47.8% |
| **all** | **38** | **77** | **5** | | |

V was undefined (so not firing) for Jan–Nov 2007 (11 months).

Worst fall within each stress episode (NAV peak to trough inside the
window):

| episode | E3-R | stack |
|---|---|---|
| 2008 | −54.16% | −54.74% |
| 2011 | −19.00% | −20.04% |
| 2013 | −20.50% | −23.33% |
| 2015–16 | −36.73% | −34.63% |
| 2018, 2020 | outside development | |

False alarms, meaning cautious months followed by a positive three-month
market return: **18 of 38** (2008-11, 2008-12, 2009-01 to 2009-03, 2011-01,
2011-02, 2011-11, 2011-12, 2012-01, 2013-07 to 2013-09, 2015-04, 2016-01 to
2016-04).

Realised result of the gear sell-downs: short-term **−₹7.96 lakh** (a net
realised loss), long-term 0.

**Prediction recorded 2026-09-25**, before any run: "E3-R passes only if the
high gear's recovery return exceeds the cautious gear's cost in 2017–2021."
It concerns the validation window and is not tested here.

## Declared (from `classify_e3r`)

- NIFTYBEES has no dividend rows. Where its dividends were paid out
  (2008–2013, per `docs/notes/E3-readiness.md`), the high gear is
  understated.
- The cost model charges NIFTYBEES the stock STT schedule.

GATE and MANDATE were computed with `pflab.eval.classify.gate_for_period` and
`mandate_for_period` on the criteria.json files above. `classify_e3r` itself
needs the validation sweeps, so it was not called.

## Conclusions (Aarsh, 2026-09-30)

E3-R fails G1 and G2 (−1.24 pp for 0.58 pp shallower; 1 of 11 rows). Its
recorded condition failed even in the decade containing 2008: the cautious
gear cost more than the high gear recovered. S7 (high gear buys the stack's
names instead of NIFTYBEES) is the only row that holds, +1.90 pp; reported,
not promotable.
