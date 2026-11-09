# S81 core-lab notes (B1 baseline_v2, B2 allocation owned by the strategist, B3 promotion A50, A55 throttle)

Branch: `worktree-agent-a893206e5a63a3e31` (worktree of the core-lab agent). Migrations 108-112 in `src/pflab/pm/mig_s79/m_core_lab.py`. Tests: `tests/test_s81_core_lab.py`.
Decisions are dated 2026-11-09 (night, unattended; his answers in the appendix of `docs/s81_autonomy_loop_prompt.md` were followed).

## What is built

### B1 `baseline_v2` (`src/pflab/core/baseline_v2.py`, `sleeves.py`, hooks in `policy.py`, `state.py`, `loop.py`)
- `policy.active_id()` / `decide_active(state)` / `universe(con, day, cfg)` / `registered()`: `[baseline_v2] version` ("v2" default, "v1" the safe fallback) picks the baseline. `policy.decide` is
  untouched (baseline_v1, the S80 tests).
- `state.build` now adds the configured core ETFs as rows with no quantity (`extra_isins`), a `sleeve` on every row and `state["sleeve_target"]` (fractions of the book).
- `baseline_v2.decide`: core ETFs (index, gold, international) are BOUGHT toward the target, each group split by inverse volatility, held to the 35% ETF rail; longterm names stay as they are
  (bought toward their risk size only while the sleeve is under its share; a name over the 10% company rail is trimmed to it); swing share held back as cash; fall gauge cuts every equity
  position by `gauge_cut` (gold and international untouched). NO stock is sold to reach a sleeve share; positions above target are held. New cash and sale proceeds go to the core first, then to
  longterm names under their size; the swing share (5% by default, `swing_reserve`) is not spent. `state["no_buy"]` (a set of ISINs) is honoured so the US agent's premium-to-NAV rail can block an international ETF.
- Default starting target in `configs/core.toml [baseline_v2]`: core 60, longterm 35, swing 5, gold 10, international 10 (of the book; index = core - gold - international = 40).
- Core ETF list (symbols the store knows, `instruments`): index `MONIFTY500` (INF247L01BU1, Motilal Oswal Nifty 500 ETF), `NIFTYBEES` (INF204KB14I2), `JUNIORBEES` (INF732E01045, Nifty Next 50);
  gold `GOLDBEES` (INF204KB17I5); international `MON100` (INF247L01AP3, Nasdaq 100). JUNIORBEES is a third index ETF so that an index-only book can sit in the index under the 35% single-ETF rail.
  Store prices for all of them exist from 2026-09-21 (35 sessions, Kite feed); `MONIFTY500` also has bhavcopy history from 2023-10-06, `MON100` from 2021-06-18, `NIFTYBEES`/`GOLDBEES` from 2004/2007
  (the panel merges the 2019-12 ISIN change by symbol). `NIF500BETA` (UTI Nifty 500) has only 48 days; `MASPTOP50`, `MAFANG` are alternatives for international if `MON100` trades at a premium.
- Lab replay of an ETF with no history: `runner.CORE_SYNTH`: `ETF:MONIFTY500` = Nifty 500 TRI x (1 - 0.20%)^years; `ETF:MON100` = Nasdaq Composite (price) x USDINR x (1 - 0.60%)^years, taxed as non-equity.
  Both costs are stated ESTIMATES (Indian index ETFs charge about 0.04%-0.25% a year and track slightly below the index; an overseas-index ETF about 0.6% plus a larger tracking gap; not read from a primary
  source tonight). The Nasdaq series is a PRICE index (no dividends, about 1% a year short of a total-return series). Neither ticker has price history in the 2005-2017 test panel: said here and in `meta["modelled"]`.
  `baseline_lab` (the plain reference the screen compares with) excludes the two modelled ETFs, so its scorecard is unchanged.
- `sleeves_s81` (108), `core/sleeves.py`: `sleeve_of(con, isin, market="IN")` (table, else ETF/gold/international -> core, else longterm), `set_sleeve` (first record sticks, `force=True` moves),
  `sleeve_weights(con, market, day)`, `tag_order`, `target_shares`, `default_shares`, `check_proposal`, `CAPS`. `core/loop.py` tags each position as its order is placed.
- `loop.ensure_policy` lists both baselines; while no lab policy is champion the config's baseline is champion, the other `previous`.

