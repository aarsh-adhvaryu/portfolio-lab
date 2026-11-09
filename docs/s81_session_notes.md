# S81 agent "session": B6b the market-hours rhythms (A54), notes

Branch: the agent's worktree branch (`worktree-agent-a66b7e18818263c52`). Migrations 137-142 in `src/pflab/pm/mig_s79/m_session.py`.

## What is built
- `core/fills.py`: `execute(...)` places and fills ONE paper order at a live quote plus the liquidity model's spread and slippage, through `book.place` and `book.fill` (charges, FIFO, tax, rails,
  fake bank are the book's own). Model `liquidity_v1` (function and parameters in the docstring and in `configs/core.toml [fills]`): half spread from 25 bp (adv Rs 1 crore) to 1 bp (adv Rs 100 crore),
  linear in log(adv); slippage 25 bp x sqrt(order / adv), at least 0.5 bp; price moved AGAINST the order and rounded to the paisa against it (asserted never better than the quote). ADV is the mean
  traded value (close x volume) of the last 20 sessions BEFORE the day from the minute bars, stored once a day in `session_adv_s81`; a name with no history is charged an unknown-liquidity assumption
  (15 bp, participation 1%) and flagged. The guard `round_trip()`: a sale may not touch shares bought today (FIFO: only a sale larger than the pre-today holding would), a buy may not follow a sale of the
  same name today; a refused part is queued (`session_queue_s81`) to the next session; a STOP bypasses it, fills and the fill is flagged "same-day round trip: its stop fired".
