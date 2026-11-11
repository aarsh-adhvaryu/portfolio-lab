# S83 drill notes: the accelerated integration check of the learning book

Branch `s83/drill` (based on `pm/s83-learning`). Files: `tools/drills_s81.py` (the new step, the new drill, the profile's pick names), `tests/test_s81_drills_harness.py` (3 new fast tests, the step list now names
`picks_learning_book`), `tests/test_s83_drill.py` (one regression test per bug below), and three small fixes in `src/` (below). No table, no migration, no config.

## What was added

`python tools/drills_s81.py run --only accelerated ...` now runs TWO drills: `accelerated` (the ten sessions as before; the new step is reported OFF there: "needs 20 sessions") and `accelerated_picks`
(20 sessions, India and US, a weekend and the Tue 20 Oct holiday and the Tue 10 Nov holiday inside; the standing assertions plus the new step). `--only accelerated_picks` runs the second alone (110 s).
`accelerated_long` keeps its own name (`ALIASES` in the tool). `python tools/drills_s81.py steps` lists the step `picks_learning_book`.

Step `picks_learning_book` (`step_picks`, `_picks_setup`, `_picks_tick`, `_picks_check`). The REAL strategist job, `strategist.tick`, `run_session`, the governor, the egress gate and the tools run; only the model is a
`ScriptedModel` (no network, no paid call: `hq.llm.client` returns no client until a script is armed, exactly the workshop's state, and `analyst.config` gives a cap with room). The standing "no paid call" check
now lets exactly the scripted answers through (`api rows == scripted answers`).

| when (session of the run) | what happens |
|---|---|
| 1 (Thu 15 Oct) afternoon | a script whose every call raises (the model API is down): the session must end `failed` at no cost, the book and the picks unchanged, and Today (`/api/core`) says "no picks yet: <reason>; the book holds what it holds" |
| 2 (Fri 16 Oct) morning | session 1: names SYNPICK1 (India) and UPICKA (US) with theses and break conditions, and SYNTHIN1 (India) that trades under the Rs 5 crore floor; the S82 first session and the S83 first picks are ONE session |
| 7 | synthetic share judgments (60 sessions of record cannot exist in 20): India behind -> 40% to 35%; a new pick is refused while it shrinks; nothing is sold |
| 9 (Wed 28 Oct) | five picks have a one-month score (horizons shortened to 7 days a month in this run): a batch with no `learned_from` is refused; session 2 withdraws SYNPICK1 (fresh lots), SYNFMCG1 (his stock, a lot 11 months 3 weeks old: inside the 12-month guard) and SYNCAPG1 (same, plus a thesis-break filing on 30 Oct) and skips SYNPICK2; its note carries `learned` |
| 12, 13, 17 | India ahead -> back to 40%; US behind -> 45%, ahead -> 50%; session 3 withdraws the US pick |
| 16 (Fri 6 Nov) | the index fallback (`adopt_index_only`) is adopted: both picks sleeves, their shares and positions stay as they are |

Two of his Kite stocks get a lot bought 11 months and 3 weeks ago (the seed events' dates are changed at the source and the lots re-derived: the lots are derived from the events, an `UPDATE lots` is overwritten).
The pick names, a synthetic US stock with bars and volume, and a thin name are part of the profile (`PICK_STOCKS`, `US_PICKS`; the benchmark is still made from the original names only, so the other drills' numbers do
not move; a test pins that).

## What the drill proved (44 checks in the step, all PASS on the last run; `D:\s82_scratch\s83drill\report.json`)
* A failed strategist session leaves the book unchanged; Today says "no picks yet: ..." until a pick exists, and not after.
* The first picks session (both once-only keys move together), the refusal of a name under the liquidity floor with the reason, a pick per market with thesis and break condition.
* The India pick: proposed -> buying -> held, bought inside the caps (one order: the room under the 40% share was 3% of the book, the Kite stocks fill the rest); the US pick: bought on two US sessions, each fill at that
  session's open plus the slippage; SPY at least 30% of the sub-book on every day; the stock at most 10% (a drift inside the 1.5-point band is not traded).
* Withdrawals: a fresh pick (lots far from 12 months: the guard does not apply) is sold at the next close; his stock inside the guard waits 5 closes, then is sold the day the guard lets go; a thesis break sells a
  withdrawn stock inside the guard at once; the US pick is sold at US opens through the sub-book's caps.
* A pick is never sold to reach a share: every sale of a pick or of one of his stocks was the exit manager's, for a reason; a new pick is refused while the share shrinks; the share rule +5 and -5 in both markets as dated rows.
* The scorecard: a pick scored after tax, a sale scored against holding, a skip scored on price only; `learned` required and kept; the strategist's message and the book card carry the scorecard and the PICKS section; the
  15:45 report tells the lowered share; the stress rows are stored for the three scopes.
* The index fallback leaves both picks sleeves, their shares and positions untouched, and no rebalance trade touched a pick afterwards.
* No error logged by pflab, no unhandled exception, no failed job, no close that fell back from its picks part, 6 scripted answers and no real call.

## Findings (real bugs in S83's code, each fixed at the root with a regression test in `tests/test_s83_drill.py`)

1. **A withdrawn US pick was never sold whole: dust stayed for ever** (`us/policy.py check`, the US wiring of A62/L3). Three ways the same stranding: (a) the turnover cap scales a full exit to a share (97%) and
   the rest is under USD 25; (b) a name wanted at zero but inside the 1.5-point band is skipped "within the band"; (c) a sale under the minimum trade or whose charges are over 2% of it is skipped. Seen in the drill:
   UPICKA withdrawn, sold on two sessions, 0.043 shares left in the sub-book and the pick kept in the picks' managed list. Fix: a name wanted at zero (a full exit) skips the band, the minimum trade and the cost filter,
   and when the cap scales it so that what is left is under the minimum trade it goes whole. Tests: `test_a_turnover_cap_that_would_leave_dust_...`, `test_a_cap_that_leaves_more_than_the_minimum_trade_...`,
   `test_dust_of_a_withdrawn_pick_left_by_an_earlier_session_...`.
2. **The stress scenarios stored 0.0 when no holding had a figure** (`core/stress.py _scenario_result`, the score agent's L7). A holding with no own history and no market series for the window adds no loss, so the
   whole-book fall came out 0.0, which reads as "this scenario does not hurt". Seen: every India and whole-book row for 2008, 2020 and the AI bubble was 0.0 on a profile with no history for those windows. Fix: the
   scenario carries `coverage_pct` and `value_without_figure_inr` (stored in the detail and returned by `stress.latest`), and `book_fall_pct` is None when no holding has a figure; a partial figure keeps its number
   with the coverage beside it. Tests: `test_a_scenario_no_holding_has_a_figure_for_...`, `..._part_of_the_book_...`, `test_the_stored_row_and_the_reader_carry_the_none_and_the_coverage`.
3. **The PICKS text ran two sentences together and under-stated what the sleeve holds** (`core/picks_card.py`, the strategist's own reading). "Thesis: held from his Kite portfolio Breaks if: ..." (no full stop), and
   "the picks hold 35%, no room left" when his stocks and the picks held 36.7% of a lowered 35% share (the figure was share minus room, floored). Fix: a thesis line ends like a sentence; the text and the block carry
   `holds` (the real weight) and say "(they hold more than the share: nothing is sold to reach it)". Tests: `test_the_thesis_line_ends_with_a_full_stop_...`, `test_the_card_says_what_the_sleeve_really_holds_...`,
   `test_the_block_built_from_the_store_carries_what_the_sleeve_holds`.

## Observed, not changed (his or the coordinator's decision)
* **The US build eats the month's turnover cap, so a US pick named in the same month waits for the next month.** The sub-book's first tranches buy about 95% of it; `us/policy.check` counts them in the 40%-a-month
  cap, so UPICKA (named 16 Oct) was first bought on 2 Nov, and a pick withdrawn in that month would not be sold until the next either (the rupee book's exit sales are exempt from its caps; the US has no exit
  manager, so its sells are not). Fix, if wanted: leave the funding purchases of a deploying session out of `_month_traded` (S82's design, not changed here).
* The strategist's first message carries the scorecard and the PICKS section twice: once inside the book card, once fresh from `picks_card.build`/`scorecard_text`. About 3,000 characters of the 11,000 in session 2
  (one call's tokens, priced as every call is). Left because the fresh copy is the point of L3 and the card's copy is the card's.
* A pick is scored from the day it is named (the scorecard's start is the first session after), also while the US pick is still 'proposed' and unbought for weeks (UPICKA showed "+1.9 points at 1 month" with 0% held).
  By design in `core/pick_score.py` (decision 1 of the score notes); it flatters or punishes a name the book has not held.
* The India pick was one order of Rs 22,000 to 34,000 (2 to 3% of the book): the Kite stocks fill the 40% share, so the room is small and one order reaches it. "Bought over several sessions" is shown by the US pick (two
  sessions, scaled by the cap), not by the India one; the daily and monthly caps held in every case (the standing check).
* The stress profile of the drill has no 2008, 2020 or 2000-02 history, so those scenarios correctly say "no data" (and, after fix 2, None); nothing here tests a real window (that is the score agent's real-path run).
* The 12-month guard only holds a lot within 21 days of turning long-term: a pick bought a week ago and withdrawn is sold at once at the short-term rate (as designed, shown in the drill); to see "inside the guard" the
  drill ages two of his stocks' lots.

## Not checked
* Real Opus, Docker and the real data (the drill is synthetic and scripted; L8's real path is the strat agent's copy-of-the-store run).
* A real 60-session record (the rule's judgment is driven with a synthetic record; the real `sleeve_record` is only read at the end: 20 sessions, and its figures are noted).
* The share rule's effect on buying after a raise (the room grows to 45%/50%): the India picks had already been withdrawn by then; the US raise came after the pick was at its stock cap.
* The screener tools (`screen_stocks`, `company_card`) and the SEC/Yahoo downloads (network): the drill's scripts name symbols directly.
* A US pick's split and dividend, a long gap with the app off (the off_* drills do not hold picks), the kill switch with picks.

## Tests
`tests/test_s83_drill.py` (9), `tests/test_s81_drills_harness.py` (10), and the neighbours that touch the changed files: `test_s81_us`, `test_s82_us`, `test_s83_picks`, `test_s83_strat`, `test_s83_score`.
