# Round 3 results (answers only, production guard), 2026-10-17

Registered in `model_decision_2026-10-17.md` before the run. qwen3:8b-q8_0, 50 new drafting tasks (seed 20261018),
the guard as the live centre runs it.

| final pass (rule: >= 98% keeps written answers) | first draft | rejected numbers per task | p90 s | median s |
|---|---|---|---|---|
| **100%** | 100% | 0 | 6.3 | 6.1 |

Decision recorded (`configs/llm_models.toml`, role eval12-r3): q8 stays the model for routing and guarded answers.
Round 2's 92% was the evaluation's stricter-than-production guard plus the trailing-period guard bug, not the
model: with both fixed, no draft was rejected. Spot check: every number in the drafts equals its fact; the
"Regulation 30 [S2]" case that used to fail now passes.

## Seen on real data afterwards (S47 list)
- The guard checks that a number exists in the facts, not what it is attached to: one deposit's payout was written
  as if it were the whole batch. Fixed at the source: the FD tool now gives batch totals computed in code.
- "Where does the money go" was answered from the bank's maturity instruction, not the deployment schedule.
  Answer quality, not correctness: S47 (prompt tuning on a labelled set), not tuned on one question.
