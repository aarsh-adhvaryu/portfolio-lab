# E1b — Verdict on re-run: INCONCLUSIVE (2026-09-22)

Required by GATE.md for every outcome. Computed by `classify.classify_e1b`,
never typed. **Supersedes the REJECT recorded 2026-09-18**, which was
measured before E1 §15's 2026-09-21 correction. No parameter changed;
§3–§7 unchanged since the 2026-09-18 lock. Sealed period untouched. **The
stack remains E1 base.**

- Why re-run: the measurement correction (buys sized net of costs instead of
  skipped; expense drag compounded by calendar days) changed E1 base and
  E1b's base rows by different amounts. A base-row regression showed the
  verdict would flip; per GATE.md's rule for a measurement error, both
  periods were re-run from scratch with the fix declared (E1b §10,
  2026-09-22), by Aarsh's decision.
- Development: `experiments/E1b/sweeps/development-6395365e3c1d9e9c/`
- Validation: `experiments/E1b/sweeps/validation-dfba386145b76734/`
- Verdict: `experiments/E1b/sweeps/validation-dfba386145b76734/verdict.json`
- Stack: E1 base re-run under the same correction,
  `experiments/E1/regression/{development-64343858a094c09e,
  validation-303190300ed98ced}/`
- Both sweeps ran on commit `983ad51`, clean. Their base rows reproduce the
  regression check exactly (9.74% / 54.96%, 15.51% / 43.34%).

## GATE (adoption) — INCONCLUSIVE

| period | G1 | G2 | G3 | G4 | CAGR gap | MaxDD gap | rows holding | turnover |
|---|---|---|---|---|---|---|---|---|
| development | **✓** | ✓ | ✗ | ✓ | **+0.77 pp** | −0.44 pp | 8/14 | 1.13 vs 1.71 |
| validation | ✗ | **✗** | ✗ | ✓ | **−11.85 pp** | +3.52 pp | 0/14 | 1.04 vs 1.31 |

INCONCLUSIVE: REJECT needs G1 to fail in both periods or G2 to be violated
in both, and each now fails only in validation. It cannot be ADOPTED:
validation fails G1 and G2 by a wide margin, and development's G3 holds in
8 of 14 rows, short of two thirds.

**What changed from 2026-09-18.** Development's gap to E1 base went from
+0.13 pp to +0.77 pp. The correction lowered E1 base (9.34% → 8.97%) and
raised E1b (9.47% → 9.74%): E1 base's month-end buys more often used the
last of the cash and were being skipped. Validation's verdict-deciding gap
barely moved (−10.73 → −11.85 pp).

## E1 §13 C1–C4 (reported; E1b is a candidate base) — REJECT, unchanged

| period | C1 vs B2 | C2 vs B3 | C3 drawdown vs B2 | C4 rows |
|---|---|---|---|---|
| development | ✗ +1.67 pp | ✗ −3.49 pp | ✓ −8.52 pp | 0/14 |
| validation | ✗ +0.72 pp | ✗ −4.67 pp | ✗ +5.40 pp | 0/14 |

## MANDATE §3 and §5 — not met

| period | §3 return vs B2 (≥ +3) | §3 drawdown vs B2 (≤ +5) | §3 rows | §5 vs B5 (≥ +2) |
|---|---|---|---|---|
| development | ✗ +1.67 pp | ✓ −8.52 pp | 3/14 | ✗ −4.00 pp |
| validation | ✗ +0.72 pp | ✗ +5.40 pp | 1/14 | ✗ −6.97 pp |

## What this changes

The label, not the conclusion. The 2026-09-18 reading stands: confining E1's
rules to the Nifty 200 costs about 12 pp a year in validation, because E1's
2017–21 return came from outside it. Under corrected measurement the Nifty
200 version does edge E1 base in development, by 0.77 pp, which is why the
verdict is INCONCLUSIVE rather than REJECT. The stack stays E1 base, and
MANDATE §4 has since chosen the whole Nifty 500 deliberately.
