# S85 exam (G2): the exam, the shadow, the per-engine calibration

Branch `s85/exam` (from `s85/engines`). 2026-11-13. Paid calls tonight: see "Real path" (none unless listed there).

## What is built
- `llm/exam.py`: `run(con, engine, *, thinking=("medium",), now, fake=None, spend_cap_rupees=60)`, `passed(con, engine)`, `grade(con, engine)`.
  - (a) FORM: a tool loop with the stored toy tool `lookup_close`; twenty short case prompts answered in the S84 structured form (`session.ANSWER_SCHEMA`) and checked by `session.validate_answer`; FAIL when the tool call does not work, any answer writes a number (a forbidden key or a numeric field), breaks a closed list (`think.OPTIONS/CLASSES/WORDS`), or three or more of the twenty are malformed (not JSON, fields missing, error).
  - (b) JUDGMENT: six stored reference cases (the S84 replays in short form with synthetic names: Nvidia held, Nvidia not held, Ather's missed run, India rotation, Indian governance, market fall; reference = the replays' registered class and option) plus up to twenty real cases of the store (reference = the in-use engine's own stored answer class and option, from the case's answer step): "agrees on N of M" needs class AND option equal.
  - (c) READING: ten synthetic documents (synthetic companies), five facts and five numbers each; facts found by key word, and every number the engine gives is checked against the source with `session._numbers` (the `only_sourced_numbers` logic): "misses N facts in 10 documents", "N number(s) not in the source".
  - (d) COST and TIME: cost and seconds per call, price of a desk day = cases per day (`[think] max_cases_per_day`) x 6 calls x cost per call + desk (2 sessions x 4 calls) (the formula is in the stored detail). "x times cheaper than <in-use engine>": measured (the in-use engine's own newest exam, cost per call) else the list-price ratio of the decide models (`input + 3 x output`).
  - One `engine_exam_s85` row per (engine, thinking, run) through `gateway.record_exam` (the table the engines agent made: the brief's name `engine_exams_s85` is that table; the detail is in `detail_json`). `use()` reads the newest row; `passed()` is True when the newest row of any thinking level passed. `--thinking medium,high` grades each setting separately.
  - Consent and cost: runs only with a recorded consent for scope `exam` (`gateway.has_consent`); all calls go through `gateway.call(scope="exam", agent="think")` (egress gate, governor, his cap); stops at `spend_cap_rupees` (the exam then reports `stopped_at_cap` and fails the form part, since fewer than twenty answers were asked). No key is ever printed.
- `think/shadow.py` + the smallest hook in `think/session.py::think_case` (4 lines after `_decide_all`, wrapped in try/except): for each engine in `gateway.shadows(con)` other than the engine in use: one `read` call and one `decide` call through the door (`engine=<shadow>`, `scope="shadow"`, same system text and first message; no tool loop), validated by `validate_answer` (one more ask), run through `odds.option_table` and `rule.decide` under THAT engine's calibration table, stored as option rows `shadow:<engine>` (its choice) and `shadow_rule:<engine>` (what the rule does on its answer) and in `think_shadow_s85`. It never orders, freezes, tells or records a decision. A failure is one `shadow_note` step on the case. Daily cap: `[engines] shadow_daily_rupees` (default 25) over `think_shadow_s85.cost_rupees` of the day.
- `think/score.py`: `score_shadow` (called by `score_due`) scores shadow rows at 5/20/60 under decision_id `1_000_000_000 + shadow_id` with the two tracks per engine (`_score_decision` takes an optional `picks`); `scorecard()` adds `by_engine` (`{engine: {in_use, rule_track, model_track, by_word}}`) so two engines are side by side; `tally_engine` / `calibrate_engines` (called at the end of `calibrate`) keep each shadow engine's own likelihood table.
- `think/cases.py::probabilities(con, engine=None)`: the table is per engine: the default engine `claude` (and every stored S84 row) in `think_calibration_s84`; any other engine in `think_calibration_engine_s85` over the starting `WORD_P` (a new engine starts from the default table). Default `engine` = the shadow context (`cases.ENGINE_CTX`) else the engine in use.
- Migration 300 (`pm/mig_s79/m_exam85.py`): `think_calibration_engine_s85`, `think_shadow_s85`. 301-304 spare.
- `cli.py`: `pflab engine test` prints the report text (and exits 1 when refused for no consent).
- Tests `tests/test_s85_exam.py` (18): good engine passes and gets a grade in words; number written fails; closed list broken fails; 2 malformed of 20 passes, 4 fails; tool call failing fails; two thinking levels graded separately; `use` refused before a pass and after a fail; spend cap; nothing sent without consent (and `scope="exam"` with it); cheaper vs the in-use engine measured; shadow stored and never acting; shadow failure a note; a shadow answer with a number not stored; shadow daily budget; calibration per engine apart; scorecard side by side; shadow scored under its own tracks; tables exist.

## Decisions (2026-11-13)
- The stored replays of the brief need their world data (`D:\s84_scratch\replay`, price bars, a built store): too heavy for the exam, which must run in minutes and for a few rupees. The judgment part uses the six replays in SHORT TEXT form with their registered class and option (written in `exam.REFERENCES`), and says so in the report (`judgment.missing`). The full replays stay the drill's (`tools/replays_s84*.py`).
- Real cases: the reference is the in-use engine's stored class/option; the case's first message is not stored, so the prompt is the case title plus the stored "happened" text (short; cost bounded).
- Agree needs class AND option.
- The form part is strict on numbers and closed lists (one is a fail) and tolerates two malformed answers of twenty (the brief's "malforms 3 of 20" fails).
- Shadow asks `read` and `decide` roles (not the Opus-for-large-exposure choice of the in-use path): the shadow's decide role is the engine's own decide model.
- Shadow steps never carry an `answer` payload (T8's `_answer_of` would read it as the in-use engine's).

## OFF / not done
- Calibration of the engine IN USE when it is not `claude`: `score.calibrate` still tallies all decisions into the claude table; a switched-to engine reads its own table (starting from the default) but is only corrected through shadow rows. A shadow engine IS calibrated (`calibrate_engines`). Not wired: a tally keyed by the engine that made each in-use answer.
- The exam's judgment part does not use the full replays (above) and does not replay India rotation / governance / March 2020 worlds.
- Nothing is on a switch: shadow runs only when `engine_state` lists a shadow engine (default none), the exam only when called.

## Shared files touched
`think/session.py` (4-line hook), `think/score.py`, `think/cases.py` (`probabilities`), `cli.py` (2 lines).

## Exposed for screens
`exam.grade(con, engine)`, `exam.passed(con, engine)`, `gateway.exam_state`, `score.scorecard(con)["by_engine"]`, `score.by_engine(con)`, `shadow.spent_today(con, day)`.

## Lines for BUILT.md / CLAUDE.md (coordinator)
Exam: `llm/exam.py` (form / judgment / reading / cost; `engine_exam_s85`); shadow: `think/shadow.py` (`think_shadow_s85`, tracks `shadow:<e>` and `shadow_rule:<e>`, daily cap `[engines] shadow_daily_rupees` 25); calibration per engine `think_calibration_engine_s85`; migrations 300.
