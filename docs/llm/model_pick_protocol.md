# Research-model pick: protocol (registered 2026-10-06T17:18:20, before any evaluation)

Registered in `configs/llm_models.toml` as role `research`, model `qwen3.5:27b`. This file fixes the
evaluation, its metric and its decision rule **before** the model is pulled or run. Nothing below may
be changed after the first evaluation run; a different design is a new, later registration.

## Question

Is `qwen3.5:27b` (Q4, CPU offload) good enough at guarded drafting to be the overnight research model,
compared with staying on the 9B baseline (`qwen3.5-9b-16k`)?

## Task set (fixed now, generated from a seed, not tuned)

40 drafting tasks from `pflab.llm.evalset.build(seed=20261006)`: each gives a facts table of 6 to 10 code-made
values (money, percent, dates, counts), 2 to 3 short source excerpts, and the instruction to write a
3-sentence note that cites every claim with `[F:name]` or `[S#]` and uses only table values written as
digits. Both models get identical prompts, temperature 0, the same seed, `think` off, 400 tokens.

## Metric (single primary)

**First-attempt pass rate**: the share of the 40 drafts that pass `llm.guard.check_all` with no violations on
the first generation (no regeneration). Secondary, reported only: tokens per second, peak memory, seconds
per draft, pass rate within 3 attempts.

## Decision rule

`qwen3.5:27b` becomes the research model if and only if both hold:
1. its first-attempt pass rate is at least **10 percentage points above** the 9B's on the same 40 tasks, and
2. it generates at least **2 tokens per second** on this laptop (otherwise an overnight report is impractical).

If either fails, the 9B stays the research model and the registration records `decision = "keep 9B"`.
A tie or a smaller gap is "keep 9B". The result is written to `configs/llm_models.toml` (`evaluated_at`,
`decision`) and `docs/llm/`, with the run ids from `llm_runs`.

## Not part of this decision

Report quality as a person reads it; correctness of any number (the guard checks that numbers come from the
table, not that the table is right); long-context behaviour beyond the task set. Those are judged on real
reports in S27.
