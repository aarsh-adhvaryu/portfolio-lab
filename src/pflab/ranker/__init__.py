"""E5-A: a learned cross-sectional ranker (docs/strategies/E5-A.md).

  features  §6 feature store; A0's price/volume family (§6a)
  labels    §4 labels with label_start / label_end / observable_at
  model     §5 LightGBM fit, the purged training-set selector, model bytes
  walk      §5/§7 walk-forward refits, the composite score, the fallback
  store     the on-disk feature store under PFLAB_DATA_DIR/e5a/<period>/

Nothing here reads a row dated after the panel it is handed; the panel comes
from `runner.prepare`, i.e. through `periods.truncate_end`.
"""
