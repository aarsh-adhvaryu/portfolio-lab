# Fallback build — spec (no code yet)

**2026-10-01, session 13.** Built only if the gap ladder's registered rule
ends the research phase (`docs/reviews/gap-ladder.md` §2). Not a charter and
not an experiment: it runs no backtest that could be adopted, and nothing in
it may be tuned on backtest results (CLAUDE.md rule 3).

## 1. The plan in one line

A monthly SIP into a **Nifty 500 Momentum 50 index fund** (B5's index), plus
a monthly **portfolio check-up** and a one-page **monthly note**. No stock
picking.

## 2. Part A — the fund SIP

- **Instrument:** one Nifty 500 Momentum 50 index fund or ETF, chosen by
  Aarsh (direct plan; expense ratio and tracking difference stated in the
  note). The backtest proxy is B5 (TRI, 0.30% a year drag).
- **Contribution:** the backtests' SIP (`sip_amount` in `configs/e1d.toml`)
  unless Aarsh sets another, invested whole each month. No trend filter, cap or timing.
- **Record:** each purchase (date, units, NAV, amount, stamp duty) appended
  to a ledger under `PFLAB_DATA_DIR` (gitignored), keyed by the fund's ISIN.
- **Output:** the month's order (amount only); Aarsh places it. No broker
  automation in v1.
- **Reuses:** `pflab.data.indices` (`NIFTY500_MOMENTUM50_TRI`, the
  daily collector) for the index; `pflab.backtest.engine.run_benchmark` for
  the reference path "what the SIP would have done" from any start date;
  `pflab.execution.costs.CostModel` for stamp duty; `configs/*.toml` loading
  via `pflab.backtest.runner.load_config`. New: a fund-NAV loader (AMFI daily
  NAV file) and the ledger writer.

## 3. Part B — the portfolio check-up

Run monthly (and on demand) over the real holdings: the fund ledger plus any
legacy stock positions Aarsh enters.

| output | content |
|---|---|
| holdings | units / shares, price, value, weight |
| FIFO lots | each lot: buy date, qty, cost, holding period, short or long term |
| unrealised tax | STCG and LTCG if sold today, after the ₹1.25 L LTCG exemption already used this FY, with cess; carried losses |
| drawdown | current and max drawdown of the money-weighted NAV, and XIRR since start |
| vs reference | the same cash flows into B5 TRI and B2 (Nifty 500 TRI) |

- **Reuses:** `pflab.tax.india_lots` (`LotBook.buy/sell/lots/positions`,
  `simulate_liquidation`, `settle_fy`, `TaxPolicy` — same rates as every
  run); `pflab.eval.metrics` (`unitized_nav`, `max_drawdown`, `xirr`,
  `cagr`); `pflab.data.panel` and `bhavcopy` for stock prices,
  `corporate_actions` and `dividends` for splits, bonuses and payouts on
  legacy stocks; `pflab.data.instruments` / `symbol_isin` (ISIN is the key).
  New: a holdings input file (CSV of trades, ISIN-keyed) and the report.

## 4. Part C — the monthly note

`docs/notes/monthly/<YYYY-MM>.md`, at most one page, written by code:

1. The order placed this month and the ledger after it.
2. Check-up table (§3), with month-on-month change.
3. Fund vs index: tracking difference over 1, 12 months and since start.
4. Flags only, no advice: drawdown beyond the B5 backtest's worst (70.15%
   development; 38.14% validation), tracking difference above 1 pp a year,
   an unrealised loss harvestable within the FY, a lot turning long term
   within 30 days.

- **Reuses:** `tools/collect_daily.py` for fresh data; `pflab.eval.artifacts`
  manifest pattern (config, data and code hashes) so each note can be
  reproduced; `pflab.execution.paper.month_end_orders` signature as the hook
  for the order line (stub today).

## 5. Not in scope

Stock selection, timing, stop-losses, leverage, Kite order placement
(`execution/kite.py` stays a stub until Aarsh asks), the sealed period.

## 6. Decisions for Aarsh before the build

1. Which fund (or ETF) and its ISIN.
2. Whether any existing stock positions are included, and if so: hold, run
   down by tax-aware sales, or switch now.
3. Source of the holdings input (broker CSV export or hand entry).
