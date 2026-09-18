# E1c — The momentum fund's own construction, through this engine

Status: DRAFT. Locks at its first development run. Judged by `GATE.md`
against STACK = E1 base, and reported against E1 §13 C1–C4 (candidate base).

## 1. Purpose
Two experiments have shown that E1's rules trail the Nifty 200 Momentum 30
fund by 4–5 pp on the fund's own universe, in both periods. Before anything
else is built, two questions must be answered with the same engine, SIP,
costs and tax that every experiment uses:
- How much of B3's 13.48% (dev) and 20.25% (val) survives real trading and
  real tax? B3's history is backfilled and untaxed until sale.
- Which of E1's departures from the fund's rules (raw 12-1 momentum,
  25 names, monthly band, trend filter) cost money, and which earned it?

E1c calibrates the bar for the entire project. If the replication lands
near B3, the bar is real. If it lands well below, C2 was set against an
inflated number and must be restated honestly (a §15 change to E1 made
with the reasoning written down, before any further experiment).

## 2. Hypothesis
A faithful replication of the fund's construction, run as a monthly SIP
with costs and tax, earns within 2 pp of B3 in both periods. E1's trend
filter and monthly band each subtract return in the years that recover and
add it only in 2008.

## 3. The construction (as close to NSE's published methodology as the panel allows)
- Universe: E1b's (Nifty 200 point-in-time; proxy 2007–2011, published
  from 2012).
- Score at each rebalance date: 6-month and 12-month price return (both
  skipping the most recent month), each divided by that name's daily
  return volatility over the same window, then averaged; standardised
  across the universe (z-score), with the fund's clipping at ±3.
- Selection: top 30 by score.
- Weights: the fund uses score-tilted free-float market cap capped at 5%.
  Free-float shares outstanding are not in the panel (declared gap), so
  weights are score-proportional capped at 5% (S1 tests equal weight).
- Rebalance: semi-annual, effective the last trading day of June and
  December, one-month lag from score date (the fund's review cycle).
- SIP: ₹50,000 monthly into the largest shortfalls versus target weights,
  at most 6 names (E1 §5). Between rebalances, only shortfall buys.
- Sells: at rebalance only, names leaving the top 30. No band, no trend
  filter, no intra-month exits.
- Costs, tax, cash sleeve, delisting, suspension, ADV skip: E1's, unchanged.

## 4. Window and benchmarks
E1's. B1–B4 as in E1b (B4 on the E1b universe).

## 5. Sweep (each isolates one of E1's departures from the fund)
| row | change |
|---|---|
| S1 | equal weights |
| S2 | E1's trend filter added (RISK_OFF: cash waits, nothing sold) |
| S3 | E1's trend filter, sell-to-cash variant |
| S4 | monthly rebalance with a 30-in / 60-out band (E1's band on the fund's score) |
| S5 | 25 names instead of 30 |
| S6 | raw 12-1 momentum instead of volatility-scaled 6+12 (E1's signal on the fund's cadence) |
| S7 | costs ×2 |
| S8 | delisting = total loss |
| S9 | quarterly rebalance |
| S10 | membership latest-possible bound (as E1b S12) |
| S11 | 2012–2016 development only, E1 base re-run on that window |

## 6. Verdict and what it decides
- ADOPT / REJECT / INCONCLUSIVE per GATE.md vs E1 base.
- C1–C4 vs benchmarks, both periods.
- Additionally, and regardless of verdict: report the replication's gap to
  B3 in both periods. If the gap exceeds 2 pp in both, B3's history is
  flattered by at least that amount for a taxed SIP investor, and E1 §13
  C2 is restated to "B3 as replicated through this engine" with a §15
  line. This is the one place an experiment may move E1's bar, and only
  downward toward what can be bought.

## 7. Reported extras
Equity-versus-cash decomposition per row; turnover and short-term share;
rebalance-day slippage; names held; overlap between S6 (E1's signal) and
base selections at each rebalance.

## 8. Not claimed
Not an alpha claim. A calibration of the benchmark and an attribution of
E1's rule choices. No new data.

## 9. Change log
- 2026-09-18 — draft, written after E1b's REJECT.
