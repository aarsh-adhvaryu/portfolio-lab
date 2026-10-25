# Portfolio Manager (`pflab`)

Personal, tax-aware portfolio bookkeeping for NSE equities owned by the investor:
FIFO tax lots, corporate-action adjustment, BSE results and announcements,
a price and NAV panel, and the loaders that feed them. Built session by
session from `docs/PLAN.md`. Not investment advice.

The earlier research project is kept only on GitHub (`origin/research-archive`,
tag `shelved/2026-10-01`). Files copied out of it are logged in
`docs/MIGRATED.md`.

```
python -m venv .venv && .venv\Scripts\pip install -e ".[dev]"
setx PFLAB_DATA_DIR D:\portfolio_lab\data
.venv\Scripts\python -m pytest -q
```

## Modules (`src/pflab/`)

| area | modules |
|---|---|
| tax / lots | `tax/india_lots` (FIFO lots, STCG/LTCG, FY), `portfolio/selldown` (tax-aware sell order) |
| costs | `execution/costs` (+ stubs `execution/paper`, `execution/kite`) |
| corporate actions | `data/corporate_actions`, `data/nse_corporate_actions`, `data/repairs`, `data/dividends`, `data/etf_events` |
| BSE | `data/bse_announcements`, `bse_scrip_isin`, `bse_shareholding`, `bse_insider`, `red_flags`, `red_flag_events` |
| price / NAV panel | `data/bhavcopy`, `panel`, `calendar`, `indices`, `instruments`, `universe` |
| ISIN / series | `data/symbol_isin`, `name_map`, `sector_map` |
| index membership | `data/index_changes`, `index_captures`, `index_membership` |
| other loaders | `data/nse_insider`, `positioning`, `india_vix`, `macro`, `fpi_flows`, `global_markets`, `gdelt` |
| engine (library) | `backtest/engine`, `hooks`; `eval/periods`, `metrics`, `artifacts`; `portfolio/construct`, `crash_rule`; `signals/momentum`, `vol_scaled`, `regime` |
| migrated in S0 | `risk/shock_betas`, `monitor/` (event reaction, promoter), `fundamentals/valuation`, `ledger/checks` |
| plumbing | `cli` (`pflab collect`), `_toml`, `_lock`, `_store_consts` |

`tools/`: collectors and backfills (`collect_daily`, `backfill_*`, `s48_collect`,
`build_index_membership`, `ingest_gdelt_*` with the `gdelt_*.sql` queries), the
live runners (`build_pm_ledger`, `kite_login`, `tfm_live_forecast`, `ocr.ps1`) and
the install scripts. (S64 rewrites this README as the first-run guide.)
`tests/`: 498 tests; the engine tests (`test_engine_*`, `test_lookahead`,
`test_negative_control`, `test_measurement_fixes`, `test_accounting_audit`)
are unchanged. `data/` is gitignored. Labelled event data and data findings are
in `docs/data/`.
