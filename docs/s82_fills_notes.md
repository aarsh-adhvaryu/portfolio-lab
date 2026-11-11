# S82 agent `fills`: C8 fill-cost calibration and C9 the first real strategist session

Branch `s82/fills`. Migrations 150 and 151 in `src/pflab/pm/mig_s79/m_fills82.py`.

## What is built

### C8 fill-cost calibration, automatic
- `session_fills_s81.source` (migration 150): where the quote came from. `core/session.py` sets `source = 'live'` only when the quotes came from Kite (`run_once` with no injected quotes) and
  `'injected'` otherwise; `core/fills.execute(..., source='sim')` defaults to a non-real source, so tests, drills, replays and simulations never count. Rows from before S82 have no source and are never counted.
- `core/fills_cal.py`: the fit (scipy soft-L1 least squares, robust to odd fills) of `half_spread_liquid_bps`, `half_spread_illiquid_bps`, `impact_bps` on the model's own features (the fill's place on the
  log-ADV scale and its participation), exactly `fills.model` including the slippage floor. Bounds 0.5x to 3x of the configured default, never under 0.5 bp spread / 5 bp impact, enforced by the optimiser and
  again when a stored row is read. A number with fewer than 5 supporting fills (too few near that end of the liquidity scale, or too few above the slippage floor) keeps its current value and the row says so.
  Fills with no known liquidity are not used in the fit (they still count toward "real fills so far").
- Cadence: first fit at 30 real fills (with known liquidity), then at most every 30 days (a rejected fit is retried after 7 days). Until then the job says `waiting: N of 30 real fills`.
- Table `fills_calibration_s82` (ids by `store.next_id`): old and new values, n, residual (rms and MAD, bps), outliers, 95% interval, bounds, accepted or rejected with reason.
- `core/fills.py`: `settings(con=None)` overlays the latest ACCEPTED row (execute uses it), `calibration_status(con)` -> `{"source": "calibrated"|"defaults", "n_fills", "values", "as_of", "text"}`,
  `bounds()`, `real_fill_count()`.
- Job `fills_calibrate` (`service/tasks_s79_fills82.py`, Interval 180 min, free, skips under the kill switch or `[core] on = false`). Also named in `app/world.py` ROUTINES.
- Today JSON: `core/card.today_extras(con)` gives `{"fills": calibration_status, "strategist": latest_strategist_note}`; `core/screens.view` merges it (keys `fills` and `strategist`).

