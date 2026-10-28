# Split or limit-below-market vs buying at once (S45, PLAN A7): pre-registered protocol

Registered 2026-10-17, before any run. Code: `quant/execution_study.py`, `tools/split_study.py`.

## Question
The investor buys a fixed rupee amount of a stock each month (FD tranches). Is a cheaper average price reliably got by
splitting the buy over days, or by a limit order below the market, than by buying it all at once?

## Plans (each buys the same rupees of the same stock, starting on day t = the first session of a month)
- **A (benchmark):** all at the close of day t.
- **B5:** one fifth at the close of each of sessions t .. t+4.
- **L(x):** a limit at x below the close of t-1, good for 5 sessions (t .. t+4): filled on the first session whose low
  reaches it, at the limit (or at that session's open if the open is already below it); if never filled, all at the
  close of t+4. x in {0.5%, 1%, 2%}.
Prices are split/bonus adjusted; charges are the same for all plans (delivery, percentage levies) and ignored.

## Measure
Saving of each plan against A, in basis points of A's price: (A - plan price) / A x 10,000 (positive = cheaper).
Per month, the mean over the stocks; the test uses the monthly means (t-statistic of their mean).

## Universe and periods
Point-in-time Nifty 500 members on day t. Development 2010-01 .. 2017-12 (choose the plan); validation 2018-01 ..
2021-12 (judge it once). 2022-2025 are spent (reported only, no say).

## Rule
The plan with the highest mean saving on development (among B5 and the three L(x)) is adopted for the trader
planner if, on validation, its mean saving is at least 10 bps AND its t-statistic is at least 2. Otherwise the planner
says "buy at once" (a limit at the last price). Whatever the result, the planner never places an order.