### B2 allocation owned by the strategist (`src/pflab/lab/alloc_lab.py`, tool in `lab/tools.py`, hooks in `lab/strategist.py`)
- Tool `propose_allocation(classes, sleeves, sectors, reasons)`: code checks the rails (`paper/allocation.validate_target`: classes sum 100, no negatives, sectors <= 25%) and the sleeve caps of his
  answer (`sleeves.check_proposal`: swing <= 20, longterm <= 60, core >= 30, sum 100, gold+international+cash inside the core), stores a PROPOSED target through
  `paper/allocation.propose_allocation` (kept, no longer dead) with its sleeve shares (`allocation_sleeves_s81`, 110) and a lab policy `alloc_t<id>` (status draft) that stands for it. The same split again
  is a re-examination (recorded, the review date moves a week). `targets.toml` is never read or written.
- `alloc_lab.tick` (called from `strategist.tick` before the session reasons; free, no paid call, idempotent): seeds the candidates, runs history replays for family members with none, then adopts by the A50 rule:
  a proposal becomes ACTIVE (`allocation.review_target(approve)`) when its history passes the index rule, its history after-tax return is above the current allocation's, and its once-only 2018-2021
  check passes the same rule; otherwise it is `reject`ed with the reasons. Verdicts and figures in `alloc_verdicts_s81` (111).
- A50b "the system owns the index": when the CURRENT allocation fails the index rule on 2005-2017 and `index_hold` passes, an index-only target (core 100) is adopted by code (`index_fallback`
  switch, default true). See "decision needed" below.
- Weekly re-examination: the first message of every session carries `alloc_lab.status_text` (allocation in force, caps, candidates against the index); the weekly reason reads "the weekly session (re-examine the allocation)";
  the SYSTEM prompt tells the strategist the allocation is its own.
- Tool count is now 17 (`propose_allocation`); S80 tests that said 16 now say 17.

### B3 promotion A50 (`lab/service.py`, `lab/promotion.py`, `lab/probation.py`, `lab/engine.py`, `core/screens.py`, `redesign.js` one line)
- `service.INDEX_RULE` / `index_rule(score)` REPLACE `INDEX_CLAUSE` / `index_clause` (kept as aliases of the new names): pass if (lag <= 2 points a year AND worst fall no deeper than the index's, within
  0.5 point of measurement noise) OR (lag <= 4 points AND worst fall at least one third smaller). The 0.5-point `fall_tol` is MY addition (an index-like candidate otherwise flickers on a hair); change it in `INDEX_RULE`.
- Both sides after tax and charges, in the engine score (`engine.score`, new fields, old ones unchanged): policy side `cagr_liq` = sold out on the last day (FIFO lots, charges, the book's tax buckets and
  year set-off); index side `bench_cagr_liq` = the total-return index held as an ETF: yearly ETF cost 0.20% (estimate, `DEFAULT_CFG["index_etf_cost"]`), buy and sell charges at the ETF rate, one sale at the end
  taxed long-term above the Rs 1,25,000 exemption. Also `bench_max_drawdown_net`, `index_tax_at_end`, `index_charges`, `policy_tax_at_end`, `excess_liq`. A run that predates these figures cannot pass the rule.
- `promotion.check`: history screen vs the baseline + index rule (+ not behind a lab champion) + the once-only final check (same index rule on the 2018-2021 score). The shadow requirement is GONE (shadow alone no
  longer blocks acting). `promotion.promote_ready` now GRANTS A PROBATION SLICE (never makes the champion); `promote()` (outright replacement) and `rollback_check` are kept.
- `probation_s81` (109), `lab/probation.py`: `slices(con, day) -> [{policy_id, share, since}]` (the function the loop asks), `grant` (5% at once, refused when the slices would pass `max_total_share` 20%),
  `review(con, now, day)` (grows 5 -> 10% after 20 sessions and 10 -> 20% after 40 sessions since the grant while the live record vs the champion's stand-in is not worse than `tolerance` 0.2%; withdraws when it is
  worse after at least 10 sessions), `record`, `blend(champion_weights, {policy: weights}, slices)`, `explain(con, day, policy_id)`, `history`. `review` is called from the `lab_close` job (`service/tasks_s79_lab.py`).
  The live record is the shadow record (flat charges, no tax: both sides on the same footing).
- `core/screens.py`: each challenger carries `slice` and `slice_why`; `policies()["slices"]`, `index_rule`; `redesign.js`: one small muted line per challenger ("trades 5% of the book: ..." / "no slice: ...") and the
  held-back line names the new rule.
