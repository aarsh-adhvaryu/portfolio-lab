# S85 wide (L1): the wide watch, exposure through funds, "what did I miss", threshold tuning (branch s85/wide, 2026-11-13)

## What is built
1. **Wide watch** `src/pflab/think/wide.py`, switch `[think] wide_watch` (now ON). After each India close and US morning pass (`watch._india_close`, `watch._us_morning`), the Nifty 500 and the stored S&P 500 universe
   (less held and picked names) get T1's cheap signals (move 1d/5d, fall 10d, relative 1d/5d/fall, thesis event, India news burst) plus `wide_run_20d` (20 points ahead of the index in 20 sessions; case kind `missed_run`).
   Score = surprise x a labelled ranking exposure (what funds hold of it + index weight proxy x 5% of the whole book), so a held name outranks it. Only the top `wide_store_top` (60) signals are stored (`detail.wide = true`);
   at most `wide_cases_per_day` (1) new case a day; when the 3-a-day cap is full the wide name takes the place of the weakest case nobody has thought through (it goes back to `noticed`) only if it scores higher. Idempotent per name, signal, day.
2. **Exposure through funds** `think/exposure.py`: `fund_exposure(con, day, isin)`, `via_funds`, `index_weights`, `apply_to_scope` (hook in `watch.scope`), `case_text` (hook in `session._first_message`, and `exposure_via_funds_inr` in a signal's detail).
3. **What did I miss** `think/missed.py` + job `think_missed` (`service/tasks_s79_think85.py`, after `think_loop`, switch `missed_job`): rows in `think_misses_s84` (kind = cap / outside_scope / below_threshold / no_event, detail JSON with the threshold that would have caught it); `missed.summary(con, day, days=7)`.
4. **Bounded tuning** `think/tuning.py`, switch `tune_thresholds` = **false (OFF)**; Amendment A2 added to `docs/protocols/s84_thinking_live_protocol.md` (registered as `s84:thinking_live_a2`, `learner/s84.register_thinking_amendment_a2`, called at app start); override table + `think.settings()` reads `PFLAB_PM_DIR/think_overrides.json` (a copy of the table, bounded again at read).
Migrations 270-272 (`pm/mig_s79/m_wide85.py`): `think_tuning_s84`, `think_overrides_s84`, `think_wide_runs_s85`.

## Decisions (2026-11-13)
- No fund holdings data exist beyond the store's `fund_holdings` (AMC files; empty in the system account) and index MEMBERSHIP files without weights. So index ETF weights are a PROXY: India = free-float market value (shares x (1 - promoter) x last close, shareholding lag 21 days); US = 60-session median dollar traded value of the stored universe (today's members: survivorship-biased); Nifty 50 / Next 50 = ranks 1-50 / 51-100 of the Nifty 100 by that proxy. Labelled everywhere. Gold and unmapped funds count as zero and are listed in `uncovered`. Fund-to-index map: `exposure.FUND_INDEX` (MONIFTY500, NIFTYBEES, JUNIORBEES, SPY), overridable by `[think] fund_index`.
- The `wide` flag lives in the signal's detail JSON (no new column on the hot table `think_signals_s84`).
- "No event" = in scope, nothing in the graph and under half of its line; "below threshold" = at least half of its line (or an event) and the threshold that would have caught it is stored; only these feed tuning.
- False alarm = a case closed "quiet for N sessions".
- Tuning OFF by default (coordinator). Even when on: gate 40 scored decisions or 60 misses, one threshold a week, step <= 10%, band [0.5x, 2x] of config, no lowering while cases/day >= 90% of the cap, revertible (`tuning.revert`).
- The job registers itself on `ondemand.AFTER/MAX_AGE_H` and `world.GROUP_OF` at import (no edit of those files); the coordinator may fold the lines in.

## Shared files touched
`think/watch.py` (scope hook, `_wide` helper and two call lines, `_merge` carries `wide`, signal detail gets `exposure_via_funds_inr`, "not built" message removed), `think/session.py` (4 lines in `_first_message`), `think/__init__.py` (`settings(raw=False)`, `overrides`, `write_overrides`), `learner/s84.py` (A2 registration, `protocol_ok`), `app/runtime.py` (one line: register A2), `configs/core.toml` `[think]` keys, the protocol file (Section 9). No `core/*`, `us/*`, `llm/*`.

## Tests
`tests/test_s85_wide.py` (25): wide signal/idempotence/stale bar, one wide case a day, cap and demotion, held outranks wide, switch and failing pass, run signal, fund arithmetic by hand, uncovered gold, index proxy, scope/stand-in, case text, first message, miss reasons and would-catch, event vs no event, job once per session, job registration, tuning gate/step/band/rhythm/revert/false alarms/cap binding, override file, status, protocol block pinned to `tuning.RULE` and registration. Related suites run green (test_s84_*, test_s79_register, test_s64_counter, test_s67_world, test_s81_ondemand, test_service, test_s70_jobs, test_s58_run_now, test_s83_score).

## Real path (copy of the app store, data folder read only)
India wide pass over 499 Nifty 500 members on the stored bars: about 3.5-4.5 s (limit 60 s); 91 signals found, 60 stored, 1 case (a thesis event on a large member). Missed job: about 1-3 s a session; over 12 sessions: 190 misses (134 outside scope, 47 cap, 8 below threshold, 1 no event). US pass 2.9 s on the last full day of the data folder (2026-10-27: the folder's US bars are stale, the app's are fresher). Names only in `D:\s85_scratch\wide\`.

## Exposed for screens
`exposure.fund_exposure`, `exposure.via_funds`, `wide.wide_text(con, day)`, `missed.summary(con, day, days)`, `tuning.status(con)`.

## Lines for the coordinator
BUILT.md job row: `think_missed` | after `think_loop`, or no run in 20 h | big movers the loop did not notice with reason and would-catch threshold; weekly bounded tuning (OFF) | `think/missed.py`, `think/tuning.py` | skips when `[think] missed_job = false`. CLAUDE.md/PLAN: Amendment A2 (tuning, OFF), `wide_watch` ON.

## Not verified
Live US wide pass on fresh bars; tuning on real scored cases (none exist yet); the effect of the wide case on the real thinking session (gateway not run).
