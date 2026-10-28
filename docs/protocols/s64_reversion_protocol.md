# S64 reversion studies: protocol (2026-10-26, committed before any run)

Two claims go through the learner's machinery (`docs/research/learner_protocol.md`, amendments 1-4) as origin `study`,
and each counts as one test in the family "all" (the bar rises with N). Nothing below changes after the first run; a
change is an amendment with its date and reason. This is the S64 Phase 2e of `docs/S64_BUILD_PLAN.md`.

## Claim 1: `sector_reversion` (a new template, long-only, usable for buy timing)
"A stock that is cheap relative to a sector index it is cointegrated with earns more than that sector over the next month."

- **Universe, each month end:** point-in-time Nifty 500 members with at least 36 months of total-return history.
- **Sector index:** the sector TRI of the stock's industry as of that month end (latest sector-map capture on or before
  it). Only industries in the table below have one; the others are left out. The table is fixed here:
  - taxonomy A (2006-2013 captures): COMPUTERS - SOFTWARE -> IT; BANKS -> BANK; AUTOMOBILES - 2 AND 3 WHEELERS,
    AUTOMOBILES - 4 WHEELERS, AUTO ANCILLARIES -> AUTO; PHARMACEUTICALS -> PHARMA; PERSONAL CARE, FOOD AND FOOD
    PROCESSING, CIGARETTES, BREW/DISTILLERIES -> FMCG; REFINERIES, OIL EXPLORATION/PRODUCTION, GAS -> OIL_GAS;
    STEEL AND STEEL PRODUCTS, ALUMINIUM, METALS, MINING -> METAL; FINANCE, FINANCE - HOUSING, FINANCIAL INSTITUTION ->
    FIN_SERVICES; MEDIA & ENTERTAINMENT -> MEDIA; CONSUMER DURABLES -> CONSUMER_DURABLES; CHEMICALS - INORGANIC,
    CHEMICALS - ORGANIC, CHEMICALS - SPECIALITY -> CHEMICALS.
  - taxonomy B (2014-2023): AUTOMOBILE -> AUTO; IT -> IT; PHARMA -> PHARMA; CONSUMER GOODS -> FMCG; FINANCIAL SERVICES ->
    FIN_SERVICES; OIL & GAS -> OIL_GAS; METALS -> METAL; MEDIA & ENTERTAINMENT -> MEDIA; CHEMICALS -> CHEMICALS.
  - taxonomy C (2024 on): the table in `quant/comove.py` `SECTOR_INDEX`.
- **Formation:** Engle-Granger (`statsmodels.tsa.stattools.coint`, constant, AIC lags) of the stock's log total-return
  index against the log sector TRI over the prior 36 months (daily). Keep names with p < 0.05. The spread is
  ln stock - beta ln sector, beta by OLS over the same 36 months; z = today's spread / its standard deviation over
  those 36 months (the spread's mean over them removed).
- **Signal:** each month, among the kept names, the bottom quintile of z (cheapest relative to the sector). Fewer than 10
  kept names that month: the month is skipped.
- **Measured:** the next month's total return of the equal-weighted quintile minus the same names' sector TRI return,
  minus `stocks.round_trip_pct(DEFAULT_ORDER)` on the share of names that changed since last month.
- **Periods:** development 2010-2017, validation 2018-2021. 2022-2025 is spent and not evidence (CLAUDE.md 2).
- **Pass (`templates.decide`, the one rule):** mean in the claimed direction in both periods; development Newey-West
  t >= `counter.t_needed(N)` (N the tests in the family including this one; never under 2.0); validation t >= 1.65;
  mean above the cost; at least 36 months each.
- **Parameters** (closed list): `direction` in {low, high}; the claim is "low" (bottom quintile of z).

## Claim 2: `short_term_reversal`
"The previous month's losers outperform the previous month's winners over the next month." It already has a template:
`cross_section` with signal `reversal_1m` (total return over the last month), direction `low`, months 1. It is
registered as that existing test; no template change, no amendment of the closed list.

## Use of the result
A pass is wired in with `claims.wire`: Claim 1 becomes a "cheap vs sector" line in `plan/buyzone` and the ready plans, at
its tested size (the mean and its n); Claim 2 a live finding. A fail gets no live feature, and `quant/comove.py` stays a
description. The result goes into `docs/research/s64_reversion_results.md`.

## Run
`.venv\Scripts\python -m pflab.cli learner test --claim <id>` per claim (more than 5 minutes on the full panel: the
investor's). Registered by `pflab learner register-s64` before the run.
