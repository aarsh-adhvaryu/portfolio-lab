# S86b closeout ledger (Saturday 14 Nov 2026): every S86 item, its state at `v2026.11.14.2`, and what closed it

States at `v2026.11.14.2`: **real path** (run against the real thing), **synthetic only** (tests / scripted model / fixtures), **not built**, **not checked**. "Now" is the state when this file was last updated (see the last column). Evidence is a file, a test or a run.

| # | item (source) | at v2026.11.14.2 | now | evidence |
|---|---|---|---|---|
| 1 | A73 lane: RED heard / freeze / case / decision told (PLAN A73) | synthetic only + Nvidia week through the real collector with raw fixtures | + live hour on real sources | `tests/test_s86_alarm.py`; `tools/s86_nvidia_week.py`; `tools/alarm_live_s86.py` |
| 2 | A74 sources: Google News, Yahoo | real path (13 Nov live hour) | real path | live hour logs |
| 3 | A74 GDELT DOC | real path: refused (429) on every request | OFF in config (A81): `[think] alarm_sources` | `docs/s86_alarm_notes.md` section 2; 3 more refusals at 12 s spacing on 14 Nov |
| 4 | A74 `merge_held` into the daily GDELT scope ("not wired in S86") | not wired | wired (`alarm.merge_scope`, hourly-stable signature) | test `test_the_held_names_are_merged_into_the_news_scope_once` |
| 5 | A75 same-day Indian filings (BSE) | synthetic only | synthetic only (the BSE file layout is real; no live Indian filing on a held name occurred) | `test_an_indian_filing_at_1120_is_heard_and_a_case_by_1140` |
| 6 | A76 eyes / blind-spot lines / gap message / latency rows | synthetic only | synthetic only + real eyes rows in the live hour | alarm tests; `pflab alarm status` |
| 7 | H2 the model reads leads the rules cannot place ("not built") | not built | built: local model, only HIGH is RED, cached, commentary markers stay AMBER | C2(a) below; `test_a_lead_the_rules_miss...` |
| 8 | H1 the index funds' ten largest members ("not built") | not built | built: `through_funds` | `test_the_ten_largest_members_of_a_held_fund...` |
| 9 | Latency target 30 min to a decision (unmeasured, stub) | not checked | measured once with the real model: 3.0 min to heard, 3.4 to decision, Rs 3.81 | `tools/alarm_real_think_s86.py` (14 Nov) |
| 10 | A77 US session loop: phases, quote delay, stop and fill at the next quote | synthetic + one real regular-hours run | + C6 real bars replay (below) | `tools/us_session_live_s86.py` |
| 11 | A77 US session loop outside regular hours on real bars | not checked | see C6 | `tools/s86b_us_bars.py` |
| 12 | A78 fast-forward: ghost record, what caused what, message, forward-test column | synthetic only (code decisions) | real gap run (C3.5) | `tools/s86b_real_gap.py` |
| 13 | A78 replayed MODEL look ("not built") | not built | built, capped at 3, cached, point in time | C3.1 tests; real run Rs 1.27 |
| 14 | A78 after-tax ghost scoring ("not built") | not built | built beside the pre-tax column; protocol A4 | `test_a_ghost_sale_is_scored_after_tax...` |
| 15 | A78 minute steps ("not built") | not built | not built (Tier 3): a gap is replayed on closes, the row says so | `ghost_s86.steps` |
| 16 | A78 sector part of the split | not separated | not separated (Tier 3): said in the text | `fastforward.caused_by` |
| 17 | A79 reserve buy vs the fall gauge | synthetic (weights test) + a replay that still sold | extended and rerun, see C3.6 | march2020 replay |
| 18 | A80 workshop cap | cap 150 set by him; per-job limit 60 set on his word | unchanged, reported | `pm/api_budget.toml` |
| 19 | OpenAI exam (real, 14 Nov) | real path: 10 "missed facts" = an exam fault; high-thinking form FAIL, reason not stored | rerun with the fixes (C4) | `docs/s86_test_findings.md` item 11+ |
| 20 | Claude's own exam | never run | estimate only unless it fits the cap rule (C4.3) | below |
| 21 | Quick role: Sonnet in config, Haiku in CLAUDE.md rule 9 | inconsistent documents | documents say what runs; one real Haiku reply Rs 0.0011 | C4.4 |
| 22 | Shadow scoring of OpenAI's decisions | scored by `score.score_shadow` (S85), tested | checked: wired in `score_due`, tested | `tests/test_s85_exam.py` |
| 23 | Real PDF >= 5 pages through the real reader | one-page dummy only | 37-page and 11-page BSE filings (C5.1) | `tools/real_inputs_s86.py` |
| 24 | Link checks, one true and one false claim | n/a verdict only | supported / contradicted, with sources | `tools/real_links_s86.py` |
| 25 | His Telegram inputs: Tijori link, earlier Ather PDFs, four spreadsheets | not diagnosed | diagnosed on the real files; fixed (C5.3) | C5.3 |
| 26 | `test_s67_local` x2 failing only in reversed order | open | root cause found and fixed (C1.2) | conftest fixture; reversed suite |
| 27 | `test_s65_fd` after `test_s79b_verify_book` | fixed in `.1` | still passes | suite |
| 28 | The 2-hour lane beside a lab run | stood in by a short concurrency test | C2(e) | `docs/s86b_progress.md` |
| 29 | CLI broke (`timedelta` shadowed in `cli.main`) | broken on `main` since `.1` (found when the exam would not start) | fixed, test added | `test_the_command_line_parses_and_runs_the_new_commands` |
| 30 | The report line "also sent to Telegram" in PLAN.md | false (the workshop sends nothing) | corrected | PLAN.md |
| 31 | First-week check armed from 16 Nov, criteria 6-14, Problems list | n/a | W1 built and tested | `tests/test_s79_week_check.py`, `tests/test_s86b_problems.py` |

Rows 5, 6 and 11 (live Indian filing on a held name, a real overnight gap with the app really off, a LIVE pre-market and after-hours US check) can only be closed by a real market day: the short list for Monday 16 Nov is in PLAN.md "What remains".
