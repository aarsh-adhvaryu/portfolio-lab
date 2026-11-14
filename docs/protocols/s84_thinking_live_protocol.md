# S84 item T8: the thinking loop is a LIVE test, with a safe fallback (pre-registration)

Written 2026-11-12 (afternoon) BEFORE the first live case and before the code that uses it is committed (`think/odds.py`, `think/rule.py`, `think/score.py`). The SHA-256 of this file
(line ends normalised) is stored in the learner's counter (`learn_tests`, origin `study`, note `s84:thinking_live`) when the study is registered
(`learner/s84.register_thinking_live`, called when the app starts). An amendment is dated, re-registered, and counts as new tests. ONE test is counted.

## 1. Claim

**The thinking loop's rule makes the book better off than doing nothing, after tax and charges, measured live.** A "case" is a situation the loop noticed and thought through
(a fall, a shock, a governance event, a missed run). For every decision the loop takes (the rule's option, in code, inside the rails), the result in rupees at 5, 20 and 60
sessions after the decision is compared with every option the loop did not take, and with "do nothing". The claim is one test in the learner's counter. Nothing here says the
claim is true: the loop has a safe fallback (section 6), and a verdict is claimed only under section 7. The model's words feed the rule (a class, a likelihood word, an option);
every rupee, size, price and probability comes from code (rule 8).

## 2. What is decided by whom

* The model READS and NAMES: the class (market fear / temporary / damage / unclear), what is pending, one option per name from the closed menu (sell, trim, hold, freeze, wait,
  buy in parts, nothing), and a likelihood WORD (very unlikely, unlikely, even, likely, very likely) for the worst, likely and best outcomes. It never writes a number.
* The RULE (`think/rule.py`, section 4) DECIDES and acts. The model's own choice and the rule's choice are BOTH stored (`think_decisions_s84`); where they differ the case says so.
* Both tracks are scored (section 5): the "rule track" is what the rule chose, the "model track" is what the model chose.

## 3. Outcomes in rupees (code: `think/odds.py`)

* Base rates: from the system's own stored price history and events, point in time (only closes dated on or before the day), the spread of what names with the same event kind, or
  a move of the same size and sign (names that traded at least Rs 5 crore that day, `history_min_turnover_inr`: the names the book could trade, 0.7 to 1.4 times the move, one case per
  name per two weeks), did against their index over the next 5, 20 and 60 sessions, with the count. The history is the collectors' adjusted-close panel (2004 on) with the store's own
  closes after it. Under 20 cases (`base_rate_min_n`) the loop says the count and
  falls back to the name's own range from its volatility (a zero-drift lognormal on its last 250 sessions; a name with too little history takes the stated 30% a year).
* Worst, likely and best = the 10th, 50th and 90th percentile of the move over the decision horizon (20 sessions). The "worst" is therefore a bad case (1 chance in 10), not the
  worst that can happen, and it is called that wherever it is shown. The index's own drift over the horizon is taken as zero (labelled).
* Each option is valued as the position's value after tax and charges as if liquidated at the end of the horizon, minus today's marked value: a sale realises its tax and charges now
  (the tax engine's dated rows, FIFO lots), a hold pays them at the horizon on the lots' holding period then (so the 12-month rule is respected), a new buy pays the buy charges now and
  the sale charges and the short-term tax at the horizon. A loss earns no tax credit (conservative). Trim means half the position (`trim_fraction`).
* The likelihood words map to probabilities by a table in the store (`think_calibration_s84`), starting at 5, 25, 50, 75 and 95%. The three scenario weights are the three words'
  probabilities normalised to add to one; with no words the weights are 30 / 40 / 30 (Swanson's rule for a 10 / 50 / 90 split). Expected rupees = the weighted sum.

## 4. The rule (code: `think/rule.py`, the constants are `RULE`)

```json rule
{
  "outcome_horizon_sessions": 20,
  "worst_quantile": 0.10,
  "best_quantile": 0.90,
  "base_rate_horizons": [5, 20, 60],
  "base_rate_min_n": 20,
  "default_weights": [0.3, 0.4, 0.3],
  "word_p_start": {"very unlikely": 0.05, "unlikely": 0.25, "even": 0.50, "likely": 0.75, "very likely": 0.95},
  "trim_fraction": 0.5,
  "history_min_turnover_inr": 50000000.0,
  "bet_worst_pct_book": 0.01,
  "reserve_third_per_name": 0.3333333333333333,
  "market_fall_reserve_share": 0.5,
  "parts": 3,
  "parts_gap_sessions": 5,
  "damage_wait_sessions": 10,
  "new_low_sessions": 5,
  "new_low_clear_days": 3,
  "sale_beats_holding_pts": 1.0,
  "stretched_sigmas": 2.5,
  "stretched_window": 20,
  "big_trade_share": 0.02,
  "min_bet_inr": 2000.0,
  "score_horizons": [5, 20, 60],
  "calibration_min_scored": 20,
  "calibration_step": 0.05,
  "calibration_floor": 0.02,
  "calibration_ceiling": 0.98,
  "advisory_after_scored": 20
}
```

For one name of a case, in this order:

1. **A held name, class "damage"**: a thesis break: SELL (the existing exit; a damage case is a high-severity break, which overrides the 12-month guard as `exits.guard_thesis_override`
   does). The guard's sentence is kept in the reason.
2. **A held name, class "not yet clear" with something pending**: FREEZE (no new buying of the name) and look again at the event.
3. **A held name otherwise**: the option with the best expected rupees after tax among sell, trim and hold. A sale or a trim must beat holding by at least `sale_beats_holding_pts` (1)
   point of the position's value, else HOLD. A name already held is added to only if the model chose "buy in parts" and every guard below passes.
4. **A name not held, class "damage" or "not yet clear" with something pending**: WAIT (damage: no buying until `damage_wait_sessions` (10) sessions after its pending outcome is public).
5. **New money** (a buy, an add, a dip, a missed run), class "market fear" or "temporary" only: BUY IN PARTS, only from the opportunity reserve, only if the expected rupees are
   positive AND the bad case loses at most `bet_worst_pct_book` (1%) of the WHOLE book (A66). The bet's size is that limit divided by the bad-case loss per rupee, inside the stock rail
   (10% of the whole book less what is held) and a third of the reserve per name (`reserve_third_per_name`); a size under `min_bet_inr` is REFUSED (the case waits). Three equal parts at
   least `parts_gap_sessions` (5) sessions apart; a later part only while the case's thesis holds (class still market fear or temporary).
   Guards, whatever the model says: no buying of a "damage" name until 10 sessions after its pending outcome is public; no buying while the name still makes new lows (a close that is
   the lowest of the last `new_low_sessions` (5) closes, in any of the last `new_low_clear_days` (3) sessions); a missed run: no first part on a day the name is more than
   `stretched_sigmas` (2.5) of its usual daily moves above its `stretched_window` (20)-session average (the options then are: wait for a pullback to that average, or nothing).
6. **A market-wide fall** may put up to `market_fall_reserve_share` (half) of the reserve into the core index ETF in the same three parts, under the same 1% limit.
7. A sale over `big_trade_share` (2%) of the book, and every reserve buy, passes the independent big-trade check first (called by the case session; `rule.needs_big_trade_check`).

## 5. Scoring and calibration (code: `think/score.py`)

* At 5, 20 and 60 sessions after each decision, its result in rupees against every option it did not take, from stored prices and after tax, for the rule's track and the model's track
  (`think_scores_s84`). "vs nothing" is the chosen option's result minus the result of doing nothing. Whatever is not yet 5 sessions old is not scored.
* The decision scorecard: how often the rule's option was the best of the menu, the rupees against "do nothing" for each track, by likelihood word, and "skips that ran" beside
  "skips that fell" (a name the system passed on that went on to beat its index by 20 points or more, against one that fell). A count under 20 is a count, not a rate.
* Calibration: how often each likelihood word came true (a "likely" worst, likely or best outcome counts as true when the scored result reached it). Once a word has 20 scored cases its
  probability is corrected at most once a month, a step of at most `calibration_step` (0.05) toward the observed hit rate, never outside [0.02, 0.98].
* The strategist's weekly session reads the scorecard, the misses and the calibration and writes what it learned. (S85 adds the nightly "what did I miss" job and the automatic tuning.)

## 6. The safe fallback: ADVISORY

* After `advisory_after_scored` (20) scored decisions, if the rule's track is behind "do nothing" after tax (the sum of its `vs nothing` rupees at 20 sessions below zero), the loop turns
  ADVISORY: cases still open, are thought through and are reported; only thesis-break sales act. It turns back to live when the track is ahead again (above zero). With fewer than 20
  scored the loop is live.
* The desk's spend halves while the loop is advisory from 2026-12-09 (A55's date), as T10 says.
* If the model's track beats the rule's by the learner's bar (the sum of the paired per-decision differences, a paired t at the 20-session horizon against `counter.t_needed(N)`, N counted
  after this registration), the report SAYS so. Changing who decides is his decision, never made by the code.

## 7. When a verdict is claimed (rule 10)

* Not before 60 scored decisions at the 20-session horizon. Then the per-decision `vs nothing` rupees as a share of the position or bet (a paired t against zero) are compared with the
  learner's bar for N tests (`counter.t_needed(N)`). A pass licenses saying "the loop adds value after tax". A fail leaves the loop advisory and says so in the report.
* 2022-2025 is spent and plays no part. No backtest of the loop is evidence: the replays and drills of S84 test the plumbing on real bars and scripted models and are never counted
  as out-of-sample results.

## 8. The rule is code

`think/rule.py` carries the numbers of section 4 as `RULE`. `tests/test_s84_odds.py` reads the JSON block above and compares it with `RULE`, with the defaults in `configs/core.toml [think]`
and with `think.WORD_P`. Changing a number here or there without the other fails the test; changing it after registration needs a dated amendment and a re-registration.

## 9. Amendment A2, 2026-11-13: bounded threshold tuning (S85)

Written BEFORE any code path can change a threshold. Section 5 said "S85 adds the nightly 'what did I miss' job and the automatic tuning". The claims of section 1, the measurement of section 2, the
outcomes of section 3, the rule of section 4, the scoring and the fallback of sections 5 and 6 and the verdict of section 7 are unchanged. What is added is a rule for the loop's own thresholds
(`think/tuning.py`), and it changes nothing about a decision: it changes only HOW OFTEN the watch opens a case.

**What may change.** One of the `[think]` thresholds of the watch: `move_sigmas`, `fall_pct_10d`, `rel_pts_5d`, `news_burst_x`, `storyline_jump_pts`, `market_down_20d`, `missed_run_pts`, `wide_run_pts`.
Nothing else: no rail, no size, no option, no cap on cases (`max_cases_per_day`), no number of section 4. The config file is never edited: a change is a dated row (`think_tuning_s84`) and an override
(`think_overrides_s84`) that `think.settings()` reads on top of the config.

**Evidence.** The misses (`think/missed.py`: after each close, the biggest 5- and 20-session movers of the watched universe that the loop did not notice, each with a reason class and, for
`below_threshold`, the value of the threshold that would have caught it) and the false alarms (cases thought through and closed "quiet": nothing happened).

**The rule** (the block is `tuning.RULE`; `tests/test_s85_wide.py` reads it and compares it key for key):

```json amendment_a2
{
  "step_max": 0.10,
  "band": [0.5, 2.0],
  "per_week": 1,
  "min_scored": 40,
  "min_misses": 60,
  "window_days": 90,
  "min_param_evidence": 5,
  "cap_binding_share": 0.9,
  "lower_to_percentile": 25,
  "tunable": ["move_sigmas", "fall_pct_10d", "rel_pts_5d", "news_burst_x", "storyline_jump_pts", "market_down_20d", "missed_run_pts", "wide_run_pts"]
}
```

1. **Gate.** Never on fewer than `min_scored` (40) scored decisions at 20 sessions AND fewer than `min_misses` (60) stored misses: either count opens the gate. Below both, the threshold stays at the
   config's value and the report says how many are still needed.
2. **Rhythm.** At most one threshold a week: none is changed if one was changed (or reverted) in the last 7 days.
3. **Which one.** Over the last `window_days` (90): for each threshold, its misses (the `below_threshold` misses it would have caught) and its false alarms (quiet cases whose strongest signal it
   governs). A threshold needs at least `min_param_evidence` (5) of the two together; the one with the largest |misses - false alarms| is the one changed.
4. **Which way.** Misses ahead of false alarms: the threshold goes LOWER (more cases), but only while the cases a day are under `cap_binding_share` (90%) of `max_cases_per_day` (a lower line adds
   nothing that the cap would not drop: "toward fewer misses at the same cases-per-day"), and never below the `lower_to_percentile` (25th) percentile of the values that would have caught the misses.
   False alarms ahead: the threshold goes HIGHER.
5. **How far.** At most `step_max` (10%) of its value today, and never outside `band` ([0.5x, 2x]) of the CONFIG value. A threshold already at the edge of its band is not moved.
6. **Recorded and reversible.** The row keeps what the rule saw (the counts, the cases a day) and why; `tuning.revert` puts the threshold back to its value before (the config's, or the earlier tuned
   one); the row stays, marked reverted. A reverted change counts as the week's change.
7. **Not evidence of anything.** Tuning moves a line, it does not claim an edge: the claim of section 1 is still measured on the decisions only (sections 5 to 7). The report states the date of every change, so a
   reader can set the decisions before it beside those after it.

Counted in the learner as one more test (`s84:thinking_live_a2`, `learner/s84.register_thinking_amendment_a2`); after it, `protocol_ok` compares the file with the amended hash. The tuning code refuses
to change anything until this amendment is registered.


## Amendment A3 (2026-11-14, S86; written before the first replayed decision was scored): the column `replayed_while_off`

His words of 2026-11-13: "if the system is off, it covers the backlog, aligns news, data, maths, what caused what, and uses that as a forward test: the same loop, but in fast forward."

1. **What is replayed.** After an app open that follows a gap containing at least one session of either market, the loop's rule is run over the gap by `think/fastforward.py`, point in time: an item counts from
   its publication time plus the alarm lane's own median delay, a price from the close that follows the decision, `recall` as of that moment; no live web search (today's web knows the ending).
