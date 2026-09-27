# E1 gap attribution, and the 2026-09-27 regression per experiment

2026-09-27, session 3 of 4. Audit Deliverable 2. **Every diagnostic here is
NOT PROMOTABLE**: no row is a charter row, nothing writes `criteria.json`,
and none of it may become a parameter, filter or rule (CLAUDE.md 3).

Change-log entries that apply (CLAUDE.md 1): E1 §15 **2026-09-21**
measurement correction (buys net of costs; drag by calendar days); E1 §15
**2026-09-27** accounting corrections a–d and their declared choices
(recovery sale, bonus = ex-date, unnamed standard-ratio factor = split,
fraction dated by completing lot); E1c §3–§7 **2026-09-21** amendments;
E2-A §6–§8a **2026-09-25** amendments. D1 (ISIN handovers) and D2 (BE-series
factors) are **not decided**, so every "new" figure below carries D1/D2's
known downward bias (`accounting-correction-2.md`).

## 1. Old vs corrected, per experiment (base rows; read off disk)

After-tax, liquidation-adjusted CAGR / MaxDD. Old = the saved verdict runs;
new = `regress_bases.py` at `19f1ea2`. The stack is E1 base on the same
window. GATE Δ = candidate − stack (CAGR pp, MaxDD pp; negative MaxDD Δ is
shallower).

| exp. | period | base old → new | stack old → new | GATE Δ old → new | G1 / G2 old → new |
|---|---|---|---|---|---|
| E1 | dev | 8.97 / 55.40 → 2.87 / 55.58 | — | C1 +0.90 → −5.19 vs B2 | C1 ✗ → ✗ |
| E1 | val | 27.36 / 39.82 → 22.84 / 47.42 | — | C1 +12.57 → +8.07 | C1 ✓ → ✓ (C3 ✓ → ✗) |
| E1b | dev | 9.74 / 54.96 → 9.03 / 55.00 | 8.97 → 2.87 | +0.77, −0.44 → +6.16, −0.58 | ✓✓ → ✓✓ |
| E1b | val | 15.51 / 43.34 → 15.22 / 43.53 | 27.36 → 22.84 | −11.85, +3.52 → −7.62, −3.90 | ✗✗ → ✓✗ |
| E1-P | dev | 9.14 / 55.78 → 3.01 / 57.23 | 8.97 → 2.87 | +0.17, +0.38 → +0.14, +1.65 | ✗✓ → ✗✓ |
| E1-P | val | 25.85 / 43.52 → 21.43 / 51.25 | 27.36 → 22.84 | −1.52, +3.70 → −1.41, +3.83 | ✗✗ → ✗✗ |
| E1c | dev | 6.73 / 70.19 → 6.19 / 70.38 | 8.97 → 2.87 | −2.23, +14.79 → +3.32, +14.80 | ✗✗ → ✓✗ |
| E1c | val | 20.10 / 36.33 → 18.67 / 35.63 | 27.36 → 22.84 | −7.26, −3.49 → −4.17, −11.79 | ✓✗ → ✓✗ |
| E1d | dev | 11.55 / 49.54 → 7.16 / 49.44 | 8.97 → 2.87 | +2.58, −5.86 → +4.29, −6.14 | ✓✓ → ✓✓ |
| E1d | val | 24.27 / 36.72 → 21.59 / 38.41 | 27.36 → 22.84 | −3.09, −3.10 → −1.25, −9.02 | ✓✗ → ✓✗ |
| E2-A | dev | 11.85 / 33.18 → 10.72 / 34.86 | 14.60 → 9.39 | −2.75, +1.81 → **+1.34, −2.21** | ✗✗ → **✓✓** |
| E2-A | val | 41.84 / 8.41 → 39.31 / 10.19 | 50.04 → 48.34 | −8.20, +1.22 → −9.03, +2.93 | ✗✗ → ✗✗ |

Verdicts on these numbers (REJECT and INCONCLUSIVE are decided by base rows
alone; ADOPT would also need G3, which no regression re-ran):

| exp. | recorded | on a–d numbers | flips? |
|---|---|---|---|
| E1 | INCONCLUSIVE | INCONCLUSIVE (C1 fails dev, holds val) | no |
| E1b | INCONCLUSIVE | INCONCLUSIVE (G2 fails val only) | no |
| E1-P | REJECT | REJECT (G1 fails both) | no |
| E1c | REJECT | REJECT (G2 fails both) | no |
| E1d | INCONCLUSIVE | INCONCLUSIVE (G2 fails val only) | no |
| **E2-A** | **REJECT** | GATE **INCONCLUSIVE** (G1 and G2 now hold in dev) → overall **INCONCLUSIVE** | **yes, provisionally** |

**E2-A's flip comes from the stack, not the candidate.** E1 base on E2-A's
2017–19 window fell 5.21 pp; E2-A fell 1.13 pp. The stack took 4 write-downs
there and E2-A 3, and the a–d numbers carry D1/D2's bias, so the flip may
not survive D1/D2. E2-A's REJECT needs GATE REJECT **and** §8a failing;
§8a is unchanged, so GATE alone decides it.

