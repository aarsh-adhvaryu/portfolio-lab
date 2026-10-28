# Workshop acceptance: Opus as the calculation writer (protocol)

Registered 2026-10-22, committed before any call. The investor's decision the same day: the workshop's writer is Opus first
(the local qwen3:8b misread "largest fall from a peak" as a one-day change on every try, 2026-10-22); the local model
only as a fallback, labelled. This is an acceptance test of the tool, not a market claim.

**Questions:** ten, in `tools/workshop_acceptance.py` (QUESTIONS), on public NSE index series only (Nifty 50 price,
Nifty 500 TRI, India VIX; columns date and close): drawdown, one-day fall, volatility, CAGR, counts of down days,
recovery time, moving average, correlation, a mean, a longest run. Each asks for a single result named `answer`.

**References:** computed by plain pandas in the same file (`references()`), printed by `--dry` before the run:
Q1 -0.38440, Q2 -0.12980, Q3 0.13724, Q4 0.08872, Q5 5, Q6 158, Q7 11569.25, Q8 0.98810, Q9 26.746, Q10 8.

**Writer:** the workshop exactly as live (`workshop.solve`, `analyst.write_calculation`, two tries with the failure fed
back, the sandbox and its checks). Opus sees the question, the schema and made-up sample rows, never the real rows.

**Rule:** a question is correct when the run is "checked" and `answer` is within a relative 1e-4 of the reference
(counts: equal). **Pass:** at least 9 of 10 correct AND no answer that is wrong but marked checked. Pass: Opus stays the
workshop's writer; its calculations are still kept as "not reviewed" until promoted. Fail: the workshop is used only
with review of every result, and the failures go into the S56 escalation design.

**Cost:** each call priced before sending (worst case about Rs 29); expected Rs 60-150 in all, within the month's cap.
Results: `PFLAB_DATA_DIR/llm_eval/workshop_acceptance.json`.

## Amendment 1 (2026-10-22, before any answer from Opus was seen)
The first run sent nothing: the egress gate blocked every question (a calendar year sat within 0.5% of small ledger
amounts; the code-made sample rows were gated too). Fixed in the gate, privacy unchanged: years and dates are not
amounts unless written as money, a number before a time unit is a window length, and the workshop gates the question
and any feedback (what can carry the investor's data), not the schema and made-up rows. Questions, references and rule unchanged;
the run is repeated.
