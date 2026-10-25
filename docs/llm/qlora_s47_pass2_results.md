# S47 pass 2 (QLoRA): results (2026-10-20)

Run under `qlora_s47_pass2_protocol.md` (amendments 1b and the implementation note). Training data: 966 tasks on the
training half, 680 kept by rejection sampling. Training: 2 epochs, 170 optimizer steps, 38 min, peak 8.2 GB; loss
about 0.11 to 0.06-0.07 in epoch 2. Export: GGUF Q8_0 (llama.cpp v0.7.0), `pflab-qwen3-8b-s47`.

Evaluation half (6 companies x 6 dates; tasks with nothing on record skipped): guard pass within 3 drafts (first draft).

| model | writing (36) | research (30) |
|---|---|---|
| base `qwen3:8b-q8_0` (decides) | 0.778 (0.667) | 0.633 (0.367) |
| tuned `pflab-qwen3-8b-s47` | 0.778 (0.722) | 0.567 (0.467) |
| check: base weights converted as the tuned (reported only) | 0.722 (0.694) | 0.733 (0.567) |

**Decision (registered rule): NOT ADOPTED for writing (0.778, below 0.85 and not above base) or research (0.567,
below 0.70 and below base).** Nothing changes in the agents: briefs and local research answers stay on
`qwen3:8b-q8_0` with their current prompts.

**What the check shows.** The same untuned weights scored 0.633 and 0.733 on research across the two exports and runs,
so on 30-36 tasks a difference of about 0.1 is noise. Training moved first-draft passes up a little (writing 0.67 to
0.72, research 0.37 to 0.47) but no measured pass rate beyond that noise. Self-distillation on the model's own passing
answers taught the format it already reaches within three drafts, not new ability.

**For any third attempt** (its own registration): an evaluation set large enough to see a 0.1 gain (several hundred
tasks), and training targets that are better than the base model's own (for example the API analyst's notes on
public documents), measured against a threshold the base cannot already reach by chance.

Kept on disk (not used by the agents): `PFLAB_DATA_DIR\llm_eval\qlora\` (data, run1 adapter, merged weights, GGUF),
`models\Qwen3-8B`, `.venv-train`, and the Ollama models `pflab-qwen3-8b-s47`, `pflab-qwen3-8b-base-q8`.
