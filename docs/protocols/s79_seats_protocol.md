# S79b item 17: the two local seats, FAST and THINKER (protocol, registered 2026-11-08 before any run of a challenger)

The investor's words: two local seats, FAST (resident in market hours; candidates Gemma 4 12B, Qwen3.5-9B, the current qwen3:8b) and THINKER
(loaded in post_close/deep; candidates Qwen3.6-35B-A3B or Gemma 4 26B-A4B, qwen3:30b-a3b, through the llama.cpp server with --n-cpu-moe); "pick each
by the existing evals; check RAM headroom with the app, DuckDB and Docker running; qwen3:8b stays the fallback". Each pick is a measured decision and
counts in the learner's counter as one test (templates `seats_s79:fast` and `seats_s79:thinker`, registered by `learner/s79.py`, note keys
`s79:seats_fast` and `s79:seats_thinker`). Code: `src/pflab/llm/s79_eval.py` (`decide_fast`, `pick_fast`, `decide_thinker`), harness
`tools/s79_llm_diag.py` (`run`, `decide-fast`, `decide-thinker`); seats machinery `src/pflab/llm/seats.py`, `configs/seats.toml`.

## Sets (the existing ones of item 13, none new, none tuned on; the harness's own prompts, schemas, `num_predict`, seed and guard)
- routing: 60 questions, `configs/llm_eval/eval12_routing_r2.toml`, score = `eval12.route_ok`.
- answers: 50 drafting tasks x seeds 20261017 and 20261018 (100 pooled), the production guard, final pass.
- extraction: 100 NSE corporate-action texts, micro F1.
- materiality: 200 BSE headlines, accuracy.
Every arm of a model is run by `tools/s79_llm_diag.py run --arm A --model M`: the old default sampling (temperature 0, the fixed seed, no other
option), thinking OFF (`think=false` in the Ollama request: the harness already passes it for all models, the same for every arm), one task at a time,
nvidia-smi before each task, 20 s between tasks. The incumbent's numbers are its arm A of 2026-11-05 (`results_s79/A__qwen3_8b-q8_0`), run alone on the card.
Challengers are run on a card that other agents may touch with short qwen3:8b calls (Ollama reloads a model evicted by them; that adds latency noise
that only hurts the challenger, which is the conservative direction; a marginal latency failure is re-measured once alone before it is final).

## FAST seat: a challenger replaces qwen3:8b-q8_0 only if ALL hold (`decide_fast`)
1. **Not worse on any task by the harness's own margin** (the margins of `decide_sampling`): routing >= incumbent - 1/60; answers_final >= incumbent - 0.02;
   extraction F1 >= incumbent - 0.01; materiality >= incumbent - 0.01.
2. **Better overall:** the unweighted mean of the four scores is at least 0.01 above the incumbent's.
3. **Latency on this GPU:** p90 of the per-call seconds <= 8 s for routing and <= 8 s for extraction; written-answer p90 per task <= 20 s (harness threshold).
4. **VRAM:** the card's peak memory.used (nvidia-smi, all processes, the display's allocation included) <= 11,264 MiB (11 of the 12 GiB), measured during the arm.
5. **Failures:** (loop + truncated + empty + format) rate not above the incumbent's. All five tasks completed with no GPU loss.
If several pass, the best mean of the four scores wins (tie: the lower routing p90). If none passes the seat stays qwen3:8b-q8_0 and a `seat-fast` row records
"chosen" for the incumbent. Qwen3.5-9B: the Q6 tag in the brief does not exist in the Ollama library; the default `qwen3.5:9b` (Q4_K_M, 6.6 GB) is what is tested.
Qwen3.5-9B and gemma3:12b were already tested in round 1 (S42, other prompts/sets, "not chosen"); this is a new, separate test of the current builds.

## THINKER seat: a challenger replaces qwen3:8b-q8_0 only if ALL hold (`decide_thinker`; the guarded window is scheduled by the lead, not this agent)
1. **Beats on score:** on at least one of routing, answers (pooled 100), materiality an exact one-sided sign test on the paired items has p < 0.05/3; and on
   none of them is the challenger significantly worse (p < 0.05 the other way); extraction F1 not lower by more than 0.01.
2. **Answers** `answers_final >= 0.98` (harness threshold) and written-answer **p90 <= 90 s**; routing p90 per call <= 60 s (nothing interactive waits on it).
3. **RAM headroom after load >= 6 GB** with the app, DuckDB and Docker running (measured from `server.free_ram_gb()` after the model is loaded and warm).
4. **Stability:** zero crashes, out-of-memory events, server restarts or GPU losses during the guarded run (any one stops the run and fails the candidate).
5. Failure rate not above the incumbent's.
If none passes THINKER stays qwen3:8b-q8_0. The run is guarded by `seats`/`server` start guards (clock caps acknowledged, free RAM and free GPU floors).

