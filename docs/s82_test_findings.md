# S82 test findings (2026-11-12 night, written by the coordinator)

Step A (test everything, no fixing) was run on the integrated tree `pm/s82-gaps` after each agent's branch was merged; the problems below are all of them. Every one has a root-cause fix and a test.

| # | where found | problem | cause | fix |
|---|---|---|---|---|
| 1 | full suite (3,252 collected, 3,250 passed) | `tests/test_s65_sync.py::test_built_md_lists_every_job_and_every_brain_tool` failed | the new job `fills_calibrate` was not in `docs/BUILT.md`; the BUILT text still described the deleted waves, sentiment, volume-profile and `construct` code | BUILT.md rewritten for S82 (job rows, deleted features, the S82 section) |
| 2 | full suite | `tests/test_s81_us.py` expected gold to be OUTSIDE the premium rail by default | C1 puts gold in the rail by default | the test now asserts gold is held to the rail by default, that a narrower setting leaves gold alone, and that a gold ETF under the limit may be bought |
| 3 | accelerated drill (10 sessions, India and US) | step `exit_plan_fires` failed: no stop fired after a 45% fall | C4b's registered verdict switched the longterm stop OFF, so the drill that proves the stop machinery had no stop | the drill switches the stop on for its own run (the shipped config is unchanged) |
| 4 | accelerated drill | step `session_replay` crashed: `TypeError` in `exits.open_plan` | REAL BUG: an explicit stop (an override) on a sleeve with no risk-sized stop has no `stop_pct`; the plan's note formatted `None` as a percentage | `exits._stop_words` works the distance out from the price and says "set explicitly"; regression test `test_an_explicit_stop_opens_a_plan_even_when_the_sleeve_has_no_risk_sized_stop` |
| 5 | merges | conflicts in `app/world.py` (job list), `tests/test_s79b_construct.py`, `construct/run.py` (deleted by one agent, edited by another), `core/state.py` (two hooks) | parallel agents | resolved keeping both sides' intent; the full suite ran after |

Not a problem but worth saying: the harvesting step of the accelerated drill is OFF ("no harvesting sale decided"): harvesting is OFF in the live book (A60, and the C4a study failed for both arms), so the step has nothing to do.

## Drills (S81's 14, on the S82 tree)
smoke, kill_switch, off_fri_mon, off_10_days, ollama_down, docker_down, kite_logged_out, budget_exhausted, failing_champion, kill9, accelerated_long, probation_withdrawn, net_down: PASS on the first run; accelerated: FAIL on the first run (items 3 and 4), PASS after the fixes (10 steps, one OFF as above).

## The S82 scenarios of the brief, and the test that proves each (synthetic stores unless said)
- a fresh store's first open opens the US account by a transfer; rupee cash falls by the same rupees, the whole book is unchanged but for the markup: `tests/test_s82_us.py` (and the real path on a copy of the real store: Rs 56,161 transferred, SPY ordered, filled at the next open, whole book Rs 1,123,220 to Rs 1,122,058 with the markup and market moves);
- SPY bought at the next US open and listed on the book card: `test_s82_us.py`, `us/report.py: holdings`, card key `us`;
- a store already opened at the 5% seed is converted without losing a row, idempotent, also at the S81 schema: `test_s82_us.py`;
- off 3 days then the US catch-up runs once per US session: `test_s82_us.py`;
- the index fallback adopted with the sub-book's share and the 40% stock sleeve kept; an old S81 index-only target repaired: `tests/test_s82_lab.py`;
- a gold ETF above its premium limit gets no new buying; a gold ETF under it may be bought: `test_s81_us.py`; real premium of GOLDBEES on 2026-11-09 was 0.2%;
- a 60% broad-index position is allowed and a 40% non-broad ETF is trimmed; JUNIORBEES capped at 35%; the lab's replay agrees: `test_s82_lab.py`;
- harvesting off live: `test_s81_exits.py` (defaults off, per-sleeve switch); a longterm stop per C4b's verdict (off): `test_s82_lab.py`, the shipped config;
- a filing with no release time read by the thesis check the next trading day, not the same day: `test_s82_kg.py`;
- a US dividend on a real past date (SPY ex-dividend 2026-09-18, USD 1.889): checked by the `us` agent on the real bar (gross USD 18.89 on 10 shares, 25% withheld, credit Rs 449); a US split: none exists in the stored US data (history is restated), so none could be tested on a real date.
