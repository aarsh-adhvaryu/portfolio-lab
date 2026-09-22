# E1c — Verdict: REJECT (2026-09-21)

Required by GATE.md for every outcome. Computed by `classify.classify_e1c`,
never typed. No parameter changed. Sealed period untouched. **The stack
remains E1 base.**

- Charter: `docs/strategies/E1c.md`, LOCKED 2026-09-19; amended after lock,
  blind, 2026-09-21 (§9), with two code fixes declared the same day (§9).
- Development: `experiments/E1c/sweeps/development-339c6a2b8b1df978/`
- Validation: `experiments/E1c/sweeps/validation-d1bff14844336e54/`
- Verdict: `experiments/E1c/sweeps/validation-d1bff14844336e54/verdict.json`
- Stack: E1 base, `experiments/E1/sweeps/{development-b7ef1437e30b0fbf,
  validation-508b12240fd70c7c}/`
- Both sweeps ran on the same frozen code, `source_sha 455f61c0803632f2`.
  The development re-run reproduced all 13 rows of the voided first sweep
  (`development-b20d89c761feeff3`) exactly, as it had to: the fixes touched
  only benchmarks and the S11 companion.

## GATE (adoption) — REJECT

| period | G1 | G2 | G3 | G4 | CAGR gap | MaxDD gap | rows holding | turnover |
|---|---|---|---|---|---|---|---|---|
| development | ✗ | **✗** | ✗ | ✓ | **−2.54 pp** | **+14.81 pp** | 2/13 | 1.13 vs 1.70 |
| validation | ✓ | **✗** | ✗ | ✓ | **−6.02 pp** | −3.23 pp | 0/13 | 1.05 vs 1.31 |

**REJECT because G2 (do no harm) is violated in both periods.** In
validation G1 passes on the drawdown limb (3.23 pp shallower), but return
fell 6.02 pp, far beyond G2's 0.5 pp tolerance.

## E1 §13 C1–C4 (reported, E1c is a candidate base) — INCONCLUSIVE

| period | C1 vs B2 | C2 vs B3 | C3 drawdown vs B2 | C4 rows |
|---|---|---|---|---|
| development | ✗ −1.27 pp | ✗ −6.68 pp | ✗ +6.70 pp | 0/13 |
| validation | ✓ +5.31 pp | ✗ −0.15 pp | ✓ −1.60 pp | 0/13 |

## MANDATE §3 and §5 (decides ADVANCE from 2026-09-21) — not met

| period | §3 return vs B2 (≥ +3) | §3 drawdown vs B2 (≤ +5) | §3 rows | §5 vs B5 (≥ +2) |
|---|---|---|---|---|
| development | ✗ −1.27 pp | ✗ +6.70 pp | 1/13 | ✗ −8.57 pp |
| validation | ✓ +5.31 pp | ✓ −1.60 pp | 11/13 | ✗ −2.72 pp |

Informational only: E1c is not adopted, so it advances nothing either way.
§5 fails in both periods with B5 as published, and also under the 0.30%
drag B3 carries (−7.07 pp, −2.47 pp) — so the open question of B5's drag
does not bear on this verdict.

## §6 — what E1c was for

**How much of B3 survives real trading and real tax?** Base row against B3:

| | E1c base | B3 | gap |
|---|---|---|---|
| development | 6.80% / 70.19% | 13.48% / 67.48% | **−6.68 pp** |
| validation | 20.10% / 36.33% | 20.25% / 33.95% | **−0.15 pp** |

In validation the fund's construction, run as a taxed monthly SIP through
this engine, lands within 0.15 pp of the index. In development it keeps
about half. Per §6 as amended, **C2 is not restated**: the gap contains a
weighting artefact this project cannot measure.

**The bound on that artefact — base against S1 (equal weight):**

| | base − S1, CAGR | base − S1, drawdown |
|---|---|---|
| development | −1.03 pp | +4.78 pp deeper |
| validation | +2.66 pp | +1.62 pp deeper |

The score tilt cost 1 pp in one period and earned 2.7 pp in the other. The
choice of weighting scheme is worth low single digits of percentage points a
year, and not with a stable sign. That is the order of magnitude of the
unmeasured free-float effect, not its value.

