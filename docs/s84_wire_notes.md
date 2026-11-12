# S84 wire notes (T1/T7 wiring, Today and the 15:45 report) - branch s84/wire, 2026-11-12

## What is built
- `src/pflab/think/wire.py` (new): the one module with the logic; the loops carry only a few hook lines.
  - `session_tick(con, now, quotes, root)`: mode `session`; the watch on live quotes for held names, then the cases it opened are thought through (`think.session.think_case`); no follow-up; no quotes means nothing to watch. Never raises.
  - `sweep(con, now, root, only_market=None, think_cases=True, follow=True)`: the close (`close`, India), the US morning (`us_morning`) and the catch-up (`catchup`) in one. Every session of a market that is not yet watched and whose closes are in the store is watched in order, oldest first (all but the newest as `catchup` at that session's own close plus settle, point-in-time; the newest as `close` / `us_morning` at `now`). Then the new cases (and any open case nothing was thought about, left by an earlier pass that failed or hit the cap) are thought through, at most `[think] max_cases_per_day` in a pass, then `follow_up` once. Never raises.
  - `today_block(con, day)` (key `think` of `core.card.today_extras`), `report_lines(con, day)` (up to 3 lines for the 15:45 report), `scorecard_line(sc)`.
- `src/pflab/service/tasks_s79_think84.py` (new): job `think_loop`, the single entry for the scheduler.
- Hooks (shared files touched, all inside try/except):
  - `core/session.py`: `run_once` calls `think.wire.session_tick` when it has quotes (result in `out["think"]`); `report_day` adds `wire.report_lines` before the strategist line (the 15-line cap is kept: the lines join `tail`).
  - `core/card.py`: `today_extras` adds `think`.
  - `service/catchup.py`: after a market's scoring, `_think_sweep(con, now, root, market)` (before the US step decides, for US); the result is added to the catch-up detail as `thinking`.
  - `service/tasks_s79_us.py`: the `us_close` job sweeps the US morning BEFORE `adapter.close_us` (the US decisions).
  - `service/ondemand.py`: `AFTER["think_loop"] = ("core_loop", "us_close", "catch_up")`, `MAX_AGE_H["think_loop"] = 20`.
  - `app/world.py`: `think_loop` in the "thinking" routine group.
  - NOT touched: `core/loop.py`, `us/adapter.py`, `core/screens.py` (see decisions).

## Decisions (2026-11-12)
1. No hook in `core/loop.py` or `us/adapter.py`: the close is watched by the `think_loop` job (due the moment `core_loop`, `us_close` or `catch_up` finishes) and by the catch-up; the US morning by the `us_close` job before it calls the adapter. A hook inside `loop.run` would have run the watch a second time and before the book is marked on some paths. The coordinator can add a call to `wire.sweep(con, now, root, only_market="IN")` after the card write in `loop.run` if it wants the close watched in the same breath; the marker makes a second call harmless.
2. Once-per-session marker: a row in `paper_acts` (loop `think_loop`, text `watch <market> <day> <mode>: ...`), written only when the watch succeeded. No new table (wire has no migration range). A failed watch leaves the session unmarked and is tried again; later sessions are not watched before an earlier one that failed (order is kept).
3. First ever sweep of a market watches only its latest session (no back-fill of history); a gap is capped at the last 10 sessions (`MAX_SWEEP_SESSIONS`).
4. A thinking failure is a visible line, never a job failure: "thinking failed: <where>: <reason>" in `session_log_s81` (kind `degrade`, so the 15:45 report's "Did not run as planned" shows it) and in `paper_acts`; said once a day per (where, error class). A refusal by the workshop guard, the cap or a budget (`OutwardBlocked`, `CapReached`, `BudgetExceeded`, or "cap"/"budget" in the first 80 characters of the message) is "thinking paused: ..." and ends that pass (the next case would be refused too); the cases stay open and are thought through at the next pass. The guard and the cap themselves are enforced by the gateway and `think_case` (the model door); this module never calls a model.
5. The kill switch: `core.killed()` or `think.on()` false -> every entry returns `{"off": True}`; the job `think_loop` is disabled; `today_block` returns None. The exit manager (thesis-break sales) is untouched and keeps acting.
6. A missing think module (watch, session, recall, desk, score) is "not installed", quietly, not a failure: this branch runs before the others are merged.
7. The 15:45 report gets at most three lines (Thinking about / Reserve / what it learned = the scorecard and the knowledge line); the desk plan is on Today only. Lines that say nothing (no open case, no scored decision, no note) are left out so the report does not grow when the loop is quiet.
8. The session tick thinks only the cases the tick itself opened (a model call every 5 minutes would be wrong); the unthought ones from earlier are retried at the close.

## What is OFF
Nothing is behind a new switch: the job follows `[think] on` and `[core] kill`. Until `think/watch.py` and `think/session.py` are merged the wire does nothing (reports "the watch is not installed").

## Tests (`tests/test_s84_wire.py`, 24, fakes in `sys.modules`)
close order watch -> think -> follow-up; US morning; a gap caught up once per missed session, oldest first, at each session's own close (the NSE calendar has no session on Tue 10 Nov 2026); first sweep latest only; no closes = nothing; the daily cap and the retry of unthought cases; a failing watch (visible, unmarked, retried); a failing think step does not stop the others, the follow-up or the marker; a failing follow-up; guard/cap refusal pauses; the failure line once a day; a missing module is not a failure; the kill and think switches; the session tick (and `session.run_once` surviving a failing watch); Today block and its fallback; the 15:45 report (one line each, 15-line cap, unchanged when nothing to say); the job registered, on a world node, due after the close; the job's result; the catch-up hook; the US job hook order.
Also run green: see the final report for the modules touched.

## Exposed for screens
- `pflab.think.wire.today_block(con, day) -> {"thinking": {"open": [...], "noticed_not_examined_today", "text"}, "reserve": [text per market], "knowledge": text, "plan": text, "scorecard": text}` (also `core.card.today_extras(con)["think"]`, already behind the Today route that serves `today_extras`).
- `pflab.think.wire.report_lines(con, day) -> list[str]` (at most 3), `wire.scorecard_line(sc)`.
- Job `think_loop` detail JSON: `{"sessions": {"IN": ["2026-11-12:close"]}, "cases_opened": n, "thought": n, "thinking_problems": [...]}`.

## BUILT.md job row (for the coordinator)
`think_loop` | every 30 min, and at once when `core_loop`, `us_close` or `catch_up` has finished (or no run in 20 h) | watches every session not yet watched (India close, US morning, any gap, each once, point-in-time), thinks the new cases through up to 3 a day (paid parts inside his cap, the workshop guard), follows up the open cases | `think/wire.py` | skips when `[think] on = false` or the kill switch is set. Also listed in `app/world.py` ROUTINES ("thinking") and `service/ondemand.py` AFTER/MAX_AGE_H.

## Could not verify
Against the real `think/watch.py`, `think/session.py`, `recall`, `desk`, `score` (not merged in this branch): the wiring is tested against the contract with fakes. The contract names assumed: `watch.run(con, now, *, mode, quotes=None, root=None)` returning a dict with `signals` and `cases_opened`; `session.think_case(con, now, case_id, *, root=None)` (a returned dict with `failed` or `error` counts as a failure line); `session.follow_up(con, now, day)`; `session.thinking_text(con, day)`; `session.reserve_status(con, market, day)["text"]`; `recall.knowledge_line(con, day)["text"]`; `desk.plan_text(con, day)`; `score.scorecard(con)` with `scored`, `vs_nothing_inr`, `skips_ran`, `skips_fell`.
