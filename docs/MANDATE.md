# MANDATE — how this system handles Aarsh's money

Status: **IN EFFECT from 2026-09-21** (§3 confirmed by Aarsh that day). From
that date it governs every ADVANCE decision (sealed reveal, live paper year,
real money) and every target the transition tool uses.

It does not change any recorded verdict. E1 (INCONCLUSIVE), E1b (INCONCLUSIVE)
and every verdict written before the effective date stand under their own
charters. GATE.md still decides adoption (whether a change joins the
stack). This file decides what the stack must achieve before it touches
money.

## 1. The investor
- One person, early twenties in 2026, horizon measured in decades.
- ₹50,000 a month by SIP, plus occasional top-ups.
- Zerodha delivery account. Indian listed equities and ETFs. No intraday,
  no F&O, no leverage.
- Private. Not a product for anyone else.

## 2. Objective
Maximise long-run after-tax wealth. Accept more volatility than a typical
investor, because time and continuing contributions let a young investor
recover from falls. Do not accept a meaningful chance of permanent loss:
a fall you recover from is a price; a company that goes to zero is not.

## 3. Risk appetite: dynamic
Risk is not one fixed setting. Equity exposure moves between three gears
by rule (§9, charter E3-R): cautious when measurable danger signals are
on, normal most of the time, high occasionally when a crash ends and
waiting cash goes back in.

The bar that judges the whole period stays fixed, because a pass mark
that moved with the market could make any result pass. It is set to
match what the gears are supposed to deliver:

| | requirement | why |
|---|---|---|
| worst fall | no more than 5 pp deeper than the Nifty 500 fund's | the worst fall always happens in a crash, when the gears should be in cautious |
| return | at least 3 pp/yr more than the Nifty 500 fund, after tax | normal and high gear the rest of the time must earn the risk taken |

Both hold in development and validation, and in at least two thirds of
the stack's sweep rows. Figures are the engine's liquidation-adjusted,
after-tax numbers, the same ones every sweep reports.

This is stricter than any single fixed setting, deliberately: it is what
a working dial must achieve. If nothing achieves it, the gears cannot see
danger in time, which is worth knowing before they run real money.

Fixed settings considered and set aside: cautious (+5 pp / +2 pp),
higher (+10 / +3), highest (+15 / +4). For reference, the Nifty 500 fund
fell about 63% in 2008 and 38% in 2020 in this engine.

**Status:** proposed 2026-09-19; **confirmed by Aarsh as written,
effective 2026-09-21.**

