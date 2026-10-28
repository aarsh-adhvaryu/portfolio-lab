# S47 model tuning, pass 1: prompts by measurement (protocol, registered 2026-10-17 before any run)

Model: qwen3:8b-q8_0 (chosen 2026-10-17). Code: `llm/tuning.py`; run: `pflab llm tune materiality|routing|writing`
(in the overnight run). Nothing changes in the agents automatically: a winning prompt is wired in by hand only if it
passes the rule below, in the next session.

## Tasks, sets, variants
| task | train (choose the variant) | test (judged once) | variants |
|---|---|---|---|
| materiality | round-1 headlines (200) | round-2 headlines (200, 2023) | v0 current; v1 + definitions of material and routine; v2 = v1 + 8 examples drawn from train (seed 20261018) |
| routing | round-1 questions (60) | round-2 questions (60) | v0 current; v1 + "pick every tool a part of the question needs"; v2 = v1 + 6 examples from train |
| writing | list companies x as-of 17 Jul, 17 Aug, 17 Sep, 17 Oct 2026, half the companies (seeded) | the other half | v0 brief prompt as used; v1 + plain-sentence format rules ([inf], units, no markdown); v2 = v1 + one worked example |

| research (added 2026-10-17, before any run) | 10 of the 20 registered comparison questions (seeded split) | the other 10 | v0 the comparison's local prompt (amendment 1); v1 + plain sentences, one tag each, figures only as written; v2 = v1 + at most 250 words + one worked example |

Writing and research are scored by the guard as it runs live: the share of tasks with an answer that passes within
3 drafts (research: threshold 0.70; the comparison's local half passed 6 of 20).

## Rule (fixed now)
For each task: the variant with the best train score (ties: the simpler one) is scored on test once, with v0 beside
it. Adopt the variant if its test score is at least the threshold (materiality 0.90, routing 0.95, writing 0.85)
AND above v0's test score (thresholds: materiality 0.90, routing 0.95, writing 0.85, research 0.70). A task whose best
variant misses the threshold is the candidate for QLoRA (S47 pass 2,
`.venv-train`, its own registration). Test sets are not used again for choosing.
