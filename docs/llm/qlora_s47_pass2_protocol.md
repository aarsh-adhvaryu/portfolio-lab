# S47 pass 2: QLoRA for writing and research (protocol, registered 2026-10-18 before any data was generated)

Pass 1 (`tuning_s47_results.md`) left two tasks below their bar: writing (briefs; best prompt 0.79 vs 0.85) and
research (answers from public documents; 0.40-0.50 vs 0.70). Pass 2 fine-tunes the base model on its own guard-passing
answers. Code: `llm/qlora.py` (tasks, data, evaluation; main venv), `tools/qlora_train.py` (training; `.venv-train`
only), `tools/qlora_setup.ps1` (environment). Nothing changes in the agents unless the rule below passes.

## Model and environment
Base: `Qwen/Qwen3-8B` from Hugging Face, the weights behind the chosen `qwen3:8b-q8_0`; the downloaded revision is
written to `REVISION` beside the weights and into the training log. `.venv-train`: torch 2.14.1 (CUDA 13.0 build),
transformers 5.20.1, peft 0.21.2, bitsandbytes 0.50.2, accelerate 1.15.0. GPU: RTX 5070 Ti laptop, 12 GB.

## Tasks, split, dates (fixed now)
- Companies: the stock list split exactly as pass 1's writing split (seed 20261018): the first half trains, the
  second half is only ever evaluated. No evaluation company contributes a training example.
- Training dates: every Friday from 2025-03-07 to 2026-06-26 (69). Evaluation dates: 15 Jan, 16 Feb, 16 Mar, 15 Apr,
  15 May, 15 Jun 2026. Pass 1 used 17 Jul - 17 Oct 2026; none of those dates is used here.
- Writing task: the brief as built live (`kb.context`, 90 days, 8 sources) with pass 1's best suffix (v2).
- Research task: one question per (company, date), the three templates below rotated from a seeded start, answered
  from `analyst.public_docs` with the local prompt and pass 1's best suffix (v1):
  1. What did {name} disclose to the exchange in the 90 days to {date}, and what do those disclosures say?
  2. What do {name}'s filed results and exchange filings up to {date} show about how the business is doing?
  3. Which risks for {name} are visible in its filings and results up to {date}, and what do they leave unclear?
- A task with nothing on record by its date is skipped (it is the same for both models).

## Training data (rejection sampling, local)
The base model (`qwen3:8b-q8_0`, Ollama, thinking off) drafts every training task exactly as live: up to 3 drafts with
the S21 guard's feedback (`graphs.run`, cited source numbers allowed). A task whose final draft passes adds one
example: (the first prompt, the passing answer). Failed tasks add nothing. No API model and no personal data are used.

## Training (fixed now)
QLoRA: 4-bit NF4 base with double quantisation, bf16 compute; LoRA r 16, alpha 32, dropout 0.05 on q, k, v, o, gate,
up and down projections; AdamW, learning rate 1e-4 with 3% warm-up then cosine; 2 epochs; effective batch 8 (one
example, 8 accumulation steps); gradient clipping 1.0; examples longer than 4,096 tokens dropped; seed 20261018; loss
on the answer tokens only; one adapter for both tasks. The adapter is merged into the bf16 base and imported into
Ollama as `pflab-qwen3-8b-s47`, quantised q8_0 like the base (`pflab llm qlora export`); if Ollama will not import the
architecture, the fallback is llama.cpp's `convert_hf_to_gguf.py` (gguf 0.19.0) and `llama-quantize` q8_0, recorded
as an amendment before use.

## Evaluation and rule (fixed now)
On the evaluation tasks, the base model and the tuned model each answer with the same prompts as above (writing v2,
research v1); measure: guard pass within 3 drafts (first-draft pass reported too), as in pass 1. For each task, the
tuned model is adopted if its pass rate is at least the pass-1 threshold (writing 0.85, research 0.70) AND above the
base model's on the same tasks (`qlora.decide`). Adopted: that task (briefs, or local research answers) uses the
tuned model with that prompt; routing and guarded answers stay on the base model. Not adopted: nothing changes; a
third attempt would need its own registration. The evaluation tasks are judged once.

## Amendment 1 (2026-10-19, before any tuned-model evaluation): import as int8
Ollama 0.40.5 refuses `--quantize q8_0` for a safetensors import ("supported types are int4, int8, nvfp4, mxfp4,
mxfp8"). The tuned model is imported with `--quantize int8`, Ollama's 8-bit format for this path, instead of the
llama.cpp fallback (which would need new downloads). The decision stays as registered: the tuned model against the
base `qwen3:8b-q8_0` already evaluated. Reported beside it, not deciding: the same base weights imported the same way
(`pflab-qwen3-8b-base-int8`) and evaluated on the same tasks, so a difference between the two 8-bit formats cannot
pass for a training effect unseen.

## Amendment 1b (2026-10-19, replaces amendment 1, before any tuned-model evaluation): GGUF Q8_0 via llama.cpp
The int8 import failed too: Ollama on Windows quantises a safetensors import only through MLX, which is not available
here. So the registered fallback is used: llama.cpp's `convert_hf_to_gguf.py` (release v0.7.0, with its own `gguf-py`)
writes the merged weights as GGUF Q8_0, the base model's own format, and `ollama create` imports the file unchanged.
The decision stays as registered (tuned against `qwen3:8b-q8_0`). Reported beside it, not deciding: the untuned base
weights converted the same way (`pflab-qwen3-8b-base-q8`) and evaluated on the same tasks.

## Implementation note (2026-10-19; no registered setting changed)
Two training attempts failed on the GPU: memory sat at 11.8 of 12.2 GB, progress crawled (under 40 examples in 15
minutes) and the GPU dropped off the bus. Cause: peft's `prepare_model_for_kbit_training` cast the frozen bf16 parts (two
152k-word vocabulary tables, about 5 GB in fp32) to fp32, and the loss built logits over every prompt position. Fixed:
frozen parts stay bf16; logits only for the answer tokens (the same mean cross-entropy, checked against the labels loss
in the smoke test); a probe of the 6 longest examples gates training (8.0 GB peak, 4 s per example); checkpoints every
5 steps with resume. Data, split, hyperparameters, export and rule are unchanged.