## 4. Universe
The whole Nifty 500 (E1's universe), not large caps only. E1b showed
E1's 2017–2021 return came from outside the top 200; this mandate chooses
that exposure deliberately.

Consequences:
- The permanent-loss guard (E2-A, red flags) becomes the highest-priority
  experiment after E1c.
- The liquidity guard (skip a buy above 1% of 20-session traded value)
  stays.

## 5. What it must beat
The honest comparison is always what could be bought in one click.

- **B2 Nifty 500 TRI**, the market. Judged by §3.
- **B5 Nifty 500 Momentum 50 TRI**, the one-click alternative for a
  whole-500 momentum investor (index funds tracking it exist since late
  2024). The stack must beat B5 by at least 2 pp/yr after tax in both
  periods: the margin that makes running your own code worth its risks.
- B3 Nifty 200 Momentum 30 stays in reports for continuity.

B5's pre-launch history is back-computed by NSE; same caveat as B3.

Direction of this change, recorded honestly: B5 replacing B3 as the
one-click bar makes the test harder in the years small caps ran, because
B5 holds the same kind of names E1 made its money on; §3 makes it looser
on drawdown. Both are chosen before E1c's verdict and before the sealed
period is opened.

## 6. Horizon and trading
Long-term core. Holding periods are set by the rules, months to years.
Short-term gains are accepted when the rules require a sale, and always
counted after tax. No change may be adopted that more than doubles
turnover (GATE G4).

## 7. Sectors
No fixed sector weights and no forecasts about sectors. The sector-trend
cap (charter E1-S, to be written): a sector whose index closes a month
below its own 10-month average is capped at half its normal weight; the
cap lifts when it closes above again. This is the rule for "let go of IT
when it is being hit harder than it should, buy back when things
normalise", written so it needs no view on AI. When trend and balance
conflict, trend wins.

## 8. Losses
- When the rules say sell, sell at the next open. Never defer an exit to
  save tax: E1-P (REJECT) found deferred names kept falling in both
  periods, 7 to 11 pp worse over three months than the names sold, and
  the tax saved was smaller than the return lost.
- No separate stop-loss. E1-P's N1 helped only in the period containing
  2008 and cost 4.7 pp a year in the next one.
- No profit-taking. N2 sold names that went on to rise 9% and 29%.
- Harvest short-term losses before 31 March in the transition tool. This
  is tax only; rebuying restarts the 12-month clock and must be priced in.
  Confirm the tax treatment with a CA before relying on it with real money.
- The system never changes its rules because a trade hurt. Rules change
  only by charter and verdict.

## 9. Crashes and the risk gears
The SIP never stops. Nothing is sold on feeling. Equity exposure moves
between three gears by rule (charter E3-R), and only if E3-R passes the
gate:
- **Cautious**: the market is below its trend and volatility or breadth
  confirms stress. Equity is taken down toward half the portfolio,
  gradually, selling lots with losses or past 12 months first. The rest
  waits in the defensive sleeve.
- **Normal**: fully invested under the adopted stack's rules.
- **High, occasionally**: when a cautious period ends, all waiting cash
  goes back in within the month, into the broad market first (momentum
  portfolios lag in the rebound after a crash), then into the stack's
  names as that holding turns long-term.

There is never certainty of losing money. The signals raise the odds;
the gears will sometimes be cautious in a false alarm and pay for it, as
in 2020. Every sweep reports that cost.

## 10. Tax
After-tax, liquidation-adjusted return is the only return that counts.
FIFO lots. Prefer sales past 12 months. Never hold a position the rules
have exited purely to save tax (§8).

## 11. The existing portfolio
Loaded as opening lots from a Zerodha tradebook export: symbol, quantity,
trade date, price per lot. Nothing else is needed or stored: no balances,
no PAN, nothing Kite can act on. The transition tool (T1) proposes only
changes whose benefit exceeds their tax and cost, and never more than a
set fraction of the book in one month.

## 12. The target
The transition tool moves the portfolio toward the adopted stack. If no
stack meets §3 and §5, the target is the B5 index fund plus whatever
defensive sleeve E3 adopts. The tool is worth running either way; it must
never churn toward a target that has no edge.

## 13. What the AI does
Reads filings, links entities, monitors holdings, flags risks and writes
the monthly memo. Never picks a stock, a parameter or a rule. Learned
models (E5) enter only through the gate. No agent places an order outside
the month-end job.

## 14. Autonomy and the human
- Before real money: a full live paper year on the adopted stack.
- After it: the month-end job builds and places the orders. Aarsh's
  routine action is the Kite login that authorises the session (Kite's
  access token expires daily). He may veto any order; every veto and
  every urge to override is logged with one line of reason. Target: zero.
- One sealed reveal, in writing, only after the stack meets §3 and §5 in
  development and validation.

## 15. What success means
- **Top:** a stack meets §3 and §5, survives the sealed period and the
  live year, and runs on real money from late 2027.
- **Bottom:** nothing meets them; the money goes into the B5 fund, the
  transition tool and sector cap run where they apply, and the harness
  stays for research.

Both are success. The failure is running code on savings without evidence.

## 16. Changes to this mandate
Only by Aarsh, with a dated line and a reason below, and never in
response to a result the change would alter.

- 2026-09-19 — drafted from the conversations of 16–19 September. §3 pending.
- 2026-09-19 — §3 made dynamic on Aarsh's instruction (fixed bar: +5 pp
  drawdown, +3 pp/yr return), pending his yes; §9 rewritten around three
  risk gears; charter E3-R drafted to test them.
- 2026-09-21 — §8 and §10 updated after E1-P's REJECT: exits are never
  deferred for tax, no stop-loss (N1 failed validation), no profit-taking.
- 2026-09-21 — **§3 confirmed by Aarsh as written; the mandate is in effect
  from this date.** Confirmed before E1c's development sweep and before any
  E1c validation verdict, so it cannot be a response to either. Recorded
  verdicts (E1 INCONCLUSIVE, E1b REJECT, E1-P REJECT) are unchanged.
- 2026-09-21 — §5: **B5 carries a 0.30% a year expense drag**, the same as
  B3, as the realised cost of the index fund it stands for (Aarsh). Set
  alongside two measurement corrections (buy sizing net of costs, E1 §15;
  expense drag compounded by calendar days), before any verdict turned on
  §5.
- 2026-09-22 — the E1b verdict quoted at the top of this file corrected from
  REJECT to **INCONCLUSIVE**: E1b was re-run from scratch under the
  2026-09-21 measurement correction and its verdict changed
  (`docs/reviews/E1b-verdict-rerun.md`). A factual correction only; nothing
  else in the mandate changes.

---

## Appendix — prompt that applies this mandate

Send once Aarsh confirms §3, and before E1c's validation verdict is
written, so the choice cannot be read as a response to it.

```
docs/MANDATE.md and docs/strategies/E3-R.md are in place. Sending this
is Aarsh's confirmation of §3 as written: mark it confirmed with today's
date. Then:
1. GATE.md and ROADMAP.md: adoption is still decided by GATE; ADVANCE
   (sealed reveal, live paper year, real money) is decided by MANDATE §3
   and §5 from its effective date. Recorded verdicts are unchanged.
2. Add benchmark B5 = Nifty 500 Momentum 50 TRI (NSE Indices historical
   data) through the same engine, SIP and tax as B1–B4, with the B3-style
   caveat on back-computed history. Report B5 for both periods alongside
   the stored E1, E1b, E1-P and E1c results, as information only; no
   verdict is recomputed.
3. ROADMAP per MANDATE §4 and §9: E2-A immediately after E1c, then
   E3-R. Report E3-R readiness (no new data should be needed) and stop.
4. classify: add a separate "mandate" block (§3 and §5) next to the GATE
   and C1–C4 blocks.
Report and stop.
```
