# Pairs trading study: pre-registered protocol (S39)

Registered 2026-10-16, committed before any pairs result was computed. Changes after the first run need a
dated amendment at the end; the first run's numbers stay in the report. Research only: no order path
(PLAN section 1). Pre-tax.

## Question
Two stocks in the same business can drift apart and come back. If a pair is cointegrated over a year (their
log prices tied by a stable linear relation), does trading the gap afterwards (long the cheap one, short the
rich one) earn more than cash after Zerodha's costs, on data the pairs were not chosen on?

## Data (on disk)
- NSE equity panel `data/panel/prices.parquet`: total return = adjusted close change times (1 + dividend/close),
  as in the dip-rule study. Log of each stock's total-return index.
- Universe at a formation date: Nifty 500 members (`index_membership/NIFTY500.parquet`, point-in-time) that
  had a stock future that day (`data/fo_bhavcopy`, month-end F&O bhavcopy). A cash-market short cannot be held
  overnight, so the short leg must be a stock future; both legs must be eligible because either can be short.
- Sector: NSE's label as of the date (`sector_map.sector_at`, `allow_later=False`). A name with no label is
  excluded. Pairs are formed only within one label.
- Cash rate and futures carry: the median annualised premium of near-month stock futures over spot at each
  month-end (`fo_bhavcopy.carry`), smoothed as the trailing 12-month median of those monthly values (known at
  the date). Used as the rate cash earns and the premium a futures short earns.

## Timing
- Formation dates: the last session of June and December. Formation window: the 252 sessions ending on it.
- Trading period: the sessions after the formation date up to and including the next formation date. Open
  trades are closed on the last session of the period. Each formation's pairs trade only in its own period.
- Development: trading periods starting 2009-01 to 2014-12 (formations 2008-12 to 2014-06).
- Validation: trading periods starting 2015-01 to 2019-12.
- 2020 onward: reported descriptively, marked "not evidence" (2022-2025 is spent: CLAUDE.md rule 2).

## Pair selection (formation window only)
For each within-sector pair with at least 240 traded sessions of the 252 for both stocks:
1. Engle-Granger (`statsmodels.tsa.stattools.coint`, constant, default lag choice) in both orderings; keep the
   ordering with the lower p-value; require p < 0.05.
2. Johansen (`statsmodels.tsa.vector_ar.vecm.coint_johansen`, det_order 0, one lagged difference): the trace
   statistic rejects "no cointegration" at 95%.
3. OLS hedge ratio beta (log A on log B, with constant) between 1/3 and 3.
4. Half-life of the residual (AR(1) on the formation residual) between 5 and 126 sessions.
Passing pairs are ranked by Engle-Granger p-value (ties: shorter half-life) and taken greedily up to K = 10,
with no stock in more than 2 selected pairs.

## Trading rule (fixed; signals at a close, trades at the next session's close)
- Walk-forward hedge: each session t, OLS of log A on log B over the 252 sessions ending at t gives alpha_t,
  beta_t and the residual standard deviation s_t; z_t = (log A_t - alpha_t - beta_t log B_t) / s_t.
- Entry when flat: z_t >= 2 shorts the spread (short A, long B); z_t <= -2 buys it (long A, short B). The
  beta at the signal sets the legs for the whole trade: notional of B = beta x notional of A, scaled so the
  long notional plus 20% margin on the short notional equals the slot's capital.
- Exit: z crosses 0; or |z| >= 4 (stop: the spread broke); or 63 sessions held; or at a month-end in the
  period the Engle-Granger p-value on the trailing 252 sessions exceeds 0.20 (breakdown); or the short leg has
  no stock future at a month-end (cannot roll); or the period ends. After a stop, a breakdown or a lost future,
  the pair is not traded again in that period.
- Capital: K = 10 equal slots of Rs 5 lakh each (Rs 50 lakh); a slot without an open trade earns the cash rate.

## Costs (Zerodha, verified 2026-10-16 on zerodha.com/charges; today's rates applied to all years)
- Long leg: equity delivery charges (configs/costs_zerodha_pm.toml) on buy and sell, DP charge per sale.
- Short leg: stock futures: brokerage 0.03% or Rs 20 per executed order, whichever is lower; STT 0.05% on the
  sell side; NSE transaction 0.00183%; SEBI Rs 10/crore; stamp 0.002% on the buy side; GST 18% on brokerage +
  SEBI + transaction. Opening, closing and a monthly roll (close and reopen) are each charged.
- Slippage: 0.05% of notional per leg per trade side (an assumption until S41 measures impact).
- Margin: 20% of the short notional, held in cash earning nothing. The short future earns the carry rate on
  its notional. Return measure: excess over the cash rate on the whole capital.

## Outcomes
Daily excess return of the Rs 50 lakh book; monthly sums. Per period: annualised excess return, Newey-West
t-statistic of the mean monthly excess return (3 lags), maximum drawdown of cumulative excess return, number
of completed trades, share of trades by exit reason, gross excess (before costs and slippage).

## Pass rule (fixed now)
The strategy passes only if, in BOTH development and validation:
1. annualised net excess return > 0 and its Newey-West t-statistic >= 2.0;
2. maximum drawdown of cumulative net excess return <= 20%;
3. at least 30 completed trades.
If it fails, the answer is: no pairs strategy. The relative-value view of two stocks (`pflab pm pair`) stays
as a description of how two prices have moved together, with no trading claim.

## Reported beside it, not used to decide
Entry at |z| 1.5 and 2.5; costs and slippage doubled; the share of selected pairs whose Engle-Granger p-value
on their own trading-period data is below 0.05 (does cointegration persist?); the cash rate series.

## Known simplifications
Futures are priced at spot plus the market's median carry, not their own quotes (only month-end futures
quotes are on disk); F&O ban days (open interest above 95% of the market-wide limit) are not known historically
and are ignored; SLB is not modelled; taxes are not deducted (the short futures leg is business income, the
long leg capital gains).

## Amendment 1 (2026-10-16, before the first full run; no performance figure had been computed)
Found in a three-formation timing check of the tool: a leg can stop trading inside a trading period (an ISIN
change after a split, a merger, a delisting), and carrying its last price forward makes a flat series. Rule
added: when either leg has had no price for 5 sessions in a row, the open trade is closed at the next close
(at the last prices) with reason `leg_stopped`, and the pair is not traded again in that period. An
Engle-Granger test on a flat series counts as no evidence (p = 1.0), so it reads as a breakdown.
