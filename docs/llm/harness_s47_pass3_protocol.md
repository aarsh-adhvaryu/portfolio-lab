# S47 pass 3: harness search (propose, probe, compose): protocol

Registered 2026-10-20, committed before any search call. The investor chose it after reading Google's Harness2 (the method,
not the software: it runs only on Linux with Vertex AI coding agents and an unsandboxed network). Code: `llm/harness.py`,
`agents/analyst.py` (`propose_harness`, the only API call), `pflab llm harness search|eval|decide`. Changes after the
first search call need a dated amendment.

## What is searched
The **harness**: the instruction text appended to each task's prompt. Nothing else is editable: the model
(`qwen3:8b-q8_0`, local), the facts and sources, the S21 guard with its 3-draft feedback loop, the egress gate.
- Tasks as in pass 2: **writing** (the brief from `kb.context`, 90 days, 8 sources) and **research** (the local
  research prompt over `analyst.public_docs`, the pass-2 question templates rotated by a seed).
- Starting harness: pass 1's best on train (writing v2, research v1). The live harness is v0 (no added text).

## Companies and dates (fixed now)
Pass 1 and 2's company split (seed 20261018). **Search** uses the training half at the 69 Fridays 2025-03-07 to
2026-06-26 only. **Evaluation** uses the evaluation half at every second of those Fridays (35 dates; research
templates rotated from seed 20261020), dates pass 2 never evaluated on. No evaluation task is seen during the search.

## The search, per task kind (fixed now)
1. Probe the starting harness on batch B0: 30 training tasks drawn without replacement (seed 20261020).
2. Six rounds. In round r the editor, Claude Opus 5.5 through the doorbell (live, budget-checked, public text only),
   gets the current harness and up to 8 failures from the latest probe of the current harness (the failed final
   draft up to 1,500 characters and the guard's rejection messages; no documents) and returns two candidates: a
   general edit and an edit specific to this task, each at most 1,500 characters.
3. Probe the current harness and both candidates on a fresh batch Br of 30 training tasks (the same tasks for all
   three). Compose: the candidate with the most passes replaces the current harness only if it passes at least 2 more
   tasks than the current one on Br (ties: general first). The current harness's failures on Br feed round r+1.
The search stops early if the next call would pass the investor's monthly cap; it expects about 12 calls, about Rs 200-250.

## Judgement (fixed now, once)
On the evaluation tasks, the live harness (v0) and the final harness each run as live; measure: guard pass within 3
drafts (first-draft pass reported). For each task kind, the final harness is **adopted** if its pass rate is at least
the pass-1 threshold (writing 0.85, research 0.70) AND it beats the live harness on the paired tasks with an exact
one-sided McNemar p < 0.05. Adopted: that task's live prompt gets the final harness text (briefs: `brief.PROMPT`;
local research answers: `analyst_compare.local_prompt`). Not adopted: nothing changes.

## Amendment 0 (2026-10-20, before any search call)
Every second Friday includes 2026-05-15, which pass 2 evaluated on; it is dropped, so evaluation uses 34 dates (the
protocol's promise of dates pass 2 never evaluated on holds). Found by the test suite.

## Data that leaves the PC
Only text built from public documents: the local model's failed drafts about public filings, results and news, and the
guard's messages about them, gated by `analyst.gate` (kind "trace") and priced against the cap before each call.
