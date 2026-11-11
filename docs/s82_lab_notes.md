# S82 lab agent notes (C3 the 60% broad-index limit and the fallback scoped to the India core; C4 the two registered studies)

Branch `s82/lab` (worktree `D:\s82_wt\lab`), based on the coordinator's C10 commit 1960e33. Migration 160 (`pm/mig_s79/m_lab82.py`, table `c4_study_s82`). Tests: `tests/test_s82_lab.py` (new, 23 tests)
and `tests/test_s81_core_lab.py` (rewritten where the swing sleeve or the old index-only target was asserted).

## What was built

### C3 the limit
* `configs/core.toml [rails]`: `broad_index_etfs = ["NIFTYBEES", "MONIFTY500"]` (JUNIORBEES, the Nifty Next 50, is not broad), `broad_index_cap = 0.60`. The defaults sit in `core/__init__.py` too.
* One function everywhere: `paper/rails.py` `limit_of(asset_class, symbol)` / `etf_limit(symbol)` / `broad_index()`. Used by `core/policy.cap_of` (so baseline_v2, the v1 baseline and `rails.clip_weights` see it),
  `core/rails.py` (docstring only: it calls `cap_of`), the fill-time cut `paper/rails.buy_room` and `flags`, the exit manager's rail trim (`core/exits.py`), `construct/run.py` (the `pflab pm propose` bounds),
  `paper/allocation.validate_target` (its printed rails) and the lab replay (`lab/engine.position_cap`, used by `clip_weights`, the state's `caps` in `engine.py` and `swing.py`).
* The replay agrees with the live rails: `runner.cost_config()` puts `broad_syms` and `max_broad_etf` (read from the config) into every job's cfg; `engine.DEFAULT_CFG` carries the same defaults, so a job folder
  without them still applies 60% to the two broad ETFs. A test compares `engine.position_cap` with `hard.limit_of` for five symbols.
* The denominator: `paper/rails.rails_denominator(con, day)` is THE HOOK. It returns the whole book (`pflab.us.wholebook.whole_book_inr(con, day)["whole_inr"]`) when that module imports and answers, else the
  rupee book; a failure there falls back to the rupee book. `buy_room` uses it (`max(rupee book, whole book)`). `core/rails.clip_weights` still works on `state["value"]` (the loop's own total): the coordinator
  must make `state["value"]` the whole book when it wires the US agent's function, or point `clip_weights` at `rails_denominator`; I did not touch `core/state.py`.

### C3 fault 2: the fallback scoped to the India core
* `alloc_lab.adopt_index_only` now KEEPS the sleeve shares (from the active target, or the starting default 60/40), the international share and the cash share, moves only the core's gold into the broad index ETFs.
  With the starting default the adopted target is: equity 90 (index 50 + longterm stocks 40), gold 0, international 10, cash 0; sleeves core 60 / longterm 40. A stored target that is S81-style (core 100, longterm 0)
  is not "a split to keep": it reads as the starting default. By `"the lab (A50 index rule, S82 scope)"`.
* The lab candidate is now `index_hold_s82` (a NEW id: its logic changed, so its once-only final window is its own). Its params: `alloc_lab.index_only_params()` = the starting allocation with gold added to idx,
  idx_syms = the broad ETFs only; sleeves and international as the default. The S81 `index_hold` is retired by `tick` (kept for the record). `INDEX_ONLY_SYMS` is gone (nothing read it).
* `alloc_lab.rescope_old_index_only(con, now)`: detects an ACTIVE target adopted by `"the lab (A50 index rule)"` with core 100 / longterm 0 / no international, replaces it by the scoped one with a dated note,
  writes an `alloc_verdicts_s81` row; idempotent (the second call finds nothing; any other active target, or none, is left alone). `tick` calls it first and retires the old variant.
* The US sub-book's own state (`us_*_s81`) belongs to the `us` agent and is not read here; the drill-style test asserts on the adopted target's classes, sleeves and international share (the share that book is
  funded to hold) and on the baseline's `sleeve_target` after adoption.

### C3.3 the real re-run (Docker sandbox, real 2005-2017 panel, after tax, charges and slippage, 60% limit; `docs/research/c3_alloc_results_s82.json`)
Run on a COPY of `D:\PL_backup\s82_pre_20261111\ledger.duckdb` in `D:\s82_scratch\lab\store2` (the live store was never opened). The 2018-2021 window was NOT run: no variant passed the history screen.

| variant | return a year after tax | Nifty 500 index held as an ETF | lag | worst fall | index worst fall | index rule (A50) |
|---|---|---|---|---|---|---|
| `alloc_default` (core 60 / longterm 40; gold 10, international 10) | 10.86% | 14.32% | 3.45 points | -51.6% | -63.8% | FAIL (lag over 2; the fall is 81% of the index's, not a third smaller) |
| `index_hold_s82` (the corrected index-only variant: gold into the two broad ETFs, sleeves and international kept) | 10.78% | 14.32% | 3.54 points | -51.2% | -63.8% | FAIL |
| the PURE index (diagnostic, not stored, not a trial: 98% in the two broad ETFs, nothing else) | 12.05% | 14.32% | **2.26 points a year** | -58.1% | -63.8% | FAIL (lag over 2.0; S81's 1.9 on the history under the 35% rail used three ETFs including JUNIORBEES) |

* The new lag of the index-only variant against the Nifty 500 under the 60% limit: 2.3 points a year on the history for the pure index (S81 1.9 under 35%), 3.5 for the scoped variant that keeps the 40% stock sleeve.
  The pure-index lag did not shrink because the limit is not what binds: two ETFs at about 49% each never touch 60%; the S81 variant held JUNIORBEES (the Next 50 did better than the Nifty 50 over 2005-2017), and the
  broad list drops it. The final window (2.6 in S81) is not re-run: a variant must pass the history screen first.
* The current allocation's figures are essentially S81's (10.88% then, 10.86% now): its ETFs sit well under any cap.
* Would `index_fallback` adopt index-only now? **No.** The current allocation fails the index rule and the scoped index-only variant fails it too (it still carries the stock sleeve, which is what lags in the replay),
  so `tick` adopts nothing. `index_fallback` stays `true` (not changed). Decision for the coordinator / him: the fallback as the brief defines it can only fire if the stock sleeve is not what drags the history; the
  honest reading of the replay is that the 40% stock sleeve (liquid-name stand-ins, not his picks) costs about 1.3 points a year of the book's return after tax against holding the broad ETFs for it (3.54 against 2.26), and a pure-index book would also fail
  the rule (2.3 lag). Nothing to do tonight; flagged.

### C4 the two registered studies
* Protocol FIRST: `docs/protocols/s82_harvest_stops_protocol.md` (commit 6835be8, before any code or run), then amendment A1 (98% invested; deploy once; a four-year sample was run to find a deployment bug before the
  amendment, disclosed in the file; commit bf7530f), then registration and the real run. The SHA of the file (line ends normalised) is in the counter rows.
* Code: `lab/c4_replay.py` (self-contained replay side: `BuyHoldBook`, `claim_a`, `claim_b`, `run_all`; runs in the sandbox through `lab_runner` `mode: "c4"` and on the host in the tests), `lab/c4_study.py`
  (`RULE`, `RULE_A1`, `register`, `protocol_ok`, `claim_a_verdict`, `claim_b_verdict`, `switches`, `run`, `apply_recorded`), `learner/s79.register_c4` (called from `app/runtime.py` next to `register_swing`),
  table `c4_study_s82`. Small hooks in `lab/swing.py`: `track_liq` (the liquidation-marked daily path), `deploy_once` (a buy-and-hold book is deployed once and never rebalanced; the "first deployment" is the first
  decision that names something), `E.position_cap` in the state's caps; `lab/runner.py` copies `c4_replay.py` into the job and carries the broad list; `lab/lab_runner.py` has the `c4` mode.
* The run: once, Docker sandbox (`contained: true`), real panel, 39 seconds, N = 98 after registration (store copy), bar `t_needed(98)` = 3.28. Result: `docs/research/c4_study_results_s82.json` (with the protocol SHA).
* The statistic (the protocol's section 4): the paired block bootstrap of the daily difference of the two LIQUIDATION-MARKED paths (each session's value if everything were sold that session), not of the plain value
  paths (a harvest changes the tax OWED, which a plain value path only shows at the end). A single path needs it to say whether the gain is distinguishable from the path's own noise; it cannot make one path many.

## The numbers, in plain words (Rs 10 lakh start, 2005 to 2017, after tax, charges and slippage, today's tax rows applied to the whole window)

**C4a, harvesting (exemption and loss) with versus without. Both arms FAIL; harvesting stays OFF for `core` and `longterm` (`harvest_core` / `harvest_longterm` = false, unchanged).**
* Index ETF held (the core): harvesting saved Rs 1.75 lakh of tax at the end (liquidation) against Rs 8,900 of extra charges and slippage, and lifted the yearly return after tax by 0.18 points (14.25% to 14.43%).
  It passes the money test and the size test in the protocol (over 0.05 points; tax saved over extra costs) but its paired t is 0.44, far under the learner's bar of 3.28 (N=98): one path, a small difference.
* Buy-and-hold stock book (20 liquid names bought on 2005-03-31, never rebalanced; the longterm sleeve): saved Rs 1.55 lakh of tax against Rs 11,300 of extra costs, +0.35 points a year (10.73% to 11.08%); paired t 1.04.
  Also under 3.28.
* In plain words: harvesting does save tax in a long-held book (more than it costs), and the saving shows up as a third of a point a year at most; but the one history we have cannot show that this is more than the
  luck of that path at the bar the learner demands after 98 tests. By the pre-registered rule it is not switched on. (A rerun with changed parameters is a new registered study.)

**C4b, risk-sized stops on long-term stocks. FAIL; `[exits.longterm] stop = false` is SET in `configs/core.toml` (and in `core/exits.DEFAULTS`).**
* Worst fall: 56.3% without stops, 50.9% with them: a cut of 10% (relative), the rule asks for at least 20%.
* Yearly return after tax: 10.16% without, 9.11% with: the stops cost 1.05 points a year, the rule allows 1.0.
* 11 stops fired in 13 years; nearly every distance sat at the 35% cap (the 2005 volatility of these names is high). The thesis-break sale, the rail trims and the fall gauge are untouched. Both numbers miss, so the
  rule is not close to a coin flip on the cut (10% against 20%).

## Decisions (dated 2026-11-11, mine, for the record)
1. `index_hold_s82` is the lab's index-only candidate and models what the live fallback does (the sleeves and international kept). The pure-index run is a diagnostic recorded in the results file only (it would be one more trial in the deflated Sharpe).
2. The old `index_hold` variant is retired, not deleted (its history rows stay); an S81-style active target is replaced by `rescope_old_index_only` at the next `tick`.
3. The broad-index limit is applied to symbols, from config; `max(rupee book, whole book)` as the buy-room denominator while `wholebook` is absent or failing.
4. C4's capital is Rs 10 lakh (the S81 study's), 98% invested; the exemption is therefore a bigger share of the gains than in a bigger book (stated in the protocol; it favours harvesting, which still failed the bar).
5. `exits.DEFAULTS["longterm"]["stop"]` is set False with the config (a file that cannot be read leaves the same behaviour).
6. The rewritten core-lab tests also cover the swing-sleeve leftovers (nine tests failed on `main`'s C10 commit for `swing`): `tests/test_s81_core_lab.py` is now green (27 tests). The 11 failing tests of `tests/test_s81_exits.py`
   at the C10 commit are the coordinator's and are untouched by me (the stop default change above can move a few of them: check after the merge).

## What is OFF and why
* Harvesting: OFF per sleeve (unchanged; the study failed both arms). Stops on long-term stocks: OFF (the study failed). Nothing of mine sits behind an off-by-default switch otherwise.
* `index_fallback = true` is unchanged; it simply does not fire on this history (see above).

## Shared files touched
`configs/core.toml` (`[rails]` two keys; `[exits.longterm] stop = false`), `core/__init__.py` (rails defaults), `core/policy.py` (`cap_of`), `core/exits.py` (rail trim; DEFAULTS), `core/rails.py` and `core/baseline_v2.py`
(docstrings only), `paper/rails.py`, `paper/allocation.py` (printed rails), `construct/run.py` (bounds), `lab/engine.py`, `lab/swing.py`, `lab/runner.py`, `lab/lab_runner.py`, `lab/alloc_lab.py`, `learner/s79.py`,
`app/runtime.py` (one line), `tests/test_s81_core_lab.py`. New: `lab/c4_study.py`, `lab/c4_replay.py`, `pm/mig_s79/m_lab82.py`, `tests/test_s82_lab.py`, the protocol, two results files, this file.
Not mine but stale after this change (for their owners): the strategist's system prompt in `lab/strategist.py` still says "an ETF 35%" and "swing at most 20%"; `lab/tools.py`'s description of `propose_allocation` still mentions sleeve caps
that include swing.

## Exposed for screens
* `paper.rails.broad_index() -> (frozenset of symbols, cap)`, `limit_of(asset_class, symbol)`, `describe()["one ETF"]` (now names the 60%), `rails_denominator(con, day)`.
* `alloc_lab.status_text(con, now)` (unchanged shape) now lists `index_hold_s82`; `alloc_lab.tick(...)["rescoped"]` and `["adopted_index_only"]` carry what the repair or the fallback did (classes, sleeves).
* `c4_study.stored(con, kind)` (`kind` in `a_index`, `a_stocks`, `b_stops`) -> {verdict, summary, ran_at}; the summary holds both arms' figures; `docs/research/c4_study_results_s82.json` for the whole record.

## Tests added
`tests/test_s82_lab.py`: limits by symbol; `cap_of` and `clip_weights` (60% allowed, a 40% non-broad ETF cut to 35%, stock 10%); fill-time `buy_room`; the denominator hook (fake whole-book module and its failure);
the exit manager reads the same limit; the lab replay agrees with the live rails (five symbols; state caps in a real replay); the index-only variant's params; the fallback keeps the US share and the sleeves; it keeps
the ACTIVE target's own split; the repair (once, dated, idempotent, leaves other targets alone); `tick` repairs first and retires the old variant; the C4 rule against the protocol's JSON blocks; registration counts three tests once
and a changed protocol is caught; claim A and claim B verdicts at their edges; the recorded result against the rule and `apply_recorded` once; the buy-and-hold book never rebalances and waits for enough names; a stop is
applied or not by the switch; the stop distance is the live exit plan's rule; claim A on a synthetic book; the runner job carries the C4 files.

## What is left
* The coordinator: `docs/STUDIES.md` (two verdicts and the 3 counted tests), `docs/PLAN.md` / `BUILT.md`, the strategist prompt text, `rails_denominator` / `state["value"]` wiring once `us.wholebook` lands.
* A study of the stock sleeve's lag (about 1.3 points a year against the broad ETFs after tax) belongs to the strategist's lab, not tonight.
