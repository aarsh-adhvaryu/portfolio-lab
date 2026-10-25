# MIGRATED — files copied out of research-archive (S0, 2026-10-06)

Authority: The investor, 2026-10-06 (CLAUDE.md non-negotiable 1). **File copies only**, via `git show research-archive:<path>`; no merge, cherry-pick or rebase. Blob SHAs are at `03f756e` (first 12 chars). `git log --merges` shows no merge from the archive.

| archive path | blob @03f756e | new path | change |
|---|---|---|---|
| `src/pflab/readers/llm.py` | `9a6a457db799` | `src/pflab/llm/ollama.py` | import of `score` only |
| `src/pflab/readers/score.py` | `74ce48bd1ab6` | `src/pflab/llm/score.py` | none |
| `tests/test_readers.py` | `cfd49202f673` | `tests/test_llm_readers.py` | imports only (docstring still says pflab.readers) |
| `tools/a1_contest.py` | `afd98db0d69f` | `tools/a1_contest.py` | import only |
| `tools/a1_read_events.py` | `387a6b34ddc0` | `tools/a1_read_events.py` | imports only; still needs `pflab.backtest.runner.load_config` and the archive's red-flag assignment — not runnable until S22 |
| `docs/notes/A1-reader-plan.md` | `009db6a06455` | `docs/llm/A1-reader-plan.md` | none |
| `docs/notes/A1-reader-scores.md` | `d20ca24e4b41` | `docs/llm/A1-reader-scores.md` | none |
| `tools/flag_audit_sample.py` | `83db513b0cc8` | `tools/flag_audit_sample.py` | none |
| `src/pflab/signals/shock_betas.py` | `5278fc884dbe` | `src/pflab/risk/shock_betas.py` | none |
| `tests/test_shock_betas.py` | `beda1d3c9cde` | `tests/test_shock_betas.py` | import only (not in the §7 register, but the register says "+ test") |
| `src/pflab/eval/event_study.py` | `898c8c80103d` | `src/pflab/monitor/event_reaction.py` | S20 (2026-10-06): rewritten as descriptive market-model residuals and CARs; the pass/fail study (`run`, `verdict`, period gates, matching) removed; only `newey_west_t` kept; new tests in `tests/test_monitor.py` |
| `src/pflab/ranker/events.py` | `567ba022a05c` | `src/pflab/monitor/issuer_events.py` | constants import only (see `_store_consts.py`) |
| `src/pflab/ranker/valuation.py` | `681c5448f508` | `src/pflab/fundamentals/valuation.py` | constants import only |
| `tests/test_e5a_a5.py` | `b4927f886ff2` | `tests/test_fundamentals_valuation.py` | import only |
| `tools/probe_bse_results.py` | `80b857ff511b` | `tools/probe_bse_results.py` | none; needs archive `ranker.store` (not migrated) for two of its modes |
| `tools/probe_a5_valuation.py` | `dea036b5f0c5` | `tools/probe_a5_valuation.py` | none; needs archive `ranker.store` (not migrated) |
| `src/pflab/ranker/holdings.py` | `5ad33af0bb96` | `src/pflab/monitor/promoter.py` | constants import only |
| `tools/check_lock.py` | `69542ba94531` | `src/pflab/theses/lock.py` | none; its REGISTRY names archive charters, to be rewritten in S25 |
| `tools/scan_etf_events.py` | `439812927284` | `tools/scan_etf_events.py` | none |
| `tools/audit/verify_accounting.py` | `156e5af516dc` | `src/pflab/ledger/checks.py` | none (reads ROOT from argv) |
| `tools/audit/reconcile_events.py` | `ba0a61aeb65a` | `tools/reconcile_events.py` | none; plan says ledger/checks.py, kept as a tool until S7 folds it in |
| `tools/status.ps1` | `41eb79668f82` | `tools/status.ps1` | none; pattern for S9 |
| `tools/overnight_queue.ps1` | `31ef3ec207df` | `tools/overnight_queue.ps1` | none; pattern for S9 |
| `docs/plans/fallback.md` | `cfe6aa4b89ef` | `docs/archive-inputs/fallback.md` | none |

Data findings: excerpts of `docs/notes/E2B-readiness.md` (§1–2), `E2D-readiness.md` (§1), `E3-readiness.md` (§1–2) are in `docs/data/archive_readiness_findings.md` (headings demoted one level, charter-specific sections omitted).

New, not copied: `src/pflab/_store_consts.py` holds the three constants (`STORE_COLUMNS`, `CLOSE_IST`, `TZ`) that migrated modules imported from the archive's `ranker/features.py`. Empty `__init__.py` in each new package (`llm`, `risk`, `monitor`, `fundamentals`, `theses`, `ledger`).

Not migrated: see PLAN §7.
