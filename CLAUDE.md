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
9. **Data lives under `PFLAB_DATA_DIR`** (env var; the code falls back to
   the relative `./data`, but never rely on that). On Aarsh's machine it is
   set explicitly to `D:\portfolio_lab\data` — see "Repo layout" below.
   It is gitignored.

## Repo layout (flattened 2026-09-19)

The repository root is `D:\portfolio_lab` and it is the only copy of
everything. Documents used to exist twice — once at the top level and once
inside a doubly-nested `portfolio-lab/portfolio-lab/` checkout — which meant
edits could land on the copy that was not law. That is fixed: **there is now
exactly one file per document, and it lives in the repo.** Never create a
second copy of a charter, roadmap or note outside `docs/`.

| what | where |
|---|---|
| charters (E1, E1b, E1c, E1-P, E2…E5) and the gate | `docs/strategies/` incl. `GATE.md` |
| experiment order and reasons | `docs/ROADMAP.md` |
| session handoff (read this first) | `docs/HANDOFF.md` |
| principles, sprint plan | `docs/principles.md`, `docs/PHASE1_SPRINT.md` |
| data findings | `docs/data/`; diagnostics `docs/notes/`; reviews `docs/reviews/` |
| superseded drafts, never law | `docs/archive/` |
| code, tests, tools | `src/pflab/`, `tests/`, `tools/` |
| gitignored outputs | `data/` (1.6 GB), `experiments/`, `.venv/`, `research/journal.jsonl` |

`PFLAB_DATA_DIR` is **set explicitly to `D:\portfolio_lab\data`** and must
stay set; do not rely on the working directory. It is set in two places, both
as of 2026-09-19:

- **Aarsh's shells** — a persistent user-scope Windows environment variable.
  Re-create it with
  `[Environment]::SetEnvironmentVariable('PFLAB_DATA_DIR','D:\portfolio_lab\data','User')`.
  Already-open terminals do not see it; new ones do.
- **Claude Code sessions** — `.claude/settings.json` `env` block, which the
  harness applies to every tool call in this repo. It uses forward slashes
  (`D:/portfolio_lab/data`) because JSON would otherwise need escaped
  backslashes; `pathlib` resolves either form to the same directory.

Why: `pflab.data.data_dir()` falls back to the relative path `data`, so a
command launched from anywhere other than the repo root silently resolved to a
different (usually empty) directory instead of failing. An explicit absolute
path removes that failure mode. Verify with
`python -c "from pflab.data import data_dir; print(data_dir().resolve())"`,
which must print `D:\portfolio_lab\data`.

## State of the repo (2026-09-23 — read `docs/HANDOFF.md` "Start here" first)

**Adopted stack: E1 base**, read from `experiments/E1/regression/` since the
2026-09-21 measurement correction (E1 §15: buys sized net of costs; expense
drag by calendar days). Development 8.97% / 55.40%, validation 27.36% /
39.82%. Verdicts: **E1 INCONCLUSIVE**, **E1b INCONCLUSIVE** (re-run 2026-09-22 under
the correction; was REJECT), **E1-P REJECT**,
**E1c REJECT**. One-page table: `docs/STATE.md`. `pytest -q`: 440 passed.

**`docs/MANDATE.md` is in effect from 2026-09-21**: GATE decides adoption;
MANDATE §3 and §5 decide ADVANCE. B5 (Nifty 500 Momentum 50 TRI) and B3
both carry a 0.30% a year drag. No stack meets the mandate yet.

Charters: E1, E1b, E1-P, E1c LOCKED (spans verified each session; hashes for
E1-P and E1c in their readiness notes). **E1d DRAFT** (next; readiness
`docs/notes/E1d-readiness.md`), E3-R DRAFT.
Forward order: **E1d, E3-R, E2-A (data ready), E2-B, E1-S,
E2-C, E2-D, E2-E, E3, E6-V, E5-A.** E4 and any stop-loss are off the list.
**E1 §13's C2 can no longer be moved by any experiment.**

**BSE announcements backfill is COMPLETE (2026-09-23):** 6,109 of 6,109 days
2010-01-01 → 2026-09-22, every day matched to the API's own ROWCNT
(`tools/backfill_bse.py --check 2010-01-01 2026-09-22`). **E2-A is unblocked.**

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

Added 2026-09-19: `pflab/signals/vol_scaled.py` (E1c §3's score),
`hooks.patience_defer` / `stop_loss` / `profit_take` (E1-P §3/§4),
`construct.score_tilted_weights` / `buy_list_weighted` (E1c §3),
`engine._decide_rebalance` and `_intra_month_exits`,
`classify.classify_e1p`, `sweep.e1p_rows` / `e1c_rows`,
`artifacts.deferred_lot_outcomes` / `control_sell_outcomes` /
`source_fingerprint`, and `configs/e1p.toml` / `configs/e1c.toml`.

**Sweeps are now content-verified.** Each writes a `manifest.json` and
refuses to overwrite a directory whose inputs differ (`SweepConflict`), and
`run_id` includes a source fingerprint when the tree is dirty, so edited code
lands in a new directory rather than on top of the old one (principle 9).
Each sweep also persists per-row `equity.parquet`, `trades.parquet` and
`decisions.json` under `rows/<row>/`, so no later extra needs a re-run.

Stubs raising `NotImplementedError` (both Phase 4, on ADVANCE only, and
nothing has ADVANCED): `pflab/execution/paper.py`, `pflab/execution/kite.py`.

Index membership (E1b §3/§4): built from 1,486 NSE Indices press releases
anchored on 72 Internet Archive captures. Exact-list check passes — Nifty
200 4/4, Nifty 100 21/21, Midcap 100 10/10, Nifty 500 13/14. Re-run with
`python tools/build_index_membership.py --all`.

Data: BSE announcements 2010 → 2026-09-22 COMPLETE and verified (collector
hardened 2026-09-22: a day is kept only if it matches the API's own count;
2026-09-23: dedup key is `(NEWSID, DissemDT)`, since BSE counts a
re-disseminated announcement twice).
Collected by code 2026-09-22/23 (`docs/HANDOFF.md` §5): India VIX
(`india_vix`), FRED Brent/USDINR/US 10y (`macro`), NSDL daily FPI flows
(`fpi_flows`), 23 sector indices price+TRI (`indices.SECTOR_SERIES`).
Not started, each needing a source decision from Aarsh: shareholding,
point-in-time fundamentals, ETF dividends. GDELT India daily aggregate
backfilled 2015-02-18 → 2026-09-21 (BigQuery, 2026-09-22); the live collector
fetches English + translingual feeds to match it. GDELT world by country,
event types (20 CAMEO codes) and bilateral pairs loaded 2026-09-23 into
`data/gdelt/world/`. World markets (`global_markets`,
30 Yahoo series) and 23 FRED series (`macro`; revised ones flagged) collected. B5's history is
in `data/indices/NIFTY500_MOMENTUM50_TRI.parquet`.

Next tasks, in order, are in `docs/HANDOFF.md` §9.

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
