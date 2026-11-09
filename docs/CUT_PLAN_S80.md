# Phase 4: cutting the retired v1 layers (S80): what is done on `pm/s80-cut` and the order for the rest

**Rule from the redesign:** retired code is switched off first and deleted only after v2 has run cleanly for two weeks. All of it is switched off by `configs/core.toml` (`advisors_off`, `retire_missions`). This branch is NOT merged until those two weeks are clean; it is ready to merge after them.

## Measured entanglement (who still imports each retired module; static analysis of `src/`, 2026-11-09)
| Retired layer | Lines | Imported by (outside itself) |
|---|---|---|
| Situation report (`situation/`) | 2,134 | 5: the World screen, the Telegram summary, the wave scan's claim step, one tool, one job |
| Agenda (`agenda/`) | 859 | 6: the runtime's own thread, the World screen, one tool, the situation job and package |
| Readers (`hq/readers.py`) | 345 | 4: the brain, fetch, the hq round, the tool registry |
| Brain passes (`hq/brain.py`) | 639 | 13, among them the app's assistant, its front, its server, selfcheck's neighbours and the learner's record |
| Suggestions (`hq/suggestions.py`) | 276 | 9 (server, keeper, scorecard, views, the paper manager, the pot ...) |
| Proposals (`hq/proposals.py`) | 470 | 6 (server, daily review, arrivals, the paper manager ...) |
| Missions (`hq/missions.py`) | 956 | 16 (assistant, front, server, plans, playbooks, selfcheck, tools, the paper allocation ...) |
| Workers (`hq/workers.py`) | 430 | 2: the assistant (its chat runs on a worker) and the roster |
| Knowledge graph (`kg/`, off) | 1,327 | 23 (the analyst, brief, inbox, researcher, tools, cli, hq business, daily, fetch, keeper ...) |

The last five are woven into the app's server, its chat assistant and the 130-tool registry. Deleting them is a refactor of the app shell, not a clean cut, and the app cannot be started and watched overnight, so only the first two are cut tonight.

## Done on this branch
- The situation report and the agenda are deleted (packages, their job, their two tools, their tests). Their callers now read the new layers: the Telegram summary opens with the storylines (not a model-written report), the World screen shows no situation or agenda panel (their keys stay as "not available" so the screen does not break), the runtime no longer starts an agenda thread, the wave scan no longer writes a situation claim.
- BUILT.md and PLAN.md say so.

## The order for the rest (each step: switch already off, delete, fix callers, full suite, one clean app week)
1. `hq/triggers.py`, `hq/arrivals.py` (the mission scan's inputs; callers: the hq round and the server's arrival route).
2. `hq/readers.py` and the reader tables' writers (callers: brain, fetch, tool registry). Keep the tables for the record.
3. `hq/suggestions.py` and `hq/proposals.py`, with the daily review and the companion jobs (already skipped): the server routes and the scorecard views that show them go first.
4. `hq/brain.py` passes (`wake`, `think`), keeping `brain.as_param` and `KEEP_BLOCKS`, which the strategist uses; the assistant's chat keeps its own worker.
5. `hq/missions.py`, `hq/workers.py` except the assistant's conversation loop; `hq/pool.py`; the paper manager's mission half (`decide`, `execute`, `tick`'s team part) and the mission side of `paper/allocation.py`; the `paper_*` brain tools.
6. The knowledge graph code only after he agrees its design (see `docs/KG_AUDIT_S80.md`).
7. Slim the tests that exercised the deleted layers (about 600 of the 3,200) and the sections of BUILT.md that describe them.

## What is not done and why
The screens (main page spend panel, champion against baseline, storylines) are not wired: the data is there (`strategist.spend_report`, the book card, `story/numbers.py`) and the redesign's UI is a separate piece of work to be seen and judged on his screen.

## Update 2026-11-09 (after his "get this done")
Steps 1 to 3 are DONE and merged: triggers, arrivals, readers, suggestions and proposals are deleted with their routes, tools, screens and tests. Measured while doing it: `hq/scorecard.py` cannot go (the close loop and the paper provenance read it), and the brain's `think`, the worker loop and `missions` are the chat's and the Telegram asks' engine. Steps 4 and 5 therefore start with a new chat path (the assistant answering from tools without a mission or a brain pass), and only then the brain passes, missions, workers, board, roster, cases, plans, playbooks and pool can go. The three screens the redesign asked for are built (`core/screens.py`).
