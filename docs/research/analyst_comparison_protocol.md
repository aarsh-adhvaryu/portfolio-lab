# API analyst vs the local model: pre-registered comparison (PLAN A7 research tier)

Registered 2026-10-17, before any API call. Decides whether the doorbell analyst (`agents/analyst.py`, Claude Opus 5.5)
is adopted (`adopted = true` in `PFLAB_PM_DIR/api_budget.toml`). Until then it is off.

## Question
On the same public research questions and the same public documents, does the API analyst give clearly better
answers than the local model (qwen3:8b-q8_0 through the guard)?

## Set
20 questions: 3 fixed templates (results change and reasons; what 90 days of filings and news say; visible risks and
open points) x the companies on the investor's list, 20 drawn with seed 20261017 (`agents/analyst_compare.py`). The file is
written to `PFLAB_PM_DIR/analyst_compare/questions.json` (company names stay out of git); its SHA-256 is recorded
below when `prepare` runs, before `run`. Documents: the public filings, results and article text in the local graph
for the 90 days to the run date, identical for both. API calls go through the egress gate and the budget as trials.

## Rating
The investor rates blind: each pair shown as X and Y in a seeded random order (`sheet.md`; the key is kept apart), and he
writes X, Y or tie per question in `choices.toml`: the more correct and more useful answer for a decision.

## Rule (fixed now)
Adopt if the API answer wins at least 70% of the 20 (a tie counts half) AND the comparison's API cost is at most
Rs 400. Otherwise not adopted; the doorbell stays off and the local model keeps all research. One run; no re-rating.

## Commands (The investor, once an Anthropic API key is in secrets.toml under [anthropic] api_key; a key not scoped to a
workspace also needs `workspace_id`)
`pflab analyst compare prepare`, then `run` (about 20 minutes; up to ~Rs 150), then `sheet`, rate, then `score`.

## Amendment 1 (2026-10-17, after the run, before any rating; Claude, under the investor's standing instruction to fix
technical faults)
The first run's local half was unfair in two ways found on its output: (1) only 6 of 20 local answers passed the
guard, mostly "uncited" sentences: the analyst instructions ask for inference and for what the documents leave open,
but the local prompt gave no way to mark such sentences ([inf], which the guard already exempts); (2) Ollama's
4,096-token default context cut long document sets short (the API calls read up to 23,500 tokens). The local half is
answered again (`compare run-local`) with the [inf] instruction and a context sized to each prompt; the paid API
answers are kept unchanged; the first run's answers stay in `answers_r0.json`. Rule and rating unchanged. Noted, not
fixed here: the guard checks that a number exists in a source, not its unit (a draft wrote "fallen by 23" for 23%).

## Amendment 2 (2026-10-17, before any rating): the rater
The investor handed the rating over ("you write [the choices] and let it run"). Claude does not judge by reading: the API
analyst is a Claude model, and the key is visible. The rating is a rubric applied by code (`analyst_compare.auto_rate`),
fixed here before it runs:
1. an answer that does not exist (no draft passed the guard) loses to one that does;
2. otherwise the answer with the higher share of its numbers found in its documents wins (faithfulness);
3. if those shares are within 0.05, the higher share of sentences carrying a citation ([S#], [D#] or [inf]) wins;
4. if both are within 0.05: tie.
Numbers: digit runs in the answer (citation tags removed), compared without commas against every number in the
question's documents and in the question itself. Sentences: 4 words or more. The 70% rule is unchanged.

## Record
- **Result 2026-10-17: ADOPTED by the rule** (API share 0.70, threshold 0.70; API cost Rs 132, limit Rs 400). Read
  plainly: the API won the 14 questions where no local draft passed the guard; the local answer won all 6 pairs where
  both answered (the rubric measures what the guard enforces). The API answers carried numbers not found in their
  documents (0-40% per answer), so the analyst goes live only behind `only_sourced_numbers`, which removes every
  sentence with a number its documents do not state (on these 20 answers: 91% of the words kept).
- questions.json SHA-256: 50300b6befd3edba8eca953cdfc237c402596ae7f346a907f086070e18bffb1f (prepared 2026-10-17,
  20 questions; written before any API call)
