# S84 agent `drillfix`: the two base drills `accelerated` and `accelerated_picks` green again

Branch `s84/drillfix` (worktree `D:\s84_wt\drillfix`), based on `pm/s84-thinking`. Only `tools/drills_s81.py` and `tests/test_s81_drills_harness.py` changed. Nothing in `src/`, `configs/`,
`docs/PLAN.md`, `docs/BUILT.md` or `CLAUDE.md`. The failures were found by the replay agent (`docs/s84_replay_notes.md`, finding 9); both were drill assertions that still described the S82 world
(share 40%, a proposal that may change the longterm share), not product bugs.

## What was wrong and what changed (2026-11-12)

1. **`allocation: BinderException: Referenced column "open" not found`** (every drill's strategist job). Cause: the lab's replay panel (`lab/runner.build_panel(extras=True)`, read by
   `alloc_lab.tick` through `service.run_lab`) selects the day's `open, high, low, close` from `panel/prices.parquet`. The real panel has them; the drills' panel (`sync_data_files`) wrote only
   `close`/`adj_close`/`turnover`, so the query failed in every drill. Root fix (the fixture is the root: the product reads columns the real panel always has): the drills' panel now carries
   `open` (0.999 x close), `high` (1.004 x close) and `low` (0.996 x close), inside the replay's sane band 0.5-1.5. Regression test: `test_the_synthetic_prices_are_deterministic_and_the_data_files_hold_nothing_from_the_future`
   now asserts the columns and builds the panel with `build_panel(extras=True)` (sector and results maps stubbed: they are real data files the drills do not carry). After the fix the strategist's
   `allocation` entry carries no error in any drill (`grep Binder` over the run's files: none).
2. **`allocation_proposed_and_adopted`**. The step proposed classes gold 15 + international 10 + cash 25 = 50 with sleeves core 60 / longterm 40. Since S83 the longterm share is the picks rule's
   (`lab/tools._keep_longterm_share`) and since F1 it is 55.12% in the drill's profile (his Kite stocks' 35.1% + 20 points), so the core is 44.88% and `sleeves.check_proposal` refuses classes that
   are core holdings and add up to more than the core. The step now reads the live share (`pick_share.share(cur, "IN")`), proposes the sleeves as they are, and a class split that fits inside the
   core (equity 62, gold 8, international 10, cash 20: "more cash, less gold"). Every check of the step is kept unchanged (tool accepted, target stored, adopted by the A50 rule, verdict on record,
   active target carries classes and reasons, the loop held it at later closes).
3. **`picks_learning_book`** (the India share). Assertions rewritten to the new rule, nothing dropped:
   * old: the India share falls 40% -> 35% and rises back, two rows. New: the FIRST India row is the decision row (`pick_share.DECISION_REASON`, old 40%, new = min(60%, Kite weight + 20 points),
     figures `kind: decision`, `extra_points` 20, `reserve_points` 10; new check), and the +5/-5 rule rows that follow start from THAT share (55.1% -> 50.1% -> 55.1%). The US rows are unchanged
     (50% -> 45% -> 50%).
   * old: Today's `picks.IN.share == 0.40`. New: it equals the decision's share (within 0.1 point).
   * old: the 15:45 report says "India picks share lowered from 40% to 35%", found from the FIRST India row. The first row is now the raise of the decision, so the step finds the first LOWERING row and
     expects "lowered from 55% to 50%".
   * new checks for the reserve: `picks.ordinary_ceiling("IN", share)` is the share less 10 points (US: SPY floor and the 10-point reserve both fit), and the system's ordinary pick SYNPICK1 never held more
     than 10 points of the book (plus the 1.5-point band) on any of the 21 closes.
   Not asserted in the drill (covered by the fixa agent's unit tests, and the drill's cash is not a clean fixture): that no ordinary pick buy ever took cash below the 10-point reserve. The fixa notes
   say the baseline's core gap can still take that cash ("left for the coordinator"), so such a drill check would be asserting something that is not built.

## Results

* `accelerated`: PASS (157.9 s); `accelerated_picks`: PASS (249.1 s); the harvest step stays OFF as before (no harvesting sale in ten sessions; `harvest_core`/`harvest_longterm` are off).
* The other twelve drills: see the final report (run once after the fixes).

## Shared files touched

`tools/drills_s81.py`, `tests/test_s81_drills_harness.py` (both shared with the replay agent's earlier edits; only the lines above).

## Exposed for screens

Nothing new.
