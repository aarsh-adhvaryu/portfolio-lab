# S81 item B5: the swing sleeve and exemption harvesting in the lab (pre-registration)

Written 2026-11-09 (night) BEFORE any run of the swing replay on the real panel and before the code that runs it is committed. The SHA-256 of this file is stored in the learner's
counter (`learn_tests`, origin `study`, notes `s81:swing:momentum_continuation`, `s81:swing:pullback_in_uptrend`, `s81:swing:post_results_drift`, `s81:harvest`) when the study
is registered (`learner/s79.py` STUDIES, `register_all`); `lab/swing_study.run` refuses to run if the file has changed since, or was never registered. An amendment is dated,
re-registered, and counts as new tests. Four tests are counted: the three swing variants (claim A, one test each) and harvesting (claim B, one test).

## 1. Claims

**A. The swing sleeve beats holding the Nifty 500 as an ETF, after tax and charges, over the history window 2005-01-01 to 2017-12-31.** Each of the three variants of section 4 is
one test. A variant "beats" the index when it clears every condition of section 6 against the index arm of section 3. The claim "the swing sleeve has an edge" is supported if at
least one variant passes; it is then reported with the number of variants tried (3) and the counter's N, and that variant alone goes to the final check (section 7). Nothing is
wired live on this study: a variant acts only through the A50 promotion rule.

**B. Exemption harvesting adds after-tax return versus no harvesting, over the same window,** on the same book, with the same trades otherwise (section 5). One test.

## 2. Data and the point-in-time rule

* The lab panel (`lab/runner.build_panel`): adjusted closes and daily traded value of the 600 most-liquid listed shares (by median turnover over the whole panel: this
  selection is a known survivorship limit of the S80 lab, shared by every arm) and the four index ETFs, 2004-01-01 to 2021-12-31 read in the query itself. 2022-2025 is spent and
  never read. The replay of the history window ends 2017-12-31.
* Added for this study, all point in time: the day's open, high and low as ratios to the day's close (from the same rows; applied to the cleaned adjusted close, so stops and targets
  read adjusted levels); the Nifty 500 total-return index as a held security (section 3); the BSE "Financial Results" announcement days of each share (section 4, drift).
* A signal at the close of session `t` uses rows dated `<= t` only. A decision made at the close of `t` is filled at the close of the NEXT session (as in the S80 lab); stops,
  targets and time exits are checked on the sessions after the fill.
