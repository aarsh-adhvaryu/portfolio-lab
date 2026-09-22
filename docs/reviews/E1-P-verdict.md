# E1-P — Verdict: REJECT (2026-09-21)

Required by GATE.md for every outcome. Computed by `classify.classify_e1p`,
never typed. No parameter changed. Sealed period untouched. **The stack
remains E1 base.**

- Charter: `docs/strategies/E1-P.md`, LOCKED 2026-09-19 (§3–§7 unchanged
  since; locked-span hash verified).
- Development: `experiments/E1-P/sweeps/development-f22a7a28de0da1ad/`
- Validation: `experiments/E1-P/sweeps/validation-708202782ce1ef66/`
- Verdict: `experiments/E1-P/sweeps/validation-708202782ce1ef66/verdict.json`
- Stack: E1 base, `experiments/E1/sweeps/{development-b7ef1437e30b0fbf,
  validation-508b12240fd70c7c}/`
- Both E1-P sweeps ran on the same code (`source_sha a3945e6f1bb5b64c`).

## Verdict arithmetic (GATE.md)

| period | G1 | G2 | G3 | G4 | CAGR gap | MaxDD gap | rows holding | turnover |
|---|---|---|---|---|---|---|---|---|
| development | ✗ | ✓ | ✗ | ✓ | +0.0062 pp | +0.0066 pp | 1/6 | 1.63 vs 1.70 |
| validation | ✗ | **✗** | ✗ | ✓ | **−1.0403 pp** | **+3.0154 pp** | 0/6 | 1.33 vs 1.31 |

**REJECT because G1 fails in both periods.** G2 (do no harm) is also violated
in validation, on both of its limbs: CAGR fell by more than 0.5 pp and max
drawdown rose by more than 2 pp. N1/N2 are excluded from G3 by construction.

## What validation added to the development review

| | development | | validation | |
|---|---|---|---|---|
| | E1 base | E1-P base | E1 base | E1-P base |
| CAGR pre-tax | 10.68% | 10.45% | 28.51% | 27.41% |
| CAGR after tax | 9.3357% | 9.3419% | 26.12% | 25.08% |
| tax drag | 1.34 pp | 1.10 pp | 2.39 pp | 2.33 pp |
| tax paid | ₹10,27,033 | ₹8,28,785 | ₹5,81,177 | ₹5,57,744 |
| short-term share | 66.2% | 52.6% | 65.2% | 63.0% |

In development the rule saved 0.24 pp of tax and gave back 0.23 pp of return.
In validation the saving nearly vanished (**0.06 pp**, 22 deferrals) while the
cost grew to **1.10 pp** of pre-tax return. The tax saving is not a stable
property of the rule; the return cost is.

**§7 extra 1 now agrees across both periods.** Forward 3-month return,
deferred names against the names the same month-end band-sold:

| row | development gap | validation gap |
|---|---|---|
| base | −10.80 pp (n=26) | **−7.33 pp** (n=21) |
| S1 | +0.52 pp | −3.82 pp |
| S2 | −14.59 pp | −13.22 pp |
| S3 | −4.04 pp | −4.25 pp |
| S4 | −9.78 pp | −11.90 pp |
| S5 | +4.17 pp | −1.82 pp |

The development review read the base gap as "consistent with the pre-tax
gap, not independent evidence" on 26 observations. It now has the same sign
in both periods, and in validation every candidate row is negative, including
the two that were positive in development. A name that slips out of the band
keeps slipping, in a falling decade and a rising one.

## N1 and N2 — reported separately, never adoptable

| | development | | validation | |
|---|---|---|---|---|
| | CAGR / MaxDD | sold names, fwd 6m | CAGR / MaxDD | sold names, fwd 6m |
| base | 9.34% / 55.38% | — | 25.08% / 42.57% | — |
| **N1 stop-loss** | 11.65% / 41.56% | **−12.18%** | **20.34% / 41.65%** | **+9.50%** |
| **N2 profit-take** | 7.85% / 40.58% | +9.05% | 20.01% / 39.12% | **+29.35%** |

**N1 did not survive validation.** It cost 4.74 pp of CAGR against the base
row, left drawdown essentially unchanged (−0.9 pp), and the names it sold
*rose* 9.5% over the following six months — the opposite of development's
−12.2%. 50 of its 85 validation sells (32 and 18) fell in 2018 and 2020, the two sharp
drawdowns that recovered. The development review set the test in advance:
"If validation agrees, it earns a pre-registered charter of its own; if not,
it was 2008." **It was 2008.**

**N2 confirmed in both periods.** Selling at +50% sold names that went on to
rise 9.1% (development) and 29.4% (validation), with 96–98% of realised gains
short-term. Impatience about winners is expensive, and consistently so.

## What this rules out

- The tax layer is not where E1's gap to B3 lives. Deferral's tax saving is
  small and unstable; its return cost is persistent.
- A stop-loss is not a candidate charter on this evidence. The one period in
  which it helped contained 2008 and nothing else like it.

## Decision

E1-P is REJECTED. The stack stays E1 base. Next in the order is E1c.
