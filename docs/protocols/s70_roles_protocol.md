# S70 protocol: can Sonnet 5.5 hold the reviewer's seat and the coordinator's planning step?

Registered 2026-11-01, before any paid call of this measurement. The rule is in code (`src/pflab/eval/roles.py`: `decide`, `decide_planner`) and was tested
without a model (`tests/test_s70_roles.py`). A model seat is a measured decision (CLAUDE.md 9). This is a model-seat measurement, not a claim about markets, so it
does not enter the learner's counter.

## Why
In the app's October record the independent reviewer (Opus 5.5) cost Rs 9.5 a call and the coordinator (Opus 5.5) Rs 5; the two seats were Rs 315 of the
month. Sonnet 5.5 costs half per token. If it does the same job the saving is real; if it does not, the seat stays.

## Materials (all invented; nothing of the investor's)
- **Reviewer set.** 24 mission dossiers in the shape a worker is handed (`hq/workers._dossier`), each with ONE planted fault, four of each kind, over four invented
  themes: an untraced number, a strategy test without a baseline, stale evidence used as today's cause, an assumption presented as an estimate, a size and tax
  stated on an incomplete ledger, a conclusion that outruns its evidence. Plus 4 clean controls (the same dossier with no fault). A dossier differs from its
  clean twin only by the planted fault (tested).
- **Planner set.** 6 investigation questions (4 strategy, 2 explanatory).
- Both models get the same system text (the production reviewer and coordinator instructions), the same single tool (`submit_review`, `plan_mission`), the same
  settings (adaptive thinking, effort medium), one call each, interleaved item by item. No prompt tuning on either, before or after.

## Measures (all by code)
- **Caught**: the verdict is revise or reject AND its words name the planted thing (a figure or an id fixed when the dossier was made; tested to be on the page).
  **False alarm**: a clean control that is not approved. No verdict counts as a miss.
- **Planner**: six checks per plan (2 to 6 steps; the first step verifies the premise with no dependency; at least one quant step; valid keys, dependencies,
  roles and promises; a baseline or comparison for a strategy question, competing explanations for an explanatory one; what would invalidate the view).

## Decision rules (fixed here)
- **Reviewer seat -> Sonnet** only if, on the items both models completed: Sonnet catches at least 90% of what Opus caught AND at least 70% of all planted
  faults AND has at most one more false alarm than Opus on the clean controls. Otherwise the seat stays with Opus.
- **Planning step -> Sonnet** only if its mean check score is at least 90% of Opus's AND it passes every check on at least 75% of the tasks. Otherwise it stays.
  The coordinator's final answer is not measured here and stays with Opus either way.
- Counts are shown with their 95% Wilson interval (small-numbers rule). The rule is operational: a difference inside the interval is not established either way,
  and the pre-registered floors, not a significance claim, decide the seat.

## Limits of this measurement (stated before the run)
- The dossiers are small (about 700 tokens); production dossiers are ten times that. A reviewer that does well on a small one may do worse on a long one.
  The live investigation of the S70 acceptance (Sonnet in the seat, if chosen) is read by hand against this.
- The reviewer here cannot call `reproduce_calc`; the dossier states the reproduction. Judgement is measured, not tool use.
- 24 faulty items: an interval of about plus or minus 20 points. The floors are set with that in mind.

## Spend
Own profile with a hard window cap of Rs 160 (`tools/s70_roles.py seed --cap 160`); a pilot of 2 faulty + 1 clean + 1 plan per model first, to measure the cost
per call. If 24 + 4 reviews and 6 plans per model do not fit the cap by that measure, the clean controls drop to 2 and the plans to 4 BEFORE the main run
(the faulty items stay at 24); nothing else changes after the pilot. A run that stops at the cap is reported as stopped, with the items both models completed.

## After the run
The result and the decision are recorded in `docs/STUDIES.md`. If a seat changes, `SPECS` in `hq/workers.py` is changed in the same commit with the reference.
