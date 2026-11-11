# S82 a60: delete the live features whose registered study failed (A60, rule 10)

Branch `s82/a60`, worktree `D:\s82_wt\a60`, 2026-11-11 night. Rule: a live feature whose registered study failed (or was inconclusive and not adopted) is switched off and its code deleted,
unless something that passed needs it. Kept: `docs/STUDIES.md`, `docs/protocols/*`, `docs/research/*.json`, the learner registrations (`learner/s79.py`, the counter N stays), the result
tables and their migrations, `index_event_study.results/record` and the `wave_studies` tool.

## Table

| item | feature (study, verdict) | action | files deleted (lines) | tests deleted or rewritten |
|---|---|---|---|---|
| 1 | Buy zone, "wait for the zone" (S54c, fail) | the verdict no longer orders or gates: `plan/ready.py:ring` picks new names in list order (symbol), `app/research.py` watch list sorted by guard then symbol, `hold_off` drops the "above its zone" reason, `hq/picture.py` drops `in_buy_zone_and_guard_ok` and "in buy zone", `plan/pot.py:zone_numbers` no longer caps `max_buy` at the zone top (it is the stored 21-session middle), `app/views.py:_nudges` no "in zone" nudge, checklists no longer make the zone a condition of a buy, app.js note says the test failed. The zone is still shown, with its label | none (code edited) | rewritten: `test_s64_picture::test_headline_is_built_from_the_sections`. Added: `test_plan_ready::test_the_zone_verdict_does_not_order_the_ring`, `test_app_research::test_a_price_above_its_zone_is_no_reason_to_hold_off` |
| 2 | Waves, rotation flag, crude-fall events (S79b, no follow-through) | job `wave_scan` removed; `quant/waves.py`, `fcast/lens_wave.py`, tool `wave_detector`, `story/adapters.waves_items` (and the "waves" entry of `ADAPTERS`, the `wave_scan` links in `service/ondemand.AFTER` and `app/world.ROUTINES`) removed; `index_event_study.event_list/va_frame/run_test` removed. Macro attribution (passed as description) stays: its job moved to `service/tasks_s79_macro.py`, its tool to `hq/tools_s79/t_macro.py`, its switch to `quant/macro_attr.settings()/is_on()` (config key `[waves]` kept: `on`, `backfill_sessions`). Tables `wave_flag`, `wave_stats` stay | `quant/waves.py` 596, `fcast/lens_wave.py` 8, `tools/run_wave_studies.py` (study driver, run once), wave part of `t_waves.py` and `tasks_s79_waves.py` | `tests/test_s79b_waves.py` renamed `test_s79b_macro.py`: the wave, rotation, crude-fall, lens, flag-store and wave_detector tests deleted (they test deleted code); macro-attribution tests (5) and the tool/job/flows tests kept and rewritten onto `t_macro`/`tasks_s79_macro`/`macro_attr.settings` |
| 3 | Sentiment and themes tone (S79b extreme sentiment, no follow-through) | job `sentiment` (nightly LOCAL-MODEL tagging step included), package `sentiment/`, tools `sentiment`, `theme_exposure`, `event_calendar`, `lens_sentiment`, `configs/themes_s79b.toml`, `[sentiment]` of `s79b.toml`, `ondemand` and `world` entries deleted. Readers outside tools/lens checked (`data/`, `kg2/`, `story/`, `plan/`): none (only `index_event_study.event_list`, deleted). `risk/themes.py` untouched. `data/gdelt_s79b.py` and the `data_s79b` job stay (data; also feeds the old KG). Table `sentiment_s79` etc. stay | `sentiment/` 9 files 1,490 lines (calendar 217, compute 211, exposure 261, fear 72, lens 94, positioning 163, themes 99, tone 281, `__init__` 92), `service/tasks_s79_sentiment.py` 78, `hq/tools_s79/t_sentiment.py` 182, `configs/themes_s79b.toml` 153 | `tests/test_s79b_sentiment.py` deleted whole (tests of deleted code) |
| 4 | Volume profile value area / POC migration (S79b, no follow-through) | deleted rather than switched off (nothing else read it): `quant/volume_profile.py`, tool `volume_profile`, `lens_value_area`, the two sentences in `hq/explain.py` (`EXTRA_TOOLS` is now empty), `[volume_profile]` section, `index_event_study.value_area_study/poc_migration_study` | `quant/volume_profile.py` 694, `hq/tools_s79/t_volume.py` 86 (its `lenses` tool moved to `t_lenses.py`) | `tests/test_s79b_volume.py` deleted whole; in `test_s79b_lens.py` the 4 `lens_value_area` tests deleted; in `test_s79b_studies.py` the 6 value-area and POC tests deleted |
| 5 | `construct` advice (S79b 18A, inconclusive, not adopted) | deleted `construct/run.py`, `construct/optimiser.py`, `hq/tools_s79/t_construct.py` and the study driver in `construct/compare.py` (now only `clean`, which `lab/runner.py` imports). `construct/__init__.py` keeps the protocol hash and the counter row (`register`, `registered_sha`, `protocol_ok`), no switches. `risk.py` and `costs.py` kept (read by `core/state.py`, `core/card.py`, `lab/runner.py`). `[construct]` removed from `s79b.toml` (nothing read it any more) | `run.py` 405, `optimiser.py` 181, `t_construct.py` 61, `compare.py` 392 -> 24 | `tests/test_s79b_construct.py` cut to 7 tests: risk (3), costs (1), registration idempotent (1) kept; optimiser (9), live path (7), tool (3), comparison (5), adoption (2) deleted with their code; added `test_a_changed_protocol_is_seen_by_the_record_check`, `test_clean_removes_a_data_break_from_the_path_and_leaves_normal_moves` |
| 6 | The three shadow lenses | gone with 2-4. `fcast/plugins._BUILTIN = ()` (no lens named). Framework `fcast/plugins.py`, its call sites in `fcast/run.py`, the `[lens]` switch and the `lenses` tool (now `hq/tools_s79/t_lenses.py`) stay: a lens that passes a registered study is named in `_BUILTIN` | none | `test_s79b_lens.py` framework tests unchanged (they already used a fake lens) |
| 7 | EWMA-scaled price ranges (S64, fail; plain passes) | `quant/forecast.LIVE_METHODS = ("stats_plain",)` is what the live price-range job computes and stores. `METHODS` (both) is kept: see "Left" | none | rewritten: `test_s64_forecast::test_store_prices_and_the_lines_the_brain_and_the_page_read` (stored rows 6 -> 3, plain only; the EWMA-serving reader check now stores legacy EWMA rows by patching `LIVE_METHODS`) |
| 8 | Harvesting-window paid session | `lab/triggers_s81.harvesting_on()` reads `exits.settings()["harvest_core"]` / `["harvest_longterm"]` (absent = false); the harvest reason (an order since the last session, or January) is added only when one is true | none | added `test_s81_ondemand::test_the_harvesting_window_starts_a_paid_session_only_while_a_harvest_switch_is_on` |

