# Limit order book simulator (S41)

Built 2026-10-16 (PLAN A5). A tool, not a hypothesis test, so there is no pass rule; what it shows on synthetic
inputs is recorded here so later calibrated runs can be compared.

## What is built
- `pflab.quant.lob.Book`: matching engine with price-time priority; limit (match what crosses, rest the rest),
  market (immediate or cancel), cancel; prices in integer ticks; every fill recorded (maker, taker, side).
- `pflab.quant.lob.simulate`: zero-intelligence order flow with clustered market orders. Market buys and sells
  arrive from the S40 bivariate Hawkes process; passive limit orders arrive at a constant rate a side and sit a
  geometric number of ticks behind the opposite best; each resting order is cancelled at a constant rate.
  Probe orders track the fill chance of a passive order at a chosen distance from the best.
- `pflab.ingest.kite_depth`: records Kite `quote()` depth (five levels a side, quantities and order counts;
  read-only, inside the S4 allowlist) to `data/kite_depth/`; `impact` walks the recorded ladders;
  `calibrate` turns recordings into a rough `Flow` (order size from quantity per order, depth per level,
  market-order rate from traded volume between snapshots; the Hawkes excitation stays at its default because
  quotes do not show order times).
- `pflab pm impact SYMBOL --amount RS [--side buy|sell]`: the cost over the mid of an order of that size,
  measured on recorded books (median and 90th percentile in basis points, and how often five levels were too
  thin). It refuses to guess when nothing has been recorded.

## Synthetic behaviour (default `Flow`, 6 simulated hours, seed 20261016)
| measure | value |
|---|---|
| spread | median 1 tick, mean 1.6 ticks |
| depth, best five levels a side | about 1,580 shares |
| market orders | 4,294, 99% filled in full |
| mid move 10 s after a market order (ticks, in its direction) | size < 50: 0.15; 50-150: 0.29; 150-400: 0.67; 400+: 0.72 |
| chance a passive order fills within 5 minutes | at the best 97%; 1 tick behind 88%; 3 ticks 65%; 6 ticks 37% |
Impact grows with size but less than in proportion, and fill chance falls with distance from the best: the
shapes the literature reports. The numbers are properties of the synthetic inputs, not of any NSE stock.

## Calibration and use for the investor's orders
No depth has been recorded yet. To record (market hours, after the daily Kite login), from D:\portfolio_lab:
`.venv\Scripts\python tools\kite_depth_record.py --minutes 60 --interval 5` (list names; about 720 snapshots a
name an hour). Then `pflab pm impact SYMBOL --amount <monthly tranche share>` gives the measured cost; for
large-cap names and orders of a few lakh rupees it is expected to be close to half the spread, but only the
recordings can say.
