# S76 learner tests: after a fall, and rebalancing bands with gold (protocol, 2026-11-01, committed before any run)

His steer (2026-11-01): "waiting always is not a good thing, but being impatient is not a good thing either; find a way through past data and daily noise."
Two families of claims test exactly that tension, with gold in the mix ("include gold"), and a few variants each ("few extra variants"). Every claim is one
test in the family "all": the development bar rises with N (`counter.t_needed`). Nothing below changes after the first run; a change is an amendment with its
date and reason. Periods as every study here: development 2010-2017, validation 2018-2021; 2022-2025 is spent and is not evidence (CLAUDE.md 2).

## Reading of his words (stated so he can correct it)
"Impatient" is reacting to today's price: selling a stock the day it is 30% below its high, or rebalancing the moment a weight drifts. "Waiting always" is never
acting: holding whatever happens, never rebalancing. The way through is a rule that acts only on a move that has PERSISTED (a confirmation window: still down
after 20 or 60 sessions) or that is LARGE (a band of 5, 10 or 20 points), checked at the month end rather than on every day's noise. The tests ask whether such a
rule beat both extremes after charges and tax, on years the system has not used.

## Template `fall_response` (new, `learner/templates.py`)
- **Universe and measure:** as `rule_filter` (docs/protocols/s64_rules_protocol.md): each month end, the point-in-time Nifty 500 members with a close on at least
  200 of the last 252 sessions; the group's equal-weighted total return over the next `months` months minus all members'. Fewer than 50 names or fewer than 10 in
  the group: the month is skipped.
- **The group (fixed here):** the adjusted close is at least `depth`% below its highest adjusted close of the last 252 sessions, and has been so on EVERY one of
  the last `confirm` + 1 sessions (confirm 0: just today; 20: a month; 60: a quarter). Rows up to the month end only.
- **Direction `out`** (they rebound: HOLDING after the fall was right): the excess less `stocks.round_trip_pct(DEFAULT_ORDER)` on the share of the group that
  changed. **Direction `under`** (they keep lagging: SELLING was right): the excess with the sign reversed, no charge (selling what one holds is the act tested;
  the charge is one sale, below the effects that matter here, and stated).
- **Parameters (closed list):** depth {30}, confirm {0, 20, 60}, direction {out, under}, months {3}.
- **Pass:** `templates.decide`: the claimed direction in both periods; development Newey-West t (lags = months) >= `counter.t_needed(N)` (never under 2.0),
  validation t >= 1.65; at least 36 months each; the effect larger than its cost.

## Template `rebalance_bands` (new)
- **Assets, rupees, daily:** the Nifty 500 total-return index (`indices NIFTY500_TRI`); gold through the gold ETF on NSE (GOLDBEES: ISIN INF732E01102 to
  2019-12-19, INF204KB17I5 from 2019-12-20, joined at the change; a one-day move beyond 50% is a unit split, never a gold price: the ratio is taken to the nearest
  power of ten and removed; its expense ratio is inside its price); cash at 7% a year (an assumption, the debt / FD rate used in `quant/policies.py`).
- **Mixes (fixed):** `60_20_20` = 60% equity, 20% gold, 20% cash; `70_30_0` = 70% equity, 30% gold.
- **Policies:** `band B`: when any asset's weight is B percentage points or more from its target, everything is set back to the target (checked at each month end,
  or `daily` on every session); `never`: bought once at the target, never touched; `monthly`: set back to the target at every month end.
- **Charges and tax:** each rupee of an ETF traded (equity is taken as an index ETF, gold as the gold ETF) pays 0.05% (half of `ETF_ROUND_TRIP_PCT`); a sale pays
  12.5% on its gain over the asset's average cost at once (long-term rate; the yearly exemption and short-term rates are left out: a stated simplification
  that is harsher on frequent rebalancing). Cash moves free.
- **Measured:** each policy starts at the target on the first session of the period with Rs 100; the series is the month's net return of the band policy minus
  that of the policy it is compared with (`against`: never or monthly).
- **Pass:** the mean monthly difference above zero with `templates.decide` (the same bars, at least 36 months), AND the band policy's worst fall from a month-end
  high no deeper than the other's by more than 1 percentage point, in both periods (a return bought with a deeper fall does not pass).
- **Parameters (closed list):** mix {60_20_20, 70_30_0}, band {5, 10, 20}, against {never, monthly}, check {month_end, daily}.

## The claims registered (`learner/s76.py`, by the learner's own nightly cycle in the app)
After a fall (months 3, depth 30):
1. confirm 0, out: stocks that have just fallen 30% below their one-year high rebound over the next three months (hold).
2. confirm 0, under: they keep lagging (sell at once).
3. confirm 20, out: still 30% down after a month, they rebound (hold).
4. confirm 20, under: still 30% down after a month, they keep lagging (sell after a month).
5. confirm 60, out: still 30% down after a quarter, they rebound.
6. confirm 60, under: still 30% down after a quarter, they keep lagging.
Rebalancing with gold:
7. 60_20_20, band 5, against never, month_end.
8. 60_20_20, band 10, against never, month_end.
9. 60_20_20, band 20, against never, month_end.
10. 60_20_20, band 10, against monthly, month_end (patience against the calendar).
11. 60_20_20, band 10, against never, daily (the same band checked on daily noise).
12. 70_30_0, band 10, against never, month_end (equity and gold only).
Twelve claims raise N by twelve: the stated price of testing them, and the reason there are not more variants.

## Use of the result
A pass is wired (`claims.wire`): a finding every agent reads, and the paper portfolio's team sees it in the record; a change to how the paper portfolio or his
real proposals act on falls or rebalancing is then proposed, never applied without his yes for his money. A fail has no live feature. Results go into
`docs/STUDIES.md`.
