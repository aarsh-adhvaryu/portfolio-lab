# S85 `rules` notes (E4, A69 door b: standing instructions)

Branch `s85/rules`. Tests: `tests/test_s85_rules.py` (32), `tests/test_s85_rules_case.py` (4).

## Built
- `hq/rules.py`: new kinds `pause_buys` (scope class gold|international|index|stocks|all, sleeve core|longterm, name, or all; optional market IN|US), `hold_name`, `no_new_names`, `cash_floor` (1 to 90%).
  Each has `until` (default 30 days, `until_defaulted` says so; at most 400 days), states active / waiting_yes / expired / undone, `undo(con, rule_id)` (the old `undo(con, now, ref)` still works),
  `change_date`, `sweep`, `listing` (for Settings: plain words, can_undo, can_change_date), `active(con, day)`, `blocks(con, day, isin, symbol, sleeve, cls, action, order_kind, new_name, market)`,
  `cash_floor`, `held_back`, `describe`, `label`. Old kinds unchanged (`until` NULL).
- `entrance/rules_intake.py`: `parse(con, now, text, gateway_call=None, apply=False)`, `standing_instruction` (parse + apply: the chat tool), `TOOL` (definition dict), `run_tool`, `undo_by_words`,
  notes (`add_note`, `unread_notes`, `take_notes_text`). The model (role quick, strict schema) only fills a form; code resolves names to ISINs, checks classes, parses dates (model ISO date, else
  "till 20 Nov" by code, past = next year, none = 30 days), requires every number to appear in his words, and applies the tightening test.
- `core/rules_gate.py`: the one place order sites ask the rules: `apply_close`, `apply_us`, `session_block`, `case_block`, `card_text`, `report_line`.
- Migrations 325-328 in `pm/mig_s79/m_rules85.py`: `hq_rules.until`, `rules_held_back_s85`, `rules_notes_s85`, `rules_requests_s85`.

## Decisions (2026-11-13)
- Rule text stored = code-written plain summary (his own words kept in `source`); an order held back says `your rule '<text>'`. Rule `name` is a slug of the text.
- hold_name never stops: kind stop, thesis, trim, rail, risk (gauge cut); a rebalance sale of a name over its rail counts as rail; a case sale of class `damage` counts as a thesis break. target / time / withdraw / harvest / view / case sales ARE held.
- no_new_names: a name with no position is new (a first buy of a core ETF too). Picks: `picks.propose` refuses a new name with the rule named.
- cash_floor only limits buying (close: shrinks buys pro rata, drops those under the minimum trade; session and case buys: held when cash after the buy would fall under it; US step: only for a rule with market US).
- Fail closed: if the rules cannot be read, buys are held (close, session, US, case); sales are not.
- A rule can only tighten: regex on his words (kill switch; turn off / ignore / remove rails, stops, circuit breaker, guards; "no limit") OR the model's `loosens` flag -> refused with the reason; `max_position` above the 10% company rail refused. Pattern check runs before any model call.
- Money rules (max_position, monthly_envelope, dip_tranche) wait for Yes (status `pending`, state `waiting_yes`). A change of targets / limits / stock list / monthly cap becomes a `plan/prefs.py` proposal
  (a `limit_proposals` preference row and an open `questions` row, which the cards agent shows as Yes/No); nothing is written to his files until Yes. Row kept in `rules_requests_s85`.
- Unfit sentence -> `rules_notes_s85` (unread); the strategist's first message includes unread notes (marked read) and the rules in force.
- US picks wire (`us/picks_wire.py`) not touched: US orders are filtered in `us/adapter.py` after `policy.check`, which covers the same ground; `no_new_names` for US picks goes through `picks.propose`.

## OFF
Nothing is behind a switch: rules only act when a rule exists.

## Shared files touched (small hooks)
`core/loop.py` (gate after exit orders, before the checker), `core/session.py` (`_carry_out`, `report_day`), `core/card.py` (one STANDING INSTRUCTIONS line), `core/picks.py` (`propose`), `us/adapter.py`,
`think/session.py` (`act`, decision reason), `lab/strategist.py` (`_first_message`). New empty `entrance/__init__.py` (the `chat` agent also creates the package: keep one).

## For the coordinator
- Register in `entrance.tools.REGISTRY`: `("standing_instruction": (rules_intake.TOOL, rules_intake.run_tool))`; Undo button / `/undo` callback: `rules.undo(con, rule_id)`; Change date: `rules.change_date`.
- The old `hq/tools.py` `add_rule` tool still makes the old kinds; the new chat should use `standing_instruction`.
- Lines for BUILT.md: tables `rules_held_back_s85`, `rules_notes_s85`, `rules_requests_s85`; modules above.

## Exposed for screens
`rules.listing(con, day)` (every rule with state, until, plain, can_undo, can_change_date), `rules.held_back(con, day)`, `rules_gate.card_text/report_line`, `rules_intake.unread_notes(con)`,
`GET /api/rules` (existing; its rows now carry `until` and `state`).

## Not verified
No real model call (scripted fakes only); no real-store run; the live Telegram/chat path is the other agents'.
