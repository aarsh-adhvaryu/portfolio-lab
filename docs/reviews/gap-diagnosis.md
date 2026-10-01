# Gap diagnosis — E1d and E5-A A0 against B5 (DIAGNOSTIC, NOT PROMOTABLE)

> **Pre-registered reading (Aarsh, 2026-10-01), written before any output
> of jobs 19–22 was read.** For each strategy and period, whichever group of
> controls explains most of the gap to B5 decides what follows:
> - **selection** explains most: the information families are the lever;
> - **cash or brake** (trend_off, cap_off; for A0, its equity share): the next
>   experiment is the trend rule;
> - **costs or tax**: no picking closes the gap, and the fallback becomes the
>   plan.
>
> Already seen when this was written: the validation smoke in §3 (base and
> selection rows only, E1d and A0, plus A0's equity-share blend). No cash,
> cost or tax control and no development figure had been computed.

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

_Full runs pending (jobs 19–22)._ **Smoke, validation only, base and
selection rows** (2026-10-01; bases reproduce STATE exactly):

| validation | terminal ₹cr | XIRR | CAGR | MaxDD | equity |
|---|---:|---:|---:|---:|---:|
| E1d base | 0.656 | 31.90% | 26.21% | 42.96% | 78.8% |
| E1d selection | 0.646 | 31.23% | 27.40% | 42.51% | 100% |
| A0 base | 0.387 | 10.14% | 7.51% | 26.69% | 64.5% |
| **A0 selection** | **0.608** | **28.69%** | **26.22%** | 32.00% | 100% |
| B5 | 0.591 | 27.51% | 22.44% | 38.14% | |
| B5 frictionless | 0.641 | 30.91% | 24.65% | 37.79% | |

A0's equity sleeve at the stack's daily equity weight instead of its own:
CAGR 9.59% → 12.50% (+2.91 pp), XIRR +3.69 pp (blend, pre-tax).
**Reading, provisional:** A0's own ranks, held by the band rule
frictionlessly, beat B5 frictionless on CAGR (+1.56 pp); its −14.93 pp gap
is not in which names it ranks highest. The cash, cost and tax rows will
say where it goes. Per run: `experiments\<E1d|E5-A>\diagnostics\gapdiag-<period>-<id>\summary.md`.

## 4. Earlier work

`docs/reviews/E1-gap-attribution.md` (E1, development, `tools/gap_attribution.py`).
