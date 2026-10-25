# Model evaluation for the 12 GB GPU: round 1 results

Run overnight 2026-10-16/17 with `tools/run_eval12.ps1`, as registered in `model_eval_12gb_protocol.md` (amendment 1
for Laya). All 7 candidates completed. Decision recorded 2026-10-17 (`pflab llm decide12 --record`): **no model
chosen**; `pflab ask` stays facts-only.

| model | routing (>= 95%) | answers final (>= 98%) | first draft | extraction F1 (>= 0.95) | materiality (>= 90%) | p90 s (<= 20) |
|---|---|---|---|---|---|---|
| qwen3:8b-q4_K_M | 90% | 96% | 96% | 1.00 | 82% | 6 |
| qwen3:8b-q8_0 | 85% | 96% | 94% | 1.00 | 81% | 6 |
| qwen3:14b-q4_K_M | 87% | 82% | 58% | 1.00 | 80% | 19 |
| qwen3.5:9b-q4_K_M | 85% | 84% | 34% | 0.99 | 80% | 16 |
| qwen3.5:9b-q8_0 | 88% | 58% | 30% | 1.00 | 78% | 21 |
| gemma3:12b-it-q4_K_M | 87% | 20% | 0% | 1.00 | 78% | 22 |
| laya (routing, materiality only) | 65% | - | - | - | 72% | - |

## Reading
- The smallest model was the best, and 8-bit did not beat 4-bit.
- Extraction is solved by every model. Guarded answers separate them most sharply: the guard rejected invented or
  altered numbers far more often for the larger models.
- Routing misses were mostly the system's fault: four questions were missed by 5-7 of the 7 models, because the
  guards tool's description did not mention the Nifty 500 drawdown or the dip rule, no tool carried the FD
  deployment schedule, and two-part questions got one tool. Fixed afterwards; re-tested in round 2
  (`model_eval_12gb_round2.md`) on new, unseen sets.
- Materiality (about 80% for all) is the real model gap: headlines are often vague. It is the first candidate for
  S47 tuning if round 2 confirms it.
