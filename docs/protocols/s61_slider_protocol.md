# S61 the model slider: pre-registered protocol (2026-10-25, PLAN A19)

Written and committed before any run below. CLAUDE.md 11: a change of model is a measured decision. Each job of the
system gets one model setting (Settings: the slider). Its default is set by the rule below; the investor may move any of them.
The cheaper model wins whenever it is not worse by the job's margin. Prices: Haiku 5.5 $0.10 / $0.50, Sonnet 5.5 $2 /
$10, Opus 5.5 $4 / $20 a million tokens; the local qwen3 8B is free but slow (it holds the GPU).

## Already decided (step 1, `haiku_vs_local_results.md`; wired in S61, no new run)
- **routing** (the ask centre picks its tools): Haiku. **extraction** (figures from documents): Haiku (the readers).
- **wording fallback** (a draft that fails the guard is worded by another model, numbers checked): Haiku.

## Job 1: live answers on his own data
- **Set:** the routing round-2 questions whose labelled tools read only his own data (`networth, fds, guards, plan, risk,
  tax`), numbers 13-50 in the set's order (38 questions; 1-12 were step 1's, so these are unseen). The real ledger, the
  labelled tools, the production guard (`llm.graphs.run`, up to 3 drafts), the same prompt for every model.
- **Arms:** local (qwen3:8b-q8_0), Haiku (effort medium), Sonnet (effort low). The cascade "local, then Haiku" is
  scored from the same runs: a question counts when local checked it or, failing that, Haiku did.
- **Score:** the number of questions with a checked answer (of 38). Latency and cost reported.
- **Rule:** the arm with the most checked answers is the default; an arm within 2 questions of it and cheaper wins
  instead (cheapest first: local, cascade, Haiku, Sonnet). Local and the cascade need Ollama; if it is not running the
  arms without it are compared alone (said in the results).

## Job 2: materiality of a filing (does it matter to an investor holding the stock?)
- **Set:** eval12's round-2 set (200 BSE headlines, gold from BSE's subcategory), the same prompt.
- **Arms:** Haiku effort medium (its low-effort score was 86%), Sonnet effort low.
- **Rule:** the cheapest arm with at least 90% is the default. Sonnet is adopted only if its monthly cost at the live
  volume (documents read in the last 30 days times its cost per item in this run) fits the readers' share of the cap
  (6% of Rs 2,500); else Haiku stays with its score said. If neither reaches 90%, Haiku stays (the gatekeeper and the
  brain judge materiality again downstream).

## Job 3: web search answers
- **Set:** the last 6 distinct questions the investor asked in Web search mode (from `api_calls`, mode `web`; public topics),
  run as trials (nothing kept) by Opus and by Sonnet, the same tool (`web_search_20250305`, at most 5 searches), prompt
  and effort.
- **Score per answer:** passages kept by `analyst.web_cited` (a passage with a number but no cited page is removed),
  distinct cited pages, passages removed, cost.
- **Rule:** Sonnet is the default if, summed over the 6, its kept passages are at least 90% of Opus's and its distinct
  cited pages at least 90% of Opus's; else Opus stays.

**Amendment 1 (2026-10-25, before any registered run; found by the smoke check):** only 2 distinct Web-search questions
exist in `api_calls`. The set is those 2 plus the first 4 questions of the research comparison's set
(`PFLAB_PM_DIR/analyst_compare/questions.json`, public company questions, out of git), 6 in all; the rule is unchanged.

**Amendment 2 (2026-10-25, after the web part stopped twice; Claude Code's fault):** the web part's budget (Rs 300)
was estimated too low (Opus web answers cost Rs 35-50 each with their search results) and the runner kept nothing
until the end, so both attempts stopped before Sonnet finished and nothing was saved: about Rs 600 spent, recorded in
`api_calls` as estimates (the runner had not recorded its own spend; fixed). Not run a third time: only 2 web questions
have ever been asked, so what Sonnet could save is small next to another ~Rs 350. **Web stays on Opus** (the rule's
default when Sonnet is not shown as good). Printed by the stopped attempts, reported and not scored: distinct cited
pages, Opus 65 and 64 on the 6 questions; Sonnet 34 on the first 4 (Opus 38) and 28 on the first 3 (Opus 28).
Also reported for job 1: 9 of its 38 questions never reached Haiku or Sonnet: their facts carry FD numbers, which the
egress list keeps on this PC (correctly); the rule was applied unchanged.

## Jobs 4 and 5: research notes and the workshop's writer
As registered in `docs/llm/sonnet_vs_opus_protocol.md` (with its amendment 1), run unchanged as part of this session.

## Job 6: the brain
Not run here: decided from the live monitoring of protocol amendment 2 (Opus and the Sonnet rival on the same passes,
predictions scored against base rates) once each has 20 scored predictions. Until then Opus.

## Spend and runs
Estimated about Rs 600 in all (live Rs 50, materiality Rs 25, web Rs 220, notes Rs 230, workshop Rs 80), inside the
monthly cap; each part stops at its own budget. One run each, no re-scoring; the results and the defaults set are
written to `docs/llm/s61_slider_results.md` by `tools/s61_slider.py score`. The runs take about 2 hours (The investor's to
start; the dashboard closed, Ollama running for job 1).
