# S85 weekrun: the accelerated week drill

Branch `s85/weekrun` (from `pm/s85-entrance`). 2026-11-13. No paid call: every model (both engines) and the Bot API are scripted fakes; nothing leaves the PC. PLAN.md, BUILT.md, CLAUDE.md untouched.

## What is built
- `tools/drills_s85_week.py`: the week (Thu 15 Oct to Thu 22 Oct 2026 on the drills' synthetic profile, a COPY). `tools/drills_s81.py` has the 7-line registration `accelerated_week`
  (`python tools/drills_s81.py run --only accelerated_week`, PYTHONPATH = the worktree `src`; about 75 s).
- The world: five Indian sessions (Thu 15, Fri 16, Mon 19, Wed 21, Thu 22), five US mornings, a weekend, the Tuesday holiday. The app opens every morning as a NEW process
  (`Env.open_app`, intake workers restarted with `intake.stop/start`) and closes every night (in flight work finishes, the store is released). All of Monday it is OFF: the fake Bot API holds two
  phone messages, the bot's first poll on Tuesday 09:00 answers them, and Monday's close is caught up once.
- Scripted models behind `gateway.set_client(..., engine=)`: `claude` (Anthropic wire, `replays_s84_model.ScriptedClient`) and `openai` (a scripted Responses-wire client in the drill file). One responder
  serves both: it answers by schema (standing-instruction form, stock verdict, PDF facts, big-trade check), by `CASE #n` (the thinking loop: class and options from the closed lists, "hold"), and the chat by his words
  (tool calls `look_into`, `suggest_stock`, `standing_instruction`; otherwise a plain line). Every chat model call takes 1 s so the loop and the chat really overlap.
- Traffic (16 messages: 9 from the phone, 7 from the laptop): good morning and thanks; a PDF note on a held name through Telegram (read by `readers`, linked by ISIN through a scope file written into the
  drill's data folder, opens a case); "look into X" (x4); a stock suggestion; "pause gold buys till 22 Oct" (rule, honoured by the Friday close, Undo pressed as a Telegram button on Saturday); a question card
  (`questions.ask` with a default and a deadline, applied by the real `voice` job); two phone messages while the app is off.
- The engine switch: Wednesday 10:10, `gateway.grant` (consent) + `record_exam(form_pass=True)` + `gateway.use(yes=True)`. A case that began on claude gets a probe call 5 minutes later through the gateway: it is
  answered by claude (the 30-minute pin); every call after goes to the second engine.
- Drill-only settings (restored at the end, his files untouched): the baseline's `gold_pct` raised to 22 so a gold buy is due at a close; the premium rail's `unknown` set to `allow` (the synthetic profile has no NAV
  series, the rail would block every gold buy; the rail's own tests stand); `gateway.key_set` returns True (a stand-in for the second engine's key: no secret is read or printed).

## What the drill asserts (all pass)
Nothing lost: queue empty, every item done/failed, every message he sent stored once and answered exactly once, no answer left pending, every update the Bot API held taken once. Nothing twice: no case (name, kind, day),
no decision with two orders, no order for the same name/side/close, no proactive message, no decision per case/day. Sessions: every session marked, closed and forecast once, Monday's caught up on Tuesday 09:00, no forecast scored
twice, no close late. Desk: a session on every day the app was open, all `done`, five US mornings, one after the gap. Cases: his looks, note and suggestion opened cases and each was read; cases were followed up on later days and
none with a look due is overdue. Rule: the Friday close bought no gold and recorded the rule (`rules_held_back_s85`), Undo from the button lifted it, the first close after bought gold. Card: default applied on time. Engine:
switched with consent and exam on record, nothing to the second engine before, the mid-case probe answered by claude, calls stored per engine, every call stored with engine, model and price, every step with engine, model and thinking,
per-engine scorecards stay apart. Isolation: loop steps ran while a chat answer was in flight (overlap counted by a sampler), no step over 60 s, calls stored = calls scripted (no paid call), no job failed, no exception, no error logged,
point in time.

## Bugs found and fixed at the root (each with a regression test in `tests/test_s85_weekrun.py`)
1. `src/pflab/think/recall.py` (`_line`, new `_shown_id`): the recalled notes' ids are hashes (`doc:analyst_note:4d675f8629119755`); a run of nine or more digits in one is what the egress gate reads as a phone or account
   number, and it refused the WHOLE case message (about one note in ten): the desk's work on the case was dropped for the day ("not sent: account-like number; phone"). The id is now shown with digit runs of 5+ split in groups
   of four (display only, ids are never parsed back from the model's text). Test: `test_a_recalled_notes_hash_id_never_looks_like_a_phone_or_account_number_to_the_egress_gate`.
2. `src/pflab/think/score.py` (`_track(decisions=)`, new `engine_of_decisions`, `by_engine`): after an engine switch the scorecard showed ONLY the engine in use, with the decisions of both engines mixed in its `model` and `rule` tracks
   and the earlier engine's record gone. Each decision is now credited to the engine of the case's newest model step on or before its day; once more than one engine has decided, every engine has its own record (`in_use` marks the
   current one; an engine that decided keeps its record over a shadow's rows). With one engine only the output is exactly what it was. Tests: `test_a_switch_of_engine_keeps_each_engines_own_record_in_the_scorecard`,
   `test_with_one_engine_only_the_scorecard_is_what_it_always_was`.

## Shared files touched
`src/pflab/think/recall.py` (one function), `src/pflab/think/score.py` (`_track`, `by_engine`, one new function). Harness: `tools/drills_s81.py` (the registration). Existing tests run green: see the report.

## Not verified / limits (honest)
- The 5-minute session-loop ticks are not stepped one by one by the harness (it steps the scheduler at 07, 10, 13, 16, 18, 21, 23 on session days): "never delayed" is shown by the closes landing on their evening, no step
  slowed by the chat (slowest step logged in the evidence) and by the overlap count; the tick-by-tick isolation (a hung intake, 50 messages during a close) stays in `tests/test_s85_isolation.py`.
- A message in flight at the moment the app closes is not simulated (a thread cannot be killed like a process without writing to a closed store); the drill waits for the queue before each close. The resume of `working`
  items at start is covered by `tests/test_s85_chat.py`.
- The second engine is a scripted double of the OpenAI Responses wire; the real wire format is covered by `tests/test_s85_engines.py`. The US picks and the real Kite are not in this profile.
- The core buys gold only because the drill raises the gold target and lets an unknown premium pass; it shows the rule is read at the close, not that the real book would have bought.

## Exposed for screens
Nothing new on the screens. `think.score.by_engine(con)` now returns one record per engine that decided (JSON-able); `think.score.engine_of_decisions(con)` -> `{decision_id: engine}`.
