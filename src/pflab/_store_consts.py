"""Constants the migrated modules took from research-archive
`ranker/features.py` (lines 45-49). Copied as values, not the module."""
from datetime import time

STORE_COLUMNS = ["isin", "month_end", "feature", "value", "available", "source",
                 "source_record_id", "published_at", "usable_from"]
CLOSE_IST = time(15, 30)
TZ = "Asia/Kolkata"
