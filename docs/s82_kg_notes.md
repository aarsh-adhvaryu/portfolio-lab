# S82 kg agent: filings with no release time (A58) and live news times

Branch `s82/kg`. Code only, no paid call, no store written, nothing under `D:\portfolio_lab\data` or the app written.

## What is built
- `src/pflab/kg2/filing_time.py` (new): `filing_time(dissem_dt, news_dt, file_day)` gives `(ts, rule, own_date)`. With a release time: that time, rule `release_time`. With only a date:
  the OPEN (09:15 IST) of the first trading day strictly after the date (market calendar `markets.get("IN")`, holidays and weekends skipped), rule `next_open_no_release_time`.
  The filing's date is the announcement file's day (the exchange's query day; checked on the real files: file day = dissemination date for 100% of timed rows), or a later news date if the row has one.
  Also `news_time` (live news), `stamp_missing` and `file_day_of` (for the DuckDB-reading study readers).
- `kg2/build.py`: `read_filings` keeps `file_day`; `filing_events` enters a no-time filing with `ts` = that open, `event_date` = its own date, `ts_rule` stored, `link_rule`
  `filing:scrip_isin_on_filing_date_no_release_time`, the proof says "no release time: used from ...". A derived row that has a timed twin (same scrip, same headline, same day) is dropped
  (counted). Filings dated after the build day are not read; one dated ON the build day is in that day's graph with a `ts` on the next open, so the store holds it before the open and readers
  hold it back. News events carry `ts_rule = article_day_next_day` (the older rule, no re-fetch). New column `ts_rule` in the event table (migration 156, `pm/mig_s79/m_kg82.py`, ADD COLUMN IF NOT EXISTS;
  old stored rows keep NULL until the next nightly rebuild, which replaces the tables).
- `kg/events.material_events(con, isins, since, until=None)`: new `until` (datetime, or a date = that day's end); rows now carry `ts_rule`. Callers already filter by time:
  `exits.check_thesis` ignores an event whose date is after `day`; story `kg_items` the same; `core/session.session_events` keeps `since <= ts <= until`.
- `kg2/audit.py`: `point_in_time` judges a derived row by its DATE (its `ts` may be the next open); new gating check `derived_time_rule` (every event has a known rule; a derived `ts` equals the
  calendar's next open after its date); `filing_link_rate` now counts no-time filings by their file day and reports the timed-only and date-only rates; the old "left out" info line became
  `info_filings_with_derived_time`.
- Shared file touched, minimal: `core/session.py` (`_filing_events` fallback reads the previous trading day's files and gives their no-time filings the open; the strict `since < ts` became `since <= ts`
  in `session_events` and in `events_for`, because a derived `ts` is exactly 09:15 = the session's open).
- Live news (item 5): the live path is the 15-minute GDELT GKG files (`data/gkg`, `gdelt_gkg.collect_day`) into the old graph's `kg_docs` (`kg/build.articles`). It stored GDELT's `DATE` (the
  publication/crawl time) as UTC, unconverted, so every article looked 5.5 hours earlier than it was (a look-ahead against the IST clock). Fixed: `articles` stores the publication time in IST (+5:30)
  through `filing_time.news_time`; an item with no time but a collection day (`gdelt_gkg.load` now adds `file_day`) is stored at the next day 00:00; one with neither is skipped. Already stored
  `kg_docs` rows are not rewritten (documents are inserted ON CONFLICT DO NOTHING, so re-ingesting them changes nothing). The kg2 news rows (GKG 1.0 daily files, day only) keep ts = 23:59:59 of their day
  and enter a build only from the next day (unchanged; `news_s81` is not on this PC's workshop data, only in the app folder).

## Places that excluded no-time filings (grep list) and what was done
Changed (shared readers, future runs only; no study re-run, earlier verdicts stand):
- `kg2/build.filing_events`, `kg2/audit.raw_filing_link_rate`: new rule.
- `core/session._filing_events` (the thesis fallback): new rule.
- `data/red_flag_events.build`: a row with neither time was `unresolved` and unusable; now keyed to the END of its file day, `key_source = "FileDay_next_open"`, which the module's after-15:30 rule turns into the next
  session. Rows already in a built table keep `unresolved` until the table is rebuilt. Rows that have a news time keep the frozen amended-section-3 rule (DissemDT else NEWS_DT).
- `lab/runner.build_results`: neither time -> file day + 1 -> the first session on or after.
- `quant/event_study.filings` and `learner/templates` (insider_sast): neither time -> `stamp_missing`, the next open after the file day. Rows with a NEWS_DT keep it (frozen rule).
Left as they are, and why:
- `kg/build.filings` (the OLD graph's `kg_docs`, `dissem_dt >=` filter): the old graph is the chat's reading memory, not a decision path; the new graph is the one the exit manager reads.
- `monitor/filings.classify_announcements`, `plan/nudges`, `quant/align`, `hq/context`, `hq/tools_s79/t_explain`: live alerts and explanations that show a filing as soon as it is known; showing earlier is the safe direction
  and none of them feeds a decision, and `align` needs a real minute. Not changed.
- `data/bse_insider`, `bse_shareholding`, `bse_scrip_isin`: data builders that use `dissem_dt` for their own keys (`dropna`); `bse_shareholding` already labels `filing_date_source = unresolved` (tested). Not changed.
- `lab/policies/swing_post_results_drift` (swing is deleted by A60), `llm/eval12` (2023-2024 evaluation, spent period).

## Audit on the real files (nightly audit function `kg2.audit.run_audit`, run through `kg2.job.run`)
Real files read through junctions to `D:\portfolio_lab\data` (announcements to 2026-10-24, scrip map, index membership, prices, results); every write went to `D:\s82_scratch\kg\root`. Day 2026-10-24, scope 513 names
(built from index membership; the news collection `news_s81` is not in the workshop data, so news rows = 0: news linking is covered by the S81 synthetic tests only). 51 s. PASSED, every gating check:
- every row has isin, source, date, rule: 0 missing.
- point in time: 0 events with a date after the day, 0 facts known after the day, 0 without a time. 555 filings carry a derived time (all at 09:15, all after their date; weekdays Mon 80, Tue 324, Wed 60, Thu 41, Fri 50).
- derived_time_rule: 0 wrong.
- filing link rate 99.94% (211,484 of 211,617 listed-scrip filings over 365 days, now counting the 2,037 no-time ones: date-only 99.95%, timed-only 99.94%; the remaining 133 are `outside_isin_validity`). S80 had 84.5%.
- duplicates 0.0%. closed lists ok. Rebuild byte-identical: two builds give equal table hashes, and two parquet writes give equal file hashes (event 08f5f4f2..., all five equal).
- Counts: 67,613 filing events (555 derived; 612 no-time rows in scope, 20 dropped as twins of timed filings, the rest are older than the 400-day window or after the day); 521 nodes, 3,363 facts, 4,326 relations.
The graph switch stays ON (`configs/kg2.toml`), because the audit passed; had it failed `job.run` empties the kg2 tables (that path is unchanged and tested in S81).

## Decisions (dated 2026-11-11, nobody awake)
1. A filing's date = the announcement file's day (or a later news date). The default needs no input.
2. A derived row is stored in the graph of its own day (ts on the next open) and held back by readers, rather than waiting for the next night's build, so the store holds it before the open it is due at.
3. Rows with a NEWS_DT but no release time in the STUDY readers keep their frozen section-3 rule; only rows with no time at all gained the new rule. (The graph treats news-only rows as no-release-time: they are 2% of the no-time rows.)
4. Live GKG time converted to IST rather than left in UTC (the system's clock is IST).

## Tests
`tests/test_s82_kg.py` (17): calendar rule (Friday, weekend, holidays 20 Oct and 10 Nov), release time unchanged, graph entry with the rule stored, build-day boundary, twin drop, byte-identical rebuild, audit passes and catches a wrong
derived time and a late date, migration 156, `material_events(until)` holding the row back, the thesis-break drill (WIN held; filing dated Fri 30 Oct with no time: Friday check sees nothing, Monday 2 Nov the thesis sale order is made; once only),
the same through `check_close`, the session fallback at the open, live news with a time / with none / with neither, `gdelt_gkg.load` file day, control-character scan.
Rewritten (not deleted): `tests/test_s81_kg.py::test_filing_without_dissemination_time_is_used_from_the_next_trading_open` (was "left out"); `material_events` key set and a positional insert gained `ts_rule`.
Run green: test_s81_kg, test_s82_kg, test_s81_session, test_s81_exits, test_s81_drills_fixes, test_kg*, test_s80_story, test_researcher, test_analyst, test_s58_drill, test_s46_quant_event_thesis, test_s79b_studies, test_red_flags, test_s62/s76_learner (see the report for the final run).
The five protected engine suites were not touched or run.

## Exposed for screens
`kev.material_events(con, isins, since, until)` rows carry `ts_rule`; the event table's `ts_rule` tells a screen whether a time is the exchange's or derived ("used from the next open, no release time given").
The audit's `derived_time_rule` and `info_filings_with_derived_time` appear in `kg2_audit.checks_json` / `data/kg/audit_last.json`.

## Left / not verified
- News linking on real files (no `news_s81` on the workshop). The app's nightly will rebuild with its own news.
- Old `kg2_event` rows in an existing store have `ts_rule` NULL until the next nightly build replaces them.
- The old graph (`kg_docs`) does not use the new filing rule (see above).