## Sampling comparison (qwen3:8b with Qwen's recommended profile, arm B)
The comparison is the one registered in `s79_local_model_protocol.md` (item 13), rule `decide_sampling`, unchanged; it was pending. Run it as arm B
after the FAST arms and record it with `decide-sampling`. It does not select a seat model.

## Registration
`configs/llm_models.toml`: `[[pick]] role = "seat-fast-candidate"` for gemma4:12b and qwen3.5:9b (registered before any run); the winner of each seat gets a later
`[[pick]] role = "seat-fast"` / `"seat-thinker"` with `decision = "chosen ..."`, and its `[model."<key>"]` entry in `configs/seats.toml`.
`manage` stays as the lead sets it.

## Amendment 1 (2026-11-08, before the THINKER runs): the matched subset of the guarded window
The full sets would take hours on a model that runs partly on the CPU, so the guarded THINKER window (the investor's "guarded run", 2026-11-08) uses a
MATCHED SUBSET, the same items for the challenger and the incumbent, fixed here before any THINKER run:
- routing: all 60 (the set has 60); answers: the first 20 tasks of seed 20261017 only (one seed; `evalset.build` draws task i from a sequential generator, so
  the first 20 of n=50 are the first 20 of n=20); extraction: the first 40 of the 100 texts; materiality: the first 60 of the 200 headlines.
- Harness, prompts, schemas, `num_predict`, seed, production guard and scoring unchanged (arm A: the old default sampling, thinking OFF). Items are scored
  by the harness's own functions; a request that takes over 240 s is a failure and ends the candidate.
- The incumbent's numbers for the same items are taken from its saved arm A per-task records (`results_s79/A__qwen3_8b-q8_0`: per-item right/wrong, per-call
  seconds, per-task seconds), sliced to the same items; its extraction F1 on the saved record is 1.0 for all 100 texts, so it is 1.0 on any subset. Nothing is re-scored.
- The THINKER rule of this protocol applies unchanged to the subset (`decide_thinker`): beats on score (sign test, p < 0.05/3, on routing, answers or materiality),
  not significantly worse, extraction F1 not lower by more than 0.01, answers_final >= 0.98, answers p90 <= 90 s, routing call p90 <= 60 s, RAM headroom after load
  >= 6 GB, zero crashes/OOM/GPU loss, failure rate not above the incumbent's. The pooled answer items are the 20 of one seed (the second seed's file is an empty marker).
  A subset of 60 and 20 items has little power: a challenger that wins here is a candidate for a longer run, and a failure is a failure of this rule only.
- Guards of the window (hard rules): clocks capped (nvidia-smi -lgc 210,2100, -lmc 405,9001) and no other model resident before each candidate; GPU < 70 C and < 2.5 GB used,
  free RAM >= 10 GB; a watchdog every 5 s: nvidia-smi must answer, temperature <= 82 C, free RAM >= 2.5 GB, the model process alive; 70 minutes per candidate; one request at a time;
  a trip kills the model process and fails the candidate as "not verified (reason)". Recorded for each candidate: load time, generation and prompt tokens/s, peak GPU memory,
  minimum free RAM, peak temperature.
- Candidates, in order, registered as role `seat-thinker-candidate` at 2026-11-08T03:38 (before any run): qwen3:30b-a3b (Ollama), qwen3.6-35b-a3b (llama.cpp server,
  Q4 GGUF, --n-cpu-moe, ctx 4096), gemma4-26b-a4b (llama.cpp server, Q4 GGUF). The result file set for the subset is `AM__<model>` (the incumbent's slice is `AM__qwen3_8b-q8_0`).
  Each decision counts as one test in the learner's counter (`seats_s79:thinker`).
- Outcome of the window (2026-11-08 03:45-04:15): no candidate was started. The preflight (free RAM >= 10 GB; the CPU part of the model must also leave 2.5 GB + margin) failed every minute: free RAM
  was 4-6 GB (the investor's browser ~13 GB, plus the lead's runs). All three are recorded "not verified (RAM guard)"; no test was made, so none counts in the learner's counter and the THINKER seat stays qwen3:8b-q8_0.
  A rerun needs about 14 GB free (for qwen3:30b-a3b) up to 20 GB (qwen3.6-35b-a3b): `python tools/s79_thinker_window.py run --model KEY --wait-until HH:MM` (needs PFLAB_DATA_DIR).
- Rerun (2026-11-08 04:23-05:18; supersedes the outcome note above): free RAM had been held by orphaned test browsers (fixed by the lead), so the guarded window ran. Run as registered, all guards on; for
  the llama.cpp server the flags `--load-mode none --cache-ram 0 --ctx-checkpoints 4` were added after two RAM-guard trips of qwen3.6-35b-a3b (mmap pulled the file in at load; then the server's 8 GB prompt cache grew
  during the run); `--n-cpu-moe` 24 (of 41 layers) for qwen3.6-35b-a3b and 16 (of 30) for gemma4-26b-a4b. A VRAM trip at 11,900 MiB was added to the watchdog. Verdicts (THINKER rule, matched subset): none chosen; see docs/STUDIES.md.