- `core/preopen.py`: `ensure_plan` / `build` / `plan_day`: the day's plan as conditional orders (exit plans' stop/target/time levels, the swing triggers, held-over orders, tactical views), the world's
  latest closes before the open, an expected Nifty 50 gap (least squares on the S&P 500's last return, 250 sessions, labelled an estimate, information only: it moves no order) and a code-written
  text; table `session_plans_s81`. Built once per session day, again once inside the pre-open window, and late (flag) if the app opens after the open.
- `core/session.py`: `run_once(con, now, quotes=None, bars=None, *, kite, events, root, data_root, liq)`; steps: queue from earlier sessions, exit plans at the live quote (`core.exits.check_quote`,
  fallback below), thesis break from a filing released during the session (`kg.events.material_events` then `core.exits.check_thesis`; fallbacks below), swing triggers (`session_triggers_s81`;
  `add_trigger` writes, `swing_triggers(con, day)` reads), tactical views carried out in session, the breaker (`cadence.breaker`: no buy of any kind while on). Entry timing (`timing()`): not in the
  first 15 minutes, within 0.5% of the day's VWAP, last 5 minutes' volume at least 50% of the typical minute volume (typical = mean of 09:30-15:00 minutes over 20 sessions); no minute data = the entry waits and
  says so. Every pass leaves a `run` row; every wait, queue, skip, fill, thesis and degradation its own row with a code-written reason (`session_log_s81`); fills in `session_fills_s81`.
  `replay(con, day, bars_dir, ...)` feeds a recorded day's minute bars through the same `run_once` at 5-minute steps with an injectable clock (`times=`), a quote being the close of the last CLOSED minute.
  `card()` is the compact Today card; `report_day()` is the 15:45 message.
- `service/tasks_s79_session.py` (auto-loaded): jobs `preopen_job` (Interval 30 min, 06-16h), `session_job` (Interval 5 min, 09-16h; the market mode decides), `session_report` (Daily 15:45; stale after 3 h;
  queues the text on the outbox as kind `summary`, dedup key per day; never sends).
- Today: `core/screens.view` has key `session` (`session_card`); `GET /api/session` in `app/server.py` returns the card with 40 recent rows.

## Decisions (2026-11-09, unattended)
1. A queued exit (held by the guard) is carried out at the FIRST allowed step of the next session (after the first 15 minutes), at that moment's quote, whether or not its level still holds: the exit
   decision was taken the day before. If an exit plan sells the name first, the queue row is voided.
2. Exits with no hurry (`time`, `harvest`, `trim`, `rebalance`) wait out the opening spike like an entry; `stop`, `target` and `thesis` do not.
3. A thesis-break sale of shares bought today is held to the next session like any exit (only a stop bypasses the guard, as the brief says).
4. Without a quote nothing is sold: a thesis break is noted once and the post-close loop (which sees the same filing) decides.
5. "Say once": one `session_said_s81` row per day and key; the Telegram message goes through `tgm.enqueue(kind="summary")` (a direct kind: goes out at once when the outbox job sends).
6. Fallbacks while their module is missing: exits -> `session_exit_fb_s81` (stop 8%, target 15%, time stop 20 sessions, `[session]`), used for positions the session itself opens and for anything seeded in
   it; thesis -> a filing of severity `high` (INSOLVENCY, DEFAULT, FRAUD, FORENSIC_AUDIT by `data.red_flags`) on a held name sells it; events -> BSE announcements by dissemination time (a filing with none is left out).
7. A tactical view is carried out in session once per name (`core_views_s80.executed_json`); `views.merge` then does not add a name the policy does not hold a second time at the close.
8. Config switches: `[session] on`, `[core] kill`/`on` stop everything; `views_in_session = false` leaves the views to the close.

## For the coordinator (wiring and shared files)
- Shared files touched (each a few lines): `paper/book.py` (`fill(..., exact=False, only=None)` and a float-safe `floor(spend / px + 1e-9)`), `core/views.py` (the merge hook), `core/screens.py` (the `session`
  key), `app/server.py` (`GET /api/session`), `app/world.py` (three job names in the ROUTINES list, needed by `test_s67_world`), `configs/core.toml` (`[fills]`, `[session]`).
  `core/__init__.py` is NOT touched: `fills.settings()` / `fills.session_settings()` read their own sections of `configs/core.toml`.
- `docs/BUILT.md` must list the jobs `preopen_job`, `session_job`, `session_report` (test_s65_sync checks every job is named in a table row).
- Contracts used from other agents, all import-guarded: `core.exits.check_quote(con, now, quotes, state)` (state is `{day, market, positions, bars, breaker, open_at, minutes_in}`),
  `core.exits.check_thesis(con, day, events)`, `core.exits.open_plan(con, now, market, isin, sleeve, entry_price, qty, plan)` (called with sleeve "swing" and a plan dict that carries the trigger's
  `stop_price` / `target_price` plus the trigger's own `plan_json`), `exit_plans_s81` (read by the pre-open plan with tolerant column names), `sleeves_s81` (one insert on a swing entry), `kg.events.material_events`.
  If `check_quote` keeps returning an order after it fired, the loop does not repeat it (one fill per `(plan_id, kind)` a day).
- The swing policies write the day's triggers with `session.add_trigger(...)` at the close (valid from the next session); the close loop's own harvest buy-backs and rebalance buys through `paper_orders` are NOT
  guarded by `fills.round_trip` (only session fills are): call `fills.round_trip(con, isin, side, qty, day)` there if the same rule must hold at the close.
- Observation, not changed: `views.merge` adds `each` to a name the policy does not hold on EVERY close while the view is active (base = the current weight), so such a view compounds; a view on a name the policy holds is stable.
- `core/loop.py` is not touched. The close loop waits while `paper_orders` has open orders; session fills never leave one open.

## Tests (`tests/test_s81_session.py`, synthetic bars)
Config; slippage and spread grow with the order's share of turnover and with illiquidity; price never better than the quote; a bigger order pays more bp in the book; the guard (a sale of today's shares held,
a stop fills flagged, buy-back after a sale held); a stop mid-session fills at the replayed quote plus slippage; a swing entry fires on its trigger only after the first 15 minutes and near VWAP (and waits when
away from VWAP, on thin volume, or with no minute bars); a same-day exit is held to the next session (queued, then executed) and a stop on the day of entry fills flagged; a filing released mid-session breaks
a thesis and sells (one before the open does not) and the exit manager's contract path with a fake `core.exits`; a tactical view is carried out once in session and not added again at the close; the breaker; Kite
lost mid-session degrades and says so once (one outbox row); no Kite login at all; outside a session nothing runs; the pre-open plan; the 15:45 report and its job; the replay never shows an unclosed minute.

## Real path
See the final report (a real recorded day replayed read-only from `D:\PortfolioLabApp\data\bars_1m` on a synthetic book; not a committed fixture).

## Not verified / left
- The live Kite path (`kite_quotes`, `kite_bars`) is covered with a fake client only; the first live market day (Wed 2026-11-11) is its real test. `kite_bars` fetches today's bars by one historical call per
  name that has a trigger, a view or a queued buy (about 3 requests a second allowed).
- The `[fills]` numbers are an assumption with no fill record to calibrate against; they are to be revisited from the first sessions' `session_fills_s81`.
- No UI beyond the compact `session` card and the API route (the redesign is his later).