* Data breaks: a daily move over 60% is removed from the path (the lab's rule). A halted name keeps its last close.

## 3. The replay (what is new: `lab/swing.py`; the monthly engine is not changed)

* One sleeve, capital Rs 10,00,000, cash earns 6.5% a year when idle (the lab's rate; interest is not taxed in the replay: stated). Every trade pays the lab's flat charge rates
  (`construct/costs.rate`: equity 0.12% and ETF 0.03% a side at a typical order) PLUS slippage (below). Tax is the lab's FIFO book: lots by acquisition date; a lot sold after MORE
  than 12 calendar months is long-term, else short-term; the year's gains net by bucket as the law sets off; the rates and the exemption are READ from the tax engine's dated
  rows (`configs/tax`, row `equity_stt_paid`, `tax.rules.exemption`), never typed in the policy or the replay. **Stated assumption: the law as the rows date it (2024-07-23 on:
  short-term 20%, long-term 12.5% above the yearly exemption) is applied to the whole 2005-2017 window.** The law then was different (long-term equity gains were exempt, short-term
  15%), and the tax engine refuses earlier dates; applying today's rows to every arm is the lab's existing rule (S80) and is kept. It penalises long holding and short trading
  alike in the index arm and the swing arms; the size of the tax paid is reported for each arm.
* Orders. A swing entry names its weight, a stop, a target and a time exit (all relative to the FILL price): stop below the fill, target above, time exit after a number of
  sessions held. A sell is never within the same day as the buy of the same shares: a target or time exit due on the entry day waits for the next session; only a stop may fire
  (configuration `entry_fill: "open"` makes an entry fill at the open so this can be seen on the entry day; the study uses the default `"close"`, under which nothing can fire
  on the entry day).
* Daily bars. Stop: the order fires when the session's low is at or below the stop; it fills at the stop, or at the open if the session opens below it (a gap), never better.
  Target: fires when the high is at or above the target; fills at the target (not at a higher open: conservative). If one session reaches both stop and target the STOP is taken.
  Time exit: at the close of the session on which the position has been held for the stated number of sessions. A discretionary exit named by a policy fills at the next
  session's close.
* Slippage (an assumption, recorded with its parameters in every run's output): every fill is moved against the trader by
  `slip = half_spread + Y * sigma_d * sqrt(share)`, where `share` = order rupees / that day's traded value in rupees (capped at 1), `sigma_d` = the name's daily volatility over the
  last 20 sessions known at the order (floor 0.5%, point in time), `half_spread = clip(0.0005 * sqrt(1e8 / traded_value), 0.0005, 0.0050)`, `Y = 1.0`. Buys fill at
  reference x (1 + slip), sells at reference x (1 - slip); a stop fills at min(stop, open) x (1 - slip). It is never better than the reference (close, stop or target).
* Sizing and rails: each entry is 9% of the sleeve's value, at most 10 positions, at most 3 new entries a day, no add-ons, one position per name; the company rail (10%) is
  respected by construction; no turnover caps (a swing book turns over by design; the monthly caps are for the other sleeves). Entries that cannot be paid from cash are skipped.
* The index arm ("hold the index ETF"): the whole capital in one security, `ETF:NIFTY500_TRI`, the Nifty 500 total-return index reduced by an expense ratio of 0.20% a year (an
  assumption, rounded up from typical Nifty 500 ETF costs), bought at the close of the first session after the first signal day, held to the end, with the ETF charge rate and
  the same slippage function (turnover set to the index ETF's own as very liquid). Tax as above.
* The cash arm: the capital at 6.5% a year, untaxed.
* Measures of every arm: after-tax-and-charges value path; **liquidation value** = the value if everything were sold at the last close of the window, with its charges, slippage-free
  at the last close, and the tax on that sale in the last financial year's books (this stops deferral of tax from looking like a gain and makes buy-and-hold and trading comparable);
  its CAGR `L`; the CAGR of the path; Sharpe over cash; the worst fall `D`; tax paid; charges; slippage paid; turnover; the number of trades, the hit rate and the average days held.
* Luck is measured, not assumed: 20 shuffled-signal runs per variant (the S80 measure: each entry lands on a random OTHER share of the same kind at the moment of the decision;
  the policy sees its positions through the same mapping; seeds `80000 + i`), and a block bootstrap of the arm's own returns (the lab's Monte Carlo).

## 4. The three variants (fixed here, no grid: each is one trial; written as policies in the toolkit's allowed language, daily cadence)

Universe: the lab's `universe` shares (the 60 most-liquid by median traded value over 250 sessions, with at least 300 sessions of history, point in time); never ETFs. Rank ties by key.

* `swing_momentum_continuation`. Entry candidate: the close is the highest of the last 55 sessions (including today) AND the 126-session return is positive. Rank by the 126-session
  return, highest first. Exits: stop 8% below the fill, target 16% above, time exit 30 sessions.
* `swing_pullback_in_uptrend`. Entry candidate: close above its 200-session average AND the 50-session average above the 200-session average AND the 5-session return at or below -5%.
  Rank by the 5-session return divided by the 20-session daily volatility, most negative first. Exits: stop 7% below the fill, target 10% above, time exit 15 sessions.
* `swing_post_results_drift`. Entry candidate: a BSE "Financial Results" announcement of the name became known by today's close (the session of its timestamp, or the next session
  if stamped after 15:30; the timestamp is the dissemination time where the file has one, else the news time: see the limits) AND today is that known session AND the name's return on
  today is at least +4% AND today's traded value is at least 2 times its 60-session median. Rank by today's return. Exits: stop 8% below the fill, target 15% above, time exit 30 sessions.
  Announcement days exist in the data from 2011; before that the variant makes no trade (it holds cash): stated.

## 5. Claim B: the harvesting rule and its test

The rule (the minimal one of the A51 brief, `lab/harvest_replay.harvest_step`, a plain function the exit manager may call; the exits agent's module was not available when this was
written, so this is the rule from the brief):

* Window: the last quarter of the financial year (1 January to 31 March), on any session.
* Exemption harvest: with the year's long-term equity gains so far (net of short-term losses, as the law sets off) the room under the yearly exemption is
  `max(0, exemption - that net)`. Sell long-term lots (held more than 12 months) with a gain, oldest first, partial lots allowed, until the gain realised reaches 98% of the room; do it
  only when 12.5% of the gain is more than the estimated round-trip cost (0.40% of the proceeds). Buy the same quantity back at the NEXT session's close (the cost price is reset to
  that price; the holding period starts again: the replay pays that price, charges, slippage and the short-term tax clock honestly).
* Loss harvest: when the year has taxable gains (short-term gains, plus long-term gains above the exemption), sell lots held with a loss until the loss realised offsets them,
  only when the tax saved is more than the round-trip cost; buy back next session.
* A lot within 30 days of turning long-term is not sold at a gain (the guard).

The test, paired and the same in both arms, window 2005-2017: ARM 1, the index ETF held (section 3) with harvesting versus without; ARM 2, the lab's `baseline_lab` policy (liquid shares
and ETFs sized by risk, rebalanced monthly through the lab's monthly engine rules) with harvesting versus without. The difference is `dL` (liquidation CAGR, with minus without) and
the tax saved (tax paid plus the tax of the liquidation, without minus with) against the extra charges and slippage paid.

## 6. The rule in code (fixed now): `lab/swing_study.RULE`

```json rule
{
  "history": ["2005-01-01", "2017-12-31"],
  "final": ["2018-01-01", "2021-11-30"],
  "capital": 1000000,
  "cash_rate": 0.065,
  "n_shuffles": 20,
  "shuffle_seed": 80,
  "bootstrap": {"block": 21, "resamples": 5000, "seed": 81},
  "swing_pass": {
    "min_excess_L_cagr_vs_index": 0.01,
    "min_t_vs_index": "counter.t_needed(N after registration)",
    "max_shuffled_beats_real_frac": 0.10,
    "min_dsr": 0.90,
    "max_extra_drawdown_vs_index": 0.05
  },
  "harvest_pass": {"min_dL_each_arm": 0.0005, "tax_saved_must_exceed_extra_costs": true},
  "slippage": {"half_spread_base": 0.0005, "half_spread_cap": 0.005, "turnover_ref": 100000000, "impact_y": 1.0, "sigma_window": 20, "sigma_floor": 0.005},
  "sizing": {"weight": 0.09, "max_positions": 10, "max_new_per_day": 3},
  "index_expense_ratio": 0.002,
  "variants": {
    "swing_momentum_continuation": {"high_window": 55, "trend_window": 126, "stop": 0.08, "target": 0.16, "max_days": 30},
    "swing_pullback_in_uptrend": {"sma_fast": 50, "sma_slow": 200, "pullback_days": 5, "pullback": -0.05, "stop": 0.07, "target": 0.10, "max_days": 15},
    "swing_post_results_drift": {"react": 0.04, "volume_mult": 2.0, "volume_window": 60, "stop": 0.08, "target": 0.15, "max_days": 30}
  },
  "harvest": {"window_months": [1, 2, 3], "fill_fraction": 0.98, "round_trip_cost": 0.004, "guard_days": 30, "lt_months": 12}
}
```

**A variant passes (claim A) if ALL of these hold** on the history window, against the index arm:
1. `L(variant) - L(index) >= 1.0` percentage point a year;
2. the paired block-bootstrap t of the daily return difference (variant minus index; block 21, 5,000 resamples, seed 81; t = mean difference / standard deviation of the resampled
   means) is at least the learner's bar `t_needed(N)`, N being the counter's N after these four tests are registered (the bar rises with N);
3. at most 10% of the 20 shuffled-signal runs reach the real run's Sharpe, AND the real run's CAGR is above the 95th percentile of the shuffled runs' CAGR;
4. the deflated Sharpe (over EVERY variant ever scored on the history window in the lab, these three included, so the bar rises with the tries) is at least 0.90;
5. the worst fall is not more than 5 points deeper than the index arm's.
Otherwise the variant FAILS and has no live feature. Claim A is "supported" if one or more pass, "not supported" if none does. A variant that passes everything but has fewer than 40
trades is reported as passing "on a thin record" and not forwarded.

**Claim B passes if** `dL >= +0.05` percentage points a year in BOTH arms AND in both arms the tax saved exceeds the extra charges and slippage paid. Otherwise harvesting is "not
shown to add after-tax return in the replay" and the exit manager keeps its tax rules only as the brief states them, labelled unproven.

## 7. The final check and counting

* The final check, 2018-01-01 to 2021-11-30, is run ONCE per variant by code (`swing_study.final_check`, which writes a once-only row and refuses a second run), only for a variant that
  passed section 6, and its result is never shown to the strategist (it receives only "cleared" or "did not clear"). Nothing is run on the final window tonight unless a variant passes.
* Counting: the four registrations above are four tests in the learner's counter (the bar for every later test rises). Every variant and every parameter set the strategist later tries
  is a trial in the lab's deflated Sharpe (`lab_runs_s80`); the three variants and the index control are scored through the same table.

## 7a. Amendment A1 (2026-11-09 night, before any code that runs this study was committed and before any registration or run)

Two things the first text left open, fixed here: (1) **the CAGR in condition 3 of section 6 is the liquidation CAGR `L`** for the real run and for every shuffled run (so that tax
deferral cannot make a shuffled run look better or worse than it is). (2) **The final check's rule** (it is run only for a variant that passed section 6, once, by code): the variant's
`L` over 2018-01-01 to 2021-11-30 is not below the index arm's `L` over the same days, AND its worst fall is not more than 5 points deeper than the index arm's, AND it made at
least 20 trades. The strategist is told only "cleared" or "did not clear". The A50 promotion rule (B3) stays the rule for any live action; this study's final check only decides
whether the study's claim A stays "supported".

```json rule
{"final_pass": {"min_excess_L_cagr_vs_index": 0.0, "max_extra_drawdown_vs_index": 0.05, "min_trades": 20}, "shuffled_cagr_is": "liquidation_cagr", "min_trades_forwarded": 40}
```

## 8. One run, and the limits stated before it

`lab/swing_study.run` is run ONCE for the record; its result goes to `lab_runs_s80` and `docs/STUDIES.md`. A rerun with changed parameters is a new registered study. Limits: adjusted
daily bars (no intraday path: a stop is checked on the low, a same-day stop-and-target is taken as the stop); survivorship in the 600-name selection; today's tax law applied to
2005-2017 (above); dividends are inside the adjusted closes (their tax is not modelled); the sector label is static; results-announcement days exist from 2011 only, and for 2011-2015
the file carries the news time only (the dissemination time is present from mid-2015): where the dissemination time exists it is used, otherwise the news time is used, and the
size of the gap between the two in 2016-2017 is reported beside the result; no minute data before 2015 so entries are not timed within the day; one decade of one market; the slippage
function is an assumption, not a measurement.
