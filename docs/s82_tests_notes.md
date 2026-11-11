# S82 tests agent: notes (2026-11-11)

Task: after commit 1960e33 (A60: the swing sleeve is deleted from the live paths, split 60/40, harvesting OFF per sleeve, gold in the premium rail) the S81 and S80 suites that exercised
the deleted behaviour are rewritten onto behaviour that still exists. Rule followed: no test turned green by skipping, weakening or stubbing; a test is deleted only when it tests code that
is gone, and each such deletion is listed below with its reason. The five protected engine suites are untouched.

## Decisions (2026-11-11)
- The swing entry (`session.add_trigger`) is replaced in tests by the two entries that remain: a TACTICAL VIEW carried out in session (`core/views.issue` -> `_views_in_session`, kind `view`) and a
  QUEUED BUY (`session_queue_s81`, kind e.g. `rebalance`). Both go through the same `session.timing` rules (first 15 minutes, VWAP band, thin volume, no minute bars).
- The session no longer opens exit plans. A test that needs a stop gives the position its plan with `core.exits.open_plan(...)` right after the fill (helper `plan_after_entry`, an
  `on_step` hook of `session.replay`) or, for the fallback path (`no_exits` fixture), writes a row in `session_exit_fb_s81` (helper `fb_plan`, the fallback code `_fb_orders` stays and stays tested).
- The queue test of the same-day round trip now runs on the fallback path (the real exit manager holds a same-day target itself, in `exits._sell`, and queues nothing); a new test covers the
  real exit manager's behaviour (target held, plan stays open, sells at the next session's first step).
- Harvest mechanics tests switch both sleeves on with a `harvest_on` fixture (patches `exits.settings`); a new test pins the defaults (both off) and the per-sleeve switch.

## Rewritten (what each proves now)
tests/test_s81_session.py
- `test_a_stop_hit_mid_session_...`: plan from the fallback table through `fb_plan` (was `session._fb_open_plan`).
- `test_no_same_day_round_trip_...`: the buy kind is `view` (was `swing_entry`); same guard proved.
- `test_a_swing_entry_fires_on_its_trigger_only_after_the_first_15_minutes_and_near_vwap` -> `test_a_view_entry_waits_out_the_first_15_minutes_and_fills_near_vwap_and_its_stop_plan_opens`:
  first-15-minutes rule, fill worse than quote, plan opened by `exits.open_plan` after the fill, view carried out once, 74 steps.
- `test_a_swing_entry_waits_when_the_price_is_away_from_vwap_or_the_volume_is_thin` -> `test_a_view_entry_waits_...`: VWAP band and thin volume, view stays un-executed.
- `test_with_no_minute_bars_an_entry_waits_and_says_so`: on a view.
- NEW `test_a_queued_buy_waits_for_the_timing_rules_too`: the other entry that remains (a queued buy) waits on the VWAP band, then fills at 09:30 and is marked done.
- `test_a_same_day_exit_is_held_to_the_next_session_unless_its_stop_fires`: view entry + fallback plan (target 110): held by the guard, queued to Tuesday, sold at 09:30 at that quote.
- NEW `test_the_exit_manager_holds_a_same_day_target_itself_and_sells_it_at_the_next_sessions_first_step`: same with the real exit manager (nothing queued; the plan stays open; the target sells at
  09:20 Tuesday: a target is not a "late kind").
- `test_a_stop_on_the_day_of_entry_fills_and_the_day_is_flagged`: view entry + `exits.open_plan` stop 97; the stop fills and the day is flagged.
- `test_the_circuit_breaker_stops_every_buy_in_session`: on a view.
- `test_the_preopen_plan_has_the_conditional_orders_...`: the trigger order is replaced by the tactical view's line; 4 orders (stop, target, time stop from the fallback plan, view); asserts no "swing" word.
- `test_the_1545_report_...`: plan line "1 view", fill "CCC (view)", held to next session, waited, 15 lines or fewer.
- `test_today_shows_one_compact_session_card`: a view instead of a trigger.

tests/test_s81_exits.py
- `test_open_plan_swing_defaults_and_overrides_and_adding` -> `test_open_plan_longterm_defaults_and_overrides_and_adding` (longterm: a stop, no target, no time stop; override keys still work).
- NEW `test_a_stored_swing_tag_gets_the_longterm_levels_and_there_are_no_swing_defaults` (no `DEFAULTS["swing"]`, no `swing_score`, a `swing` sleeve argument reads as longterm).
- `test_target_and_time_stop_each_fire_once`, `test_a_name_bought_today_waits_...`: the plan is opened in longterm with the levels the swing sleeve used to default to given as overrides.
- `test_record_laplace_rate_only_from_twenty`: sleeve tag `longterm`; the `swing_score` lines are removed (see deleted).
- harvest tests (6): `harvest_on` fixture. NEW `test_harvesting_is_off_by_default_and_each_sleeve_has_its_own_switch`.

tests/test_s81_core_lab.py: swing shares removed (60/40 split, `swing` accepted only as zero by `check_proposal`, `set_sleeve("swing")` raises, a legacy `swing` row reads as longterm, the first message
no longer says "swing <= 20%"); NEW `test_the_held_names_are_bought_only_up_to_longterm_buy_pct_...`; the default target test is now 60/40/10/10.
tests/test_s81_drills_fixes.py: `test_a_swing_trigger_stop_and_target_become_the_exit_plans_levels` -> `test_a_plans_own_stop_and_target_become_the_exit_plans_levels` (a view entry then `exits.open_plan` with `stop`/`target` overrides; the override keys are the drill's finding).
tests/test_s81_drills_harness.py: the step name `swing_opened_closed_scored` is now `view_entry_exit_closed`.
tools/drills_s81.py: `step_swing` -> `step_view_entry`; the `session_replay` drill brings its third name in with a second tactical view and opens the plan with `exits.open_plan` through the replay's `on_step`;
the `propose_allocation` drill uses sleeves {core 60, longterm 40}; the `swing_score` note is gone.

## Deleted (code gone)
- `test_swing_score_with_few_sales_does_not_grow` (tests/test_s81_exits.py): tested `exits.swing_score`, deleted in A60.
- the `exits.swing_score(...)` assertions inside `test_record_laplace_rate_only_from_twenty` (grow True/False): same function. The `record()` assertions in that test stay.
- no test was deleted in test_s81_session.py: every swing-entry test was rewritten (the trigger-specific part, "the trigger is armed/fired", went with `add_trigger`).

## Still failing / owned by others
Verified green on this branch (commit below): tests/test_s81_session.py, test_s81_exits.py, test_s81_core_lab.py, test_s81_drills_fixes.py, test_s81_drills_harness.py, and (run once before and
after, no change needed) test_s80_core.py, test_s80_advisors/lab/lab_promotion/lab_service/screens/story/strategist/tactical.py, test_s81_loop_exits/loop_probation/kept_behaviour/autonomy/ondemand/swing.py
(first run: 171 passed, the 22 failures were all in the five files above and are fixed). Not run (owned by others): test_s81_us.py, test_s82_*.py, kg and fills tests, `lab/alloc_lab.py` /
`core/rails.py` 60% limit tests. Nothing in my files fails because of their work: no failure was left for another agent, and no test depended on the premium default
(`test_the_rail_can_be_extended_to_gold_by_a_setting` is not in the S81/S80 files I ran).
Not exercised: `tools/drills_s81.py` itself (the accelerated drill needs the full harness run; the harness unit tests pass and the `session_replay` rebuild follows the same calls as the session tests,
but the drill's end-to-end run is for the coordinator).
Shared files touched: none (tests, tools/drills_s81.py and this note only).