### C9 the first real strategist session
- `lab/first_session_s82.py` and table `strategist_first_s82` (migration 151): key `first_session_s82`. `strategist.tick` adds the reason "the first strategist session in the app (S82)..." while the trigger is not
  `done`. Idempotent: `done` once a session ran (done, wasted or budget); `waiting` with the reason when no session could start (no cloud client or key, workshop guard, the paid cap or window cap used up
  or none set, skipped), tried again at most once a day at later ticks; a session that FAILED after spending money counts as a paid attempt and the trigger stops after 2. Never fails the app. The kill
  switch / `[strategist] on` still stop the whole tick; the governor still holds his Rs 2,500 cap and the strategist layer's limits.
  The reason is added in `tick`, not in `due()` (the weekly rule's own test `test_triggers_weekly_challenger_ready_and_nothing_to_do` is unchanged).
- `lab/service.latest_strategist_note(con)` -> `{"when","note","proposal","cost_rupees","session_id","status"}` (the allocation the same session proposed or re-affirmed, from `system_allocation_s79`).
- `core/session.strategist_line(con, day)`: one plain line in the 15:45 report (`report_day`) when the newest note is at most 3 days old; the report keeps its 15-line cap and its last line.

## Decisions (2026-11-11, unattended)
1. The real-fill marker is a new column `source` (no marker existed). `'live'` = a Kite quote in the app's session loop.
2. HONEST LIMIT: a paper fill is priced BY the model, so the observed cost equals the model's own prediction plus paisa rounding; today the fit is a consistency check that reproduces the numbers. It becomes
   informative when a fill's price is not model-made (an executed or measured price). Recorded in the module docstring; the job is harmless until then (it can only move a number inside 0.5x-3x).
3. scipy (a pinned dependency of statsmodels, already in `requirements.lock`) is used for the bounded robust least squares; statsmodels RLM cannot enforce bounds.
4. The first-session reason waits for the market to be closed (the existing `_strategist_enabled` gate), so "first open" means the first tick outside the session.
5. A failed-after-spending first session is retried at most twice (money guard), a session that merely could not start is retried daily.

## Tests (`tests/test_s82_fills.py`, 21 tests, plus `tests/test_s80_strategist.py` unchanged and green)
Under 30 -> defaults and "waiting: N of 30"; test, drill, old and sim rows excluded; 30+ fits inside the bounds, recovers a synthetic truth and logs old/new/fit; the calibrated numbers price the next
fill; outliers and absurd worlds are bounded; bounds arithmetic; a stored out-of-bounds row is clamped; monthly cadence; one-sided liquidity freezes what it cannot fit; unknown-liquidity fills are not
used; the session marks live vs injected quotes; the job; Today blocks. C9 with a scripted fake model: fires once and a second open does not; weekly + first = one session; missing key -> waiting then
done next day; cap exhausted or no cap -> waiting without a model call; paid failures stop after 2; kill switch; the real `run_session`/`llm.call`/governor path with a scripted SDK client; note + proposal
+ report line.

## Shared files touched
`core/fills.py`, `core/session.py` (source on the live ctx and fill call; `strategist_line` and a report tail; NOTE the main tree removes add_trigger/swing_triggers/the swing block here: a small merge),
`core/card.py` (`today_extras`), `core/screens.py` (merge of the extras), `lab/service.py` (`latest_strategist_note`), `lab/strategist.py` (the trigger in `tick`), `app/world.py` (ROUTINES name).
New: `core/fills_cal.py`, `lab/first_session_s82.py`, `pm/mig_s79/m_fills82.py`, `service/tasks_s79_fills82.py`.
`docs/BUILT.md` must name the job `fills_calibrate` in a table row (`test_s65_sync` fails until it does) and the tables `fills_calibration_s82`, `strategist_first_s82`.
My tests in `tests/test_s82_fills.py` import `CCC, MON, day_bars, db, no_exits, FakeKite` from `tests/test_s81_session.py`; none uses the swing triggers (the live/injected test goes through a tactical view).

## Exposed for screens
- `GET`/screens view: `fills` = `core.fills.calibration_status(con)`; `strategist` = `lab.service.latest_strategist_note(con)` (both in `core.screens.view`, i.e. the Today JSON).
- `core.fills.calibration_status(con)`, `core.fills.bounds()`, `lab.service.latest_strategist_note(con)`, `lab.first_session_s82.status_line(con)` (one line on the trigger's state).

## What is OFF / left
Nothing is behind a switch. The calibration only starts moving numbers after 30 real fills. Left: show `fills.text` and the strategist note on the Today page (UI is the redesign's).

## The real run (the one paid run), 2026-11-11 23:26 IST
- On a COPY of `D:\PL_backup\s82_pre_20261111` in `D:/s82_scratch/fills/store` (schema 102, migrated to 151 by this tree). Scratch `api_budget.toml` only: `dev_monthly_cap_rupees = 430`
  (the strategist layer's 70% share = Rs 301), `counted_since` = 23:00 so only this run counted; `PFLAB_PAID=1`; the real key from `secrets.toml` (never printed); the real Docker sandbox
  (`pflab-sandbox:2`) and the real panel under `D:\portfolio_lab\data` (read only).
- It went through the real path: `strategist.tick` with the real `llm.client`, real governor, egress gate, `run_session`. The tick found the first-session reason (plus "the book is far from its allocation
  target"), ran the allocation replays (free), then ONE session: status `done`, 9 Opus calls (11 log entries), 2 lab runs, 2 variants, 1 challenger, 1 note, 1 allocation proposal (target #3).
- COST: Rs 18.43 in total (calls 5041-5049, Rs 1.0 to 3.4 each). Far under the Rs 300 session cap and the night's Rs 600.
- The trigger recorded `done` (attempts 1, session 2, Rs 18.43); the note and proposal came back through `latest_strategist_note` (cost, proposal #3: equity 88, gold 10, cash 2); `strategist_line` and
  `screens.view` (`fills`: "defaults, 0 of 30 real fills"; `strategist`) read them from the real store copy.
- The note (the model's own words, sourced from lab runs): index plus 10% gold without the fall gauge lagged the index by about 1.2 points a year after tax; the allocation template inherits the gauge
  drag so its proposal (alloc_t3) likely fails the index rule; the index-only target in force stands; next: test gold with rebalancing. Nothing was adopted (code decides, by the A50 rule), no live store was touched.
- The scratch store copy was deleted afterwards; the log is `D:/s82_scratch/fills/real_run.log`.
