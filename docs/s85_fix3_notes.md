# S85 fix3 notes (branch s85/fix3, 2026-11-13)

Three root fixes from `docs/s85_replay3_notes.md` ("Findings in others' code"). Tests: `tests/test_s85_fix3.py` (12 cases). Baseline/fall-gauge interaction NOT touched (his decision).

## 1. A held name's refused buy keeps its guard (`think/rule.py::_decide_one`)
- Root: for a name already held, `_buy` ran, was refused (timing guard, new-low, stretched, damage wait, pending outcome, minimum size, not positive), and the decision read only
  "Hold: no sale beats holding..." with the guard dropped.
- Now the hold's reason carries a second sentence, "The buy waits: <guard>; <guard>." (`rule.BUY_WAITS`, at most two guards; the "size is set by" line is left out), placed before the
  "Looks again at" text so the stored 500-character cap cuts the pending text, not the guard. `guards` of the hold carry the same list. `refused` stays False on purpose:
  `session._decide_all` and `shadow` read `refused` as "option nothing", which would change what the rule chose.
- `_retry_refused` now also finds a held name's waiting buy (a hold whose reason holds `BUY_WAITS`); before, only `nothing`/`wait` rows were retried, so a held name never was.

## 2. Re-look off the calendar (`think/session.py::follow_up`, new `_off_calendar`)
- (a) A NEW thesis-break-kind (`kg2.classify.THESIS_BREAK_KINDS`) or high-severity `thesis_event` signal joined to an open/waiting/acted/advisory case after its last model step
  (`answer_ok`/`failed`) re-thinks the case at once through `think_case`, once per trigger (step `relook`, payload `signal_id`; the same signal never re-looks twice). Inside the day's cap:
  cases opened today + re-looks today must stay under `[think] max_cases_per_day` (3). The model's own governor/gateway budget rules still apply (a refusal is stored and returned as `failed`).
- (b) The first look after a timing guard cleared: for a case whose model chose `buy_in_parts` and that has no part bought, code runs the rule on the stored answer (`_retry_refused`, no model call);
  checked once per case per day (step `guard_checked`), so a 5-minute loop does not rescan. When the guard's own condition is clear, the first part is bought by the rule alone.
- An ordinary or medium event of a non-break kind still waits for the calendar (`_changed`, unchanged). Nothing is called when nothing changed.
- New step names `relook`, `guard_checked` (free text in `think_steps_s84`; no migration). `follow_up`'s result gains `relooked` and `guard_cleared` when non-zero.

## 3. Names with digits (`think/session.py::validate_answer`)
- Not fixed on the branch: `NIFTYBEES` itself passed, but any name with digits in the prose (`ICICIB22`, `BHARAT22`, `NIFTY50BEES`, `GOLDBEES2`) was read as the figure "22"/"50"/"2" the sources did not give,
  so the answer was refused. `_numbers` now drops (i) a ticker shape (3+ letters then digits, never INR/USD/EUR/GBP glued to an amount) and (ii) every choice symbol of the answer. A real figure
  next to such a name (`ICICIB22 fell 3.5%`) is still refused.

## Files touched
`src/pflab/think/rule.py`, `src/pflab/think/session.py`, `tests/test_s85_fix3.py`, this note. No config, migration, CLAUDE.md, PLAN or BUILT change (the coordinator's).

## Left / for the coordinator
- BUILT.md could add: steps `relook`, `guard_checked`; follow_up keys `relooked`, `guard_cleared`; rule marker "The buy waits".
- The held-name retry in the test uses an ETF; a held single stock at its 10% rail is correctly refused by `act` ("a rail leaves no room"), which the retry records as a decision.
