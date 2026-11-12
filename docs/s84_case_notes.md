# S84 case: T3 understand and choose, T6 act and tell, T7 come back, the reserve and the freezes

Branch `s84/case`. Modules: `src/pflab/think/session.py`, `src/pflab/think/reserve.py`; tests `tests/test_s84_case.py` (26). No migration (nothing new to store: steps, options, decisions and freezes use the shared tables).

## What is built
- `session.think_case(con, now, case_id, *, root=None, web=None)`: Sonnet (`read`) reads first with a short tool loop (recall, graph_events, company_card, base_rates, outcome_table, web_check); the structured
  answer is a second call, by Opus (`decide`) when the book's exposure to the case is over `[think] opus_exposure_share` of the whole book OR the book does not hold the name (a chance could spend the reserve),
  else by Sonnet. The answer is validated (`validate_answer`): closed lists only; any numeric field, a forbidden key (size, price, weight, probability, ...), an unknown word, or a figure in the prose that neither
  the first message nor a tool result gave is refused and asked once more (`answer_refused` step); a second failure leaves the case open. The schema sent to the vendor is stripped of length limits and closed
  (`_strict`); sizes are checked in code. Every model step is stored with engine, model, thinking, cost and cached tokens (`cases.add_step`); the reading and decision are written back with `recall.write_back`
  (source `case`), what was read is marked with `recall.mark_used`.
- OPTIONS and DECIDE: `odds.option_table` rows are stored as track `table`; for each choice the model's row is stored as track `model` and the rule's (`rule.decide`, called once per name with the answer plus
  `isin`, `symbol`, `option`, `model_option`) as track `rule`; `cases.record_decision` keeps both (`differs`). The rule acts. A refused rule decision is "nothing".
- `act(con, now, case_id, decision)`: sale = the exit manager's own `_sell` with kind `case` (12-month guard, pending, same-day rules all apply) then a paper order and decision row as the close loop does it; trim = the
  rule's `size_inr` (half when none); reserve buy = a paper order of one part (`size_inr / parts`) after: the stored `worst_pct_book` is at most `bet_worst_pct_book`, the reserve has room, `rails.buy_room` (stock 10%,
  sector 25%) has room, and the independent check passes; US = `us.book.place` (sell whole/half; buy in dollars at the stated rate from the US reserve). freeze/wait = `cases.add_freeze` (until the pending event, or
  `look_max_sessions` sessions). A buy lifts the name's own freeze. Parts are stored as `part` steps; `follow_up` buys the next part only after `parts_gap_sessions` and only if `rule.decide` still says buy_in_parts.
- The independent big-trade check (`big_trade_check`): a sale over `big_trade_share` of the whole book and EVERY reserve buy; through the gateway role `quick` (one door), logged in `core_checks_s80` kind
  `case_trade`. It does not reuse `core/checker.review` because that only looks at orders over the share and prints their share of the book from its own state.
- Advisory (`score.advisory` or `[think] mode = "advisory"`): cases open and report, nothing acts except a class-`damage` sale of a held name.
- `follow_up(con, now, day)`: due looks only (`cases.looks_due`); once per case per day; a look is re-thought only when a signal joined since the last answer (or the case was never thought); otherwise parts are
  continued, a case with nothing pending that acted is closed ("decided, nothing pending"), a case quiet for `quiet_close_sessions` closes, else the look moves `look_max_sessions` on. Closing releases its freezes.
  Point-in-time: it uses the `now`/`day` given, so the catch-up can call it for each missed day.
- `tell`: plain Telegram text (kind `watch`, dedup per case/day/decision count) when a case acts or opens on more than 2% of the book. `thinking_text(con, day)`: the "Thinking about" block, a failed-case line and
  the reserve lines.
- `reserve.reserve_status(con, market, day)`: India = `reserve_india_pts` of the rupee book value, free = cash+bank less open buy orders, at most the reserve; US = the same in dollars of the sub-book shown in
  rupees at the stated rate (`fx`, `reserve_usd`, `free_usd`). `reserve.hold_fraction(market)`; `reserve.text(con, day)`.
- Freezes (hooks, each with a test): `core/baseline_v2.decide` reads `state["frozen"]` (no increase for those names) and `state["reserve_frac"]` (the reserve stays cash: new money and sale proceeds meet it
  first); `core/state.build` sets both keys (`cases.frozen_isins`, `reserve.hold_fraction`); `core/picks.target_weights` (system picks: held amount stays); `us/picks_wire.extra_weights` (a frozen US pick's target is
  what the sub-book holds).
- `cases.frozen_isins(con, day, market)` added at the end of `think/cases.py`. `exits.KINDS` gains `"case"`.

## Decisions (2026-11-12, one line each)
- The reserve buy is a direct paper order (India) / US order, NOT `propose_picks` kind `opportunity`: `core/picks.propose` has no such kind and a thesis-bound pick record was not wanted for a chance; the
  stock and sector rails are enforced by `rails.buy_room`, the US stock rail by the US reserve and the F2 caps (fixb) at the US step. If the coordinator wants a pick record, `act` is the one place.
- A reserve buy whose big-trade check cannot run waits (the case stays open); a SALE whose check cannot run goes ahead (as the close loop's checker does: a missing check never stops a risk exit).
- Opus condition = exposure over the line or the name not held (a chance), because the reserve spend is only known after the answer.
- The reserve is defined from cash on hand (not a side ledger): it refills by itself because the baseline leaves `reserve_frac` of the India part as cash (hook above). With plenty of cash beside the
  reserve an order does not reduce `free_inr`; it does once cash falls below the reserve.
- The web check goes through `analyst.web_search` (its own egress gate, price check, cap, and its own note `analyst.keep`), checked first with `recall.same_subject_fresh` (second ask on an unchanged subject
  returns the stored note at zero cost), at most 2 per case. The default client is made the analyst's way; tests/the replay pass `web=`.
- Failures: a gateway refusal is stored as the plain `gateway.refusal_reason`; the case stays open with its next look the next session; the exit manager's thesis sales are a separate path and still act.

## What is OFF / not done
- Nothing is switched off by a flag. Not done by me (wire's): the `core/card.py today_extras` key and the `core/session.py report_day` line call `session.thinking_text(con, day)` (one function for both); the loop
  wiring, the daily cap loop and the `think_loop` job. The brief listed those hooks for me and for `wire`; I left them to `wire` to avoid a double edit.
- `notice -> think` ordering and the 3-a-day cap are the caller's (`watch` opens at most 3; wire thinks through the open ones).

## Shared files touched
`core/baseline_v2.py` (frozen, reserve), `core/state.py` (two state keys), `core/picks.py` (`target_weights` freeze), `us/picks_wire.py` (freeze), `core/exits.py` (`KINDS` only), `think/cases.py` (one function
appended). Existing tests run on the touched files: see the report.

## Exposed for screens (plain functions, JSON-able)
`session.thinking_text(con, day)` (Today and 15:45 text), `cases.thinking_block`, `reserve.reserve_status(con, market, day)`, `reserve.text(con, day)`, `session.tell` (text), `cases.get_case` (steps with
engine/model/thinking/cost; options by track; decisions with `differs`).

## How to run one case from a script (the replay agent)
`session.think_case(con, now, case_id, web=None)` on a store copy with `gateway` real (no `DEPS`), the dev cap set; `session.DEPS["gateway"|"recall"|"odds"|"rule"|"score"]` override any piece with a fake.
`web=` may be a callable `(con, question, now) -> {"text", "cost_rupees"}`; leaving it None uses the analyst (paid: the replay's Rs 60 cap applies through the governor).