**Which of E1's departures from the fund cost money** (each row changes one
thing; CAGR / MaxDD, after tax):

| row | change | development | validation |
|---|---|---|---|
| base | the fund's construction | 6.80% / 70.19% | 20.10% / 36.33% |
| S2 | E1's trend filter (cash waits) | 8.77% / 51.17% | 18.83% / 30.35% |
| S3 | trend filter, sell-to-cash | 10.65% / 42.47% | 19.40% / **15.64%** |
| S4 | E1's monthly 30-in/60-out band | 9.30% / 70.71% | 21.29% / 36.63% |
| S5 | 25 names | 6.29% / 72.11% | 20.79% / 38.13% |
| S6 | E1's 12-1 signal | **1.82%** / 72.48% | **14.87%** / 41.98% |
| S9 | quarterly rebalance | 8.89% / 68.55% | 19.51% / 37.33% |
| S12 | NSE's standardisation order | 7.11% / 68.46% | 20.06% / 35.13% |

Two results hold in both periods:

- **E1's raw 12-1 signal is much worse than the volatility-scaled 6+12 score
  on the fund's cadence** — about 5 pp a year in each period — even though
  the two select 76–77% of the same names at each rebalance. E1's signal
  choice costs money.
- **E1's monthly band beats the fund's semi-annual cadence** (S4 +2.50 pp,
  +1.19 pp). E1's cadence choice earns money.

The trend filter pays in the decade containing 2008 (S2 +1.97 pp, S3
+3.86 pp) and costs a little in the one without (−1.27 pp, −0.70 pp).
Sell-to-cash (S3) cut validation's drawdown from 36% to 16%.

## Reported extras (§7)

- Decomposition, base row: equity 6.95 pp + cash 0.54 pp (development, 89%
  mean equity weight); equity 23.20 pp + cash 1.24 pp (validation, 84%).
- Turnover 1.13 / 1.05; short-term share of realised gains 48.0% / 76.7%;
  tax drag 1.03 / 2.45 pp.
- Rebalance-day slippage, fill against the month-end reference close: buys
  +0.14% / +0.23% mean, sells +0.22% / +0.32% mean (a positive sell
  slippage is a better fill than the reference).
- Names held at month-ends: mean 23.6 / 22.6 against a target of 30.
- Overlap of S6's selections with the base row's: 76% / 77% mean, range
  53–93%.

## A measurement flaw found while writing this, not fixed

When a benchmark's monthly buy is sized to use all its cash and the costs
then no longer fit, the engine skips the whole buy (it cannot overdraw the
cash sleeve). Whether that happens comes down to rupee rounding. The NAV is
time-weighted, so a skip in the first month — when that SIP is the whole
book — counts for the whole period. It happened to B5 in 2007-02: B5 sat
out February 2007's fall by accident. Sized so the costs fit, the stored
development figures move by:

| | development | validation |
|---|---|---|
| B5 | 15.37% → 14.14% (**+1.23 pp** inflated) | unchanged |
| B3 | 13.48% → 13.32% (+0.15 pp) | unchanged |
| B1, B2 | ≤ 0.01 pp | unchanged |

**No verdict depends on it**, E1c's or any earlier one. GATE reads rows
only; B2 (C1, C3, MANDATE §3) is unaffected; and only DEVELOPMENT B3 and B5
move, where C2 and MANDATE §5 fail by far more than the correction (E1c:
−6.68 → −6.52 pp against B3, −8.57 → −7.34 pp against B5). Validation, where
E1c's C2 gap is a narrow −0.15 pp, is untouched. It sits on E1's locked §5 buy-sizing path, so it is Aarsh's to
decide, not fixed here. A second, smaller point on the same path: the
benchmark expense drag compounds per session over 365, so B3's "0.30%" is
applied as roughly 0.21% a year.

## Decision

E1c is REJECTED. The stack stays E1 base. The code freeze for E1c ends with
this note. Next in the order is E2-A, the permanent-loss guard (MANDATE §4).
