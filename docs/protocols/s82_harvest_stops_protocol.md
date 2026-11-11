# S82 item C4: harvesting where it can help, and stops on long-term stocks (pre-registration)

Written 2026-11-11 (night) BEFORE any run of these two studies and before the code that runs them (`lab/c4_study.py`, `lab/c4_replay.py`) is committed. The SHA-256 of this file is stored in
the learner's counter (`learn_tests`, origin `study`, notes `s82:c4a:index`, `s82:c4a:stocks`, `s82:c4b:stops`) when the study is registered (`learner/s79.py register_c4`, called from the
app's start-up next to `register_swing`); `lab/c4_study.run` refuses to run if the file has changed since, or was never registered. An amendment is dated, re-registered, and counts as new
tests. THREE tests are counted: two arms of claim A and one claim B. Why these two: the S81 study (`docs/protocols/s81_selling_swing_protocol.md`, claim B) found no after-tax gain from harvesting
on a monthly-rebalanced book and on the index ETF, and A60 (his decision 2026-11-10) switched harvesting OFF in the live book per sleeve until a NARROWER study passes for that sleeve. A harvest
pays only where a position is held for years; the S81 baseline arm rebalanced every month (so it rarely held a lot long enough to harvest). This study tests the two places where holding is
long: the index ETFs held, and a stock book that is bought once and never rebalanced.

## 1. Claims

**A. Exemption and loss harvesting adds after-tax return, per arm, WITH harvesting versus WITHOUT it** (the S81 rule of `lab/harvest_replay.harvest_step`, section 5 of the S81 protocol, one
switch for exemption and loss harvesting together; the same book, the same trades otherwise). Two arms, each one test:
* **A-index**: the index ETF held buy-and-hold (the Nifty 500 total-return index less 0.20% a year as one security, `ETF:NIFTY500_TRI`, bought once and held; this stands for the live core's
  Nifty 500 and Nifty 50 index ETFs);
* **A-stocks**: a buy-and-hold STOCK book (section 3), bought once, never rebalanced, risk-sized.
A passing arm switches harvesting ON for that arm's sleeve ONLY: A-index -> `core`; A-stocks -> `longterm` (`configs/core.toml [exits] harvest_core` / `harvest_longterm`). A failing arm
changes nothing (they stay false, the A60 state).

**B. Risk-sized stops on long-term stocks cut the worst fall without costing return,** on the same stock book with versus without stops. One test. The stops are those of
`configs/core.toml [exits.longterm]` (section 4). They are KEPT only if they pass section 6; otherwise `[exits.longterm] stop = false` (the thesis-break sale, the rail trims and the fall
gauge stay).

## 2. Data and the point-in-time rule

* The S81 swing study's panel (`lab/runner.panel_data(root, pm_dir, swing_study=True)`): adjusted closes, daily traded value, the day's open/high/low ratios of the 600 most liquid
  listed shares (by median turnover over the whole panel: a known survivorship limit of the lab, shared by every arm) plus the index ETF key above. 2004-01-01 to 2021-12-31 is read in the
  query; **the window used is 2005-01-01 to 2017-12-31. 2018-2021 is NOT touched by this study** (it has its own once-only use by variants; 2022-2025 is spent).
