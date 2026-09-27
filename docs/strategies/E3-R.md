# E3-R — Risk gears (dynamic equity exposure)

Status: DRAFT. Locks at its first development run. Judged by `GATE.md`
against the current stack, and reported against MANDATE §3 and §5.
Slotted after E2-A.

## 1. Purpose
MANDATE §3 asks for risk that moves with the market: cautious when danger
is high, normal most of the time, high occasionally. E1's single on/off
trend filter is the crude version of this. It paid in 2008, cost in 2020,
and never sold, so it could not reduce exposure it already held. E3-R
tests a three-gear exposure rule built on measurable, point-in-time
signals.

## 2. Hypothesis
Stress shows up in trend, volatility and breadth together. Holding about
half the usual equity while stress is confirmed, and redeploying all
waiting cash quickly when it clears, gives a smaller worst fall than E1's
filter without giving up return.

The evidence it rests on:
- Scaling a momentum portfolio's exposure by its own recent volatility
  nearly doubled its risk-adjusted return and removed most of its crashes
  (Barroso and Santa-Clara, 2015).
- Momentum portfolios suffer most in the rebound after a crash, when the
  most beaten-down stocks jump and a momentum portfolio does not own them
  (Daniel and Moskowitz, 2016). This is why high gear buys the broad
  market first.
- This project's own S7 rows: selling to cash on RISK_OFF cut drawdown
  sharply for similar return (E1b validation 24.1% vs 43.6%; E1b
  development 49.2% vs 54.7%; E1 development 53.3% vs 55.4%).

## 3. Signals at month-end M (point-in-time; no new data)
*Amended 2026-09-27, §11 (a): an undefined signal counts as not firing.*

- **T, trend**: Nifty 50 month-end close below its 10-month average
  (E1 §6, unchanged).
- **V, volatility**: realised daily volatility over the last 126 sessions
  of an equal-weight basket of the current top 25 by the stack's score,
  above its own trailing 36-month 80th percentile.
- **B, breadth**: share of eligible names closing above their own
  200-session average is below 40%.

## 4. The one change: E1 §6's on/off rule is replaced by three gears
*Amended 2026-09-27, §11 (b)–(d): the sell-down ranks names, not lots;
the high gear buys NIFTYBEES; what interrupts its disposal.*

- **Cautious**: T and (V or B). Target equity is 50% of portfolio value.
  If equity is above target, sell down at the next open, at most half the
  excess per month, choosing lots in this order: realised loss first,
  then long-term lots, then short-term lots with the smallest gain. New
  SIP cash and sale proceeds go to the cash sleeve (or to E3's sleeve if
  E3 has been adopted by then).
- **Normal**: otherwise. Target equity 100%. The stack's rules unchanged,
  including six buys per month.
- **High (occasional)**: the first month-end in normal gear after at least
  two consecutive cautious month-ends. All waiting cash is invested at the
  next open into the Nifty 500 index security (as used for B2, with a
  declared 0.30% p.a. expense drag, equity tax class). That holding is
  kept as its own position and sold only once it is long-term, in thirds
  over the following three month-ends, with the proceeds entering the
  stack's normal buy rules.

No leverage in any gear: equity never exceeds 100%.

## 5. Window and benchmarks
E1's full window: development 2007–2016, validation 2017–2021. Sealed
untouched. Benchmarks B1–B5.

