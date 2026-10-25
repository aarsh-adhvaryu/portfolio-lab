# Memory retrieval: ours vs local embeddings (S49, PLAN A7): pre-registered protocol

Registered 2026-10-17, before any run. Code: `agents/memory_compare.py`; run: `pflab memory compare`.

## Question
When an agent looks something up (a decision, an analyst note, a filing, an article), does semantic search find the
right item more often than our word matching?

## Corpus and questions
Corpus: every memory row, analyst note, brief and the filings, results and articles in the knowledge graph from the
120 days to the run date. 80 items are drawn (seed 20261018); for each the local model writes one question whose
answer is in that item, without copying its title. The item is the right answer. Questions 1-40 are development,
41-80 test.

## Systems
- **words** (ours): the number of question words (4+ letters, stop words out) found in the item; ties by recency.
- **embed**: cosine similarity of `nomic-embed-text` embeddings (Ollama, local, downloaded once).
- **hybrid**: reciprocal-rank fusion of the two (k = 60).
- **supermemory**: added only once the investor installs its local server (it is not installed; nothing is guessed).

## Measure and rule
Recall@5 (the right item among the top 5) and mean reciprocal rank. embed or hybrid, whichever has the higher
development recall@5, is adopted for agent look-ups if its test recall@5 is at least 0.10 above words. Otherwise words
stays. Test questions are scored once.
