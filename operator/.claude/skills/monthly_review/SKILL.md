---
name: monthly_review
description: The monthly review: read the scorecard (5/20/60-session scores after tax against the index), the calibration of the likelihood words, what to test next; write the lessons.
---
<!-- pflab-operator s87.2 -->
1. Call `decision_scorecard`, `pick_scorecard` and `scorecard` (decisions and picks, by horizon, after tax, against the index).
2. Call `decision_log` for the month and `usage_so_far`.
3. Write `notes/monthly_<yyyy-mm>.md`: what worked, what did not, calibration, three things to test next (each as a candidate study, never a live change). Thresholds are tuned only after 40 scored decisions or 60 misses.
