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
  This order — average the two ratios, then z-score — stands as written.
  NSE standardises each window first and averages the two z-scores; that
  order is tested as S12, not adopted.
- Selection: top 30 by score.
- Weights: the fund uses score-tilted free-float market cap capped at 5%.
  Free-float shares outstanding are not in the panel (declared gap), so
  weights are score-proportional capped at 5% (S1 tests equal weight).
- Rebalance: semi-annual, **effective at the open of the first session
  after the last trading day of June and December** (E1 §7's convention:
  decide at the month-end close, fill at the next open).
  **One lag in total, not two**: the score's skip of the most recent month
  IS the lag, and there is no separate one-month lag from a score date. Any
  lag is counted in month-end positions, never in calendar days.
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
| S12 | NSE's standardisation order: z-score each window's ratio, then average the two |

## 6. Verdict and what it decides
- ADOPT / REJECT / INCONCLUSIVE per GATE.md vs E1 base.
- C1–C4 vs benchmarks, both periods.
- Additionally, and regardless of verdict: report the replication's gap to
  B3 in both periods, and attribute as much of it as the run can support
  (cadence, selection, costs, tax, cash carry).
- **E1c MAY NOT restate E1 §13's C2.** Free-float shares outstanding exist
  in no dataset available to this project, so the replication cannot
  reproduce the fund's weighting and the reported gap necessarily contains
  an unmeasurable weighting artefact. A bar must not move on an artefact.
  C2 moves only on a replication that uses real free-float weights.
- To bound how much the weighting could be worth at all, report **base
  against S1 (equal weight)** in both periods. That spread is the visible
  range across two weighting schemes and is the honest ceiling on what the
  third, unavailable one might have done.

## 7. Reported extras
Equity-versus-cash decomposition per row; turnover and short-term share;
rebalance-day slippage; names held; overlap between S6 (E1's signal) and
base selections at each rebalance.

## 8. Not claimed
Not an alpha claim. A calibration of the benchmark and an attribution of
E1's rule choices. No new data.

## 9. Change log
- 2026-09-18 — draft, written after E1b's REJECT.
- 2026-09-19 — §6: **E1c may no longer restate E1 §13's C2.** Reason: free
  float exists in no dataset here, so the gap to B3 contains an unmeasurable
  weighting artefact and a bar must not move on one. C2 moves only on a
  replication with real free-float weights. §6 now also requires base vs S1
  as the bound on how much weighting matters. Requested by Aarsh.
- 2026-09-19 — §3: **one lag in total, not two.** The score's skip of the
  most recent month IS the lag; the separate "one-month lag from score date"
  is deleted. Lags are counted in month-end positions, never calendar days.
  Requested by Aarsh.
- 2026-09-19 — §3: rebalance **effective at the open of the first session
  after** the last trading day of June and December, which is E1 §7's
  convention and needs no engine change. Requested by Aarsh.
- 2026-09-19 — §3/§5: averaging order stays as written (average the ratios,
  then z-score); NSE's order added as **S12**. Requested by Aarsh.
- 2026-09-19 — §3 weighting: the halt on a non-positive selected score
  stands. If it fires, the run stops and is reported; it is not resolved in
  code. Confirmed by Aarsh.
- 2026-09-19 — LOCKED. No changes to §3–§7 after this line.

- 2026-09-21 — amended after lock, blind: the development sweep halted
  on the non-positive-score rule before any strategy metric existed.
  (1) §3: weights are proportional to max(score, 0), capped at 5%. A held
  name whose score is not positive keeps its shares, receives no new
  money, and leaves only by its row's exit rule. This is the smallest
  extension of 'proportional' and changes no row whose selected scores
  were all positive (checked read-only: base, S1–S3, S5, S7–S12).
  (2) §5 S6: E1's raw 12-1 momentum replaces the volatility-scaled 6+12
  ingredient and passes through the same z-score and ±3 clip as §3, so
  S6 changes the signal only. (3) S4 keeps §3's score weights through
  the band, as implemented, so S4 changes the cadence only. NSE's
  normalisation stays unadopted.
- 2026-09-21 — code fix, declared before any run (no charter text
  changes): §3 standardises the score "across the universe", but the
  implementation standardised it across every name in the panel with a
  score (1,130 on 2015-12-31) and restricted to the 184-name universe only
  afterwards. Fixed to standardise within the universe at each decision
  date, as §3 says. Found while implementing the amendment above. Under
  the corrected standardisation the halt that prompted that amendment
  would not have fired: REPCOHOME's score on 2015-12-31 is +0.462, not
  −0.024, and every score in S4's 60-name band was positive that day. The
  amendment stands on its own terms (S6's raw momentum was never
  z-scored, and max(score, 0) remains the rule should any selected score
  be non-positive), and the read-only check it cites was re-run on the
  corrected scores before the run. Still blind: no strategy metric from
  any row has been written or read.
- 2026-09-21 — code fix, declared, and the development sweep re-run from
  scratch (no charter text changes): the first development sweep
  (`development-b20d89c761feeff3`) reported B1, B2, B3 and B5 at the 6% cash
  rate, because the benchmark runner copied E1c's stock-picking settings
  onto the one-security index and it never bought; and S11's companion,
  labelled E1 base, ran E1c's rules on E1's universe. Both fixed: a benchmark
  now takes only the experiment's money settings (SIP, cash, delisting), and
  the companion runs the stack's own config. No strategy row depends on
  either, so the re-run must reproduce all thirteen rows exactly; that
  sweep's benchmarks, C1–C4, mandate block and §6 gap to B3 are void.