- Seeding: `alloc_lab.seed` registers `index_hold` ("hold the index ETFs": 98% in the three index ETFs) and `alloc_default` (the starting target as a variant) once each (idempotent), drafts that are not
  shadowed or sliced (they are allocation candidates, adopted through `alloc_lab.tick`).

### A55 throttle switch
- `configs/core.toml [strategist] throttle_after = "2026-12-09"` (release plus 28 days); `core.throttle_active(day)`. `strategist.session_budget` records both halving rules in `why` ("recorded, NOT applied
  before ...") and applies them only from that date; the "tell him after 8 weeks" message waits too; the per-session cap stays Rs 300. Tests for the old halving rules turn the date back (`_throttle_on`).

## Real path (scratch store, never the live one)
Copy of the app's store at D:\s81_scratch\core_lab, workshop data (panel rebuilt, 4471 days x 606 columns incl. the two modelled ETFs), Docker sandbox (`contained: True`), `service.run_lab` exactly as the S80
strategist session ran it, n_shuffles 0 (luck is not the question for a fixed split), then the final check once per variant, then `alloc_lab.tick`. Files: `D:\s81_scratch\core_lab\realpath.py`, `realpath2.py`,
`realpath_history.json`, `realpath_final.json`, `realpath.out`.

History 2005-2017 (Rs 10 lakh start; both sides after tax and charges, sold out on the last day):

| row | return a year (after tax) | index (ETF, after cost, charges, tax) | lag | worst fall | index worst fall | index rule |
|---|---|---|---|---|---|---|
| `alloc_default` (baseline_v2's lab reading: 40 index, 10 gold, 10 Nasdaq, 35 liquid stocks, 5 cash, gauge, no sale to rebalance) | 10.88% (cagr after tax paid in the path 11.34%) | 14.32% | 3.44 points | -50.8% | -63.8% | FAIL (needs 2 points with a no-deeper fall, or 4 with a fall a third smaller: it is 80% of the index's) |
| `index_hold` (35% Nifty 500 ETF + 35% Nifty 50 ETF + 28% Next 50 ETF, 2% cash) | 12.42% (13.03%) | 14.32% | 1.89 points | -59.7% | -63.8% | PASS via A |
| plain baseline `baseline_lab` | 9.25% | benchmark 15.55% raw | | -60.0% | | (not rule-checked: no after-tax figures in its old run) |

Full cards: `alloc_default` sharpe 0.356, DSR 0.871, turnover 0.36 a year, tax paid in path Rs 20,787, charges Rs 12,406, end value Rs 39.2 lakh, tax at the end Rs 1.94 lakh, days to recover 1,809;
`index_hold` sharpe 0.405, DSR 0.890, turnover 0.22, tax Rs 14,839, charges Rs 8,235, tax at the end Rs 3.09 lakh. Index side: ETF cost 0.20%, charges Rs 9,416, tax at the end Rs 6.24 lakh, end after tax Rs 54.9 lakh.

Final check 2018-2021 (the once-only window; after the engine fix below): `alloc_default` 9.47% vs index 11.62% (lag 2.15 points, fall -31.9% vs -38.1%: FAIL by 0.15 point), `index_hold` 9.06% vs 11.62%
(lag 2.56, fall -36.1% vs -38.1%: FAIL), baseline over the window 5.32% (benchmark 13.0% raw).

`alloc_lab.tick` then adopted the index-only target (id 2) by A50b on the scratch store: reasons written by code, `proposed_by` "the lab (A50 index rule)".

### BUG FOUND AND FIXED in the real path (shared file `lab/engine.py`)
`promotion.final_run` runs `evaluate(..., n_shuffles=0, n_mc=0)` and `engine.monte_carlo(v, 0)` raised `IndexError` on empty arrays, so the once-only 2018-2021 check could NEVER run for real
(the S80 tests mocked `final_run`). Fixed (`n <= 0 -> {}`), regression test `test_the_final_check_setting_of_no_monte_carlo_no_longer_raises`.

## Decisions needed from him / the coordinator (the facts, not options)
1. The starting split (core 60 / longterm 35 / swing 5) FAILS his index rule in the lab (3.4 points a year behind after tax, fall only 20% smaller) because the lab's longterm sleeve is a proxy (30 liquid
   stocks, risk-sized): the plain baseline's stock book trailed the index by 6 points a year in 2005-2017. With `index_fallback = true` (default) the first `alloc_lab.tick` therefore makes the active target
   index-only (core 100): the live book would buy MONIFTY500/NIFTYBEES/JUNIORBEES up to 35/35/28% with its cash and hold its eight stocks. Set `[baseline_v2] index_fallback = false` in `configs/core.toml` to keep
   his 60/35/5 start regardless (the coordinator should decide before the release; I did not touch his targets).