Other small edits: `tools/drills_s79.py` (`S79B_ITEMS`), `tools/realpath_s79b.py` (tool list), `tools/drills_s81.py` (job names in two lists; names not in the registry were ignored anyway),
`deep_pool.py` docstring, `service/tasks_s79_story.py` docstring, `configs/s79b.toml` comments.

## Decisions (2026-11-11)

- Buy zone: `paper/watch.py` kind "zone" LEFT. It is a price alert he or the team sets with its own numbers (a calculation id or his own), it never reads the zone verdict
  (`plan/buyzone.py`), and 12 tests and the watchlist screen use it. The failed claim was "waiting for the zone beats buying at once"; a standing price alert is not that claim. If he wants the
  kind removed too, it is `KINDS` in `paper/watch.py` plus the tool schema in `hq/tools.py` and `redesign.js:wlRule`.
- Buy zone: `plan/buyzone.py` itself kept (the plain year range and `touch_chance` are shown as information; `touch_chance` is the bootstrap engine whose coverage passed in S64). `RICH` (implied-growth caution)
  stays as a labelled caution, not a gate; `idea()` already said "yes" above the zone.
- Macro attribution kept (not a failed study: a description feeding storylines). Its config key stays `[waves]` as the brief said.
- Event-study module: the generic `index_event_study` rule and its gate stay with the record (tests use them); only the event lists and the two rate-study functions that needed deleted code went.
- `fcast/plugins.py` stays; the `lenses` tool was in the deleted `t_volume.py`, so it was moved to `t_lenses.py` unchanged.
- Harvest switches default to false when the key is missing (this worktree's `configs/core.toml` predates the coordinator's A60 keys, so before integration the trigger is simply off).

## Left, and why

- Item 7 is only half done on purpose: `METHODS = ("stats_plain",)` would break `quant/ranges_eval.py` (the S64 study code reads `cov_ok["stats_ewma"]`) and `test_s64_forecast` (the ranges and calibration tests need both). The live job now draws only
  plain. Old `stats_ewma` rows in `forecasts` stay as the record. To finish: delete `ranges_eval` and the `ewma_scale` code with their tests in a later pass, then set `METHODS`.
- Not touched (the inventory says keep): `comove` job (`sector_index_for` is read by `decompose` and learner templates), `who_is_buying`, the starter scans, PEG, the failed rule tests (all labelled context), the S71 front intents.
- `docs/PLAN.md`, `docs/BUILT.md`, `CLAUDE.md` mention the deleted jobs and tools (`wave_scan`, `sentiment`, `wave_detector`, `volume_profile`, `construct`): the coordinator's to update. `docs/STUDIES.md` and protocols unchanged.
- The tables written by the deleted jobs (`wave_flag`, `wave_stats`, `sentiment_s79`, `theme_exposure_s79`, `construct_runs_s85`, ...) stay with their migrations; nothing writes to them any more.

## Shared files touched

`fcast/plugins.py` (one tuple), `service/ondemand.py` (two AFTER lines), `app/world.py` (ROUTINES names), `hq/explain.py`, `story/adapters.py`, `service/tasks_s79_story.py` (docstring), `quant/forecast.py` (two lines),
`lab/triggers_s81.py` (its own), `configs/s79b.toml`, `tools/drills_s79.py`, `tools/drills_s81.py`, `tools/realpath_s79b.py`, `app/static/app.js` (one sentence). Not touched: any file the brief reserves.

## Exposed for screens

Nothing new. Removed from existing payloads: `on_offer.in_buy_zone_and_guard_ok` (`hq/picture.py`), the watch list's "zone" entries in `hold_off`, the IN ZONE nudge.
