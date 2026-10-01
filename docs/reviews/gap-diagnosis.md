# Gap diagnosis — E1d and E5-A A0 against B5 (DIAGNOSTIC, NOT PROMOTABLE)

Audit Deliverable 2, 2026-10-01. Nothing here is a charter row or a verdict
input: `classify` cannot read it and no rule may be changed because of it
(CLAUDE.md rule 3). It says where each shortfall to B5 comes from.

**Status: tool built and tested; runs are Aarsh's (RUNNING.md jobs 19–22).
Results are filled in here after they land.**

## 1. The gaps (from STATE, after tax, liquidation-adjusted CAGR)

| | development | validation |
|---|---|---|
| E1d (the stack) − B5 | −5.67 pp (2007–16) | +3.77 pp |
| A0 − B5 | −5.26 pp (2011–16) | −14.93 pp |

A0's validation equity share is 64.5% against the stack's 78.8%.

## 2. Method (`tools/gap_diagnosis.py`)

One change per row from each base row, same panel, universe and decision
dates. Each reports terminal wealth, XIRR, CAGR and max drawdown, and how
much of the gap to B5 it closes ((row − base) ÷ (B5 − base)).

| control | changes | group |
|---|---|---|
| selection | the names the base run's own ranks choose by the band rule (top 25, exit past 50), equal weight, rebalanced at month-end close, fully invested, no costs, tax or cash; same SIP | selection |
| trend_off | no trend filter | cash |
| cap_off | no six-buy cap | cash |
| costs_0 | costs zero | costs |
| tax_0 | tax zero (pre-tax) | tax |
| equity_share (A0) | A0's equity sleeve blended with cash at the stack's daily equity weight vs at its own | equity share |

B5 runs as in every sweep (costs; taxed only on liquidation, so a fund's
deferral is already in the comparison; 0.30% drag) and frictionless. The
selection row is read against B5 frictionless, the others against B5.

Readings (diagnostic, not charter): selection uses close-to-close returns
from the decision close (the engine fills at the next open); a name with no
price is flat; the equity-share blend is pre-tax with costs left where the
base row paid them. The controls do not add up to the gap: each is measured
alone, and they interact (the E1 attribution found the same).

## 3. Results

_Pending jobs 19–22._ Per run: `experiments\<E1d|E5-A>\diagnostics\gapdiag-<period>-<id>\summary.md`.

## 4. Earlier work

`docs/reviews/E1-gap-attribution.md` (E1, development, `tools/gap_attribution.py`).
