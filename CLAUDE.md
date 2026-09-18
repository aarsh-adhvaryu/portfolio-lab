# CLAUDE.md — instructions for Claude Code on this repo

You are working on `portfolio-lab` (package `pflab`): a personal,
tax-aware, monthly-SIP portfolio research harness for NSE equities owned
by Aarsh. Read `docs/principles.md` and `docs/strategies/E1.md` before
touching code. The charter is the spec; the code implements it.

## Non-negotiables

1. **Never change `docs/strategies/E1.md` §2–§13** except by appending
   to §15 with a date and reason, and only when Aarsh asks. If the charter
   and the code disagree, the charter wins; fix the code.
2. **Never load data beyond a period's end.** `pflab.eval.periods.truncate_end`
   is the only path from raw data to the engine. The sealed period requires
   `--unseal "reason"` and is journaled to `research/journal.jsonl`.
   Do not run the sealed period. Do not read `experiments/*/sealed*`.
3. **Never add a parameter, filter or rule that is not in the charter**
   because a backtest looked bad. Write the result up instead.
4. **Point-in-time everywhere.** Any feature at decision date M uses only
   rows dated <= M. Announcements use dissemination timestamp.
5. **Every run writes a manifest** with SHA-256 of config, data snapshot
   and code (`git rev-parse HEAD` + dirty flag). Identical inputs land in
   the same directory and verify instead of overwriting.
6. **Tests for lookahead are mandatory** before Phase 2 is done:
   shifting a future price must not change any decision made before it.
7. **Keep it dependency-light.** pandas, pyarrow, duckdb, numpy, requests,
   python-dateutil, tomli (3.10) / tomllib, pypdf. No backtesting frameworks.
   `pypdf` was added 2026-09-17 for the NSE index constituent-change
   circulars (E1b §3); `pdfplumber` is a named fallback, permitted only for a
   circular whose tables `pypdf` returns garbled, and nothing else.
8. **ISIN is the security key.** Never join on symbol without a date.
9. **Data lives under `PFLAB_DATA_DIR`** (env var, default `./data`).
   It is gitignored. On Aarsh's machine point it at the D: drive.

## State of the repo (2026-09-18 — see `docs/HANDOFF.md` for the full picture)

**Adopted stack: E1 base.** Verdicts so far: **E1 INCONCLUSIVE** (2026-09-17),
**E1b REJECT** (2026-09-18, GATE G1 failed both periods and G2 violated in
validation). `pytest -q`: 362 passed.

Charters: E1 LOCKED 2026-09-17 (§2–§13 untouched since). E1b LOCKED
2026-09-18 (§3–§7 untouched since). E1-P DRAFT, partly built. E1c DRAFT,
not prepped. Order: E1, E1-P, E1b, E2-A, E2-B, E2-C, E2-D, E3, E4, E5.

Implemented, tested and used in real runs:
- `pflab/tax/india_lots.py`, `pflab/execution/costs.py`
- `pflab/eval/` — `periods` (incl. `truncate_end`, `truncate_membership`,
  seal + journal), `metrics`, `artifacts`, `sweep`, `classify` (§13 C1–C5
  and GATE G1–G4)
- `pflab/signals/momentum.py`, `pflab/portfolio/crash_rule.py`,
  `pflab/portfolio/construct.py`
- `pflab/backtest/` — `engine` (full loop, §4/§5/§6, tax settlement, ADV
  skip per §15, delisting/suspension, B1–B4), `hooks`, `runner`
- `pflab/data/` — `bhavcopy`, `panel` (8.03M rows, 4,380 securities,
  2004-01-01..2026-09-16), `universe`, `instruments`, `symbol_isin`,
  `indices`, `calendar`, `corporate_actions`, `nse_corporate_actions`,
  `dividends`, `red_flags`, and the 2026-09-18 membership stack:
  `index_changes`, `index_captures`, `index_membership`, `name_map`
- `tools/` — `backfill_bhavcopy`, `collect_daily`, `red_flag_sample`,
  `build_index_membership`

Stubs raising `NotImplementedError` (both Phase 4, on ADVANCE only, and
nothing has ADVANCED): `pflab/execution/paper.py`, `pflab/execution/kite.py`.

Index membership (E1b §3/§4): built from 1,486 NSE Indices press releases
anchored on 72 Internet Archive captures. Exact-list check passes — Nifty
200 4/4, Nifty 100 21/21, Midcap 100 10/10, Nifty 500 13/14. Re-run with
`python tools/build_index_membership.py --all`.