## 6. Sweep
| row | change |
|---|---|
| S1 | cautious target 30% |
| S2 | cautious target 70% |
| S3 | no selling in cautious gear (new cash waits only; E1's behaviour with V and B added to the trigger) |
| S4 | V only in the trigger (no B) |
| S5 | B only in the trigger (no V) |
| S6 | two gears (no high gear; waiting cash re-enters at six names a month) |
| S7 | high gear deploys straight into the stack's names (tests the rebound trap) |
| S8 | India VIX above its 36-month 80th percentile instead of realised V (from 2009) |
| S9 | costs ×2 |
| S10 | cautious sell-down all at once instead of half the excess per month |

## 7. Verdict
ADOPT, REJECT or INCONCLUSIVE per `GATE.md` against the current stack,
plus a separate MANDATE block reporting §3 (worst fall within 5 pp of the
Nifty 500 fund, return at least 3 pp/yr above it) and §5 (at least 2 pp/yr
above B5), both periods.

## 8. Reported extras
Months in each gear by year; equity exposure over time; false alarms
(cautious months followed by a positive three-month market return) and
what they cost; tax paid on sell-downs; worst fall in each stress episode
(2008, 2011, 2013, 2015–16, 2018, 2020) for stack versus candidate.

## 9. Relationship to other charters
E2-C tests GDELT tone and VIX as an extra RISK_OFF trigger; if E3-R is
adopted first, E2-C tests its trigger as an addition to E3-R's cautious
condition instead. E3 decides where non-equity money sits; E3-R decides
how much equity there is.

## 10. Not claimed
No prediction of crashes. The signals raise the odds of a bad period;
they never give certainty, and false alarms are counted, not hidden.

## 11. Change log
- 2026-09-19 — draft, written from MANDATE §3's dynamic risk requirement.
- 2026-09-25 — **declared as noticed after E1d's verdict, before any E3-R
  run.** E1d showed a near one-for-one trade of return for drawdown in
  validation, which G2 refuses. E3-R's cautious gear is the same kind of
  trade; its high gear (fast redeployment after a cautious period) is the
  part that must pay for it. **Prediction recorded before any run: E3-R
  passes only if the high gear's recovery return exceeds the cautious
  gear's cost in 2017–2021.** No rule changes on this line — it is recorded
  so the prediction cannot be written after the result is known.
- 2026-09-27 — **four decisions by Aarsh, before lock and before any E3-R
  run**, settling the four questions in `docs/notes/E3R-readiness.md` §3.
  §3 and §4 above are read together with these entries.

  **(a) An undefined signal counts as not firing.** V needs 126 sessions and
  then 36 months before its percentile exists, so it is undefined until
  about 2007-07. Until then the cautious condition is effectively **T and
  B**. The months with undefined V are recorded in the manifest. *Reason:*
  the readiness note's three readings each change the 2008 result; this one
  uses every signal that exists and invents none.

  **(b) The sell-down chooses names and share counts, never lots.** Within
  a name the lot book sells **FIFO**, as Indian demat rules require, so
  `tax/india_lots.py` does not change. Held names are ranked by the tax
  cost per rupee raised if the whole position were sold FIFO: **net loss
  first, then net long-term gain, then short-term gain, lowest tax per
  rupee first; ties broken by the weakest current score.** Whole names are
  sold down the ranking, the last one partially in whole shares, until the
  month's sell-down amount is met. *Reason:* §4's "lot order" is a ranking
  across the book, but a broker cannot sell a chosen lot of a name out of
  FIFO order; ranking names by what a FIFO sale would cost is the version
  that can actually be executed.

  **(c) The high gear's broad-market instrument is NIFTYBEES**, not a
  synthetic Nifty 500 index: tradable, with real traded value and its fees
  already in its price, so there is no injected index row and no synthetic
  expense drag. It is **exempt from E1 §2's eligibility and from the band**
  (the gear holds it, not the rank); **subject to the ADV guard** like any
  buy; **equity tax class**. Its adjusted series is to be confirmed free of
  unexplained jumps across the window, and whether its dividends are in the
  dividend table recorded (if not, the high gear is slightly understated,
  and the verdict note says so). *Reason:* an index cannot be bought; the
  ETF can, and it removes three of the readiness note's open questions at
  once. This replaces §4's "Nifty 500 index security (as used for B2, with
  a declared 0.30% p.a. expense drag)".

  **(d) The NIFTYBEES holding is one position.** In **normal** gear, its
  lots that have turned long-term are sold in thirds over the next three
  month-ends, proceeds going to the stack's buy rules. In **cautious** gear
  it is ranked with every other holding by (b). A new high-gear month adds
  to it; its lots keep their own dates. *Reason:* settles what interrupts
  the disposal clock without giving the position a lifecycle of its own.

- 2026-09-27 (Aarsh, session 1 of 4) — **(e) the high gear's NIFTYBEES buy is split across sessions**, each
  session's slice capped at 1% of NIFTYBEES's trailing 20-session average
  traded value, until the month's amount is bought; it is **never
  skipped**. Replaces the ADV-guard skip for this buy only (E1 §7's skip is
  unchanged for stocks). *Reason:* the readiness note (§8) found the guard
  would skip the 2009-04 high month outright (1% of ADV was ₹6.8 lakh); a
  skipped high gear tests nothing.
