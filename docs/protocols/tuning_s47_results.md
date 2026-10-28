# S47 tuning, pass 1: results and what was wired in (2026-10-18)

Run in the overnight run of 2026-10-17 under `tuning_s47_protocol.md`; scores are shares of the test set.

| task | best on train | its test score | v0 test | threshold | outcome |
|---|---|---|---|---|---|
| materiality | v2 (definitions + 8 examples) | 0.945 | 0.785 | 0.90 | **ADOPTED** |
| routing | v1 (pick every tool) | 0.933 | 0.950 | 0.95 | not adopted; v0 stays |
| writing | v2 (format rules + example) | 0.792 | 0.458 | 0.85 | not adopted; QLoRA candidate |
| research | v1 (plain sentences) | 0.40 | 0.50 | 0.70 | not adopted; QLoRA candidate |

**Materiality v2, wired in** (`llm/tuning.py` `ADOPTED`, `materiality_tagger`): the researcher asks it only about a
filing whose BSE subcategory is in neither registered map (material or routine) and whose headline has 40+
characters, as in its test; a "material" answer is a `material_filing` flag marked "model-tagged". Mapped
subcategories are still decided by the map. Model down: no model flag (the map alone, as before). Note: the test
headlines came from mapped subcategories, so unmapped ones are a shift; the flags say they are model-tagged.

**Routing:** v0 already meets the bar on test (0.95), so it is not a QLoRA candidate. **Writing:** v2 is far above v0
but below the bar; by the rule nothing changes. **Research:** 10 test questions; train and test disagree (v1 0.8 on
train, 0.4 on test), so the gap is real and the sample small. Writing and research go to pass 2 (QLoRA,
`.venv-train`), which needs its own registration before any training run.

The nightly tuning steps are off from 2026-10-18 (their test sets are spent); `-Phases tuning` only under a new
registration.