* A signal at the close of session `t` uses rows dated `<= t` only; a decision at the close of `t` is filled at the close of the next session. No same-day round trip in a name.
* Data breaks: a daily move over 60% is removed from the path (the lab's rule).

## 3. The arms

* Common to every arm: capital Rs 10,00,000 (the S81 study's; the yearly exemption is then a larger share of the gains than in a bigger book: stated, it favours harvesting); cash earns 6.5% a
  year untaxed; charges the lab's flat rates; slippage the S81 liquidity function (parameters in the rule block, recorded in every run's output); tax the lab's FIFO book with the S81
  amendment A2 loss carry-forward, the rates and the exemption READ from the tax engine's dated rows (`swing_study.tax_params()`), today's rows applied to the whole window (the lab's
  stated rule: the law then was different; it penalises long holding in every arm alike); lots are long-term when held MORE than 12 calendar months.
* **Index arm.** The whole capital in the index ETF security at the first signal (the first month-end of the window, filled the next session), held to the end. Harvesting OFF versus ON.
* **Stock book (arms A-stocks and B).** Selection at the first signal, point in time: the 20 shares with the largest median traded value over the 250 sessions up to that signal, among those
  with at least 300 sessions of history and a price that day (no sector or quality screen; ties by key). Sizing: weight proportional to 1 / the share's volatility (standard deviation of
  its daily log returns over the 250 sessions up to the signal), each at most 10% of the book, the excess handed to the others, as the lab's `cap_and_fill`; the sector rail (25%) as the lab
  applies it. The book is bought once, **never rebalanced, no replacement of a name, no new money**; a name that is stopped, or whose weight drifts above a rail, is left to the rules
  of its arm (a stop sells; nothing is trimmed in the study). Cash left over earns the cash rate. Survivorship caveat: the names are chosen at 2005 from a panel built from names that exist
  in the data, so a name that later failed and left the data is not in the pool (the panel holds the 600 most liquid by median traded value over the whole history): this flatters the book
  in every arm alike and flatters the stops arm LESS than it would have, because a failed name is exactly what a stop is for.
* **A-stocks mechanics:** the monthly-cadence machinery of `lab/swing.replay_daily(cadence="monthly")`, with a policy that at the first signal returns the section 3 weights and at every
  later month-end returns the book's own current weights (no trade); harvesting is the replay's own switch.
