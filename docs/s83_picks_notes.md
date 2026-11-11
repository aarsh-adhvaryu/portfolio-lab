# S83 picks (L1) and the share rule (L5): notes

Branch `s83/picks` (based on `pm/s82-gaps` 1960e33). Protocol first: `docs/protocols/s83_picks_live_protocol.md` (commit 3da0d18, before any code that uses it).

## What is built
* `core/picks.py` (L1): `propose`, `withdraw`, `skip_idea`, `active`, `all_picks`, `adopt_kite_holdings`, `target_weights`, `attach`, `universe`, `merge`, `prepare`, `sync`, `needs_learned`, `share`,
  `status`, `us_floor`. States: proposed -> buying -> held -> withdrawn / stopped / broken.
* `core/pick_share.py` (L5): `RULE`, `settings`, `share`, `judge`, `status`, `report_line`. One dated row in `sleeve_share_s83` per JUDGMENT (a "level" judgment has old = new), with the figures.
* `learner/s83.py`: `register_picks_live(con, now)` counts two tests (`s83:picks_live:IN`, `s83:picks_live:US`, origin `study`, protocol SHA stored), idempotent; `protocol_ok`.
* Migrations 170 `picks_s83`, 171 `skips_s83` (`m_picks83.py`); 180 `sleeve_share_s83` (`m_share83.py`). Contract columns exactly as agreed.
* The withdraw exit in `core/exits.py`: `_withdrawals`, kind `withdraw` in `KINDS`.
* Config: `[picks]`, `[picks.in]`, `[picks.us]` in `configs/core.toml` and `DEFAULTS["picks"]` in `core/__init__.py`. Shared keys sit in `[picks]`; the market tables hold `on`, `start_share`, `min_share`,
  `max_share`, `step`. `[picks] on` and the market's `on` must both be true. `[picks.us] on = false` (the coordinator turns it on when the US wiring lands). Read through `pick_share.settings(market)`
  (it merges the nested tables key by key; `core.settings()` would replace `[picks.in]` whole).

## Decisions (dated 2026-11-11)
* The sleeve's share is a share of the whole rupee book (India: of the India part = the rupee paper book; US: of the sub-book). His Kite stocks count inside it. The room for the system's picks is
  `share - what his Kite stocks (and any withdrawn pick still held) hold`. If his Kite stocks already hold more than the share, the system's picks wait for room (propose still accepts them and says so
  in a `note`); a pick is never bought by selling his stocks.
