# Claude Sonnet 5.5 vs Claude Opus 5.5 for the system's two paid jobs: pre-registered comparison

Registered 2026-10-23, before any call. CLAUDE.md 11: a change of model is a measured decision. Sonnet 5.5
(`claude-sonnet-5-5`) costs half of Opus 5.5 ($2 / $10 against $4 / $20 a million tokens). Each job is decided on its
own; Opus stays wherever Sonnet is not adopted. Web search (S54b) is not compared and stays on Opus.

## Job 1: research notes (the doorbell analyst)
- **Set:** the 20 questions of the 2026-10-17 comparison (`PFLAB_PM_DIR/analyst_compare/questions.json`, SHA-256
  50300b6b..., company names out of git). Documents: the public filings, results and article text in the local graph
  for the 90 days to the run date, identical for both models; the same prompt, system text, adaptive thinking and
  effort `high`; called live as trials (`analyst.trial_note`: the egress gate and the budget apply; nothing is kept in
  the graph or memory).
- **Scoring:** the rubric of the 2026-10-17 comparison (amendment 2, `analyst_compare.measures` / `judge`), applied by
  code to each model's raw answer (before `only_sourced_numbers`): an answer that does not exist loses; else the higher
  share of its numbers found in its documents wins; within 0.05, the higher share of sentences carrying a citation wins;
  within 0.05 again, a tie. Also measured: the share of each answer's words kept by `only_sourced_numbers`, and cost.
- **Rule:** Sonnet is adopted for research notes if its share of the 20 (a win 1, a tie 0.5) is at least 0.45 AND
  its mean share of words kept is at least Opus's minus 0.05. (At half the price, "not clearly worse" is enough.)

## Job 2: calculations (the workshop's writer)
- **Set:** the 10 questions of the workshop acceptance test (`tools/workshop_acceptance.py`, reference answers computed
  by plain pandas), the same writer prompt, schema and made-up rows, run with `--model claude-sonnet-5-5`.
- **Rule:** Sonnet is adopted for the workshop if it passes the bar Opus passed on 2026-10-22: at least 9 of 10
  correct and none wrong but marked checked.

## Commands and cost (The investor; about 60-90 minutes in all, both within the monthly cap)
- `.venv\Scripts\python tools\model_compare.py research` (40 answers; about Rs 200)
- `.venv\Scripts\python tools\workshop_acceptance.py --model claude-sonnet-5-5` (about Rs 30)
- `.venv\Scripts\python tools\model_compare.py score` (writes the decision)

## Amendment 1 (2026-10-23, before any run of either half)
The workshop's writer prompt gained one instruction the same day (reusable calculations: name changeable values as
parameters). Opus's 10/10 was measured on the earlier prompt, so both models take the acceptance test on the current
prompt: `tools\workshop_acceptance.py --model claude-opus-5-5` as well (about Rs 50). Rule for Sonnet unchanged.
Added check of the change itself: if Opus no longer passes the bar on the current prompt, the parameter instruction is
taken out again and the library reuses calculations only for the same question.

One run each; no re-scoring. If adopted, the job's model is set in `api_budget.toml` (`model_research`,
`model_workshop`), with Opus as the fallback when Sonnet declines (the doorbell's server-side fallback).
