# Model evaluation for the 12 GB GPU, round 2: protocol (registered 2026-10-17T12:12, before any round-2 run)

## Why a second round
Round 1 (`model_eval_12gb_protocol.md`, run 2026-10-16/17) chose no model: none passed all five thresholds.
The best, qwen3:8b (4-bit), scored routing 90%, guarded answers 96%, extraction 100%, materiality 82%, p90
latency 6 s. Its six routing misses were mostly questions that most candidates also missed, and their cause was
the system, not the models: the guards tool's description did not mention the Nifty 500 drawdown or the dip rule,
no tool carried the FD deployment schedule, and two-part questions got one tool. Fixed before this registration:
clearer tool descriptions (`agents/tools.py` TOOLS) and the deployment schedule in the plan tool.

Round 1's routing questions and headlines were then used to diagnose those failures, so they are no longer
unseen. Round 2 uses NEW sets; passing round 1's sets again would prove nothing.

## Candidates
qwen3:8b-q4_K_M (5.2 GB) and qwen3:8b-q8_0 (8.9 GB): the two that led round 1. Others are not re-tested.

## Tasks (as round 1, new data)
1. **Routing**: 60 new questions, `docs/llm/eval12_routing_r2.toml` (no overlap with round 1).
2. **Guarded answers**: 50 drafting tasks from `llm.evalset.build(seed=20261017, n=50)` (all 50 differ from round 1).
3. **Extraction**: the round-1 set, unchanged (every candidate passed it; nothing was tuned on it).
   SHA-256 4693c3ac392b61d43c144b94197ae97ed2dece5cd89dea873e294bd0e8cff8a7.
4. **Materiality**: 200 new BSE headlines from 2023 (round 1 used 2024-01 to 2026-09; no overlap), same subcategory
   map, seed 20261017. File `data/llm_eval/materiality_r2.json`, SHA-256
   eaf831f215f61863c8c6091e535aac7815dab7714aa63699e6c6cda75cf80fca.
5. **Latency**: p90 seconds per guarded answer.

## Thresholds and decision rule: unchanged from round 1
routing >= 95%; answers final >= 98%; extraction F1 >= 0.95; materiality >= 90%; latency p90 <= 20 s. The smaller
download wins among models passing all five; ties go to the faster, then the higher-bit version. If neither
passes: no model; `pflab ask` stays facts-only; the remaining gap (expected: materiality) goes to S47 tuning
(prompt or QLoRA) under a new registration.

## How it is run
`powershell -ExecutionPolicy Bypass -File tools\run_eval12.ps1 -Round 2` (pulls, runs and removes each model;
results in `data\llm_eval\results_r2\`), then `pflab llm decide12 --round 2`, and `--record` to apply.
