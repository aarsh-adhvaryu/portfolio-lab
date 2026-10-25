# S47 pass 3: harness search: results

Run 2026-10-20 (log `PFLAB_PM_DIR\reports\s47p3_2026-10-20.log`: search 08:52-18:12, with Ollama HTTP 500 stops
between 14:16 and 15:20, resumed from the saved state; evaluation 18:20-22:03; decision 22:03:57, FINISHED). Checked
2026-10-22 against `data/llm_eval/harness/` (writing.json, research.json, eval_*.json), not the notice. The resume
redrew nothing: research.json used 210 training tasks = the first probe (30) + 6 rounds x 30, as registered.
Protocol: `harness_s47_pass3_protocol.md` (amendment 0: 34 evaluation dates). Opus spend ~Rs 42 (writing 9.9,
research 31.7), against the expected Rs 200-250.

## Search (training half)
| task | start probe | rounds (current / general / specific, on 30; kept) | final harness |
|---|---|---|---|
| writing | 23/30 | r1 26/25/23 current; r2 30/30/28 current; r3 no failures left, search ends | pass 1's writing v2, unchanged |
| research | 16/30 | r1 14/18/21 specific; r2 21/6/23 specific; r3 17/8/16 current; r4 18/18/21 specific; r5 27/17/22 current; r6 17/10/6 current | Opus's round-4 specific edit |

The final research harness tells the model how the S21 guard reads a note: a citation tag ends every sentence, no full
stop inside a sentence (honorifics, abbreviations, clock times), no uncited commentary sentences, a cited first
sentence, 5-8 sentences, no numbers written as words. It changes how a note is written, not what the guard accepts.

## Judgement (evaluation half, every second Friday, 34 dates; rule: pass rate >= threshold AND McNemar p < 0.05)
| task | n | live (v0) pass | final pass | first-draft live / final | McNemar (final only / live only) | threshold | decision |
|---|---|---|---|---|---|---|---|
| writing | 204 | 0.358 | 0.765 | 0.309 / 0.706 | 84 / 1, p 2e-24 | 0.85 | **not adopted** (below the threshold) |
| research | 165 | 0.097 | 0.745 | 0.036 / 0.576 | 108 / 1, p 2e-31 | 0.70 | **ADOPTED** |

## Decisions
- **Research: adopted.** The final harness text joins the local research prompt (`analyst_compare.local_prompt`),
  which serves the local model's research answers. Nothing else changes: model, facts, guard and its 3-draft loop.
  **Wired 2026-10-22:** the text lives in `llm/adopted.py` (generated from research.json, hash pinned by a test) and is
  appended exactly as evaluated. Live use: the doorbell's local-first step (`analyst.local_answer`): when `/deep` or
  `pflab analyst ask` does not ring Opus (off, over budget, waiting for the investor's yes, egress-blocked, declined), the
  reason comes with the local model's guarded answer from the same public documents. Studies (`qlora`, `tuning`,
  `analyst_compare.run_local`) keep the prompt they were registered on (`harness=False`).
- **Writing: not adopted.** It beats the live prompt by a wide margin but misses the registered 0.85 bar, so
  `brief.PROMPT` stays as it is. A new attempt needs its own registration.
- What the numbers say: the local model's research notes almost never passed the guard live (1 in 10); with the harness
  3 in 4 do, more than half on the first draft. The gain is in format, the guard is unchanged.
