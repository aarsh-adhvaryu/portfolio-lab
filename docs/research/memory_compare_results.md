# Memory retrieval (S49): results and what was wired in (2026-10-18)

Run in the overnight run of 2026-10-17 under `memory_compare_protocol.md`: 2,070 items, 80 questions written by the
local model (40 development, 40 test).

| system | dev recall@5 | dev MRR | test recall@5 | test MRR |
|---|---|---|---|---|
| words (ours) | 0.650 | 0.524 | 0.425 | 0.292 |
| embed (nomic-embed-text) | 0.850 | 0.682 | 0.550 | 0.418 |
| hybrid (rank fusion, k 60) | 0.875 | 0.654 | 0.575 | 0.396 |

Chosen on development: hybrid. Test recall@5 0.575 vs words 0.425: +0.15, above the registered +0.10. **ADOPTED.**

**Wired in** (`agents/memory_compare.py` `lookup`): the ask centre's `context` tool adds the five best matches for
the question itself (graph documents, analyst notes, memory rows, briefs of the last 120 days, nothing dated after
the as-of day) as quotable sources. Embeddings are cached in `PFLAB_PM_DIR/index/lookup.npz` (the corpus holds
The investor's memory rows, so the index stays with his data); only new items are embedded (first build 96 s, 2,109 items).
Ollama down: word overlap alone, the registered baseline. `pflab memory find "question"` shows what it returns;
`pflab memory index` (in the overnight run) keeps it current. Supermemory joins the comparison only once its local
server is installed.
