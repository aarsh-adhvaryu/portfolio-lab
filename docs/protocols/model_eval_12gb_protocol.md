# Model evaluation for the 12 GB GPU: protocol (S42, registered 2026-10-16T17:05, before any download)

PLAN A6. GPU: RTX 5070 Ti Laptop, 12,227 MiB. Candidates are registered in `configs/llm_models.toml` (roles
`eval12`, `eval12-decision`); `pflab llm eval12` refuses a model that is not registered there earlier. Nothing
below may change after the first run; a different design is a new, later registration.

## Candidates (Ollama library tags, sizes read 2026-10-16)
| model | quantization | download |
|---|---|---|
| qwen3:8b-q4_K_M | 4-bit | 5.2 GB |
| qwen3.5:9b-q4_K_M | 4-bit | 6.6 GB |
| gemma3:12b-it-q4_K_M | 4-bit | 8.2 GB |
| qwen3:8b-q8_0 | 8-bit | 8.9 GB |
| qwen3:14b-q4_K_M | 4-bit | 9.3 GB |
| qwen3.5:9b-q8_0 | 8-bit | 10 GB |
| laya (decision model, 421M) | - | 0.4 GB |
Q6_K is not offered in the Ollama library for these models and gemma3:12b at 8-bit (13 GB) does not fit; both
are left out rather than imported by hand. Laya is judged on routing and materiality only.

## Tasks and labels (labels never come from a model)
1. **Routing**: 60 questions in `docs/llm/eval12_routing.toml`, each labelled with the agent tools it needs.
   Correct when every needed tool is picked and at most one more. JSON-schema-constrained choice, as `pflab ask`.
2. **Guarded answers**: 50 drafting tasks from `llm.evalset.build(n=50)` (seed 20261006; the first 40 are the
   S21 set), through the draft-check-revise loop (3 attempts). Measures: final pass rate (primary),
   first-draft pass rate and guard rejections per task (reported).
3. **Extraction**: 100 NSE corporate-action texts (2015 on; 40 single-amount dividends in rupees, 20 bonuses,
   20 face-value splits, 20 other actions with no number), gold fields from the tested parsers
   (`data.dividends.parse_dividend`, `data.nse_corporate_actions.parse_purpose`). Micro F1 over (field, value).
   File `data/llm_eval/extraction.json`, SHA-256 4693c3ac392b61d43c144b94197ae97ed2dece5cd89dea873e294bd0e8cff8a7.
4. **Materiality**: 200 BSE announcement headlines (2024-01 to 2026-09, at least 40 characters): 100 material and
   100 routine by BSE's own subcategory (`llm.eval12.MATERIAL` / `ROUTINE`). Accuracy.
   File `data/llm_eval/materiality.json`, SHA-256 fc60900c84003dd4c76dd4cc36a27c6ab2d759ea020c022c153e84a1f14b8308.
5. **Latency**: seconds per guarded answer (task 2, including revisions), 90th percentile.
Settings for every model: temperature 0, seed 20261016 for sets and 20261006 for drafts, thinking off, the
prompts in `llm.eval12` and `llm.evalset` as committed with this file.

## Pass thresholds (fixed now)
routing >= 95%; guarded answers final pass >= 98% (49 of 50); extraction F1 >= 0.95; materiality >= 90%;
latency p90 <= 20 s.

## Decision rule
The general model is the smallest download among candidates that pass all five; ties on size go to the faster
median answer, then to the higher-bit version. Laya replaces the general model for routing and materiality only
if it passes those two thresholds and is faster there. If no candidate passes everything, no model is chosen
for the failing roles: `pflab ask` stays facts-only and the gap is reported; fine-tuning (LoRA in
`.venv-train`) is considered only for a task with a measured gap, under a new registration.

## Amendment 1 (2026-10-16, before any download or run): how Laya is asked
Laya's model page (read 2026-10-16) shows it is served only on Ollama's `/v1/systemone` endpoint, scoring given
options; it has no chat. It is asked through that endpoint (`llm.eval12.evaluate_laya`) on the same 60 routing
questions and 200 headlines, the same thresholds: routing as one true/false question per tool, a tool picked
when its probability of "true" is at least 0.5 (at most 3, the most likely always kept); materiality as a
two-option choice (material, routine) described as in the chat prompt. `laya:latest` is 846 MB (the
candidate table's 0.4 GB was the 421M MLX build).

## How it is run (The investor: downloads and runs, one model at a time)
`ollama pull <model>`, then `.venv\Scripts\python -m pflab.cli llm eval12 --model <model>` (writes
`data/llm_eval/results/<model>.json` and logs every call in `llm_runs`), then `ollama rm <model>` if space is
short. After the last candidate: `.venv\Scripts\python -m pflab.cli llm decide12` applies the rule above and
prints the choice; Claude records it in `configs/llm_models.toml` and `docs/llm/`.
