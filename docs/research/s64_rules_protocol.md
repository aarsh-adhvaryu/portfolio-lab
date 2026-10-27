# S64 rule tests: protocol (2026-10-27, committed before any run)

The investor's steer (2026-10-27): the system must test what it shows him, collect, personalise and correct itself while it
works. The rules of thumb the brain reads (`hq/valuation.py`) and the starter scans (`quant/scan.py`) are labelled "not tested".
This protocol turns each into a claim for the learner (`docs/research/learner_protocol.md`, amendments 1-4), origin `study`.
Each claim is one test in the family "all"; the development bar rises with N (`counter.t_needed`). Nothing below changes
after the first run; a change is an amendment with its date and reason.

## Template `rule_filter` (new, in `learner/templates.py`)
A rule is a yes/no condition on a stock at a month end, computed from rows dated on or before it (point in time).

- **Universe, each month end:** the Nifty 500 members of that day (delisted names included) with a close on at least 200 of the
  last 252 sessions; fewer than 50 such names: the month is skipped.
- **Group:** the names for which the rule is true. Fewer than 10 in the group: the month is skipped.
- **Measured:** the next month's total return of the equal-weighted group minus the equal-weighted return of all names in the
  universe with a next-month return. A name that stops trading keeps its last value (as in `cross_section`).
- **Direction `out`** (the group outperforms; a rule to buy): minus `stocks.round_trip_pct(DEFAULT_ORDER)` on the share of the
  group that changed since the previous month. **Direction `under`** (the group underperforms; a rule to avoid): the claim
  is tested on the same excess with the sign reversed and no cost, because avoiding a name is not a trade.
- **Periods:** development 2010-2017, validation 2018-2021. 2022-2025 is spent and is not evidence (CLAUDE.md 2).
- **Pass (`templates.decide`, the one rule):** mean in the claimed direction in both periods; development Newey-West
  t >= `counter.t_needed(N)` (never under 2.0), validation t >= 1.65; the effect larger than its cost; at least 36 months each.
- **Parameters (closed list):** `rule` in the table below, `direction` in {out, under}, `months` in {1}.

## The rules (fixed here)
| rule | true when |
|---|---|
| `pe_above_50` | price over the trailing-twelve-month EPS is above 50 (EPS above zero) |
| `pe_below_15` | the same ratio is above 0 and below 15 |
| `near_52w_low_5` | adjusted close within 5% above the lowest adjusted close of the last 250 sessions |
| `below_sma200` | adjusted close below its 200-session average |
| `volume_spike_2` | the month-end session's traded value above twice its average over the 20 sessions before |
| `ath_fall_40` | adjusted close at least 40% below its highest adjusted close since 2008-06 (the panel start) |
| `rsi_below_30` | Wilder RSI(14) of the adjusted close below 30 |

**P/E, point in time.** EPS is the sum of the basic EPS of four consecutive filed quarters from `data/bse_results` (quarters
2007-2021). A quarter is usable 60 days after its quarter end (past the 45-day filing deadline, so never earlier than the filing).
The price is the traded close of the day. The ratio is left out (not true, not false) when the EPS is older than 15 months, or when
the adjustment factor (adjusted close over traded close) has moved more than 2% since the EPS became usable: a split or bonus
makes the old EPS a different unit from today's price. Loss-makers have no P/E and are not in a P/E group.

**Not tested here, and why:** `alpha_negative` (needs a monthly CAPM fit per stock per month: a separate study), the futures
build-up classes (F&O history starts 2024, inside the spent years), the buy-zone `RICH` verdict (needs the implied-growth model
per stock per month). They stay labelled "not tested".

## The claims registered (`pflab learner register-rules`)
1. `pe_above_50`, under: stocks above 50 times trailing earnings earn less over the next month than the others (the investor's rule).
2. `pe_below_15`, out: cheap stocks (P/E below 15) earn more.
3. `near_52w_low_5`, out: stocks near their 52-week low earn more.
4. `below_sma200`, under: stocks below their 200-day average earn less.
5. `volume_spike_2`, out: stocks with a volume spike earn more.
6. `ath_fall_40`, out: stocks 40% or more below their high rebound.
7. `rsi_below_30`, out: oversold stocks bounce.
Seven claims raise N by seven; that is the stated price of testing them.

## Use of the result
A pass is wired in (`claims.wire`): the brain's `findings` tool shows the rule and which of his names meet it today; a scan
whose condition matches a passed rule is labelled "tested: passed", one that failed "tested: failed" (and the brain is told the
rule has no evidence). A fail gets no live feature. The result goes into `docs/research/s64_rules_results.md`.

## Run
The learner's nightly cycle tests registered claims; to run one by hand:
`.venv\Scripts\python -m pflab.cli learner test --claim <id>` (more than 5 minutes on the full panel: the investor's).
