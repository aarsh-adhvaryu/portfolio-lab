# Model evaluation for the 12 GB GPU: round 2 results

Run 2026-10-17 with `tools\run_eval12.ps1 -Round 2`, as registered in `model_eval_12gb_round2.md` (new routing
questions, new answer tasks, new 2023 headlines). Both candidates completed. Decision recorded 2026-10-17
(`pflab llm decide12 --round 2 --record`): **no model chosen**; `pflab ask` stays facts-only, routing by keywords.

| model | routing (>= 95%) | answers final (>= 98%) | first draft | extraction F1 (>= 0.95) | materiality (>= 90%) | p90 s (<= 20) |
|---|---|---|---|---|---|---|
| qwen3:8b-q4_K_M | 93% | 90% | 90% | 1.00 | 78.5% | 7 |
| qwen3:8b-q8_0 | **95%** | 92% | 88% | 1.00 | 79% | 12 |

## Reading
- The routing fix worked: q8 now passes (85% -> 95%), q4 rose 90% -> 93%. Remaining misses: two-part questions
  given one tool ("dip rule active and the extra tranche"; "gold target vs big-fall risk") and "tax left after
  TDS" sent to `fds` by both (TDS is on FD interest, so the label is arguable; labels stay as registered).
- Guarded answers fell (96% -> 90-92%) on the new tasks. All failures used up 3 drafts with a number rejected each
  time. The harness kept only the count of rejections, not the drafts, so whether the model invented numbers or
  the guard refused a legitimate rewrite (e.g. a margin written as a percent) cannot be told from these files.
- Materiality is unchanged at about 79-80% on unseen 2023 headlines: confirmed as the model gap.

## Next (S47, under a new registration)
1. Save every rejected draft and the rejected tokens in the answers detail, so the cause is visible.
2. Materiality: prompt tuning on a split of the labelled headlines, then QLoRA in `.venv-train` only if the gap stays.
3. Two-part routing: allow more than one tool per question, tested on unseen questions.
