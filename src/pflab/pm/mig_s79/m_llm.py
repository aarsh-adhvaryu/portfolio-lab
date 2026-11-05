"""S79 item 13: the local-model comparisons kept as rows (version 77): one row per (comparison, arm, task, metric)."""

MIGRATIONS = [
    (77, "llm_s79_eval",
     "CREATE TABLE IF NOT EXISTS llm_s79_eval ("
     "market VARCHAR, comparison VARCHAR, arm VARCHAR, model VARCHAR, task VARCHAR, metric VARCHAR, value DOUBLE, n INTEGER, "
     "run_at TIMESTAMP, note VARCHAR);"),
]
