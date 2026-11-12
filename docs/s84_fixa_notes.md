# S84 fixa notes: F1 (room for the system's own Indian picks) and F5 (the first message once)

Branch `s84/fixa` (worktree `D:\s84_wt\fixa`), based on `pm/s84-thinking` e2551bc. No migration (none needed).

## Built
**F1 start rule** `core/pick_share.py`: `RULE_A1`, `decision_done(con, market)`, `set_start_by_decision(con, now)`. Once (idempotent by the reason prefix "his decision 2026-11-12"), India's share = his Kite
stocks' weight in the India part + 20 points, at most the 60% maximum, never lower than the current share; one dated row in `sleeve_share_s83` (figures: kite_weight, extra_points, reserve_points).
Nothing is written (returns "waiting") while no Kite stock is held. The 20-60 range, the 5-point steps, the 60-session judgment and the `min_system_picks_bought` gate are untouched; the config's
`start_share` stays 0.40 (the formal start of the rule; the decision row overrides it). The US share is untouched. Called from `app/runtime.py` at the app's start (own try block, after the S79 registrations).

**F1 sizing** `core/picks.py`: `reserve_points(market)` (India 10, US 10, from `[think] reserve_india_pts/reserve_us_pts`), `ordinary_ceiling(market, share)` (India: share - reserve; US: min(share,
1 - SPY floor - reserve)). `target_weights` budgets the system's ordinary picks under that ceiling (so with the new share: 10 points), and `_from_cash_above_reserve` limits the picks' increases to the
cash ABOVE the reserve (India only, when the state has a cash figure): the reserve refills from new money and sale proceeds before an ordinary pick takes any cash. `propose` (room check, US ceiling text)
and `picks_card.share_ceiling` use the same ceiling; the card's India line says how many points are the opportunity reserve. Buying stays what the baseline already does (from cash, after the core's gap,
inside the turnover caps; `baseline_v2` never sells to reach a target), so nothing in the core is sold to make room.

**F1 amendment** `docs/protocols/s83_picks_live_protocol.md` section 8 "Amendment A1, 2026-11-12" with a `json amendment_a1` block pinned to `pick_share.RULE_A1`. `learner/s83.py`:
`register_picks_amendment_a1` counts it as ONE new test (`s84:picks_live_a1:IN`; the learner's counter goes up by one in the app at its next start); `protocol_ok` then compares the file with the amendment's hash.

**F1 first picks session** `lab/first_session_s82.py`: key `first_picks_in_s84`, reason `REASON_PICKS_IN`, in `KEYS` (so `keys_in`, `waiting`, `after_session` handle it with no change in `strategist.py`). It is
listed only once the share's start row exists (`decision_done`), once a day while waiting, never an error; without cap or client the existing paths record "waiting".

**F5** `lab/strategist.py`: `without_picks(card_text)` cuts the card's trailing PICKS SCORE / PICKS blocks; `_first_message` sends the fresh ones once (if the fresh ones cannot be read, the card keeps its own).
The stored card is unchanged (Today still shows it).

## Decisions (2026-11-12)
- Reserve is a number of points of the India part that ordinary picks cannot plan for or buy with; his Kite stocks' weight can already exceed what is left (nothing is sold, as before).
- Reserve protection is in `picks.target_weights` (cash above the reserve). The baseline's core gap still takes cash before the picks and could use cash that the reserve wants: see "Left for the coordinator".
- The amendment counts as a new test (rule 10: an amended protocol is re-registered and counts as new).
- Existing pin updated: `tests/test_s83_picks.py::test_an_accepted_pick_is_bought_over_several_sessions...` now sets the decision start first and expects 10 points (tolerance 1e-3, since the share is the Kite weight at that moment).
- With the app's real book: ordinary picks are also held back until the book's cash is above the reserve, i.e. they are bought only from new money/sale proceeds/cash above 10% of the India part.

## OFF / not done
Nothing is OFF. Nothing for the US beyond the ceiling arithmetic (the US reserve itself is the `case` agent's `think/reserve.py`).

## Shared files touched
`app/runtime.py` (one try block), `lab/first_session_s82.py`, `lab/strategist.py` (`without_picks`, three lines in `_first_message`), `core/picks.py`, `core/picks_card.py`, `core/pick_share.py`, `learner/s83.py`,
`docs/protocols/s83_picks_live_protocol.md`, `tests/test_s83_picks.py` (one pin).

## CLAUDE.md lines that change (the coordinator edits the file)
S83 paragraph, A61: "India's `longterm` sleeve (his Kite stocks plus the system's own picks) starts at 40% and moves in 5-point steps between 20% and 60%" -> add: "from 2026-11-12 (A64/F1) it starts at his Kite
stocks' weight plus 20 points, at most 60%: 10 points for ordinary picks, 10 the opportunity reserve in cash that only the thinking loop spends (`pick_share.set_start_by_decision`, protocol Amendment A1)".
Also the S82 paragraph's "longterm at most 60%, core at least 30%" stays.

## Exposed for screens
`pick_share.status(con, "IN")` (share, source "his decision 2026-11-12: ..."), `picks.reserve_points(market)`, `picks.ordinary_ceiling(market, share)`, `picks_card.market_block(con, "IN", day)` (room is now under the ordinary ceiling),
`picks_card.build(...)["text"]` (the India line names the reserve), `first_session_s82.state(con, "first_picks_in_s84")`.

## Left for the coordinator
- Core gap vs reserve: `baseline_v2` spends free cash on the core's gap first; to protect the reserve from it too, subtract `reserve_points/100 * total` from `free` there (not touched here).
- `think/reserve.py` should read `picks.reserve_points` and treat the cash weight above/below it as used/free.
