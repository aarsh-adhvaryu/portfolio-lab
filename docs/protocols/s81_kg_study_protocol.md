# S81 B7: the graph earns its place (pre-registered 2026-11-09, written before any run; judged later on live data only)

**Claim (rule 10, A52).** The rebuilt knowledge graph (`src/pflab/kg2/`) helps the storyline layer: (1) evidence the storyline reader attaches from graph events
is attached to the right company; (2) storyline predictions hold more often when graph facts and events were attached to the storyline than when none were.
Nothing about the graph's value is assumed: if either part fails at its first judgement the graph's switch (`configs/kg2.toml`) stays OFF and no feature of it is
wired into the agents. This protocol counts as one claim in the learner's counter (the bar for a new claim rises with N).

**What counts as graph evidence.** A row of `storyline_evidence_s80` whose `source_kind` is `kg2_event` and whose `source_ref` is a `kg2_event.event_id`, dated on
or before the day the prediction was made. A storyline is in the GRAPH arm for a prediction if it had at least one such row at that day; otherwise in the
PLAIN arm. (The graph's facts, relations and the position layer reach the storyline reader in the same prompt block; the arm is defined by the events because
they are the only part that can be counted per storyline without judgement.)

**Measure 1: attachment is correct (`kg2/study.py::attachment_check`).** Two independent counts, both by code, never by a model:
(a) the week's hand-check sample (`<data>/kg/audit_sample.csv`, 50 random links with their proof): each link's proof is re-derived from the raw files by a second
implementation (filing: the scrip code in the proof maps to the ISIN on the filing's date in `bse_scrip_isin`; news: the organisation token equals an alias of the
ISIN and the article's text, or its URL, names the company); (b) each evidence row of kind `kg2_event`: the event's ISIN is an ISIN the storyline is exposed to
(`storyline_exposure_s80`). Rule: correct share >= 95% in both (a) and (b), on at least 100 rows pooled over the weeks judged, else FAIL; under 100 rows: the
count and no conclusion.

**Measure 2: predictions hold more often with graph facts (`kg2/study.py::prediction_comparison`).** Over scored rows of `storyline_predictions_s80`
(`outcome` good or bad; `void`/not due excluded): hit rate in the GRAPH arm against the PLAIN arm. Statistic: the two-proportion z with the pooled variance,
stratified check by storyline `kind` (the pooled difference must keep its sign in every stratum with at least 10 scored predictions in each arm).
Rule: at least 30 scored predictions in EACH arm and not before 2027-05-01 (six months of live closes); then PASS if hit_rate(GRAPH) - hit_rate(PLAIN) >= 5
percentage points and z >= 1.96 and the stratified check holds; FAIL if the sample is complete and the rule is not met; before that: the counts, no conclusion.
The learner's bar for the claim (its N-adjusted threshold at the time of judging) applies on top.

**What a pass does.** The switch may stay ON and graph facts stay in the storyline reader's block. **What a fail does.** The switch is set OFF by the coordinator
at the next release; the storyline layer already carries what the graph was meant to (the 5-6 Nov storyline layer); no graph feature is live.

**Not claimed.** That the graph improves returns (that is a policy question for the lab, not this study); that the model reading text is accurate beyond the
closed-list classification (its picks are validated by code and logged; thesis-break kinds feed the exit manager's check, whose sales are scored on their own).

**Data limits stated up front.** News before 2026-11 comes from the GDELT 1.0 GKG daily files (a day, not a time: an article is usable from the next day). Filings
with no dissemination time are left out of everything (his decision 2026-11-09), so the graph's coverage of old filings is lower by design (16% of the 2015-2026 file).
The 2022-2025 period is spent: this study uses live records only.
