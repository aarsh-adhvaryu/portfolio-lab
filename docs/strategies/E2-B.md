# E2-B — Shock-exposure graph

Status: DRAFT. Locks at its first development run. Judged by `GATE.md`.

## 1. Purpose
Test whether limiting the portfolio's exposure to any single macro shock
reduces drawdown without giving up return. This is the knowledge-graph idea
in its first measurable form: companies and sectors as nodes, estimated
exposures as edges, used as a constraint and as the explanation layer.

## 2. Hypothesis
E1's momentum rank concentrates in whatever has been working, which is often
one shock exposure (rate-sensitive financials, crude-sensitive names,
rupee-sensitive exporters). Capping each exposure to a multiple of the index's
own exposure lowers drawdown in 2008, 2013, 2020 and 2022.

## 3. Graph
- Nodes: companies (ISIN), sectors (NSE industry classification, current
  mapping applied to history — declared simplification), shock factors.
- Factors (five, full-window): Brent crude (USD), USDINR, US 10-year yield,
  net FII equity flows (monthly, ₹), India VIX (from 2009; absent before —
  declared).
- Edges company→factor: beta from the trailing 36 monthly returns regressed
  on the factor's monthly change, re-estimated at each month-end using only
  data ≤ M. Minimum 24 observations, else the edge is missing and the name is
  treated as index-like for that factor.
- Edges sector→factor: median of member betas. Company→sector: membership.

## 4. Rule (the one change)
At each month-end, for every factor f:
`|beta_portfolio(f)| ≤ 1.5 × |beta_Nifty500(f)|`, with betas value-weighted
by holding size after the planned buys. A buy that would breach any factor's
cap is skipped and the next entry candidate by rank is tried. Held names are
never sold for a cap breach (no forced turnover).

## 5. Data
FRED for Brent, USDINR, US 10-year. NSE/NSDL for FII flows. NSE for India
VIX. NSE industry classification file for sectors. All stored under
`data/macro/` with fetch dates in the manifest.

## 6. Window
E1's full window (development 2007–2016, validation 2017–2021), with the
VIX edge absent before 2009.

## 7. Sweep
| row | change |
|---|---|
| S1 | cap 1.25× |
| S2 | cap 2.0× |
| S3 | 24-month betas |
| S4 | sector cap 30% of equity value as the constraint instead (graph, not betas) |
| S5 | VIX factor removed (full window without gaps) |

## 8. Reported extras
Portfolio beta to each factor over time vs the index; which buys were skipped
and why; per-episode drawdown (2008, 2011, 2013, 2016, 2018, 2020, 2022) for
STACK vs CAND.

## 9. Not claimed
No forecast of any factor. The graph is a map of exposure, not a model of
causes.

## 10. Change log
- 2026-09-16 — draft.
- 2026-09-27 (Aarsh, session 1 of 4) — **beta cap and sector source settled
  before build.** Cap: |portfolio beta − Nifty 500 beta| ≤ **1.0
  cross-sectional SD** of the eligible names' betas at M (S1 / S2: 0.5 /
  1.5 SD). *Reason:* a cap proportional to the index's own beta collapses
  to zero width when that beta crosses zero (Brent 16 times, US 10-year 11
  times; `docs/notes/E2B-readiness.md`). Sectors: a hand-verified
  crosswalk of NSE's three schemes; gaps filled from BSE's scrip master,
  which is current rather than point-in-time (declared).