**Decision for Aarsh (E1b's procedure).** When a base-row regression shows a
flip, both periods are re-run from scratch with the fix declared in the
charter's change log, by Aarsh's decision, and `classify_e2a` recomputes the
verdict (`E1b-verdict-rerun.md`). Recommended: decide D1/D2 first, re-run
`regress_bases.py`, and only then run E2-A's full sweeps if the flip survives.
Until then STATE keeps REJECT, marked provisional.

## 2. E1's development shortfall against the mandate

Required (MANDATE §5 binds; §3 is B2 + 3 = 11.06%): **B5 + 2 = 15.73%**.
E1 base 8.97% before a–d (gap 6.76 pp), **2.87% after** (gap 12.86 pp).
Most of the a–d move is D1: 13 holdings written to zero (₹7.8 L at last
quote), 8 of them ISIN handovers; terminal wealth ₹1.03 cr → ₹0.67 cr.

### Design (`tools/gap_attribution.py`)

One change per row from E1 base, on the same panel, universe and decision
dates; Δ = row − base. Reported per row: CAGR and MaxDD (liquidation NAV,
the sweeps' basis), terminal wealth after liquidation, the SIP's XIRR, mean
equity weight, trades, ADV skips, write-downs.

| bucket | row | the one change |
|---|---|---|
| deployment | `trend_off` | §6 never RISK_OFF |
| | `cap_off` | §5 six-buy cap removed |
| | `topup_top25` | rank eligibility: held names ranked 26–50 get no top-up * |
| | `adv_off` | §7 ADV skips off |
| | `deploy_all_off` | all four (interaction = this − sum of the four) |
| selection | `lottery_1..5` | fixed random score per ISIN, same eligible set * |
| weighting | `mom_weighted` | weights ∝ momentum, NSE-normalised, 5% cap (E1c machinery) |
| costs | `costs_0` | every cost zero |
| tax | `tax_0` | gains, dividend and interest tax zero |
| combined | `frictionless` | deployment rows + zero costs + zero tax |
| benchmarks | B2, B5 | as in sweeps, and frictionless (no cost, tax or drag) |

\* Diagnostic-only engine knobs added this session (`strategy.signal =
"lottery"`, `strategy.topup_max_rank`); unreachable from any charter
config; the E1 golden digests are unchanged. Selection = base − mean of the
five lotteries. The selection-plus-weighting residual against the index =
`frictionless` − B5 frictionless.

**Choices Aarsh may overrule:** (i) "rank eligibility" read as §5's top-up
of band names; the alternative reading (universe eligibility, e.g.
`min_sessions`) is a D1 question, since split ISINs restart the 250-session
clock. (ii) Weighting against a momentum tilt, since B5 is cap × score and
the panel has no shares outstanding for a cap weight.

### Results

**Pending: Aarsh's run** (`docs/RUNNING.md`). Run it once now and once
after D1/D2 with the same command; the second run is the one to read.

**Smoke run (Claude, `0642432`, base + `trend_off`)**:
`experiments/E1/diagnostics/gap-development-4a30f7b5ab154849/`. Base
reproduces the regression exactly (2.87% / 55.58%, 839 trades, 39 skips,
13 write-downs; B2/B5 as in the sweep). Required (§5): CAGR 15.73%, XIRR
17.53%, terminal ₹1.51 cr; base XIRR 2.11%, terminal ₹0.67 cr. First
reading: `trend_off` **lowers** CAGR by 1.24 pp (MaxDD 75.84%) yet **raises**
XIRR by 3.14 pp and terminal wealth by ₹11.7 L. The unit-NAV CAGR and the
money-weighted return disagree on the trend filter's sign, so this note
reports both throughout. 0.9 min per row: the full job is ~15 min.

### Results (Aarsh's run, `5bba5f8`; `experiments/E1/diagnostics/gap-development-ce4403d3ad65303b/`)

Full table in that directory's `summary.md`. The same evening's regression
re-run at `5bba5f8` reproduced every one of the 14 base rows to 0.01 pp:
D1/D2 are not implemented there, and the new knobs are off by default.

Required (§5): XIRR 17.53%, terminal ₹1.51 cr. Base: XIRR 2.11%, ₹0.67 cr.
**Gap: 15.42 pp XIRR, ₹0.84 cr.** One change each, Δ vs base:

| bucket | CAGR pp | XIRR pp | terminal ₹L | reading |
|---|---:|---:|---:|---|
| six-buy cap off | +3.19 | +3.24 | +12.1 | largest single item; the cap strands cash (eq. wt 73% → 82%) |
| trend filter off | −1.24 | +3.14 | +11.7 | CAGR and XIRR disagree on sign; MaxDD 55.6% → 75.8% |
| rank top-up ≤25 | −0.04 | −0.01 | −0.0 | nil |
| ADV skips off | −0.30 | −0.10 | −0.3 | nil to slightly negative |
| all four together | −3.03 | +1.33 | +4.7 | interaction ≈ −4.9 pp XIRR vs the sum (+6.27) |
| selection (base − mean of 5 lotteries) | −0.37 | **−1.28** | −4.7 | momentum picks did **no better than random** (lotteries 0.45–4.80% XIRR) |
| weighting (momentum-tilted) | −0.26 | −0.33 | −1.1 | equal weight is not the problem |
| costs zero | +0.45 | +0.57 | +2.0 | |
| tax zero | +1.50 | +2.05 | +7.4 | |
| frictionless (all above) | −1.22 | +3.66 | +13.9 | still 5.77% XIRR vs B5 frictionless 17.38% |

**Findings.** (1) Removing every friction closes 3.7 of 15.4 pp. The other
**11.6 pp XIRR is selection and universe against the index**, and in this
decade E1's momentum selection earned less than a random pick from the same
universe. (2) **This is contaminated by D1**: base has 13 write-downs, the
lotteries 4–9, frictionless 19. Momentum holds split-heavy winners, so the
ISIN-handover write-downs fall mostly on it. The selection finding cannot be
read until D1 is fixed. (3) Deployment frictions overlap heavily. Taken
alone, the cap and the trend filter are each worth ≈3 pp XIRR; together with
the rest they are worth 1.3.

Decisions for Aarsh: none new. D1 first; then re-run this job (same command).
