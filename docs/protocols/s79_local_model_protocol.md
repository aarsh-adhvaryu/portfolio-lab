# S79 item 13: local model, sampling and a larger MoE (protocol, registered 2026-11-05 before any run)

Two comparisons, both on the existing S42/S43 evaluation sets, both counted in the learner's counter as tests (family "all", origin
"study", templates `s79_llm_sampling` and `s79_llm_moe`; recorded by `tools/s79_llm_diag.py record`). Code: `src/pflab/llm/s79_eval.py`
(rule in `decide_sampling`, `decide_moe`), `llm/client.py` (sampling profiles), `llm/diag.py` (loop, truncation, empty, format reading).
The model picks are registered in `configs/llm_models.toml` (role `eval-s79-moe`, `qwen3:30b-a3b`, registered 2026-11-05T09:00, before
the download); `registry.require_registered` is checked before the MoE run. Sampling is not a model pick; it is registered here.

## Sets (all existing, none new; none tuned on)
- routing: 60 questions `configs/llm_eval/eval12_routing_r2.toml` (round 2/3 set), score = tools picked per `eval12.route_ok`.
- answers: 50 drafting tasks per seed, seeds 20261017 (round 2) and 20261018 (round 3), the production guard, pooled 100 tasks.
  Final pass = the guard accepts a draft within its attempts. Latency per task.
- extraction: 100 NSE corporate-action texts (`data/llm_eval/extraction.json`), micro F1.
- materiality: 200 BSE headlines (`data/llm_eval/materiality_r2.json`), accuracy.
Prompts, schemas, `num_predict`, seed (`client.SEED`) are the harness's own, unchanged. Only the sampling options (comparison 1) or the
model (comparison 2) differ between arms.

## Diagnosis (done first, no rule needed: counts only)
`llm_runs` of a copy of the app's store (31 calls, all `ok`, no loops visible: the table has tokens, seconds, status and note, not the text,
so a loop cannot be read from it; from now on `client.chat` writes the `diag` label into `note` and Ollama's `done_reason` is kept).
Loop, truncation, empty and format rates are therefore measured here on the raw replies of the evaluation arms, per task kind.

## Comparison 1: Qwen's recommended sampling vs the old default (qwen3:8b-q8_0)
- Arm A (old): temperature 0, the fixed seed, no other option (today's default).
- Arm B (new): `sampling="auto"`: free text, thinking off: temperature 0.7, top_p 0.8, top_k 20, min_p 0, presence_penalty 1.5;
  constrained (JSON) calls take the same values (profile "json" = "text" for this run); same seed. (Qwen3 model card, non-thinking mode.)
- Per call kind, B is adopted for that kind only if it does not lose AND it reduces failures:
  - kind **text** (answers): `answers_final(B) >= answers_final(A) - 0.02`, first-attempt pass `B >= A - 0.04`, median latency `B <= 1.25 * A`,
    and the failure rate (loop + truncated + empty over all raw replies of the answers task) is strictly lower for B than for A.
  - kind **json** (routing, extraction, materiality): `routing(B) >= routing(A) - 1/60`, `materiality(B) >= materiality(A) - 0.01`,
    `extraction_f1(B) >= extraction_f1(A) - 0.01`, and the failure rate (loop + truncated + empty + format) strictly lower for B than A.
  A kind adopted goes into `client.DEFAULT_KINDS`. A kind not adopted keeps the old default; the profile stays available by name.
  If A has no failures at all there is nothing to reduce: "not adopted" (determinism of temperature 0 is kept).

## Comparison 2: qwen3:30b-a3b (MoE, Q4_K_M, about 19 GB, CPU offload beside the 12 GB GPU) vs qwen3:8b-q8_0
Both run with the sampling arm chosen in comparison 1 (the 8b's adopted arm, per kind; A for kinds not adopted), so only the model differs.
The MoE is **adopted** (a new pick row, decision "chosen general+routing") only if ALL hold:
1. **Beats on score.** On at least one of routing (60 items), answers (100 pooled tasks), materiality (200 items), an exact one-sided sign
   test on the paired items (MoE right and 8b wrong vs the reverse) has p < 0.05/3 = 0.0167 (Bonferroni over the three tasks); and on none
   of the three is the MoE significantly worse (one-sided p < 0.05 the other way); and extraction F1 is not lower by more than 0.01.
2. **Harness thresholds** (`eval12.THRESHOLDS`) on routing >= 0.95, answers_final >= 0.98, extraction F1 >= 0.95. Materiality is not required
   (it is not used live: amendment 2026-10-17, where the 8b was adopted at 0.79).
3. **Latency and VRAM bound for the agenda on this 12 GB laptop GPU:** answer p90 <= 20 s (the harness threshold), answer median <= 12 s,
   routing-call median <= 8 s, generation speed (median tokens_out / seconds on answers) >= 10 tokens per second, and no GPU loss or Ollama
   failure during the run; `ollama ps` is recorded for the split between GPU and CPU. (The chat front's wait is 120 s; a routing call over
   8 s makes his chat feel slow.)
4. Failure rate (loop + truncated + empty + format) not above the 8b's.
Otherwise "not chosen". A model beaten only on materiality (not used live) is not adopted.

## Running (the GPU drops off the bus under sustained load)
`tools/s79_llm_diag.py run --arm A|B|C`: one task at a time, nvidia-smi checked before each task (abort on a failure, partial results kept
and resumable), 20 s pause between tasks, 90 s between arms. Results: `data/llm_eval/results_s79/` (JSON with the raw reply labels and per-item
outcomes) and rows in `llm_s79_eval` (migration 77). A concurrent single short model call by another process is tolerated (it adds latency
noise, noted in the result).
