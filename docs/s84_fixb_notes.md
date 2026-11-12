# S84 fixb notes (F2, F3, F4), 2026-11-12

Branch `s84/fixb`, based on `pm/s84-thinking` (e2551bc). Released as its own tag once green.

## What is built
**F2, the US monthly cap** (`src/pflab/us/policy.py`, `check` and `_month_traded`; `[us] exempt_day_share = 0.25`, in `us/__init__.py` DEFAULTS and `configs/core.toml`).
Two kinds of order now. REBALANCING keeps the registered caps (10% a day, 40% a month, counted on what rebalancing traded). OUTSIDE the monthly cap, and limited to 25% of the sub-book a day:
buying a newly named pick (a stock that is not the broad index ETF), a reserve buy (`decision["kinds"][SYMBOL] == "opportunity"`, for the `case` agent to set), and the full exit of a withdrawn pick;
the SPY sale that funds such a purchase rides with them (it is outside too, scaled with them). The funding purchases of a deploying session never count toward the month either.
How the month ignores them: the order's reason carries the tag `[outside the monthly cap: <kind>]` and `_month_traded` leaves out fills of orders with that tag (join `us_orders_s81`).
The scaling is the old dust-safe scaling (a full exit never leaves dust under the minimum trade), now one helper `_scale`.

**F3, a pick is scored from its first fill** (`core/pick_score.py`: `first_fill`, `pick_started`, `started_ids`, `named_not_held`; `core/picks_card.py`).
A pick's record starts on the first session on or after its first BUY fill (India `paper_trades`, US `us_trades_s81`). A pick named and not bought is "named, not yet held": no pick score is written, it is left out of
`picks_scored`, `picks_ahead`, the per-horizon counts and the recent verdicts (also a score stored before this fix for such a pick), and shows in `scorecard()["named_not_held"]`, in the scorecard text and on the card
("named, not yet held (its record starts at its first purchase)", no "days in the book"). His Kite stocks count as held from the start; a pick in state `held` with no trade of its own (an old row) keeps the first session after
it was proposed. `sleeve_record` is built from the days' holdings, so an unbought pick was never in it: it still is not (tested). The skip scoring is unchanged.

**F4, stress estimate bounds** (`core/stress.py`): with no own history in the window the sensitivity is kept between 0.5 and 2.0 (`BETA_MIN`, `BETA_MAX`; the measured one stays in the detail as `beta_measured`, the note says
"kept at ..."), and the fall is never reported beyond -90% (`MAX_FALL`, before and after the rupee move). Still `basis: "estimate"` with `coverage_pct`.

## Decisions (2026-11-12)
- A "pick" for the cap is a row whose `asset_class` is `equity` and that is not a broad index ETF (the sub-book holds ETFs and stocks only; an ETF other than SPY is rebalancing unless the caller says `opportunity`).
- A funding SPY sale is exempt only whole and only up to the value of the exempt buys; a larger SPY sale is rebalancing (conservative).
- Trades filled before this change carry no tag, so the earlier funding purchases of this month still count in `_month_traded` (they are not rewritten). Pick buys and withdrawn exits no longer wait for it.
- F3 start: the fill day's own close is the start price (the day-before-plus-first-session rule), later than the fill itself, so it never flatters.
- F4: the -90% floor also applies after the rupee move of a US share.
- The 25% limit counts purchases and exits; the funding sale is scaled by the same share.

## What is OFF
Nothing. The reserve-buy kind is not wired by anyone yet (the `case` agent adds the caller); without it nothing changes.

## Shared files touched
`us/policy.py` (check, `_month_traded`), `us/__init__.py` (one DEFAULTS key), `configs/core.toml` (one line under `[us]`), `core/pick_score.py`, `core/picks_card.py`, `core/stress.py`.
Tests rewritten for changed behaviour: `tests/test_s83_drill.py` (two US withdrawn-pick tests: the exit's day cap is now 25%, was 10%).

## Tests
`tests/test_s84_fixb.py` (9): pick bought within four sessions with the month used up; the usual 10% pick in one session with the SPY funding sale outside; a withdrawn pick sold whole within two sessions; the month ignores
tagged fills; rebalancing still meets the month and deploying buys are tagged; a reserve buy; a named unbought pick is out of the record and in after its first fill; the card text and the sleeve record; a high-beta name in the
stress estimate. Neighbours run: test_s81_us, test_s82_us, test_s83_drill, test_s83_picks, test_s83_score, test_s83_strat, test_s80_strategist, test_s80_lab_service, test_s81_drills_harness, test_s73_loop.

## Exposed for screens
`pick_score.scorecard(con, market)["named_not_held"]` (list of symbols), `pick_score.pick_started(...)`, `picks_card.market_block(...)["picks"][i]["held_yet"]`, stress detail `beta_measured`/`beta`/`limits`. Text: the scorecard
text carries the "named, not yet held" line; the card's PICKS section says it per pick.

## Also rewritten (behaviour that changed)
`tests/test_s83_score.py::test_a_pick_cut_early...` (the pick now has a first fill: bought, then withdrawn) and `tests/test_s83_strat.py::test_the_picks_section...` (shows "named, not yet held" first, then the record after a first fill).
Run green: test_s81_us, test_s82_us, test_s83_drill, test_s83_picks, test_s83_score, test_s83_strat, test_s80_strategist, test_s80_lab_service, test_s81_drills_harness, test_s73_loop, test_s81_drills_fixes, test_s82_cut, test_s79_forecast, test_s79_transmission, test_s79b_lens; privacy grep clean.