2. **Ghost, not real.** The decisions fill `ghost_s86`, never the paper book. The live book then decides now from today's prices.
3. **A forward test.** The code that replays was frozen before the gap happened; a gap that began before the running release's own date is not replayed (that would be a backtest of code written after the data).
4. **Scored apart.** A ghost sale is scored at 5, 20 and 60 sessions after its fill (the share of the fill price the name has since fallen, pre-tax; tax is not replayed) in its OWN column `replayed_while_off`,
   never mixed with the live scorecard, and counted in the learner as one more test.
5. **Code decisions only, tonight.** Every ghost row carries `source = code` (a HIGH-severity break sells, a medium one only freezes buying). A replayed model look (at most three cases a gap, RED first) is not built;
   when it is, it is a new amendment and its rows are labelled apart.
6. **Not evidence of an edge.** The column measures whether the loop's rule, run on what was stored by the time, would have beaten waiting; it claims nothing before 20 decisions are scored.


## Amendment A4 (2026-11-14, S86b; written before any model-made or after-tax ghost decision was scored): what A3 left out is now built

1. **A model look is added.** At most three cases a gap (RED first, largest exposure first) are also read by the model at the replayed moment, through the gateway, with only what was stored by then (the headlines published by then, `recall` as of then, the closes of the sessions already over), no web, no tools, closed lists only. Its option replaces the code's for that ghost row, which then carries `source = model`, the code's own option beside it (`code_option`), the model's class and likelihood words, and its price. A replay is stored per (gap, release, name, headline) and never paid twice. The rest stay `source = code`.
2. **After tax beside pre-tax.** A ghost sale is scored at 5, 20 and 60 sessions in rupees after tax (the repo's tax rows, FIFO lots of the book): what selling at the ghost's fill leaves after tax minus what holding to that horizon and selling then leaves. The pre-tax share column stays.
3. **Still closes only.** No minute bars are stored for a gap: each step is a close; the row says so (`steps`).
4. **Same label, own column.** Both rows are `replayed_while_off`, never mixed with the live scorecard; model and code rows are counted separately in the report.
