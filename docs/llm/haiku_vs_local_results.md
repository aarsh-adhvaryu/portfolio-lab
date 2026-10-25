# Haiku 5.5 vs the local model: results (2026-10-24; protocol `haiku_vs_local_protocol.md`)

## Tasks 1-4 (eval12, same sets and code; Haiku run 2026-10-24, the local model's recorded scores)

| task | threshold | local qwen3:8b-q8_0 | Haiku 5.5 | rule says |
|---|---|---|---|---|
| routing (60) | >= 95% | 95% | **96.7%** | Haiku takes it |
| guarded answers, final (50) | >= 98% | 100% | **100%** (first draft 94%) | Haiku takes it |
| extraction F1 (100) | >= 0.95 | 1.00 | **1.00** | Haiku takes it |
| materiality (200) | >= 90% | 79% | **86%** | neither passes: undecided, Sonnet in step 3 |
| answers p90 latency | reported | 6.3 s (GPU) | 6.1 s (API) | - |

Haiku's spend for these four tasks was not written to the ledger (the run stopped when the dashboard held it, before
the record step); by token volume it was about Rs 10-20. The run is in `tools/haiku_vs_local.py`.

## Task 5 (live answers on the real ledger; run by the investor 2026-10-24, the dashboard closed)

12 questions, each model's draft through the production guard (up to 3 drafts): **local 8 of 12, Haiku 7 of 12**
(under 20: counts, not rates). Spend Rs 1.23. Both pass: worth in total, idle cash, gold bonds, the holdings list, top
gainer. Local only: buckets' shares, surveillance stage, profit tests. Haiku only: one holding's value, the dip-buy
check. Neither: profit or loss on stocks overall, "is a name safe to add". Local took 5-121 s (median ~17 s), Haiku
3-31 s. Rule: Haiku is not higher, so the local model keeps live answers for now.

## Decision (by the committed rule)

- Routing, guarded answers (eval set), extraction: **Haiku**.
- Materiality: undecided (neither reaches 90%); Sonnet is measured in step 3 (the readers already tag filings with Haiku).
- Live answers: **the local model stays first**. Local first with Haiku when the local draft fails (as the Portfolio
  agent already does since S59) would have answered 10 of 12 here: the slider (step 3) measures that cascade, with
  Sonnet, on a larger live set (20+ questions) before any default changes.
- The local model is not removed now; the investor decides after step 5.

## Reading

On curated sets the two are level. On live questions both fail where the question needs a judgement the facts do not
state ("safe to add", "profit or loss overall"): the facts and the guard, not only the model, limit these. That is
input for step 2 (per-stock tools that state drift, probability and edge as facts).
