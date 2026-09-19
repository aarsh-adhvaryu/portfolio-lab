# The gate — how every experiment after E1 is judged

Every experiment (E2-A onward) is ONE change applied on top of the current
adopted stack (E1 base row plus everything adopted before it). It is run under
the same engine, the same after-tax liquidation-adjusted metrics, the same
verdict arithmetic, and a sweep of its own declared rows. The sealed period
(2022–2025) is never used to choose. Order is sequential: E1, E1b, E1-P, E2-A,
E2-B, E2-C, E2-D, E3, E4, E5. An experiment does not start until the previous
one has a verdict written down — written meaning a note in `docs/reviews/`
naming the verdict and the sweep it came from, for every outcome including
INCONCLUSIVE and REJECT, not only for the ones that advance.

## Comparison

`STACK` = the adopted stack without the change. `CAND` = with the change.
Both are run on the experiment's declared window (some experiments have
shorter data than E1; the stack is re-run on the same window so the
comparison is like for like).

## Adopted if, in BOTH development and validation:

- **G1** CAGR(CAND) − CAGR(STACK) ≥ +0.5 pp/yr **or** MaxDD(CAND) ≤ MaxDD(STACK) − 2 pp
- **G2** the other metric does not get worse by more than the tolerance:
  CAGR may fall at most 0.5 pp/yr; MaxDD may rise at most 2 pp
- **G3** G1 and G2 hold in at least two thirds of the experiment's sweep rows
- **G4** turnover does not more than double (a change that "works" by trading
  ten times as often is a different strategy, not an improvement)

In plain words: the change must clearly help on return or on drawdown, must
not noticeably hurt the other, must survive small perturbations of its own
settings, and must not smuggle in a lot of extra trading.

## Verdicts

- **ADOPT**: G1–G4 hold in both periods. The change joins the stack.
- **REJECT**: G1 fails in both periods, or G2 is violated in both.
- **INCONCLUSIVE**: anything else. Written note. No retry with new numbers.

## What never changes an outcome

Re-running with different thresholds after seeing results. Adding a row to
the sweep after seeing results. Extending or trimming the window after seeing
results. If a data error is found, it is fixed, logged in §15 of the charter,
and the experiment is re-run from scratch with the fix declared.