* **B mechanics:** the daily-cadence machinery of the same file: at the first signal day only, one entry per selected name (weight as above, `max_positions` 20, `max_new_per_day` 20,
  `entry_fill` close); the entries carry their exit levels; no later entries (no re-entry after a stop). Arm WITH stops: stop = fill x (1 - d), `d = clip(2.0 x sigma x sqrt(63 / 252),
  0.12, 0.35)`, `sigma` = the name's annual volatility (std of the daily log returns over the 250 sessions up to the signal, x sqrt(252); 0.30 if under 60 sessions), the level fixed at
  the fill (the live exit plan's rule, `core/exits._levels`); no target, no time stop. Arm WITHOUT: no stop. A stop fills at the stop (or the open if it gaps below) less slippage, the
  proceeds stay as cash earning the cash rate, the tax of the sale is paid by the FIFO book, nothing is bought back. Harvesting is OFF in both arms (the live default).
* Measures of every arm: after-tax-and-charges value path; the **liquidation value** (everything sold at the last close with charges and the tax on that sale in the last financial year's
  books; this stops deferral of tax from looking like a gain) and its CAGR `L`; the worst fall `D` of the value path (peak to trough, after tax and charges, cash included); tax paid;
  charges; slippage; number of sales. For claim A also the **liquidation-marked path**: each session's value if everything were sold that session (the same function), so that a
  harvest, which only changes the tax OWED later, shows up on the day it is done.

## 4. The rule in code (fixed now): `lab/c4_study.RULE`

```json rule
{
  "history": ["2005-01-01", "2017-12-31"],
  "final_window_used": false,
  "capital": 1000000,
  "cash_rate": 0.065,
  "bootstrap": {"block": 21, "resamples": 5000, "seed": 82},
  "stock_book": {"n_names": 20, "turnover_window": 250, "min_history": 300, "vol_window": 250, "max_weight": 0.10, "rebalance": "never", "max_positions": 20, "max_new_per_day": 20},
  "stops": {"sigmas": 2.0, "horizon_days": 63, "vol_window": 250, "min_pct": 0.12, "max_pct": 0.35, "fallback_vol": 0.30, "target": "none", "time_stop": "none"},
  "slippage": {"half_spread_base": 0.0005, "half_spread_cap": 0.005, "turnover_ref": 100000000, "impact_y": 1.0, "sigma_window": 20, "sigma_floor": 0.005},
  "harvest": {"window_months": [1, 2, 3], "fill_fraction": 0.98, "round_trip_cost": 0.004, "guard_days": 30, "lt_months": 12},
  "claim_a_pass": {"min_dL_per_arm": 0.0005, "tax_saved_must_exceed_extra_costs": true, "min_t_vs_off": "counter.t_needed(N after registration)"},
  "claim_b_keep_stops": {"min_worst_fall_cut_relative": 0.20, "max_return_cost_per_year": 0.01},
  "switches": {"a_index_pass": "[exits] harvest_core = true", "a_stocks_pass": "[exits] harvest_longterm = true", "b_fail": "[exits.longterm] stop = false"}
}
```

**An arm of claim A passes if ALL of these hold,** on the history window:
1. `dL = L(harvesting) - L(no harvesting) >= +0.05` percentage points a year;
2. the tax saved (tax paid plus the tax of the liquidation, without minus with) is more than the extra charges plus extra slippage paid with harvesting (so the gain is not just cheaper
   deferral eaten by costs);
3. the paired block-bootstrap t of the daily return difference of the two LIQUIDATION-MARKED paths (with minus without; block 21, 5,000 resamples, seed 82; t = mean difference / standard
   deviation of the resampled means) is at least the learner's bar `counter.t_needed(N)`, N being the counter's N after these three tests are registered (the bar rises with N).
   Why a single path needs a t at all: harvesting is tested on ONE historical path, so a gain could be the luck of that path's particular prices and exemption years; the bootstrap asks
   whether the difference between the two paths is distinguishable from the path's own day-to-day noise, with blocks to keep its autocorrelation. It cannot make one path many; it is
   stated as a necessary condition, and the single path is a limit (section 7).
Otherwise the arm FAILS: harvesting stays OFF for its sleeve.

**Claim B: the stops are KEPT if BOTH hold:** (1) the worst fall WITH stops is at most 80% of the worst fall WITHOUT (a cut of at least 20%, relative); (2) `L(without stops) - L(with
stops) <= 1.0` percentage point a year (the stops cost at most 1 point a year of return after tax). Otherwise they FAIL and are switched off for the longterm sleeve
(`[exits.longterm] stop = false`; a risk exit by thesis break, the rail trims and the fall gauge stay). Both numbers (worst fall with and without; yearly return after tax with and without)
are reported in plain words.

## 5. Counting

The three registrations above are three tests in the learner's counter (the bar for every later test rises). Claim A's arms are scored through the paired t against `counter.t_needed(N)`;
claim B is a stated decision rule on two figures (no t: it is a risk-control decision, not a claim of excess return). Nothing else is wired live on this study.

## 6. One run

`lab/c4_study.run` runs once, in the Docker sandbox (the lab runner's `mode: "c4"`), on the real panel; its result goes to `docs/research/c4_study_results_s82.json` and is written onto a store by
`apply_recorded` once. A rerun with changed parameters is a new registered study.

## 7. Limits, stated before the run

Adjusted daily bars (a stop is checked on the low, a same-day stop and target is taken as the stop; a stop may fill at the open on a gap below it); survivorship in the 600-name selection (see
section 3); today's tax law applied to 2005-2017 (the law then was different); dividends are inside the adjusted closes (their tax is not modelled); one decade of one market and ONE path;
Rs 10 lakh of capital (a larger book makes the yearly exemption a smaller share of its gains: harvesting would then help less); the stock book's 20 names are not the live book's names;
the stop is applied to a book bought on one day, not to purchases spread over time; the harvest rule's costs (0.40% round trip) and the slippage function are assumptions, not measurements;
the stops arm does not model the thesis-break sale (it needs event data the panel does not hold), which the live book keeps either way.
