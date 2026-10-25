# The brain's shadow trial: pre-registered protocol (S59, PLAN A16)

Written and committed on 2026-10-24, before the brain's first pass. Nothing below changes after the first pass; a
change is an amendment with its date and reason, and passes before it are reported both ways.

## Question

Does the brain (Opus 5.5 on events, `hq/brain.py`) earn its cost, and is Sonnet 5.5 as good for less? If neither
beats the reflexes alone (the jobs, `jobs.FOLLOWS`, the guards, the researcher's flags), the brain does not stay
(CLAUDE.md rule 12).

## Design

- **Shadow mode:** 14 calendar days from the first pass with role `brain` (`hq_passes`). The brain journals decisions
  and predictions and acts on nothing (`brain.SHADOW = True`). The investor's own orders to it ("Think now", `/brain`) are
  passes like any other and count.
- **Same input, two models:** every pass is made by Opus 5.5 (role `brain`) and then by Sonnet 5.5 on the same
  built input (role `rival`). The weekly reflection is Opus only and is not scored.
- **Predictions:** a stock in the portfolio or on the watch list, `return_above` / `return_below` a level in percent from
  the last close before the pass to the close on the due date (5-90 days ahead), with a confidence. Code records the
  reference close and the **base rate**: the share of the stock's own windows of the same number of sessions, over
  the three years before the pass, that made such a move (at least 250 windows, else no base rate).
- **Scoring (`hq/keeper.py`):** on the close on or up to 6 days before the due date, never an earlier one; a
  prediction with no close within 10 days of its due date is void. Outcomes all come after the prediction was made.

## Measures and the judgement

The judgement is made when 14 days have passed **and** each model has at least 20 scored predictions with a base
rate; until then the trial continues in shadow (it stops at 60 days with whatever is scored, reported as
insufficient if under 20).

1. **Skill:** Brier score of the model's confidences against the outcomes, compared with the Brier score of the base
   rates on the same predictions. A model has skill if its Brier is lower than the base rate's and the paired
   difference (base minus model, per prediction) has a one-sided bootstrap 90% lower bound above zero (10,000 resamples,
   seed 20261024).
2. **Usefulness (recall):** of the events the investor marks as mattering during the trial (he may mark any journal pass or
   event "mattered" / "did not"; unmarked passes do not count), the share the model acted on (any decision other than
   `nothing`) in the pass that saw it. Reported as a count ("k of n") under 20 marks.
3. **Cost:** rupees per pass and per day for each model, from `api_calls` (agents `brain`, `brain_rival`, `gatekeeper`).

**Decision rule.**
- Neither model has skill (1) -> the brain stays a journal writer at most (no acting), or is switched off if the investor
  finds the journal useless (2); its predictions stop.
- Exactly one has skill -> that one is the brain.
- Both have skill -> Sonnet is adopted unless Opus's Brier is lower by more than 0.01 **and** Opus's recall (2) is not
  lower; the cheaper model wins ties.
- Acting (SHADOW = False) is a further step that also needs the investor's yes; it starts with `investigate` decisions only
  (tasks on the board, priced and capped as any other).

## Fixed settings during the trial

Brain setting `economy` unless the investor changes it (passes per day: 4 each model; effort low; morning review on
trading days after 08:45; event passes only after the Haiku gatekeeper says wake). Spend limits as in
`hq/governor.py` on 2026-10-24 (brain layer 40% of the Rs 2,500 cap, Rs 120 a day). The prompt (`brain.SYSTEM`) and
the output schema do not change during the trial; a fix to the code that builds the input is allowed and dated in
STATE.

## Reported

`docs/research/brain_shadow_results.md`: passes per model and trigger, predictions made, scored and void, the Brier
scores with the bootstrap bounds, recall, cost, the decision, and anything that went wrong.

## Amendment 1 (2026-10-25, S60, PLAN A18; reason: The investor's decision of 2026-10-24 to make the brain one model with tools)

What changes, from the first pass made by the S60 code (`hq_passes.role = 'brain'` with tool calls in `hq_tool_calls`):
- **The pass** is a bounded tool loop (at most 8 turns, the governor before each), not one call. The prompt
  (`brain.SYSTEM`) gains the tool rules; the final message is the journal note. Decisions are made through the action
  tools (`ask_investor`, `tell_investor`, `order_research`, `order_calculation`, `prepare_plan`, `correct_memory`), recorded
  and never carried out in shadow mode; predictions through `record_prediction` (same fields, same checks, same base
  rate and scoring); suggestions through `record_suggestion` (a new ledger, not a measure of this trial).
- **Sonnet** stays the rival: the same built input and the same tools, its own loop.
- **The measures and the decision rule do not change.** Skill: predictions scored as before. Usefulness: "acted on"
  means at least one action-tool call in the pass that saw the event (was: a decision other than `nothing`). Cost:
  rupees per pass now sum every turn of the pass.
- **The 14 days** count from the first S60 pass. Passes before it (S59 single-call passes, from 2026-10-24) are reported
  apart, and the results give each measure both ways (with and without them). Passes with trigger `check` (made by
  Claude Code while building S60, 2026-10-25, passes #11-#14) are not trial passes: they neither start the clock nor
  count in any measure; their suggestions and predictions are reported apart.

## Amendment 2 (2026-10-25, the investor: "I am not spending 14 days on this"; the system exists to do the work for him)

The shadow trial ends before any judgement: `brain.SHADOW = False` from 2026-10-25. The brain (Opus) carries out its
action tools, each capped a day (`hq/tools.py` DAILY: tell 3, ask 2, research 3, calculations 3, fetches 5; beyond that
kept in the journal as "held"); it still never trades, moves money or changes targets, and every paid call is priced and
governed as before. The Sonnet rival stays journal-only on the same passes. The measures above are kept as monitoring,
not as a gate: predictions and suggestions are scored as written, and `docs/research/brain_shadow_results.md` reports them
(both models, per kind, with n) when 20 predictions per model are scored. Should Opus show no skill against the base
rate then, or Sonnet match it, the brain's model is changed by the slider's rule (S61), not switched off.
