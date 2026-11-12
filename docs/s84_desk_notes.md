# S84 desk notes: T10 the daily desk (`src/pflab/think/desk.py`)

Branch `s84/desk` (based on `pm/s84-thinking`, with the gateway merged in). 2026-11-12. No paid call was made; every model in a test is a scripted fake (one test drives the REAL gateway with a scripted vendor client).

## What is built
- `think/desk.py`: the strategist at a desk with an agenda. One working session after the Indian close (`india_close`, from 15:45 IST on an Indian session day) and one in the IST morning after a US session (`us_morning`, from 07:00); a day off or two open slots at once is ONE `catchup` session covering every open slot and measuring "what changed" from the last session (never one per missed day).
- `agenda(con, now, mode)` (code, no model, no cost), most important first: (1) open cases with a look due or a new signal; (2) holdings with a thesis-break or high-severity event or a watch signal since the last session (`kg.events.material_events`, `think_signals_s84`); (3) the scorecards when something was scored since; (4) storylines updated since; (5) one search for a new idea per market while the picks sleeve has room (`picks_card.market_block`), looking OUTSIDE the sector of a name a case trimmed or sold in the last 3 days first. Then the plan.
- Working it: Sonnet (`read`) reads each item with `recall` text (what we already know); Opus (`decide`) only for a decision: a withdrawal of a held pick whose thesis an event breaks, a pick (the idea search: code screens, Sonnet shortlists, code builds the company cards and `recall`, Opus names picks or skips, `lab.tools.run` `propose_picks` / `skip_idea` validate and record: the model writes no size, price or weight), a case over the 2% line (`think.session.think_case`, once a day, only if the case has no step today).
- Rule 8: model answers are JSON from a schema; a model sentence carrying a number that is not in the facts it was given is replaced by the code's own line (`sourced`).
- Knowledge: `recall.recall` before holding and case items, `recall.mark_used` after, `recall.write_back` of every finding (source `desk`); never pay twice: a holding with no new event but a fresh note (`recall.same_subject_fresh`) is "used", cost 0.
- Budget: `[strategist] daily_budget_rupees = 30` and `desk_on = true` in `configs/core.toml`. `budget_status(con, day)`; the day's spend is the larger of the desk's own sessions and `gateway.spent(agent="desk")`. From `[strategist] throttle_after` (2026-12-09), while `think.score.scorecard` shows >= 20 scored decisions and `vs_nothing_inr` < 0, the budget halves (before that date the verdict is shown, "recorded, not applied", A55); ahead, full. His monthly cap (`cap_left`) and the governor's refusals (`gateway.refusal_reason`) stop the day: the rest of the agenda is stored "not_reached" and waits for the next session.
- A day with nothing changed: status `quiet`, a two-line plan, no model call, cost 0.
- Tables (migration `pm/mig_s79/m_desk84.py`, versions 255-256): `desk_sessions_s84`, `desk_steps_s84` (engine, model, thinking level, cost, cached tokens, status, finding per step).
- Tests `tests/test_s84_desk.py` (18): quiet day; busy day in order and stops at its budget; midway stop with "not reached"; his cap and a failing call; weekly review once a week through `strategist.tick`; catch-up in one session; slots; the 2026-12-09 halving with synthetic scorecards; cost line; fresh note used (cost 0); recall/mark_used/write_back; the number guard; withdrawal through the tool (and keep); the idea search (outside sector first, shortlist-only picks, no size/price/weight in tool args, one search a day); case over 2%; plan text; the switch; the real gateway with a scripted client and a governor refusal.

## Decisions (2026-11-12)
- The desk is NOT a heavy strategist session: it never calls `run_session`; the weekly review stays `strategist.due`'s. The hook in `strategist.tick` runs `desk.tick_hook` before the weekly logic, independent of it. `desk.due()` exists (contract) and is what a caller can use to ask "is there an agenda"; the tick hook itself runs the desk whenever a slot is open (a quiet agenda is a free two-line note).
- A reserve with room does NOT by itself trigger an idea search: only the thinking loop may spend the reserve, so a search for it belongs to the cases. The search runs on room under the picks sleeve's share (ordinary picks). Say if you want the reserve to trigger a look-around.
- A case over the 2% line is thought through through `think.session.think_case` once a day when its look is due and it has no step today (the wire agent's `follow_up` may also run; both are guarded by "a step today"). If `follow_up` already ran, the desk just reads.
- Budget refusal from the governor = stop for the day, not a failed item.
- `us_morning` is open when the previous calendar day was a US session (a Friday US close is worked on Saturday IST morning if the app is open; a Monday morning is not a US-morning slot).
- Scope of holdings: `think.watch.scope` when it exists, else the paper book's positions.
- Sessions marked `failed` are retried at most twice a slot a day.

## What is OFF
Nothing is off. `[strategist] desk_on = false` or the kill switch (`think.on()` / `core.on()`) stops the desk.

## Shared files touched
`src/pflab/lab/strategist.py` (one hook in `tick`, 5 lines), `configs/core.toml` (`[strategist]` two keys). Own: `think/desk.py`, `pm/mig_s79/m_desk84.py`, `tests/test_s84_desk.py`, this file.

## Exposed for screens
- `desk.plan_text(con, day)` (Today and the 15:45 report: the latest plan, a text block), `desk.cost_line(con, now)` (rupees spent on thinking this month per decision that beat doing nothing), `desk.budget_status(con, day, now)` (dict), `desk.sessions(con, limit)`, `desk.steps(con, session_id)` (JSON-able), `desk.agenda(con, now, mode)`, `desk.due(con, now)`.

## Could not verify
- A real call through the desk (none made). `think.recall`, `think.watch`, `think.score`, `think.session` are reached through optional imports and tested with fakes; the contract names are assumed as in `s84_common.md` (`recall.recall/mark_used/same_subject_fresh/write_back`, `watch.scope`, `score.scorecard` keys `scored`/`vs_nothing_inr`, `session.think_case`).
- The idea search needs the screen's data (bhavcopy, US bars) and was tested with a fake screen.
- Failure of the weekly session is not affected, but a failing `desk.tick_hook` is returned as `out["desk"]["error"]` and never raises.
