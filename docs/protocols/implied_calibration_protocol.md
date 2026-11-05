# Option-implied fall chances against what happened: pre-registered protocol (S79 item 11)

Registered 2026-11-05, committed before any calibration is read from real data. Descriptive; a feature enters no model unless a later registered comparison passes.

## Question
How far do the NIFTY 50 option-implied (risk-neutral) chances of a fall of 5, 10, 15 and 20% at the nearest expiry (`quant/implied.py`) run from the frequency with which those falls happened (the variance / risk premium)?

## Data and rule (in code: `quant/implied_calibration.py`)
- Each kept session's chance, per level, is stored in `implied_calibration_s79` (market, asof, horizon in sessions on the market's calendar, fall_pct, p_implied) with outcome NULL.
- Resolved when `session_after(asof, horizon)` has passed and the Nifty 50 close is known: outcome = 1 if that close is more than fall_pct below the index level on asof, else 0.
- Point in time: the map at date M uses only outcomes resolved on or before M.
- Map: `p_calibrated = min(1, k * p_implied)`, `k = sum(outcome) / sum(p_implied)`. Under 20 resolved observations: report n and no conclusion (k not used).
- Rows on one expiry share their outcome: the distinct expiries are reported beside n. 2024-2026 is spent: the result is a description, not evidence.
- Counted as one test in the learner's counter when first read at 20 resolved observations (template `implied_calibration:scale_k`).

## Pass rule for use by an agent as a probability
A feature may enter `fall_risk` only if a later registered comparison shows the calibrated chance beats the raw chance (Brier score) on outcomes unseen when k was fitted, over at least 20 distinct expiries.
