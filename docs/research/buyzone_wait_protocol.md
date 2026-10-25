# Waiting for the buy zone vs buying at once (PLAN A9; the S54c decision): pre-registered protocol

Registered 2026-10-23, before any run. Code: `quant/zone_study.py`, `tools/zone_study.py`.

## Question
The watch list shows each stock's buy zone (v1, `plan/buyzone.py`: the 20th to 40th percentile of the last 250
sessions' closes) and says WAIT when the price is above it. The ready plans buy at once and show the zone beside each
ticket; the zone may change the plans only if waiting for it gets a better price, net of the time the money waits.

## Plans (the same rupees of the same stock, from day t = the first session of a month, only when the close of
day t-1 is above the zone's top; a stock at or under its top is bought at once by both plans and is not counted)
- **A (benchmark):** all at the close of day t.
- **W(H):** a limit at the zone's top (set from the 250 closes up to t-1), good for H sessions (t .. t+H-1): filled on
  the first session whose low reaches it, at the limit (or at that session's open if the open is already below it);
  if never filled, all at the close of day t+H-1. While it waits the money earns the debt rate the simulations use
  (`risk.montecarlo.DEBT_RATE`, a year, simple, per calendar day). H in {21, 63, 126} (one, three, six months).

Prices are split/bonus adjusted (`adj_factor`); charges are the same for both plans and ignored.

## Measure
Saving of W(H) against A in basis points of A's price, the waiting interest counted as a lower price:
effective W price = fill price / (1 + DEBT_RATE x days waited / 365); saving = (A - effective W) / A x 10,000
(positive = waiting was cheaper). Per month, the mean over the stocks counted; the test uses the monthly means with a
Newey-West t-statistic (lags = H / 21, rounded up), because windows of later months overlap.
Also reported, with no say: the share of stock-months above the zone, the fill rate, and the saving among filled and
unfilled orders separately.

## Universe and periods
Point-in-time Nifty 500 members on day t with at least 250 sessions of closes before t. Development 2010-01 ..
2017-12 (choose H); validation 2018-01 .. 2021-12 (judge it once). 2022-2025 are spent (reported only, no say).
The last month started is the one whose H sessions end inside its period.

## Rule
The H with the highest mean saving on development is adopted if, on validation, its mean saving is at least 50 bps
AND its Newey-West t-statistic is at least 2. Then the ready plans show, for a stock above its zone, "a limit at the
zone's top for H sessions, else buy at the close" as the ticket (still text, the investor places every order); otherwise
nothing changes: the plans buy at once and the zone stays a description beside them. No other H, threshold or zone
definition is tried after the run.
