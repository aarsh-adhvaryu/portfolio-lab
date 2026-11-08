# Model lab (A41, S79)

A separate workspace to steer or QLoRA-tune the local model (qwen3 8B) and hand the app a **GGUF**. Development only.

## What the app sees
Only an Ollama tag. The lab ends with `ollama create <tag> -f Modelfile`; from then on the tag is one more local model that
`pflab.llm.client` can call. **The app never imports torch**, transformers, peft or trl: they live in the optional extra `[ml]` of
`pyproject.toml`, which is not in `requirements.lock` and not installed with the app (a test checks that `import pflab` loads none of them).
Every script here runs its `--dry-run` without the extra and, when a real step needs it, stops with one clear message (exit code 3).

## Workflow
1. **Data**: `build_dataset.py --ledger <COPY of ledger.duckdb>` -> `datasets/train.jsonl`, `valid.jsonl`, `manifest.json`.
2. **Steer or QLoRA**: `steer.py` (a direction from contrastive prompts, applied by a hook; an experiment on the base model) or
   `train_qlora.py` (4-bit QLoRA, recipe in `config/qlora_qwen3_8b.toml`). Always `--dry-run` first.
3. **Merge and convert**: `merge_and_gguf.py` merges the adapter into the bf16 base on the CPU, converts with llama.cpp
   `convert_hf_to_gguf.py` and quantises with `llama-quantize` (`--dry-run` prints the exact commands).
4. **Ollama**: `make_modelfile.py --gguf <file> --tag <tag>` then `ollama create <tag> -f outputs/Modelfile.<tag>`.
5. **Same evals as the app**: `run_evals.py --tag <tag> --round N` calls `pflab.llm.eval12.evaluate` (routing, guarded answers, extraction,
   materiality from `configs/llm_eval/*` and `data/llm_eval/*`; same seeds, prompts, thresholds) and writes the app's result shape
   `{model, scores, passes, detail, run_at}` (plus a `harness` block) to `outputs/evals/`.
6. **Register, then adopt**: a pick is registered in `configs/llm_models.toml` BEFORE its full run (`run_evals.py` refuses otherwise; a
   `--limit` smoke run is exempt and flagged). Adoption happens only through a pre-registered comparison against `qwen3:8b-q8_0` on unseen
   data (rule 10; the comparison counts in the learner's counter). A tag that fails has no live use. Changing the model is a measured decision (rule 9).

## Hardware (RTX 5070 Ti Laptop, 12 GB)
* QLoRA: 4-bit NF4 base (about 5.5 GB), LoRA r=16 on all attention and MLP projections, gradient checkpointing, batch 1 x accumulation 16,
  `max_len` 2048: fits 12 GB. Close the app and `ollama stop` any loaded model first (the card is shared).
* The laptop GPU drops off the bus at top boost under sustained load. **Before a long run**, from an Administrator PowerShell:
  `nvidia-smi -lgc 210,2100` and `nvidia-smi -lmc 405,9001`. After a loss use Restart, not Shut down.
* Blackwell (sm_120) needs the CUDA 12.8 torch wheel (see `requirements-ml.txt`). Use a separate venv (`.venv-train`, as in S47).
* The merge runs on the CPU in bf16 (about 16 GB of RAM) so it does not fight Ollama for the card.

## Privacy
Training data is built from **the system's own journal** (guarded briefs in a ledger copy) and **public text** only. No statements, no
personal records. The builder reads a copy (the live store and the app's folder are refused), drops every row the guard rejected, and
drops (does not edit) any example that `pflab.scrub` or `hq/redact.py` would change. Datasets, adapters, GGUFs and eval outputs are gitignored.

## Known limits (be honest before a real run)
* The `briefs` table keeps the text but not the facts it was written from. Trained on text alone the model learns the style and the citation
  habit, **not** the discipline of using only given numbers; it may even learn to invent them. Before a real QLoRA run the journal must keep the
  prompt with its facts (`build_dataset.py` already uses a `prompt` column when the table has one).
* No training has been run in S79; `train_qlora.py`, `steer.py` and `merge_and_gguf.py` real paths are untested against a GPU (their
  dry-runs, maths and plumbing are tested). Versions are pinned in `[ml]`; check them on first install.
* Steering changes no weights: it cannot be shipped as a GGUF as it is.
