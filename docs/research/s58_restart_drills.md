# S58 restart drills (PLAN A8): protocol

Committed before each drill runs. A drill passes when every expectation holds; a miss is a finding, fixed and re-run.
The before and after states are read-only snapshots (`pm\reports\drill_<label>_<time>.json`, never in git).

## Drill 1: days offline, jobs killed mid-run, no Kite login (2026-10-23)

Real situation, not staged: the system has been mostly idle while S54-S57 were built (most jobs last ran 18 Oct);
three runs (collect, kg, research) were cut off at 11:35-11:39 today when a test stopped the dashboard, leaving
"running" rows and lock files of dead processes; the investor has not logged in to Kite today. Snapshot `before` at 16:20.

The investor double-clicks the desktop shortcut, does not log in to Kite, leaves the window open until the Schedule screen
shows nothing due and nothing working (expected 30-60 minutes), then closes it.

Expectations:
1. The window opens at once ("starting"), then the dashboard; no error box.
2. The first tick marks the three abandoned runs failed ("abandoned: the process died") and clears their locks; the
   jobs then run again.
3. Every job due runs once (collect, prices, nav, filings, global, guards, forecast, kg with the cleanup, research,
   plans, conductor; analyst only if its slot is due); none twice for one slot; a failure is recorded with its reason,
   never silent, and does not stop the others.
4. Data catch up: bhavcopy and the store's prices to the last trading day before the run (22 Oct; 23 Oct's file is
   published after the close), indices and VIX updated past 18 Oct, NAVs and gold to the last published day.
5. Kite: the trade check stays off ("no Kite login today"), live prices stay idle, the Kite button is offered; nothing
   else waits for it.
6. Held Telegram messages stay held (the outbox is not flushed: telegram_send is off); new messages queue as pending.
7. The conductor runs: a sync-check finding list, the backup ask (no target), the wake note queued (held).
8. The screen stays usable while jobs run (screens load; the status chip shows the job working).
9. Closing the window stops everything within the job grace (60 s while a job writes): no python, pythonw or app
   Edge process left, the app log ends "system stopped".
10. A second run of the snapshot after the drill shows no job still "running" and nothing due but the timed ones.

## Results (drill 1, run 16:21-16:45; snapshots `before` 16:20, `after` 16:46)

| # | expectation | result |
|---|---|---|
| 1 | window at once, no error box | PASS: up in 6.3 s ("starting" page first) |
| 2 | abandoned runs reaped, locks cleared, jobs re-run | PASS: collect, kg, research marked "abandoned: the process died", then run |
| 3 | each due job once, failures recorded | **MISS**: every job ran once (none twice), but `collect` reported ok while its news step had failed |
| 4 | data caught up | PASS for prices, NAVs, gold (22 Oct), indices and VIX (16 -> 22 Oct); **MISS** for GDELT news (still 17 Oct) |
| 5 | Kite off, nothing waits for it | PASS: trade check "no Kite login today", the rest ran |
| 6 | held messages stay held | PASS: 12 -> 15 pending, none sent |
| 7 | conductor: sync check, backup ask, wake note | PASS: one ask (backup target), wake note queued (held) |
| 8 | screen usable while jobs run | **MISS**: settings saves failed five times ("file in use"); job durations were not recorded, so the load could not be measured |
| 9 | clean stop | PASS: "Edge exited" 16:44:57, "system stopped" 16:44:59; no process left |
| 10 | nothing left running | PASS: no "running" row; due only the 15-minute conductor and the held outbox |

Findings and fixes (each with a test; 1641 pass):
- The news step of `collect_daily` opened the ledger, which the dashboard holds (one writer), and failed; the collector
  treats news as non-critical, so the job said ok. Now the job hands the step the names it needs
  (`PFLAB_GKG_ALIASES`), and any failed step fails the job with its reason (retried after the cooldown, shown in
  health). Checked with the ledger held by another process: before, the drill's error; after, it runs.
- Two settings saves at once raced on one temp file (and Windows can hold a file a moment): saves are now one at a
  time, each with its own temp file, with a retry.
- A job's finish time was the tick's start (`ctx.now`): it is now the real finish, so durations show.
- Not in the protocol, found in the run: research raised 22 flags (new results filed 22 Oct) but queued no Opus note,
  because each company's 17 Oct note was reused for 14 days. A material change flagged after a company's last note
  now buys a fresh note (batch, within the cap).

Drill 1 is to be re-run after these fixes (the news catch-up downloads about 1 GB a day missed).

**Re-run 2026-10-24** (The investor: double-click 12:02, closed 13:01; 18 h offline; before snapshot
`pm\reports\drill_before_20261024_1147.json`). Every due job ran once, in order, with real durations (collect 40 min,
kg 7 min, the rest under 45 s); nothing left running; held messages held (15 -> 16: a guard alert); clean stop.
- PASS: collect ok with its news step; news 21-23 Oct fetched; prices, NAVs, gold, indices to 23 Oct.
- **MISS**: news 18-20 Oct still missing: the 23 Oct run that failed was recorded ok (before the fix), and the next
  window (3 days from the last success) never reached back. Fix: the news step looks back 14 days every run; a day
  on disk is skipped at once.
- **MISS**: no fresh Opus note: this run raised no new flags (the 23 Oct run had), and notes were queued only when a
  run raised its own. Fix: every research run checks the last 2 days' flags; a note already queued or submitted is
  not bought again (research may now run at any time).
- Not in the protocol: a workshop calculation ("largest fall from a peak in 2020") is marked checked but computes the
  largest one-day fall; the local model wrote a test that agrees with its own mistake. Open (below the drills).

## Drills 2-4 (2026-10-23, run by Claude on scratch ledgers; the investor's ledger untouched)

**Drill 2, power cut.** A fresh ledger is built from the investor's statements in a scratch folder, then a second rebuild is
cut off (the process killed, as a power cut would) after 100 of 1,383 events were rewritten.
- Before the fix: **DAMAGED**: 100 events left, the derived tables (lots, cash, income, fees) out of step with them.
  `tools/build_pm_ledger.py` wrote without a transaction (the inbox's "Add to the ledger" had one; the command line
  did not); so did the FD master, FD interest, targets, the look-through, the forecast scoreboard and the derived
  tables.
- Fix: `store.transaction` (all or nothing; nested calls join the outer one) around every delete-then-insert write.
- After the fix: **INTACT**: 1,383 events and every derived table as before the cut.
- Caches (simulations, Monte Carlo, the cleanup log, the situation sheet) are read defensively: a half-written file
  counts as missing and is recomputed; the settings and the watch-list cache are written to a temp file and swapped.

**Drill 3, a killed job.** Covered by drill 1 on the real system: three runs killed mid-job were reaped as abandoned
and run again; the dashboard killed hard (11:35) left a lock that the next start cleared by its process id.

**Drill 4, a full disk** (simulated: the free space reported as 0.5 GB; an out-of-space error injected mid-write).
- Before: the health check marked the disk FAIL, but the wake-up check only listed it (no ask), and `collect` would
  still have downloaded.
- Fix: below the health limits the conductor asks the investor to free space (once a month while it lasts, naming what the
  system keeps that is largest and rebuildable); `collect` refuses to download below 3 GB free (a failed run with the
  reason, retried later); an out-of-space error inside a write rolls the whole write back.
- Tests: `tests/test_s58_drill.py`.
