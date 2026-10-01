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

**Status: jobs 19–22 done 2026-10-01; results in §3.**

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

## 3. Results (jobs 19–22, 2026-10-01)

Read off each run's `summary.md`; no figure here is computed by hand. Runs:
`experiments/E1d/diagnostics/gapdiag-development-8e8a6227895839a6`,
`gapdiag-validation-eeec340eaac1f787` (commit `77dca37`);
`experiments/E5-A/diagnostics/gapdiag-e5a_development-95cbba51ed271e74`,
`gapdiag-validation-6153fe0c46b8ef3a` (commit `ff968b0`; between the two
commits only `bse_shareholding.py` changed, which the tool does not read).
The validation base and selection rows reproduce the smoke exactly.

"Explains" = (row − base) ÷ (B5 − base), on CAGR / XIRR / terminal wealth.

### E1d, development (gap −5.68 pp CAGR, −7.34 pp XIRR, ₹−43.8 L)

| row | group | ₹cr | XIRR | CAGR | MaxDD | eq. | explains CAGR / XIRR / terminal |
|---|---|---:|---:|---:|---:|---:|---|
| base | | 0.915 | 8.18% | 8.06% | 54.74% | 71.0% | |
| trend_off | cash | 0.880 | 7.44% | 4.04% | 75.55% | 92.9% | −71% / −10% / −8% |
| cap_off | cash | 1.113 | 11.89% | 12.60% | 54.70% | 80.6% | +80% / +50% / +45% |
| costs_0 | costs | 0.920 | 8.28% | 8.33% | 54.63% | 70.8% | +5% / +1% / +1% |
| tax_0 | tax | 0.984 | 9.57% | 8.96% | 54.67% | 70.6% | +16% / +19% / +16% |
| selection | selection | 1.766 | 20.48% | 13.49% | 77.01% | 100% | **+96% / +167% / +194%** |

B5 1.353 / 15.53% / 13.73% / 70.15%; B5 frictionless 1.495 / 17.38% /
15.08% / 69.97%. Selection vs B5 frictionless: CAGR −1.58 pp, XIRR +3.09 pp.

### E1d, validation (gap **+3.77 pp** CAGR, +4.39 pp XIRR, ₹+6.5 L: no shortfall)

| row | group | ₹cr | XIRR | CAGR | MaxDD | eq. | explains CAGR / XIRR / terminal |
|---|---|---:|---:|---:|---:|---:|---|
| base | | 0.656 | 31.90% | 26.21% | 42.96% | 78.8% | |
| trend_off | cash | 0.801 | 40.49% | 32.72% | 43.34% | 89.7% | −173% / −196% / −223% |
| cap_off | cash | 0.682 | 33.59% | 28.38% | 40.78% | 91.5% | −58% / −38% / −41% |
| costs_0 | costs | 0.666 | 32.52% | 26.82% | 42.45% | 78.9% | −16% / −14% / −15% |
| tax_0 | tax | 0.744 | 37.27% | 29.61% | 42.66% | 78.9% | −90% / −122% / −135% |
| selection | selection | 0.646 | 31.23% | 27.40% | 42.51% | 100% | −32% / +15% / +16% |

B5 0.591 / 27.51% / 22.44% / 38.14%; frictionless 0.641 / 30.91% / 24.65% /
37.79%. Selection vs B5 frictionless: CAGR +2.75 pp, XIRR +0.32 pp. (With a
positive gap, a negative share means the change widens the lead.)

### A0, `e5a_development` 2011–16 (gap −5.26 pp CAGR, −5.72 pp XIRR, ₹−9.8 L)

| row | group | ₹cr | XIRR | CAGR | MaxDD | eq. | explains CAGR / XIRR / terminal |
|---|---|---:|---:|---:|---:|---:|---|
| base | | 0.521 | 12.21% | 12.59% | 14.46% | 63.4% | |
| trend_off | cash | 0.569 | 15.12% | 13.56% | 17.97% | 87.2% | +18% / +51% / +49% |
| cap_off | cash | 0.547 | 13.79% | 13.37% | 15.01% | 73.9% | +15% / +28% / +26% |
| costs_0 | costs | 0.519 | 12.04% | 12.60% | 15.72% | 63.6% | +0% / −3% / −3% |
| tax_0 | tax | 0.560 | 14.58% | 14.43% | 14.42% | 63.3% | +35% / +41% / +40% |
| selection | selection | 0.611 | 17.51% | 16.09% | 21.98% | 100% | **+67% / +93% / +92%** |

