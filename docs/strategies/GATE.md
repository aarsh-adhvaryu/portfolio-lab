# The gate — how every experiment after E1 is judged

Every experiment (E2-A onward) is ONE change applied on top of the current
adopted stack (E1 base row plus everything adopted before it). It is run under
the same engine, the same after-tax liquidation-adjusted metrics, the same
verdict arithmetic, and a sweep of its own declared rows. The sealed period
(2022–2025) is never used to choose. Forward order is sequential: E1d,
E3-R, E2-A (when its data is complete), E2-B, E1-S, E2-C, E2-D, E2-E, E3,
E6-V, E5-A (E1, E1b, E1-P and E1c have verdicts). An experiment does not start until the previous one has a
verdict written down — written meaning a note in `docs/reviews/`
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

## Adoption and ADVANCE are decided separately (from 2026-09-21)

- **Adoption** — whether a change joins the stack — is decided here, by
  G1–G4, exactly as before.
- **ADVANCE** — the one sealed reveal, the live paper year, real money — is
  decided from **2026-09-21** by `docs/MANDATE.md` §3 and §5, not by E1
  §13's C1–C4:
  - **§3**: in development and validation, worst fall no more than 5 pp
    deeper than B2 (Nifty 500 TRI) and after-tax return at least 3 pp/yr
    above it, in the base row and in at least two thirds of the sweep rows;
  - **§5**: after-tax return at least 2 pp/yr above **B5** (Nifty 500
    Momentum 50 TRI) in both periods.

ADVANCE is a property of the **adopted** stack: a candidate that meets the
mandate but is not ADOPTED here advances nothing. From E1c onward `classify`
reports a separate mandate block beside the GATE block (and beside C1–C4 for
a candidate base).

**Recorded verdicts are unchanged.** E1 INCONCLUSIVE, E1b REJECT and E1-P
REJECT stand under their own charters and the arithmetic they were judged by.

## Order, and how it has changed

The order line above is the current one. Two corrections are recorded here so
that a stale copy is recognisable as stale:

- **2026-09-18** — E1-P was moved **ahead of** E1b (reason in
  `docs/ROADMAP.md`: E1-P needs no new data, and blocking a ready experiment
  on an unready dataset buys nothing). This file kept the pre-swap line
  "E1, E1b, E1-P" until 2026-09-19; that line was stale, not law.
- **2026-09-19** — **E1c slotted immediately after E1-P**, on Aarsh's
  instruction. E1b ran out of order on 2026-09-18 and was **REJECTED**, so it
  is complete and no longer appears in the forward order.
- **2026-09-21** — forward order reset on Aarsh's instruction after the
  mandate took effect: **E1c, E2-A, E3-R, E2-B, E1-S, E2-C, E2-D, E2-E, E3,
  E6-V, E5-A**. E1-P was REJECTED. **E4 is off the list, and so is the
  stop-loss**: E1-P's N1 helped only in the period containing 2008 and cost
  4.7 pp a year in validation.
- **2026-09-22** — **E1d and E3-R ahead of E2-A**, on Aarsh's instruction,
  while E2-A's BSE backfill runs. E1c was REJECTED on 2026-09-21.

## E1's bar is now fixed

E1 §13's C1–C4 are still reported for every candidate base, as its charter
asks, but from 2026-09-21 they no longer decide ADVANCE (the mandate does;
see above). **No experiment may move them.** E1c §6 was the single sanctioned
route by which one could have — restating C2 to "B3 as replicated through
this engine" — and it was closed on 2026-09-19: free-float shares
outstanding exist in no dataset available here, so E1c's gap to B3 contains
an unmeasurable weighting artefact, and a bar must not move on an artefact.
C2 moves only on a replication built with real free-float weights, which
would be a new experiment with a new charter.

## A short-window row must say which periods it applies to

**Convention, 2026-09-25.** A sweep row that shortens the window (E1b's S13,
E1c's S11, E1d's S11) exists to ask its question on a sub-period. In a
period that already starts at or after the row's own start, the row has no
question to ask.

Such a row is **reported as not applicable and excluded from the G3 and C4
row counts. It is never run as a duplicate of the row it was derived from.**

The case that produced this: E1d's S11 declared `period.start = 2012-01-01`
to ask S10's question on the years Nifty 200 membership is published.
Validation begins in 2017, so the start was already past, the period was
returned unchanged, and S11 ran settings identical to S10 — reporting the
same 19.67% / 32.47% on the same 458 trades. Validation's G3 count of 2 of
12 therefore counted one row twice. Both copies failed, so **E1d's verdict
does not move and is not revisited**; the convention exists so the next one
cannot be counted wrong in a direction that matters.

A charter's row table declares this by carrying the row's start; the code
derives applicability from it rather than from a second list, so a row
cannot be declared in the charter and forgotten in the counting.

## What never changes an outcome

Re-running with different thresholds after seeing results. Adding a row to
the sweep after seeing results. Extending or trimming the window after seeing
results. If a data error is found, it is fixed, logged in §15 of the charter,
and the experiment is re-run from scratch with the fix declared.
