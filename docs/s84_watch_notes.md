# S84 watch (T1 NOTICE): notes (branch s84/watch, 2026-11-12)

## What is built
- `src/pflab/think/watch.py`: `run(con, now, *, mode, quotes=None, root=None)`, `scope(con, day, ...)`, `watch_text(con, day)` (text block for Today, the 15:45 report and Telegram), `missed_runs(con)` (what the
  scorecard's "skips that ran" reads), `settings()`. Code only: no model, no cost, nothing reaches a broker.
- Migration 220 `think_watch_runs_s84` (`src/pflab/pm/mig_s79/m_watch84.py`): one row per India close and per US morning pass (the catch-up's bookkeeping). Session-loop passes are not logged there.
- `configs/core.toml [think]`: one line added, `wide_watch = false` (the brief names it). The other watch numbers are defaults in `watch.WATCH_DEFAULTS` and any of them can be put in `[think]` to override.
- Tests: `tests/test_s84_watch.py` (25 tests, synthetic data only).

## Signals (each a number with its threshold; `surprise` = value over threshold, 1.0 = at the line)
move_1d / move_5d (beyond `move_sigmas` x the name's usual daily move, 5-day line = sigma x sqrt 5; sigma = std of the last 250 daily returns before today), rel_1d / rel_5d (the same on the move against
its market: Nifty 500 TRI for India, SPY for the US), outside_forecast (the move since a stored live hedge forecast outside that forecast's 5%-95% range), fall_10d (-20%), rel_fall_5d (15 points behind
its market), market_down_20d (index -10% in 20 sessions; pseudo key `MARKET:IN` / `MARKET:US`), news_burst (news today vs its own 60-day norm, at least 3 items), thesis_event (`kg/events.material_events`: the
graph's own thesis-break kinds and severities, so `leadership_crisis` from the kgkind agent flows in with no change here), storyline_jump (15 points in a day; key `STORY:<id>`), overnight_shock (S&P 500,
Nasdaq, dollar-rupee, Brent beyond `move_sigmas`; key `MACRO:<series>`; US morning only), missed_run (a skipped or screened name 20 points or more ahead of its index since the day it was passed on).

## How a pass works
`mode='session'` (needs `quotes`, isin or symbol -> price): held India names only, price signals + stored forecast ranges + thesis events; no news, storylines or missed-run queries. `mode='close'`: the India
close of `markets.get("IN").session_closed_by(now)`. `mode='us_morning'`: the US session just closed (`us.clock.session_closed_by(now)`); `quotes` (symbol -> price), if given, are the after-hours prices and count
as one more bar. `mode='catchup'`: each India close and US morning after the last logged one, up to `catchup_max_sessions` (10), each once; with nothing logged only the latest. Score = surprise x exposure
in rupees. A new signal on a name with an open case joins it (`cases.case_for`); at most `max_cases_per_day` NEW cases a day (counted with `cases.cases_opened_on`), largest score first; the rest are stored as
state `noticed` (their signals `not_examined`). Every signal is stored once per (name, signal, day); a thesis event once per event ref.

## Decisions (dated 2026-11-12, made without asking: nobody awake)
1. A price signal is raised only when the name's last bar IS the pass's day (India close, US session). A stale bar gives no signal. A close whose NSE prices have not arrived is NOT logged as done (unless it is
   more than 3 days old), so the next `close` or catch-up runs it again. (Found on the real store copy: three catch-up days were repeating one stale bar.)
2. History comes from `app.research.closes` (the panel's split-safe adjusted history joined to the store's recent closes, the same join the forecasts use), because the store's `prices` holds only about
   35 sessions; splits that went ex after the panel's end are adjusted from the corporate-action factors (a factor is new price over old, so a 1-for-2 split is 0.5). US names use `us/raw/<SYMBOL>.parquet`.
3. A missed run measures a PRICE return of the name from its pass-on day (the close on or before it, at most 10 days old) against the index's total return: a small understatement of the name (no dividends);
   labelled in the signal's detail (`return_basis`). The most recent skip of a name sets its pass-on day. Screened names: the first screen day inside `screen_lookback_days` (60); skips: `skip_lookback_days` (365).
   A name that fired is not fired again for `missed_cooldown_days` (30). Held names and active picks are never "passed on". At most 300 such names per pass.
4. Exposure: a held name = its value in rupees (US sub-book: dollars x the stated rate); the case's `exposure_pct` is over the whole book. A name the book does not hold: STAND-IN `standin_weight` = 0.1% of
   the whole book, labelled in every signal's detail (`exposure_basis`) because index weights are not stored. A market or macro signal's ranking exposure = 25% (`market_exposure_factor`) of the equity the book
   holds: a ranking weight only, never a rupee claim. A thesis event's surprise is 2.0 (medium) or 3.0 (high); a case's score is its largest signal's score.
5. Pseudo keys for non-security cases (`MARKET:IN`, `MARKET:US`, `MACRO:<series>`, `STORY:<id>`) sit in `think_cases_s84.isin`, so one case per subject joins as usual. Whoever reads `case.isin` must not look
   it up as a security for these (`book.inst` returns empty fields, safely).
6. "Names he asked about" (`strategist_requests_s81` holds free text, no symbols): not parsed tonight. Left for S85 with the wide watch.
7. Sector exposure and exposure through funds: S85 (the brief). `[think] wide_watch` is read and says "not built" if switched on; no half-written code.
8. Catch-up holdings are today's holdings (the ledger's lots are not time-sliced here); prices, filings and probabilities are point in time (<= the pass's day, filings <= its clock).

## OFF and why
Nothing of mine is OFF behind a switch. `wide_watch` (the Nifty 500 and S&P 500 members) is OFF and not built (S85). The watch runs only when something calls `watch.run`; the coordinator wires it.

## Wiring for the coordinator (shared files NOT touched by me)
- `core/session.py` `run_once`, after the quotes are fetched: `watch.run(con, now, mode="session", quotes=quotes)` (isin -> price), inside a try.
- the close loop (`core/loop.py`), after prices and filings are in: `watch.run(con, now, mode="close")`; the US morning job: `watch.run(con, now, mode="us_morning")`; on app open after a gap: `watch.run(con, now, mode="catchup")`.
- `watch_text(con, day)["text"]` for Today and the reports (one line); `cases.thinking_block` already shows the open cases.
- The `case` agent reads open cases with `cases.open_cases` / `looks_due`; a `noticed` case is never returned by `open_cases` (by design).

## Shared files touched
`configs/core.toml` (one line, `wide_watch = false`). No other shared file.

## Exposed for screens (plain functions returning JSON-able dicts / lists)
`watch.scope(con, day, market=None, held_only=False)` (list of dicts: name, isin, symbol, market, exposure_inr, exposure_pct, why, held, base_day, base_why, exposure_basis),
`watch.watch_text(con, day)` ({text, signals, cases_opened, joined, noticed_not_examined, by_signal}), `watch.missed_runs(con)` (list), and `cases.signals(con, day=...)` for the raw rows.

## Real path (a COPY of the store, schema 102 migrating on open; app data read only)
Copy of `D:\PL_backup\s82_pre_20261111\ledger.duckdb` (no fresher copy existed at 16:20) with the app's data folder read only. Scope: 8 holdings (all India). The store's last price day is 2026-11-09 and the
copy has no news events, no picks, no skips and no screens, so the live signals were few: `close` at 2026-11-09 raised 1 signal (a 5-day move beyond 2.8 times the usual 5-day move on one holding, 1 case); the
catch-up to 2026-11-12 raised no more signals (a stale bar gives none) and logged only the days whose prices had arrived; the US morning raised 1 overnight shock (S&P 500 +2.3%, 2.8 times its usual move). A
skip recorded by hand on a real stored name on a day it was near Rs 1,450 gave a missed run of +28.6 points against the index on the real bars to 2026-11-09 (the replay agent's drill uses the same path). Each
pass took under a second. Names are in `D:\s84_scratch\watch\` only.

## What I could not verify
Live quotes in the session loop (no market open, no Kite): tested with a scripted quote map. US after-hours prices: tested with a scripted quote; no live source exists tonight. News bursts and thesis events on
the real store (the copy's graph is empty).

## Left (S85)
The wide watch over Nifty 500 and S&P 500 members; exposure through funds and sector; names he asked about; US company filings in the graph (T2 b); automatic threshold tuning (T8).