B5 0.619 / 17.93% / 17.85% / 22.63%; frictionless 0.665 / 20.32% / 19.49% /
22.48%. Selection vs B5 frictionless: CAGR −3.40 pp, XIRR −2.81 pp. Equity
share: at the stack's weight (64.3%) instead of A0's (63.4%), −0.47 pp CAGR,
−0.84 pp XIRR.

### A0, validation 2017–21 (gap −14.93 pp CAGR, −17.37 pp XIRR, ₹−20.4 L)

| row | group | ₹cr | XIRR | CAGR | MaxDD | eq. | explains CAGR / XIRR / terminal |
|---|---|---:|---:|---:|---:|---:|---|
| base | | 0.387 | 10.14% | 7.51% | 26.69% | 64.5% | |
| trend_off | cash | 0.405 | 11.92% | 9.17% | 28.95% | 78.2% | +11% / +10% / +9% |
| cap_off | cash | 0.439 | 15.18% | 13.71% | 27.88% | 89.6% | +42% / +29% / +25% |
| costs_0 | costs | 0.393 | 10.75% | 8.10% | 26.10% | 64.5% | +4% / +4% / +3% |
| tax_0 | tax | 0.413 | 12.77% | 9.17% | 26.28% | 64.5% | +11% / +15% / +13% |
| selection | selection | 0.608 | 28.69% | 26.22% | 32.00% | 100% | **+125% / +107% / +108%** |

B5 and frictionless as E1d validation. Selection vs B5 frictionless: CAGR
+1.56 pp, XIRR −2.22 pp. Equity share: at the stack's weight (78.8%) instead
of A0's (64.5%), +2.91 pp CAGR, +3.69 pp XIRR.

### Reading against the pre-registered cases

| | largest control (CAGR / XIRR / terminal) | next | case |
|---|---|---|---|
| E1d development | selection, on all three | cap_off (cash) +80% CAGR | **selection** |
| E1d validation | — (the stack leads B5) | | **none**: no shortfall to explain |
| A0 development | selection, on all three | tax +35% CAGR | **selection** |
| A0 validation | selection, on all three | cap_off (cash) +42% CAGR | **selection** |

Costs never explain more than 5% of a shortfall, and tax at most 35% (A0
development), so the **costs-or-tax case is matched nowhere**. Read by the
rule as written, the three shortfalls match **selection**: the information
families are the lever.

Two facts the rule does not weigh, for Aarsh (nothing is changed by them):
1. The selection row is not one change. It also holds 100% equity and pays
   no costs or tax (§2), so it contains part of what cap_off, tax_0 and
   costs_0 measure. Against its own frictionless comparator it still trails
   B5 in **both development runs** (E1d −1.58 pp, A0 −3.40 pp CAGR) and leads
   it only in validation (E1d +2.75 pp; A0 +1.56 pp CAGR, −2.22 pp XIRR).
2. In A0 validation the names are not the problem: A0's own ranks, held by
   the band rule, beat B5 frictionless on CAGR. The shortfall is in turning
   those ranks into holdings, where the largest separable control is the
   six-buy cap (+42%), a cash control.

Diagnostic only; not promotable; no verdict or rule depends on it.

## 4. Earlier work

`docs/reviews/E1-gap-attribution.md` (E1, development, `tools/gap_attribution.py`).

## 5. Change log

- 2026-10-01 (session 13, Aarsh) — **The "selection" row is relabelled
  "picks, frictionless and fully invested" and is not read as selection.**
  It bundles 100% equity and zero costs and tax with the names (§3, fact 1),
  so §3's "selection" case does not say the information families are the
  lever. The §3 figures are unchanged. The cumulative decomposition is the
  gap ladder (`gap-ladder.md`, registered 2026-10-01).