* Kite stocks keep what they hold: `baseline_v2` no longer tops them up toward the risk size / `longterm_buy_pct` (they are "managed" by the picks rule and their target is what they hold). This is a
  change of the S81 baseline's behaviour for his stocks, as the brief asks. A fall gauge still cuts them like the other equity. A pick (his or the system's) over the company rail is brought down to it
  (the baseline's old "trim to the rail", kept: `tests/test_s81_drills_fixes` kill9 relies on it), never bought.
* Sizing: inverse volatility among the system's picks, each at most the 10% stock rail (US: `us_stock_cap`), total at most the room. A pick above its risk size keeps what it holds (max of current and target).
* Where the picks enter: `state.build` adds `state["picks"]` (`weights`, `managed`, `share`) and the not-yet-held picked names as rows with no quantity (so rails see them). `baseline_v2` takes the
  picks' weights into `weights` and `inc_lt` (new cash goes to the core first, then to longterm and the picks: the existing path). A promoted lab policy or a probation blend gets `picks.merge` in the loop:
  pick names are overridden with the picks' sizing (a lab policy never sells a pick to reach a weight); a baseline is left as it is.
* States: `sync` runs after the orders are placed, outside the transaction. proposed -> buying when a buy is open or shares are held; buying -> held when the current weight is within the band of the target
  (`baseline.band_pts`, 1.5 points: the rails skip a gap smaller than the band, so "reached" cannot mean exact); held -> stopped / broken when the position is gone (a thesis event = broken). A failed read of
  the positions never reads as "nothing held" (strict mode, the exception is caught and reported).
* Share rule: judged at the first close with 60 sessions of record AND at least one system pick bought (without that the sleeve would judge his Kite stocks alone: protocol section 3), then every 60 more
  sessions of record. Measure: `points_a_year` from `pick_score.sleeve_record` (ahead = above 0, behind = below minus 2.0); if the record lacks it, it is computed from the sleeve and index returns over the
  window. The record function is asked for `window=120` when its signature has that argument. A shrink (the last judgment lowered the share) refuses new picks until the next judgment.
* `report_line(con, day)` tells a move made at that close or at the previous session's (the judgment happens in the evening close loop, so the next 15:45 report tells it). Wired into `core/session.report_day`.
* India liquidity: the median of `turnover` over the last 60 sessions from the lab's price panel (`data_dir()/panel/prices.parquet`, bhavcopy turnover), at least 50 of the 60 sessions present;
  `picks.traded_value_source` can be set to another function `(con, market, isin, symbol, day) -> (median, observations)`. The panel is refreshed by `data/panel.refresh` (it can be weeks old: stated).
* US floor: `pflab.us.picks_floor.check(con, symbol, day)` when it exists (dict with `ok`/`reason`, a tuple or a bool are accepted); else the stored bars in `data/us/raw` with the A62 numbers (price at least
  USD 5, median traded value at least USD 2 million over 60 sessions), and the reason says it was checked on stored bars.
* A pick in a `Tech`-like sector is refused when the sector is already within one point of the 25% rail (the rails would also scale the buying back at the close).
* Withdraw: state `withdrawn`; the sale is the exit manager's `withdraw` order, from `check_close` after thesis and level checks (a stop or a thesis break fires first and takes the name that close), before trims.
  Inside the 12-month guard the sale is recorded as `guarded` and waits. It is scored like every sale (`exit_scores_s81`, kind `withdraw`). A withdraw sale is not under the turnover cap (like the other
  exit sales).

## Shared files touched (smallest hooks; the coordinator resolves merges)
* `core/state.py` (extra isins from `picks.universe`; `picks.attach` at the end of `build`), `core/baseline_v2.py` (managed names leave the longterm rule; picks' weights join `weights` and `inc_lt`),
  `core/loop.py` (`picks.prepare` before the state, `picks.merge` after the policy, `picks.sync` after the orders), `core/exits.py` (`withdraw` kind and `_withdrawals`), `core/session.py` (one line in `report_day`),
  `core/__init__.py` (DEFAULTS), `configs/core.toml` (the `[picks*]` tables), `app/runtime.py` (one line: `register_picks_live`).

## Exposed for screens
* `picks.status(con, market, day)` -> {market, on, share (see below), picks: [{pick_id, symbol, isin, source, state, thesis, break_condition, storylines, proposed_on, days_held, weight, state_reason}], needs_learned, last_learned}.
* `pick_share.status(con, market)` -> {market, on, share, start, source, min, max, shrinking, judged_on, last_judgment{decided_on, old, new, reason, figures}, next_judgment_at_sessions, judged_every_sessions,
  system_picks_bought, no_new_picks}.
* `pick_share.report_line(con, day)`, `picks.target_weights(con, state, market)`, tables `picks_s83`, `skips_s83`, `sleeve_share_s83`.

## For the other S83 agents / the coordinator
* Tools agent: `propose(con, now, market, items, session_ref=..., learned_from=...)`, `withdraw(...)`, `skip_idea(...)` return plain dicts (`ok`/`problem` for withdraw and skip). `needs_learned(con, market)` says when `learned` is required.
  Refusals are plain sentences. An accepted item may carry a `note` ("it waits for room").
* Score agent: `pick_scores_s83` must have a `pick_id` column (read by `needs_learned`: count of distinct pick ids with a score, joined to `picks_s83` for the market). `core/pick_score.sleeve_record(con, market, day[, window])`
  must return `sessions` and `points_a_year` (or `sleeve_return_after_tax` and `index_return`). A sale made by `withdraw` is in `exit_events_s81` with kind `withdraw`.
* US agent: the US loop calls the same functions with market="US": `picks.prepare(con, now, day, "US")` (judges the US share), `picks.attach(con, us_state, "US")` (state needs `rows`, `value`, `vol`, `gauge`,
  `cfg`; rows for unheld picks from `picks.universe(con, day, "US")`), `picks.merge`, `picks.sync(con, day, "US", us_state)`. `[picks.us] on = false` until then. Sizing keeps SPY at least 30%: the picks' budget is
  `min(share, 1 - us_spy_floor)`; a pick is at most `us_stock_cap`; `propose` refuses a 13th stock and a pick when the picks already hold 69% or more.
* Strategist agent: the card's PICKS section can use `picks.status`; `pick_share.status` has the share and why.
* L6 (lab): the longterm share in `sleeves.target_shares` still comes from the allocation / defaults; `pick_share.share(con, "IN")["share"]` is the number the L5 rule owns. `baseline_v2` does not yet read it for the
  core/longterm split (that belongs to L6): the picks' room uses it.

## Tests (`tests/test_s83_picks.py`, 18)
Refusals with reasons (unknown symbol, short thesis, ETF, liquidity floor, sector rail, thin traded-value record, already a pick, `learned_from`); Kite adoption once and a thesis added to a Kite stock; an accepted
pick bought over several sessions inside the turnover cap then held (real loop, real fills); never sold to reach a share and no new pick while the share shrinks; a withdrawn pick inside the guard waits and goes
when the guard lets go; a stop fires for a withdrawn pick inside the guard; a withdrawn unbought pick is dropped; a skipped idea is price-only; the share rule +5, -5, level, bounds, cadence, no sale; the report line;
the US share; the rule's numbers pinned to the protocol text, the config and the code defaults; registration counts two tests once and catches a changed protocol; US picks obey the floor, the stock count and the SPY floor.

## Not verified / left
* The score agent's `pick_score` and `pick_scores_s83` did not exist when this was built: `sleeve_record` and the score table are read defensively and tested with injected records only.
* The US wiring (state, orders, fills, a US loop) is the US agent's: only the validation, the sizing and the share are here and tested on synthetic state; `[picks.us] on = false`.
* The real India traded-value panel was not read (synthetic injection in tests); on the real store `panel/prices.parquet` must carry `turnover` (it does in the lab's panel build).
