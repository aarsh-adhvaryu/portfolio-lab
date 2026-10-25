# Haiku 5.5 vs the local model (qwen3:8b-q8_0): pre-registered protocol (2026-10-24, step 1 of the one-brain program)

Written and committed before any Haiku call on these sets. The investor 2026-10-24: if the local model is not needed after
the five steps, it goes; this measurement decides which of its jobs move now.

## Tasks (the local model's jobs)

1-4. **eval12** (`llm/eval12.py`, unchanged code and sets): routing (round-2 set, 60 questions), guarded answers
(round-3 seed 20261018, 50 tasks, production guard), extraction (100 NSE texts, gold from the parsers), materiality
(round-2 set, 200 BSE headlines, gold from BSE's subcategory). The local model's scores are the recorded ones
(`model_eval_12gb_round2_results.md`, `..._round3_results.md`): routing 95%, answers final 100%, extraction F1 1.00,
materiality 79%. Thresholds as registered in S42: routing >= 95%, answers final >= 98%, extraction F1 >= 0.95,
materiality >= 90%.

5. **live answers** (new): the first 12 questions of the round-2 routing set whose labelled tools read the investor's own data
(networth, fds, guards, plan, risk, tax), answered by the ask centre on the real ledger with its labelled tools, the
draft written by each model and checked by the production guard (`llm.graphs.run`, up to 3 drafts). Score: the share
of questions with a checked answer. Both models run it today, same facts, same order.

## Haiku settings

`claude-haiku-5-5`, effort low (routing, extraction, materiality) and medium (answers), the same prompts as the local
model, JSON asked for in the system text (no structured-output schema, as the local model had none beyond Ollama's
format hint), the API through the egress list (identity and banking never) and priced. Spend stops at Rs 150 for the
whole run.

## Decision rule (per task)

Haiku takes a task when it meets the task's threshold **and** is not more than 2 points below the local model's
score; otherwise the local model keeps it for now (Sonnet is measured in step 3). For live answers: Haiku takes them
when its checked share is higher. The local model leaves the main path when Haiku takes every task; whether it is
removed altogether is decided after step 5 (The investor). Latency is reported, not judged (the API is not on this GPU).

## Reported

`docs/llm/haiku_vs_local_results.md`: scores side by side, cost per task and per month at live volumes, failures read.
