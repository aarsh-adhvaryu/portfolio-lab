# S79 test findings (overnight 2026-11-08) — collected in Step A, fixed once in Step B

Format: what / where / how to reproduce / status.

## From the drills (agent R, first full battery, 02:30)
1. **Offline Daily jobs are recorded "failed", not "skipped: offline".** `service/jobs.py::run_job` converts to skipped/offline only for Interval schedules whose failed parts are ALL offline; `collect`, `global`, `nav` (Daily) fail with the ConnectionError text. `data_s79b` stays failed when the network is down because it also reports a non-failed "no source answered" part. Effect: an offline laptop queues a "job failure" Telegram alert per job and the World says "1 thing failed". Reproduce: `python tools/drills_s79.py run --only net_down`. Status: FIXED (Step B): a lost connection is the job status `offline` for Daily jobs too (`service/jobs.py`): retried after the cooldown, no alert, World shows it as waiting; the S70 test that pinned the old `failed` was updated; `data_s79b` reports a source that did not answer as a failed part so it reads as offline.
2. **The injected clock is ignored by the catch-up.** `service/catchup.py::run` calls `fcast.run.catch_up(con, market, closed)` without `now=`, so `forecasts_s79.made_at` is the real clock. Reproduce: `--only off_fri_mon`. Status: FIXED (`catchup.run` passes `now`).
3. **Cost on open / in the loops (verify live).** One post_close took 6-9 s; a session took >40 s while the volume_profile lens was being added (`quant/volume_profile.py::value_area_idx` loop). First catch-up on open does 10 sessions per market (about 1.5 min). Over 32 accelerated ticks `wave_scan` ran 32 times (13.9 s average), `situation` 32 times (7.6 s), `catch_up` 32 times (2.7 s): they may re-run every 5 minutes with nothing new (the AFTER chain on `catch_up`, an Interval(5) job that always ends ok). Status: FIXED the cause I could see: a `catch_up` run that did nothing is now `skipped` (waiting for data or nothing new), so the jobs that follow it are not started every 5 minutes. To confirm in the live run (hour check).
4. **A failed agenda item is not shown on the World panel** (`agenda/runner.py::snapshot` lists recent_done and recent_skipped only). Status: FIXED (`recent_failed` in the snapshot and a 'Failed' group on the panel).
5. Minor: the tools sweep reports `proposals` and `work_status` as errors ("not a tool of this role"); they are read tools that are WORKER_ONLY. Status: OPEN (harness note).

## Other known items carried into Step A
- Privacy grep (`python -m pflab.hq.security`) flags lines in `global_markets.py`, `leadlag.py`, `transmission.py`, `tests/test_s79b_seats.py` (names from his stock list). Status: OPEN.
- Full suite not yet run on the combined branch.

## Step A results on the combined branch (04:00)
- Full suite: 3218 passed, 3 failed (24 min under load). (a) `test_built_md_lists_every_job_and_every_brain_tool`: BUILT.md lacked the new jobs/tools: FIXED (table added). (b) `test_the_picture_reads_the_whole_system`: depended on there being NO real Kite login on the machine (the investor logged in tonight): FIXED (the test is hermetic now). (c) `test_files_are_chosen_shown_in_a_tray...` (headless Edge): passes alone; flaked under load (GPU and suite at once). Status: re-run in Step C.
- Privacy grep: 7 lines flagged (two ticker names on his list in code/comments/tests): FIXED, prints clean.