Not started (Stage 3 was redirected to E1b and never resumed): BSE
announcements backfill to 2010 (only 2026 collected), shareholding,
point-in-time fundamentals, macro, IPO list, ETF dividends. GDELT needs
Aarsh to run `tools/gdelt_bigquery.sql` in BigQuery.

Next four tasks, in order, are in `docs/HANDOFF.md` §9.

## Task order (do them in this order; each is done when its tests pass)

### Phase 1 — Data
**Follow `docs/PHASE1_SPRINT.md`; it is the minimum and it overrides the task list below where they differ.** Tasks 1.5 and 1.6 backfills are deferred until after the first development run; only the daily collector (1.7) is on the critical path.
- 1.1 Run `pflab collect bhavcopy --from 2024-06-20 --to 2024-07-20`.
  It spans the format change. Fix URL patterns, headers, the switch date
  and the normaliser until both formats parse. Then backfill 2005-01-01
  to today. Log holidays and failures to `data/bhavcopy/_log.jsonl`.
- 1.2 Split/bonus factors from bhavcopy `PREVCLOSE` (sprint step 3) in
  `corporate_actions.py`; dividends via yfinance (sprint step 5) in
  `dividends.py`. The NSE corporate-actions scraper is only a fallback.
- 1.3 Write `panel.py`: build `data/panel/prices.parquet` (long format:
  `date, isin, symbol, open, high, low, close, prev_close, volume,
  turnover, adj_factor, adj_close, adj_open, dividend`). Include the
  symbol->ISIN map for pre-2011 rows. Implement the plausibility checks
  from charter §9 as a function returning findings, with halts.
- 1.4 Index series: ingest the four NSE Indices CSVs into
  `data/indices/*.parquet`. Assert the Nifty 50 price series and the
  bhavcopy calendar agree on sessions.
- 1.5 Run `pflab collect bse` for one recent week; fix the endpoint;
  backfill from 2010. Run `red_flags.classify` over the backfill and
  write the 50 most common flagged headlines to `docs/data/red_flag_sample.md`
  for Aarsh to review the keyword rules.
- 1.6 GDELT: write `tools/gdelt_bigquery.sql` for the India backfill
  (Aarsh runs it and drops the CSV in `data/gdelt/backfill/`). Run
  `pflab collect gdelt` for yesterday; fix column positions.
- 1.7 `tools/collect_daily.py` runs all three collectors for the last 3
  days, idempotently. Aarsh schedules it (Windows Task Scheduler).

### Phase 2 — Engine
- 2.1 `engine.py`: daily mark-to-market loop over the truncated panel,
  month-end decision, next-open execution, SIP, liquid sleeve accrual,
  §4/§5/§6 rules, tax settlement on first session of FY, delisting exit,
  ADV guard, trade ledger with reference vs fill price.
- 2.2 Benchmarks B1–B4 through the same engine (index as single security).
- 2.3 `artifacts.py`: content-addressed run dir with manifest, metrics,
  decisions, equity curves (pre-tax, after-tax, liquidation-adjusted),
  trade ledger, provenance line.
- 2.4 Lookahead tests: (a) perturb all prices after date T, assert every
  decision <= T is byte-identical; (b) seal-identity test: appending data
  after a period end does not change the run id.
- 2.5 Synthetic-data negative control: driftless random-walk panel; the
  strategy should earn about the cash rate minus costs.
- 2.6 `sweep.py`: run the base row plus S1–S9 from one config; write
  `summary.md` leading with the base row.
- 2.7 `classify.py`: C1–C5 arithmetic and ADVANCE / REJECT / INCONCLUSIVE.

### Phase 3 — Runs (Aarsh decides, you execute)
- Lock the charter (append to §15). Development sweep. Aarsh writes
  `docs/reviews/E1-development.md`. Validation sweep. Classify.
  **Do not touch the sealed period.**

### Phase 4 — On ADVANCE only
- `execution/kite.py` using Kite Connect Personal: month-end job that
  produces the order list, places after-market orders at next open,
  reconciles fills into the ledger. Paper mode first (log only).

## Conventions
- Dates are `datetime.date`; sessions are integer positions in the
  trading calendar derived from bhavcopy; money is float rupees.
- Long-format parquet, DuckDB for queries, pandas for the engine.
- Tests in `tests/`, run `pytest -q`. Keep them fast (synthetic data).
- When you are unsure whether something is allowed by the charter, stop
  and ask Aarsh. Do not guess in the direction of better results.
