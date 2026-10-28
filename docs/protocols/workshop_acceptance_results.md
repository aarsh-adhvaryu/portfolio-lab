# Workshop acceptance: results

Run 2026-10-22 under `workshop_acceptance_protocol.md` (amendment 1: the first run sent nothing, the egress gate
blocked every question; fixed before any answer was seen). Writer: Opus through the doorbell, the workshop as live.

**PASSES: 10 of 10 correct, none wrong but marked checked, ~Rs 51** (of the month's cap). Nine answers on the first
try; Q9's first try used `pd.to_numeric`, which the static check refused (a pure conversion: now allowed), and the
second try passed. Every answer matched the pandas reference to within float rounding (Q3: 6e-16 relative).

**Decision:** Opus stays the workshop's writer; the local model is only the labelled fallback. Calculations are still
kept "not reviewed" until promoted: ten maths questions on index series do not prove every question. For contrast, the
local qwen3:8b on the Q1-style question (2026-10-22): a one-day rise reported as the drawdown, then no checked answer.
Rows: `PFLAB_DATA_DIR/llm_eval/workshop_acceptance.json`.
