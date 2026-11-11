# S83 strat: L3 (the strategist's session), L6 (the lab stays consistent), L8 (the first picks)

Branch `s83/strat` (based on `pm/s83-learning` ca15bce, then `pm/s82-gaps` merged in for the lab agent's C3/C4). Migration 195 (`m_strat83.py`; 196-199 spare).

## What is built

### L3 the strategist names stocks
* SYSTEM text: the two A63 lines rewritten ("You do not trade. You may name stocks for the picks sleeve through `propose_picks`, each with a thesis; you never write a size, a price or a weight" and "Every
  number comes from code. You never write a size, a price or a weight into a decision: you write rules, and you name stocks with reasons"), a PICKS step (6) added to the session, `write_note` is step 7,
  the wasted-session line says "no lab run and no pick named, withdrawn or skipped", and the allocation bullet says the longterm share is the picks rule's. The rest is as it was.
* Tools (`lab/tools.py`): `propose_picks(market, items:[{symbol, thesis, break_condition, storylines}], learned_from)`, `withdraw_pick(market, symbol, reason)`, `skip_idea(market, symbol, why)`; thin
  wrappers over `core/picks.propose/withdraw/skip_idea`, `session_ref` = "strategist session <id>", refusals in plain words (`problem`), no size/price/weight argument anywhere (a test walks the schemas).
  Descriptions at most 480 characters (the cap test counts 22 tools now: raised from 19 in `test_s80_strategist` and `test_s80_tactical`).
* `write_note(text, learned)`: `learned` (40+ characters) is REQUIRED once `picks.needs_learned` is true for a market whose picks are on; `propose_picks` refuses a batch with `learned_from` under 40
  characters in the same case, with a clear message (the tool checks first; `picks.propose` enforces the same). The note's `learned` part is kept in `core_notes_s80.learned` (migration 195);
  `service.write_note(..., learned=)`, `service.notes()` shows it, `service.last_learned(con)`.
* First message: the fresh PICKS SCORE (`pick_score.scorecard_text` for IN and US) and the PICKS section (`core/picks_card.build`) go in beside the allocation status; earlier notes show their `[learned: ...]`.
* A session that names, withdraws or skips a pick but runs no lab is NOT "wasted" (stats `picks`, `skips`; the code-written note covers it).
* The book card (`core/card.py`): `facts["picks"]` = `picks_card.build` (per market: share, why, room, each pick's one-line thesis, days in the book, state, weight, result against the index at its longest scored
  horizon from `pick_scores_s83`, the break condition; `learned` = the newest note's learned part) and one text block (PICKS, India / PICKS, US / WHAT I LEARNED). The score agent's PICKS SCORE block is untouched.
* `needs_learned` FIX (the picks agent's file): it joined `pick_scores_s83.pick_id`, but the score agent's table has `kind` and `ref_id`, so it silently returned False in production. It now counts distinct
  `ref_id` with `kind='pick'`. The picks test that built its own table was rewritten against the real table.

### L8 the first picks
* `lab/first_session_s82.py`: a second once-only key `first_picks_s83` in `strategist_first_s82` (no new table). `reasons()` returns the reasons still pending (`REASON`, `REASON_PICKS`); when both are
  pending it is ONE session (the picks step is in every brief) and `after_session`/`waiting` move both keys together; when the S82 session already ran, one session for the picks alone. Idempotent; a failed or
  waiting first picks session leaves the book as it is; a paid failure counts, two stop it.
* At that first open `picks.adopt_kite_holdings` runs (idempotent; in `strategist.tick`, before the cap check).
* Today: `core.card.today_extras(con)["picks"]` = `{line, IN, US, learned}`; `line` = `first_session_s82.picks_line(con)` = "no picks yet: <reason> ...the book holds what it holds (his Kite stocks, the core and SPY)"
  until the system has named a pick (None after). `core.screens.view` merges it (key `picks`).
* US wiring, `[picks.us] on = true` (configs/core.toml and `DEFAULTS`): `us/picks_wire.py` (`symbols`, `extra_weights`), `us/policy.build(pick_syms=)` (picked names are rows, buyable with a bar today, vol from their
  own bars), `policy.decide(extra=, core_total=)`, `us/adapter._session` (prepare, attach, decide with the picks, sync). The picks' total is held to `invested_share - SPY floor` (0.95 - 0.30), so SPY's target is
  never under 30%; a stock at most 10% (the sub-book's cap), at most 12 stocks (`picks.propose`). Any failure of the picks part leaves the core decision as it was and says so in the run note.
  A withdrawn US pick has target 0 and is sold at the next US open (the 12-month guard is the rupee book's; the US has no counterpart yet: stated in the order's reason, estimated tax included).

### L6 the lab stays consistent
* `propose_allocation`: a proposal that changes the longterm share is taken for its other fields, keeps the live share and is told "the longterm share is set by the picks rule (S83 L5), not by a proposal"
  (tool hook `_keep_longterm_share` and the same in `alloc_lab.propose`, key `longterm_share`).
* `core/sleeves.target_shares` returns longterm = `pick_share.share(con, "IN")["share"]` and core = the rest (index = core - gold - international - cash), through `with_pick_share`; `baseline_v2` reads it
  through `state["sleeve_target"]` and keeps `longterm_buy_pct` as the cap for his held names that are not picks. `target_shares_raw` is the old stored/default read.
* `alloc_lab`: `default_params`, `index_only_params`, `candidates`, `proposal_params` take a `con`; with it the liquid-stock stand-in for the picks sleeve carries the LIVE share, for the candidates seeded
  and for a proposal, so picks neither help nor hurt a core proposal. `adopt_index_only` and `rescope_old_index_only` keep classes except gold, and the longterm share is the picks rule's.
  Limit: a candidate seeded earlier keeps the share it was seeded with (its history run is cached); a later judgment moving the live share does not re-seed it.
* Rewritten (behaviour changed by design): `test_s82_lab::test_the_fallback_keeps_the_active_targets_own_...` (the longterm share is now 40, the picks rule's, not the target's 45).

## Decisions (2026-11-12)
1. The weekly session covers both markets through the SYSTEM text and the first message (both markets' scorecard and PICKS sections are always there); sessions stay inside A55 and the Rs 300 cap.
2. The reason text of a first session is joined whole (`[:700]`; the DB keeps 300) so the picks instruction is never cut.
3. The weights/room numbers on the card are code numbers from `picks.status`/`pick_share.status`; "against the index" is the scorecard's longest scored horizon for the pick (not scored before 1 month).
4. US withdraw: sold at the next open, no guard (see above). US stops: the sub-book has no exit manager yet (A59 says stops act at the next open; nothing in `us/` places one): a US pick has no stop today.

## Tests (`tests/test_s83_strat.py`, 19)
Tools registered, short, no size/price/weight; wrappers and plain refusals; `learned` required once five picks are scored (batch and note); a scripted-model session through the real `run_session`/llm/governor
(scorecard and PICKS in the first message, picks and skips, not wasted; a no-pick no-lab session still wasted); the PICKS section and the card in text and JSON; the first session + first picks is one session and both
keys move together; only the picks session after the S82 one; Kite adoption at the first open; no client / no cap room -> "no picks yet: ..." never an error; failed first picks stop after two paid failures; the line goes
when a pick exists; US pick bought beside SPY through `close_us` (SPY at least 30%, stock on its way to 10%); 12 US stocks, the SPY floor and a withdrawn pick sold; no picks = the US decision as it was; the
longterm share is the picks rule's (baseline) and a proposal that changes it is told; the index fallback changes neither picks sleeve nor positions; candidates and proposals at the live share.
Also touched: `tests/test_s80_strategist.py`, `test_s80_tactical.py` (cap 22), `test_s82_fills.py` (Today has `picks`), `test_s83_tools.py` (the migrated picks table; the three tools exist now),
`test_s83_picks.py` (real `pick_scores_s83` columns; the US floor wording of the tools agent; US on), `test_s82_lab.py` (see L6).

## Real path (L8), 2026-11-12 00:31 IST, on a COPY of `D:\PL_backup\s82_pre_20261111` (schema 102 -> 195 by this tree), deleted afterwards (log kept: `D:\s82_scratch\s83strat\real_run.log`)
Scratch `api_budget.toml` only (`dev_monthly_cap_rupees = 400`, `counted_since` = now), `PFLAB_PAID=1`, the real key (never printed), the real Docker sandbox. Data root = a scratch folder whose `us` is a COPY of
the app's `data/us` and whose other folders were junctions to the app's folders (read only; removed with `rmdir`, the app's data untouched). SEC contact: ABSENT, so the US universe was the symbols under `data/us/raw`.
* `strategist.tick`: both once-only reasons plus "the book is far from its allocation target" -> ONE session (id 2): 10 Opus calls, 19 steps, 2 lab runs, 1 note, 1 allocation proposal, 4 picks, 2 skips.
  COST Rs 24.40 (of the Rs 400 allowed; the night's S83 cap Rs 800). Both keys `done`, attempts 1. 8 of his Kite stocks adopted as picks (thesis "held from his Kite portfolio").
* India: NONE named. The model's note: "no room (the Kite stocks fill the 40%)". His stocks already hold at least the 40% share, so by L1's rule the system's picks wait for room.
* US picks (all `proposed`; the sub-book is not open in the copy, so nothing was bought), each with a thesis and a break condition (below the 200-day average or a named business event):
  LLY (GLP-1 franchise, mega-cap, liquid), ADP (payroll/HR processing, defensive, 28% volatility), TMO (life-science tools, recurring consumables), ABBV (Skyrizi/Rinvoq growth, dividend, 25% volatility).
  Skipped: MPC (refining-margin spike, rolling over), VEEV (43% volatility, too jumpy).
* What went wrong or is worth knowing: (a) the screen listed US names whose bars were from 2026-10-27; the model read cards (which refresh bars on demand) and `propose_picks` refused TMO and the skips of VLO/BBY
  as "last stored bar more than 15 days old" until the card had refreshed them: a name from a screen row must be refreshed first (the card does it; the `skip_idea`/`propose` refusal says why). (b) All four US
  picks are large-cap health/services names: there is no US sector rail (A62), so the model chose its own spread. (c) The session also tried a lab policy (traded-value weighted, failed: 7.5% a year) and proposed
  alloc_t3 (index 85/gold 10/cash 5, fails the index rule, not adopted): normal strategist work. (d) The SEC ticker file could not be read (no `[sec] user_agent` in secrets): no CIKs, so US picks are keyed `US:SYMBOL`
  until the map exists (mapped by alias later, S82).

## Shared files touched
`core/card.py` (picks section hook, `today_extras`), `core/picks.py` (`needs_learned` fix only), `core/sleeves.py` (`with_pick_share`, `target_shares_raw`), `core/__init__.py` (`picks.us.on` default),
`configs/core.toml` (`[picks.us] on = true`), `lab/strategist.py` (SYSTEM text, first message, wasted rule, tick), `lab/tools.py`, `lab/service.py` (`write_note`, `notes`, `last_learned`), `lab/first_session_s82.py`,
`lab/alloc_lab.py` (live share, `_scoped_shares`), `us/policy.py`, `us/adapter.py`. New: `core/picks_card.py`, `us/picks_wire.py`, `pm/mig_s79/m_strat83.py`, `tests/test_s83_strat.py`.
`docs/BUILT.md` should name: table column `core_notes_s80.learned`, the key `first_picks_s83` in `strategist_first_s82`, the three tools, `us/picks_wire.py`, `core/picks_card.py`.

## Exposed for screens
* `core.picks_card.build(con, day)` -> `{IN: market_block, US: market_block, learned: {when, learned, session_id} | None, text}`; `market_block` = `{market, on, share, share_why, room, no_new_picks,
  system_picks_bought, next_judgment_at_sessions, picks: [{pick_id, symbol, source, state, thesis, break_condition, days_held, weight, vs_index {horizon_months, return_pct, index_return_pct, excess_pct} | None}],
  needs_learned}`.
* Today JSON (`core.screens.view`): key `picks` = `{line, IN, US, learned}` (`line` = "no picks yet: ..." or None); key `strategist` (the newest note) as before.
* Book card JSON `facts["picks"]` (same shape as `picks_card.build` without `text`).
* `lab.service.last_learned(con)`, `lab.service.notes(con)` (each with `learned`), `lab.first_session_s82.picks_line(con)` / `state(con, "first_picks_s83")`, `us.picks_wire.symbols/extra_weights`.

## Not verified / left
* The India side of a real first pick was not exercised for real (no room under the share in the copy); India `propose` was tested synthetically and by the picks agent.
* The US picks were never bought on real data (the copy's sub-book is not open): the buy path is tested on synthetic bars through the real `close_us`.
* US stops and a US 12-month-style guard: not built (the US has no exit manager).
* `tests/test_s83_score::test_the_dollar_scenario_hits_only_the_us_sub_book` (expects `us.wholebook` absent) and `tests/test_s81_us::test_the_rail_can_be_extended_to_gold_by_a_setting` fail on the merged base and
  are not from this item (S82's `us.wholebook` and the premium rail's gold class).