2. Under the 35% single-ETF rail the system cannot hold exactly the Nifty 500: even "index only" in the lab lags the Nifty 500 total-return index by 1.9 points (history) and 2.6 (final) after tax and cost
   (mix of Nifty 50 / Next 50 / 500, 2% cash). Raising the rail for a broad index ETF is his decision.
3. The ETF cost estimates (0.20% index, 0.60% Nasdaq) and the 0.5-point fall tolerance are mine; change in `runner.CORE_SYNTH`, `engine.DEFAULT_CFG["index_etf_cost"]`, `service.INDEX_RULE`.

## What the coordinator must wire (I did not touch beyond the hooks listed)
- `core/loop.py` (already hooked: baseline choice, ensure_policy, sleeve tag). TO WIRE for probation slices: after the champion's `dec`, `sl = probation.slices(con, day)`; for each slice run its policy
  (`live.decide(con, root, day, service.get(con, s["policy_id"]), holdings, data=live_data)`, converting panel keys to ISINs as `live.decide` does) and `dec["weights"] = probation.blend(dec["weights"], slice_weights, sl)`
  BEFORE the views merge; the decision text should name the slice policy. `probation.review` already runs in `lab_close`.
- Sleeve caps for the swing agent: `sleeves.set_sleeve(con, isin, "swing", day)` when it opens a position (the loop's `tag_order` defaults to the instrument's sleeve; `tag_order(..., sleeve="swing")`).
- US agent: `state["no_buy"]` for the premium rail; `market` is a parameter of `sleeve_of`, `set_sleeve`, `sleeve_weights`, `alloc_lab.propose`, `current_variant` (the loop's ISIN-keyed state is still IN only).

## Shared files touched
`core/__init__.py` (defaults, `baseline_version`, `throttle_active`), `core/loop.py`, `core/policy.py`, `core/state.py`, `core/screens.py`, `lab/engine.py` (score fields, `index_after_tax`, `liquidation`, Monte Carlo n=0 fix),
`lab/runner.py` (CORE_SYNTH panel columns, cache rebuild once), `lab/service.py` (INDEX_RULE, index_rule, screen_rules, baseline ids), `lab/promotion.py`, `lab/shadow.py` (baseline ids), `lab/strategist.py`
(prompt, throttle, allocation hooks), `lab/tools.py` (propose_allocation, compare), `lab/policies/baseline_lab.py` (excludes the two modelled ETFs), `service/tasks_s79_lab.py` (probation review),
`app/static/redesign.js` (two lines), `configs/core.toml`. NOT touched: `docs/PLAN.md`, `docs/BUILT.md`, `CLAUDE.md`.

## Tests
`tests/test_s81_core_lab.py` (27): baseline_v2 buys core ETFs and sells nothing; gradual path (no stock sale, cash to the core, swing held back, core never above target); gauge and rail trim; the loop runs v2 and tags sleeves;
v1 fallback; unknown ETF named; default target; sleeves; sleeve caps refuse bad proposals (swing 20.5, longterm 60.5, core 29, sum 95, gold+intl over core, sector 25); the tool; first message; the rule on four
hand-made pairs (+ edge cases); both sides after tax (engine); candidates seeded once; allocation variants replay and buy the core ETFs; adoption (adopted, rejected, final-check failure, index owned);
probation 5/10/20, withdrawal, room and blend; screens show slice and why; throttle (not applied before 2026-12-09, applied after, config switch); migrations; modelled ETFs; the final-check n_mc=0 fix.
Changed for the replaced rule / baseline: `tests/test_s80_lab_promotion.py` (shadow no longer a gate; `promote_ready` grants slices; index test rewritten to the two-dimension rule; GOOD score carries the after-tax figures),
`tests/test_s80_core.py` (policy id is `policy.active_id()`), `tests/test_s80_strategist.py` (weekly reason text, 17 tools, halving tests turn the throttle date back), `tests/test_s80_tactical.py` (17 tools).
