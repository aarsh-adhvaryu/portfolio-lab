# PLAN — Portfolio Manager (written 2026-10-06)

Build plan for the investor's personal portfolio manager. It collects, reconciles,
calculates, monitors, researches and proposes. **The investor makes every investment
decision; the system never places a trade.** Scope: Indian shares, IPOs, mutual
funds and ETFs, gold (ETF, fund, SGB, physical), bonds (government, corporate,
listed) and debt funds, cash. International is excluded. Everything in scope is
built; there is no MVP. Sessions follow `docs/SESSION_TEMPLATE.md`.

## 0. Decisions taken (The investor, 2026-10-06)

| topic | decision |
|---|---|
| Broker | Zerodha, **Kite Connect paid (₹500/month), live data**; read-only use |
| CAS | **CDSL CAS** (all demats on the PAN, incl. the old dormant one) + **CAMS/KFintech** detailed MF statement |
| Runtime | always-on Windows laptop; **local web dashboard** on 127.0.0.1; **Telegram** |
| LLM | **local only** via Ollama: ~9B on GPU (classification, summaries) + ~27B Q4 with CPU offload (overnight research). RTX 5070 Ti Laptop 12 GB, 31 GB RAM |
| Laya | Convai's 421M ModernBERT decision model (Apache-2.0). Zero-shot it is near random on typed decisions (0.362), so it is **fine-tuned** on our labels, in a separate `.venv-train` |
| Tax regime | not known yet (first active year FY2026-27, no salary) → **compute new and old regime every year, show the cheaper; the investor chooses** |
| Dashboard | **FastAPI** (maintained library, rule 5; decided 2026-10-06, replaces stdlib `http.server`) |
| Scoreboard benchmark | a **Nifty500 Momentum 50 index fund**, real NAV (scheme picked in S29) |
| Bank | **SBI only** (linked to Zerodha). No G-secs, T-bills or bonds today |
| Migration | reuse research-archive code by **file copy only** (S0, `docs/MIGRATED.md`) |
| Knowledge layer | **Open Knowledge Format (OKF) v0.2 + PyYAML** |
| Libraries | **prefer maintained libraries over hand-written code** (LangChain, LangGraph, kiteconnect, casparser, …) |

## 1. Hard rules and how code enforces them

| rule | enforcement |
|---|---|
| Every financial number comes from tested code, never an LLM | LLM output passes a **numeric guard**: every number in generated text must equal (within tolerance) a value in the code-produced facts table handed to it, or sit inside a quoted, cited source span. Otherwise the text is rejected and regenerated or dropped. LLMs have no write path to the ledger. Each number in an OKF note links to an *Attested Computation* (function, params, inputs hash, code commit). |
| Tax rules are dated tables with sources | `configs/tax/*.toml`: rows `{instrument_class, conditions (listed, stt_paid, acquired_from/to), holding_months_lt, stcg_rate, ltcg_rate, exemption, effective_from, effective_to, source_url, source_title, verified_on}`. Lookup **raises** for a date no row covers; a test fails if any row lacks a source or `verified_on`. |
| Forecasts are labelled estimates | one `Estimate` type `{value, method, inputs_hash, horizon, as_of}`; renderers refuse a bare number from an Estimate. `ClassifierScore` is a separate type that cannot be rendered as "probability of profit". GMP rows carry `source, fetched_at, unofficial=True` and print with that label. |
| Rebalancing steers new money first | allocator fills underweights from contributions; a sale is proposed only when a **hard** band is breached and only with a side-by-side tax + cost comparison; a minimum-trade threshold blocks small tidy-up sales. |
| Never places trades | `ingest/kite.py` wraps the official SDK in a read-only class; order/GTT/modify/cancel methods raise; a test enumerates the SDK's mutating methods and asserts each raises. `execution/paper.py` stays a stub. |
| Kept engine modules change only with a justifying test | CLAUDE.md rule 7; engine tests stay byte-unchanged. |

## 2. Architecture and data flow

```
 sources                         raw store (immutable)        normalise          ledger (DuckDB)
 Kite API / Console CSV  ─┐      PFLAB_DATA_DIR/<src>/...     ingest/*  ──────►  PFLAB_PM_DIR/ledger.duckdb
 contract notes (PDF)     │      every file: sha256,          (tests per         instruments, accounts,
 CDSL CAS, CAMS/KFin CAS  ├────► fetched_at, source url  ───► source)    ──────► transactions, lots, cash,
 SBI statement            │                                                      income, fees, ipo, prices
 bhavcopy, AMFI, IBJA,    │                                        │
 RBI SGB, NSE/BSE IPO,    │                                        ▼
 BSE filings, GMP(unoff.) ┘                           reconcile (ledger vs Kite vs CDSL vs CAMS vs bank)
                                                                   │
                       calculators (pure functions, tested): tax · valuation · returns · risk · plans
                                                                   │
              proposals + journal ──► Telegram (evidence + alternatives) · dashboard · monthly note
                                                                   ▲
 LLM layer (beside, never in the number path): Ollama 9B/27B + Laya · LangGraph workflows ·
 reads raw docs + OKF knowledge bundle + facts tables · output → numeric guard → OKF note
```

- **Scheduler**: Windows Task Scheduler triggers `pflab service run <job>`; every job is
  idempotent, records `last_success`, and catches up after sleep or reboot.
- **Secrets**: `%USERPROFILE%\.pflab\secrets.toml` (outside the repo and OneDrive):
  Kite key/secret/access token, Telegram token, CAS passwords.
- **Backups**: nightly copy of `PFLAB_PM_DIR` and `knowledge/` to the investor's backup target;
  a monthly job restores the latest backup into a temp dir and re-runs reconciliation.

## 3. Modules

New subpackages under `src/pflab/`. "Kept" = existing modules reused unchanged.

| module | responsibility | kept modules used |
|---|---|---|
| `pm/store` | DuckDB connection, schema, numbered migrations, backup/restore | `artifacts.file_sha` |
| `pm/instruments` | ISIN master: asset class, tax class, listing, issuer, sector; AMFI scheme master; ISIN successions | `instruments`, `symbol_isin`, `name_map`, `sector_map`, `bse_scrip_isin` |
| `ingest/kite` | read-only Kite client: holdings, positions, trades, funds, quotes, historical; daily login callback | `execution/kite.py` stub replaced |
| `ingest/tradebook`, `ingest/contract_notes` | Console CSV; Zerodha contract-note PDFs (charges are truth) | `execution/costs` |
| `ingest/cas` | CDSL CAS + CAMS/KFin detailed CAS via `casparser` | — |
| `ingest/bank` | SBI statement import; classify credits (dividend, interest, refund, transfer) | — |
| `ingest/amfi`, `ingest/gold`, `ingest/bonds`, `ingest/ipo` | NAVs; IBJA gold; bond master + debt prices; IPO issue data, subscription, anchors, RHP, GMP | `bhavcopy`, `bse_announcements` |
| `ledger/events`, `ledger/lots`, `ledger/cash`, `ledger/reconcile`, `ledger/checks` | event log; fractional multi-asset FIFO lots per account; cash ledger; reconciliation; accounting invariants | `india_lots` (parity test), migrated audit checks |
| `ledger/corporate_actions` | apply split/bonus/rights/merger/demerger/buyback/ISIN change to lots | `nse_corporate_actions`, `dividends`, `etf_events`, `repairs` |
| `tax/rules`, `tax/gains`, `tax/income`, `tax/proposed` | dated rule lookup; realised gains + set-off + carry-forward; slab income, surcharge, cess, regimes; tax of a proposed sale by lot | `india_lots` (`fy_of`, `is_long_term`, set-off order as reference) |
| `calc/valuation`, `calc/returns`, `calc/growth`, `calc/whatif` | holdings/cash/total; realised/unrealised; XIRR, TWR; gains vs income vs contributions; what-if | `metrics.xirr`, `metrics.unitized_nav`, `metrics.cagr` |
| `risk/exposure`, `risk/stats`, `risk/shock_betas`, `risk/targets` | exposures by asset, sector, stock, issuer (with MF look-through); vol, drawdown, beta, correlation, concentration; targets and bands | `indices`, `panel`, `metrics.max_drawdown`, migrated `shock_betas` |
| `plan/rebalance`, `plan/entry` | new-money steering, sale proposals; entry plans | `selldown` (name ordering only), `costs` |
| `monitor/filings`, `monitor/falls`, `monitor/event_reaction`, `monitor/issuer_events`, `monitor/promoter` | filings classification and alerts; market-wide vs company-specific falls; past reactions to similar events | `bse_announcements`, `red_flags`, `red_flag_events`, `bse_shareholding`, `positioning`, migrated modules |
| `theses` | locked dated theses, milestones, kill criteria, quarterly checks | `_lock`, migrated `check_lock` |
| `fundamentals` | point-in-time results and valuation | migrated `valuation`, `probe_bse_results` |
| `llm/ollama`, `llm/score`, `llm/guard`, `llm/registry`, `llm/laya`, `llm/graphs` | local model client; scoring; numeric + citation guard; model digest and prompt SHA registry; Laya inference; LangGraph workflows | migrated `readers/*` |
| `knowledge` | OKF bundle read/write/validate | — |
| `research/company`, `research/ipo` | sourced reports | everything above |
| `journal/proposals`, `journal/scoreboard` | proposal log with the investor's choice; picks vs Momentum 50 fund | `metrics.xirr` |
| `service/scheduler`, `service/telegram`, `service/web`, `service/monthly_note` | jobs, notifications, dashboard, monthly note | `tools/collect_daily` |

## 4. Storage and schemas

Ledger: `PFLAB_PM_DIR\ledger.duckdb` (default `D:\portfolio_lab\pm`, gitignored).
Every row carries `source_doc_sha` (sha256 of the file or API payload it came from) and
`ingested_at`. Money is float rupees, dates are `datetime.date`, quantities are float
units (fractional for MFs).

| table | key columns |
|---|---|
| `instruments` | isin, asset_class, tax_class, listed, issuer, sector, name, valid_from, valid_to, successor_isin |
| `accounts` | account_id, kind (demat/folio/bank/physical), provider, dp_id/folio, opened, closed |
| `transactions` | txn_id, account_id, isin, trade_date, settle_date, side, qty, price, gross, kind (buy/sell/sip/switch/allot/redeem/transfer) |
| `lots`, `lot_events` | lot_id, account_id, isin, acq_date, qty, cost, tax_class; events: consume/split/bonus/merge/demerge/rekey |
| `cash_ledger` | account_id, date, amount, kind, ref |
| `income` | isin, account_id, kind (dividend/interest/coupon), ex/record/pay date, gross, tds, net |
| `fees` | txn_id/ref, kind (brokerage, STT, exchange, SEBI, stamp, GST, DP, AMC), amount |
| `ipo_applications` | ipo_id, category, bid, amount_blocked, blocked_on, mandate_ref, allotted_qty, refund_on, listed_on |
| `prices`, `navs` | isin, date, close (or nav), source, fetched_at, stale_flag |
| `corporate_actions_applied` | isin, ex_date, kind, ratio, applied_at, source_doc_sha |
| `recon_breaks` | run_id, source_a, source_b, isin/account, field, a_value, b_value, status, note |
| `tax_years`, `carry_forward` | fy, regime, components, computed_at, rule_rows_used; origin_fy, character, amount, expires_fy |
| `targets` | bucket, target_weight, soft_band, hard_band, effective_from |
| `theses`, `thesis_checks` | thesis_id, isin, locked_at, sha, milestones, kill_criteria, review_by; check rows |
| `proposals`, `decisions` | proposal_id, kind, evidence_sha, alternatives, created_at; the investor's choice, reason, decided_at |
| `estimates` | estimate_id, value, method, inputs_hash, horizon, as_of |
| `llm_runs` | run_id, model, model_digest, prompt_sha, sources, guard_result, tokens, seconds |

Knowledge: `knowledge/` OKF bundle (theses, research notes, source cards, tax-rule source
notes, attested computations); personal parts gitignored.

## 5. External data sources

| source | what | cost | limits | failure handling |
|---|---|---|---|---|
| Kite Connect | holdings, positions, trades, funds, live quotes, historical candles | ₹500/month | quotes 1 req/s, historical 3 req/s; access token expires ~06:00, **manual login daily** via dashboard callback | no token → EOD only, flagged; retries with backoff |
| Zerodha Console | tradebook CSV, tax P&L, ledger | free | manual export | missing period → recon break |
| Contract notes | charges per trade (truth for fees) | free | emailed PDF, PAN-password | parse failure → quarantine + alert |
| CDSL CAS | all demat holdings monthly | free | emailed PDF | manual drop folder |
| CAMS/KFintech | MF transactions since inception | free | mailback PDF | manual drop folder |
| SBI | bank statement | free | manual export | manual drop folder |
| NSE bhavcopy | EOD equity/ETF/SGB prices | free | existing collector | holiday log; stale flag after 1 session |
| AMFI | daily NAV (`NAVAll.txt`) + NAV history | free | polite | stale flag after 1 business day |
| IBJA | gold rates (physical gold mark) | free | daily | fallback: last value, flagged |
| RBI | SGB issue/redemption prices, interest dates | free | press releases | manual table, sourced |
| NSE/BSE debt segment | listed bond prices | free | sparse trades | model price as labelled Estimate |
| NSE/BSE IPO pages | issue details, category subscription | free | cookies, rate limit | retry; last snapshot kept with time |
| BSE announcements | filings, anchors, results | free | existing collector (count-verified) | as today |
| SEBI | RHP/DRHP PDFs | free | — | — |
| GMP site (TBD, §9) | grey market premium | free | scrape politely, respect ToS | **unofficial**, timestamped, never in a number path |
| Telegram Bot API | notifications | free | 30 msg/s | queue + retry; dashboard shows undelivered |
| Ollama / Hugging Face | local models, Laya weights | free | GPU time | job budget per night |

## 6. Tax rule tables (verified 2026-10-06)

Rates still come from the Finance Acts; the Income-tax Act 2025 replaced the 1961 Act from
1-Apr-2026 and renumbered sections. Everything below goes into `configs/tax/` in S2 with
its source; the S2 session re-verifies each row against incometaxindia.gov.in and the
Finance Act texts and records `verified_on`.

| instrument | short-term | long-term | LT if held | notes |
|---|---|---|---|---|
| Listed equity, equity MF, equity ETF (STT paid) | 20% | 12.5% over ₹1,25,000/yr | > 12 m | from 23-Jul-2024; grandfathered cost = higher of cost and 31-Jan-2018 FMV for pre-1-Feb-2018 buys |
| Listed bonds/debentures, gold ETF, commodity ETF, foreign-equity ETF | slab | 12.5%, no indexation | > 12 m | |
| Specified MF (>65% debt; definition from 1-Apr-2025) bought on/after 1-Apr-2023 | slab | — (always ST) | — | s50AA |
| Debt MF bought before 1-Apr-2023 | slab | 12.5% | > 24 m | |
| Gold FoF, commodity FoF, other non-equity non-specified funds | slab | 12.5% | > 24 m | |
| Unlisted bonds/debentures, MLDs | slab | — (always ST) | — | from 23-Jul-2024 |
| Physical gold | slab | 12.5% | > 24 m | |
| SGB | slab | 12.5% | > 12 m (listed) | maturity redemption exempt **only for original subscribers holding to maturity** (Finance Act 2026, from 1-Apr-2026); interest 2.5% at slab |
| Buyback (from 1-Apr-2026) | 20% | 12.5% (non-promoter) | > 12 m | taxed as capital gains in the holder's hands; promoter rates differ |

Other rows: loss set-off (STCL vs STCG and LTCG; LTCL vs LTCG only; carry forward 8
years if the return is filed on time); new-regime slabs FY2026-27 (0–4L nil, then 5, 10,
15, 20, 25, 30% in ₹4L steps; 87A rebate up to ₹12L income, **not** against special-rate
gains); surcharge on 111A/112A gains and dividends capped at 15%; cess 4%; dividend TDS
threshold ₹10,000 per payer per year.

**S2 resolution (2026-10-06).** Tables are in `configs/tax/` (`capital_gains.toml`,
`special_events.toml`, `general.toml`); lookup in `pflab.tax.rules`. Each row carries
`verification` = primary (document read), secondary (search result only) or unverified.
- **SGB conflict resolved against the primary text.** Finance Act 2026 (No. 4 of 2026,
  assent 30-Mar-2026, e-Gazette CG-DL-E-31032026-271439), **s.43**, substitutes clause (x) of
  s.70(1) of the Income-tax Act 2025: exempt "by way of redemption, of Sovereign Gold Bond
  issued by the Reserve Bank of India under the Sovereign Gold Bond Scheme, 2015 or any
  subsequent Sovereign Gold Bond Scheme, if held by an individual from the date of original
  issue till maturity". In force 1-Apr-2026 (s.1(2)(a)). Mirae's reckoner is wrong on this;
  the Act wins. Secondary buyers are taxed on redemption as an ordinary listed sale (12 m,
  12.5%). Redemptions before 1-Apr-2026 stay exempt for any holder (secondary source).
- **New-Act section numbers confirmed** by the Finance Act 2026 text: 111A→196, 112→197,
  112A→198 (First Schedule Part I-B and the s.42 buyback table). Promoter buyback extra tax
  (s.69(2)): 2%/10% short-term, 9.5%/17.5% long-term. Surcharge cap 15% on dividend and
  s.210 capital gains, cess 4%, new-regime basic exemption Rs 4,00,000: all read from the Act.
- **Rates/holding periods** (20/12.5%, 12 and 24 months, Rs 1,25,000 from FY2024-25, 12.5%
  without indexation): read from the CBDT FAQ (PIB 2036604). The FAQ has no numeric worked
  cases, so tests pin its stated rules and boundaries instead.
- **Resolved in S13 (2026-10-06) against the Income-tax Act, 2025 gazette text** (e-Gazette 265620; the Act's section
  numbers, not the 1961 ones): s.76 is the old 50AA (specified MF acquired on/after 1-Apr-2023, unlisted bonds from
  23-Jul-2024: short-term, slab); s.90(7)-(8) grandfathering (higher of cost and the lower of 31-Jan-2018 FMV and sale
  value; FMV = highest price that day); ss.108(2), 109(2), 111 loss set-off and 8-year carry-forward; ss.196(2), 197(2),
  198(3): a resident individual's unused basic exemption reduces special-rate gains; s.202(1) new-regime slabs
  (0-4L nil, then 5/10/15/20/25% in 4L steps, 30% above 24L); s.156 rebate (new: min(100% of tax, Rs 60,000) up to Rs
  12L, marginal relief above, capped at the slab-rate tax so it never offsets capital-gains tax; old: Rs 12,500 up to
  5L); old-regime slabs from Finance Act 2026 First Schedule; ss.403(3), 404, 408 advance tax; s.393 dividend TDS 10%,
  no deduction for an individual's non-cash dividends up to Rs 10,000 a year.
- **Still open:** (1) the timely-return condition for carrying losses forward (flag kept, unverified); (2) the order in
  which unused basic exemption is spread over 196/197/198 gains (the Act fixes none; tax-minimising order used and
  reported); (3) surcharge marginal relief above Rs 50,00,000 (not implemented: the calculator refuses); (4) new-regime
  slabs for tax year 2025-26 (Finance Act 2025 not read: rule lookup raises); (5) old-regime rebate s.156(1) applied
  to the whole tax (wording has no slab-only cap); (6) IPO allotments and other acquisitions without STT: s.198(1)(c)(i)
  needs STT on acquisition unless notified (s.198(5)); the notification list is not loaded (S19); (7) SGB premature
  redemption stays taxable (The investor, 2026-10-06); (8) buy-back non-promoter treatment (s.69(1) not opened).

Sources: CBDT FAQs on the 2024 capital-gains regime (PIB PRID 2036604); Finance (No. 2) Act
2024; Finance Act 2026 (SGB, buyback); Mirae Asset Tax Reckoner FY2026-27; taxguru, "Capital
Gains under New Income tax Act, 2025"; incometaxindia.gov.in (primary, S2).

## 7. Migration from research-archive

The investor, 2026-10-06: "migrate things from the old repo, as much of that can be used here
instead of just redoing". **File copy only** (`git show research-archive:<path>`), never a
merge, cherry-pick or rebase. Each copied file is logged in `docs/MIGRATED.md` with its
archive path, blob SHA at `03f756e`, new path and what was trimmed; its archive test comes
with it, changed only for imports. Done in S0.

| archive path | new home | used by |
|---|---|---|
| `src/pflab/readers/llm.py`, `score.py`, `tests/test_readers.py` | `llm/ollama.py`, `llm/score.py` | S21, S22 |
| `tools/a1_contest.py`, `tools/a1_read_events.py`, `docs/notes/A1-reader-plan.md`, `A1-reader-scores.md` | `tools/`, `docs/llm/` | S22 — the Qwen 9B baseline is already scored |
| `tools/flag_audit_sample.py` | `tools/` | S22 — draw more blind labels for Laya |
| `src/pflab/signals/shock_betas.py` + test | `risk/shock_betas.py` | S15, S20 |
| `src/pflab/eval/event_study.py` (verdict code removed) | `monitor/event_reaction.py` | S20 |
| `src/pflab/ranker/events.py` | `monitor/issuer_events.py` | S20, S23 |
| `src/pflab/ranker/valuation.py`, `tests/test_e5a_a5.py`, `tools/probe_bse_results.py`, `tools/probe_a5_valuation.py` | `fundamentals/`, `tools/` | S24 |
| `src/pflab/ranker/holdings.py` | `monitor/promoter.py` | S25 |
| `tools/check_lock.py` | `theses/lock.py` | S25 |
| `tools/scan_etf_events.py` | `tools/` | S11 |
| `tools/audit/verify_accounting.py`, `reconcile_events.py` | `ledger/checks.py` | S7 |
| `tools/status.ps1`, `tools/overnight_queue.ps1` (pattern) | `tools/status.ps1` | S9 |
| `docs/plans/fallback.md` | `docs/archive-inputs/fallback.md` | S17, S29, S31 (fund SIP, check-up, monthly note) |
| data findings in `docs/notes/E2B-`, `E2D-`, `E3-readiness.md` | excerpts into `docs/data/` | S8, S11, S15 |

Not migrated: `eval/sweep`, `eval/classify`, ranker `model/walk/labels/features/store/
family/combined/exposure` (LightGBM), run/lock/gap/E5-A/identity tools, charters, reviews,
verdict notes.

## 8. Libraries, LLM stack and knowledge layer

- **Policy:** prefer maintained libraries over hand-written code. Each new dependency is
  pinned and listed in CLAUDE.md with date and reason. Numbers a library produces are still
  covered by our tests.
- **Adopted:**
  - `kiteconnect`, behind the read-only wrapper.
  - `casparser`, checked against statement totals.
  - `PyYAML`, for OKF.
  - `langchain-ollama` and `langgraph`, for the research, IPO and filing workflows; LangChain PDF loaders for filings and RHPs.
  - `python-telegram-bot`.
  - `graphify` (S21, gated: it must work with the local models, else dev use only).
- **Laya fine-tuning:** `transformers`, `peft` and `torch` in `.venv-train` only. The main
  package calls models over HTTP.
- **Models:** a 9B model (the archive's `qwen3.5-9b-16k`, already scored on A1) for
  classification and summaries. A 27–32B Q4 model for research, picked in S21 by a small
  evaluation registered before it is run. Model digests and prompt SHAs go in `llm_runs`.
- **Budget:** GPU time instead of money. Research reports are queued overnight with a
  per-night cap, and the 9B model runs on demand.
- **OKF bundle** (`knowledge/`) holds theses, company and IPO notes, source cards, tax
  source notes and attested computations:
  - `stale_after` is the review deadline.
  - `sources` carries the citations.
  - The in-house validator checks frontmatter, `type`, links and staleness.
- **Graphify** has two uses: (a) a graph of `src/`, `docs/` and `knowledge/` so Claude Code
  sessions load less context; (b) a research graph over filings and the OKF bundle for the
  local LLM.

## 9. Build order — 33 sessions (each 2–4 h)

Format: **Goal** · Files · Tests · Accept · the investor provides · Stop.

**Status board** (updated by `tools/status_board.py`; DONE only when every Accept line is met on
real data; PENDING = built and tested on synthetic fixtures, acceptance waits on the investor).
<!-- status-board -->
| session | status | pending / note |
|---|---|---|
| S0 | DONE | |
| S1 | DONE | |
| S2 | DONE | amendment A1; open items in §6 |
| S3 | DONE | synthetic year round-trips; parity with india_lots on 40 random histories |
| S4 | DONE | Kite Connect key works (login via tools/kite_login.py on the registered redirect); read-only holdings = ledger Zerodha holdings, 7 ISINs, 2026-10-15; tradebooks, contract notes, Console funds ledger all reconcile. Open: margins() reported available cash 0.00 vs Console ledger balance: to check |
| S5 | DONE | real NSDL CAS May/Jun/Aug 2026: both demats imported, HDFC demat dormant+read-only, holdings = ledger at each period end; casparser column shift on older NSDL bond rows recovered only when qty x price = value; no mutual funds held (The investor), so no CAMS statement |
| S6 | DONE | real SBI (encrypted .xlsx) and HDFC (.xls) Apr-Oct 2026: every credit classified or listed (2 SBI lines listed); own transfers paired across statements; each bank's ledger cash = statement closing balance |
| S8 | DONE | every held ISIN priced within 1 session on real data (2026-10-15): NSE closes, BSE closes for BSE-only listings (new source, kept apart from the NSE panel), SGBs at their NSE GB-series close |
| S9 | BUILT, ACCEPTANCE PENDING | built+tested (mocked Telegram, synthetic jobs/catch-up/backup/health); NO Task Scheduler entry registered; backup job disabled until a target is set; acceptance needs Telegram token+chat id, registered task, backup target |
| S10 | DONE | acceptance (synthetic portfolio values correctly) met; schedules tested on textbook cases, no real bond terms asserted; real SGB/bond master rows await holdings |
| S11 | BUILT, ACCEPTANCE PENDING | built+tested: split/bonus/rights/merger/demerger/buyback(2026)/isin_change/cash credit, NSE-feed builder; acceptance needs Kite holdings (S4) |
| S12 | DONE | FY2026-27 realised gains = Console tax P&L per ISIN (qty, buy, sell); differences = Console's own non-STT charge columns to 3 paise; no MFs so no CAMS statement |
| S13 | DONE | slabs/rebate verified in Income-tax Act 2025 text (PLAN §6); pflab pm tax --fy prints both regimes; open items listed in §6 |
| S14 | DONE | The investor keeps no spreadsheet (2026-10-15): accepted on the ledger's statement cross-checks instead (Zerodha/bank cash, holdings vs CAS, gains vs Console tax P&L); pflab pm networth on real data |
| S15 | BUILT, ACCEPTANCE PENDING | built+tested: exposures (bucket/sector/stock/issuer, look-through hook), vol/drawdown/beta/correlation/HHI, `pflab pm risk`; acceptance (risk page = CLI) needs the S31 page; real-data run needs ledger |
| S16 | BUILT, ACCEPTANCE PENDING | built+tested on synthetic workbooks (two layouts): parser, weight-sum check, stale flag, category-only reason, feeds risk exposures; openpyxl 3.1.5 pinned; acceptance needs real AMC files for held funds |
| S17 | BUILT, ACCEPTANCE PENDING | real targets set by the investor 2026-10-15 (PFLAB_PM_DIR/targets.toml, out of git; cash floor; FDs as locked debt, reserve FDs outside); pflab pm propose runs on real data; pflab pm deploy spreads FD maturities over monthly tranches. Open: fund picks, his direct-stock list, dip-buy rule numbers |
| S19 | DONE | a real IPO application replays: bid and block from the broker's email, allotment and payment from the tradebook and bank statement, unallotted part released; ledger checks all pass |
| S20 | DONE | acceptance met on real history (Gadget Co/HDFC Bank 2020-03-23 market-wide; Adani Ent 2023-01-27 and 2023-02-01 company-specific; thresholds fixed beforehand); live alerts stay OFF until the investor gives a watchlist; event_reaction verdict code removed |
| S21 | BUILT, ACCEPTANCE PENDING | built+tested: Ollama client, numeric guard + citation checker (rejects invented numbers; 39 tests), model/prompt registry + llm_runs, night budget, LangGraph draft-check-revise loop, OKF v0.2 validator + attestation, pre-registered 40-task evalset and protocol; 9B smoke PASSED on real Ollama (35.6 s, guard clean first try); 27B pick REGISTERED 2026-10-06T17:18:20 before any evaluation but the model is not pulled so its smoke is pending; Graphify trial deferred |
| S24 | BUILT, ACCEPTANCE PENDING | built+tested: BSE quarterly lines, PIT dating (announcement / unmatched_90 / first_seen), ratios (gaps stay None), reverse DCF as Estimate, store, `pflab pm results`; real 8-quarter excerpt fixture; acceptance needs a held company |
| S33 | DONE | fixed deposits (amendment A3): SBI convention reproduces the bank's maturity amount to Rs 2 on all 14 real deposits and current values to the paisa where no TDS was taken; FY interest from certificates (facts) or labelled estimates; ladder, payout net of TDS, renewal warnings; FD interest and TDS in `pflab pm tax`; `pflab pm fd load|cert|show` |
| S34 | DONE | dip-rule study pre-registered and run (docs/research/dip_rule_*.md); chosen: market-wide 10% dip + Fsafe; live safety checks (plan.safety) |
| S35 | BUILT, ACCEPTANCE PENDING | guards built and run on the real list (13 names: 6 ok, 4 fail, 3 data gaps); NSE surveillance + index updates in collect_daily; guards job in the service; alerts queue in the outbox; open: Telegram (pending by the investor), task registration, lender/new-listing results source |
| S36 | DONE | pflab pm simulate: block bootstrap (main) + correlated GBM (reference), 10,000 paths each, target vs current mix, 10-month vs lump sum; efficient frontier page (5,000 mixes, worst-fall colour) in PFLAB_PM_DIR/reports; Gold BeES split break handled |
| S37 | DONE | pflab ask: the centre routes a question to read-only agent tools (networth, guards, fds, plan, risk, tax) via a bounded model choice (keyword fallback), answers only from their facts through the S21 guard; no checked draft -> facts only; tested on the real store |
| S38 | DONE | time-aware knowledge graph in the PM store (migration 16): ownership periods from the ledger, list, sectors, 3,247 BSE filings (2025-26), filed results, guard verdicts, GDELT GKG articles (company-filtered), robots-respecting article text (trafilatura 2.0.0 pinned); pflab kg build|show|text; context agent for pflab ask with source-cited answers; nightly kg job; GKG in collect_daily |
| S39 | DONE | pre-registered pairs study run 2026-10-16: FAILS (dev t 1.82, val t 0.71; 9% of pairs stay cointegrated; edge gone after 2015); not used (pair command removed); dip-rule amendment 1 re-run keeps market-dip+Fsafe |
| S40 | DONE | pre-registered Hawkes study 2026-10-16: market -2% days cluster (passes); amendment 1 (The investor): market state calm/elevated/high (T1 40% by 90% recall, T2 80%), one message per change, in guards/propose/ask; dip-wait test failed so dip rule unchanged |
| S41 | BUILT, ACCEPTANCE PENDING | built 2026-10-16: matching engine (price-time), Hawkes-driven flow, probes; Kite quote() depth recorder + pflab pm impact (measured) + calibrate; synthetic shapes in docs/research/lob_simulator.md; acceptance needs the investor's depth recordings |
| S42 | BUILT, ACCEPTANCE PENDING | round 2 run 2026-10-17: no model passed (q8 routing 95 passes; answers 90-92, materiality 79 fail); recorded not chosen; ask stays facts-only; gap to S47 (save drafts, materiality tuning, two-part routing) |
| S43 | BUILT, ACCEPTANCE PENDING | built 2026-10-17: maths audit (5 fixes, docs/research/maths_audit_s43.md); trade-check agent, memory, questions, two-way bot (synthetic tests); model q8 adopted (amendment), guard bug fixed; acceptance needs a Kite trade check and a bot round trip on real data |
| S44 | BUILT, ACCEPTANCE PENDING | built 2026-10-17: researcher (flags in code, briefs, digest, job) run on real data; API analyst behind the doorbell built OFF (egress gate, budget, batch, notes); acceptance: the blind comparison (needs a key) and a week of nightly digests |
| S45 | BUILT, ACCEPTANCE PENDING | built 2026-10-17: advisor (per-stock quantities, guard-OK names, cap), trader planner (tickets, no order path), split/limit study registered (runs overnight) |
| S46 | BUILT, ACCEPTANCE PENDING | built 2026-10-17: drift checks (market state DRIFT: recall 75% since 2020), event-study template, quant researcher, event research, thesis tracker |
| S47 | todo | pass 1 (prompt tuning by measurement) registered 2026-10-17 (docs/llm/tuning_s47_protocol.md); runs in the overnight script; QLoRA only for a task whose best prompt fails |
| S49 | BUILT, ACCEPTANCE PENDING | built 2026-10-17: words vs local embeddings vs hybrid, registered; runs overnight; supermemory needs the investor's install |
<!-- /status-board -->

### Foundation
**S0 Migration.** Copy §7's register.
- Files: as listed, plus `docs/MIGRATED.md`.
- Tests: migrated tests green; engine tests unchanged.
- Accept: every register row logged with its blob SHA; no merge commit; `git log --merges` is empty for the archive.
- The investor provides: nothing.
- Stop: pushed.

**S1 Store and instruments — DONE 2026-10-06.** DuckDB schema and migrations, `PFLAB_PM_DIR`, the secrets loader, the instrument master (panel ISINs plus AMFI scheme master), and the CLI `pflab pm …`.
- Files: `pm/store.py`, `pm/instruments.py`, `pm/secrets.py`, `cli.py`.
- Tests: migrations are idempotent; secrets never logged; tax class assigned to every ISIN type (STK, ETF, REIT, INVIT, MF, SGB, bond).
- Accept: `pflab pm init` creates the db; `pflab pm instruments` lists ≥ 4,380 equities and all AMFI schemes.
- The investor provides: confirm `PFLAB_PM_DIR` and the backup target; run `python tools/collect_daily.py --days 25` (prices stale since 2026-09-16).
- Stop: pushed.

**S2 Tax rule tables — DONE 2026-10-06 (see A1).** Build `configs/tax/*.toml` from §6, re-verified against primary sources, plus `tax/rules.py` lookup.
- Tests: every row has a source and `verified_on`; a date gap raises; known examples (CBDT FAQ worked cases) reproduce.
- Accept: lookup covers 23-Jul-2024 → today for every tax class (amended by A1; was 1-Apr-2018); the flagged items are resolved or listed as open (§6).
- The investor provides: nothing.
- Stop: pushed.

**S3 Ledger core.** Event log, fractional multi-asset FIFO lots per account, cash ledger, fees.
- Files: `ledger/events.py`, `ledger/lots.py`, `ledger/cash.py`.
- Tests: FIFO per account; fractional units; oversell raises; **parity with `india_lots`** on equity-only random histories; cash never negative without a recorded overdraft.
- Accept: synthetic year round-trips.
- The investor provides: nothing.
- Stop: pushed.

### Imports and reconciliation
**S4 Zerodha.** Read-only Kite client (`kiteconnect`), the daily login callback, Console tradebook CSV, contract-note PDFs, and `costs_zerodha.toml` extended for ETF/MF/SGB.
- Tests: mutating SDK methods raise; contract-note charges match a hand-checked note; tradebook replay builds lots.
- Accept: holdings from Kite equal ledger holdings for the investor's account.
- The investor provides: Kite app key/secret (₹500 plan, redirect `http://127.0.0.1:<port>/kite/callback`); tradebook and tax P&L since May 2026; contract-note PDFs.
- Stop: pushed.

**S5 CAS.** CDSL CAS and CAMS/KFin detailed CAS via `casparser`, into accounts, folios, MF transactions and lots.
- Tests: totals per folio equal statement totals; the dormant demat appears as an account.
- Accept: MF holdings equal CAMS closing units.
- The investor provides: latest CDSL CAS and the CAMS/KFin statement since inception, plus passwords.
- Stop: pushed.

**S6 Bank and income.** SBI statement import; match dividends, interest, refunds and transfers to Zerodha.
- Tests: classification rules on sample lines; dividend matches `dividends` feed amounts × qty.
- Accept: every credit since May 2026 classified or listed.
- The investor provides: SBI statement export since May 2026.
- Stop: pushed.

**S7 Reconciliation.** Ledger vs Kite vs CDSL vs CAMS vs bank, opening balances, break report, and migrated accounting checks.
- Tests: injected breaks are found; invariants (cash + holdings flows) hold.
- Accept: zero unexplained breaks on real data.
- The investor provides: explain any break the data can't.
- Stop: pushed.

### Prices, service, instruments
**S8 Prices.** Bhavcopy for ETF/SGB/bond series, AMFI NAV daily and history, IBJA gold, a Kite live poller in market hours, and staleness flags.
- Tests: parsers on fixtures; staleness rules; NAV history continuity.
- Accept: every held ISIN has a price ≤ 1 session old.
- The investor provides: nothing.
- Stop: pushed.

**S9 Service I.** Task Scheduler jobs (collect, prices, NAV, filings, backups), catch-up after sleep, health page and `tools/status.ps1`, Telegram sender.
- Tests: idempotent jobs; catch-up logic; message formatting with evidence links.
- Accept: a test alert arrives; a missed day is caught up.
- The investor provides: Telegram bot token and chat id; approve the Task Scheduler entries.
- Stop: pushed.

**S10 Bonds, SGB, physical gold.** Bond master and cash-flow schedules (coupon, frequency, day count), accrued interest, coupon matching; SGB interest and redemption; physical gold entries (weight, purity) marked at IBJA; bond model price as a labelled Estimate.
- Tests: schedules vs known bonds; accrued-interest conventions; SGB maturity rule for original vs secondary holders.
- Accept: synthetic portfolio values correctly.
- The investor provides: physical gold holdings (if any).
- Stop: pushed.

**S11 Corporate actions in the ledger.** Split, bonus, rights, merger, demerger (cost split per announced ratio), buyback (2026 rule), ISIN successions re-keying lots; migrated `scan_etf_events`.
- Tests: each action type on synthetic lots; holding period preserved; KOTAKBANK 2026-01 ISIN change.
- Accept: ledger qty equals Kite qty across every action since May 2026.
- The investor provides: nothing.
- Stop: pushed.

### Tax and numbers
**S12 Realised gains.** Per-FY gains by rule table, holding periods, grandfathering, exemption, set-off order, carry-forward.
- Tests: CBDT examples; set-off order; 8-year expiry; parity with `india_lots` for equity.
- Accept: FY2026-27-to-date gains equal Console tax P&L and the CAMS capital-gains statement, or the differences are explained.
- The investor provides: Console tax P&L.
- Stop: pushed.

**S13 Income tax and proposed sales.** Dividends and interest at slab; both regimes; surcharge, cess and 87A; basic-exemption absorption; advance-tax dates; tax on a proposed sale by lot (FIFO per account).
- Tests: hand-worked cases per regime; proposed-sale equals the realised result after the sale.
- Accept: `pflab pm tax --fy 2027` prints both regimes with components.
- The investor provides: other income (if any).
- Stop: pushed.

**S14 Calculations.**
- Scope: invested holdings, available cash, whole portfolio; realised and unrealised P&L; dividends; XIRR (`metrics.xirr`) and TWR (`unitized_nav`); growth split into gains, income and contributions; what-if for a purchase or next month's ₹50K.
- Tests: identities (start + contributions + gains + income = end); XIRR vs known cases.
- Accept: matches a spreadsheet check on real data.
- The investor provides: nothing.
- Stop: pushed.

**S15 Risk.** Exposures by asset, sector, stock and issuer; vol, drawdown, beta vs Nifty 50 TRI, correlation, concentration (HHI, top-N); migrated `shock_betas`.
- Tests: known synthetic portfolios.
- Accept: risk page numbers reproduce from the CLI.
- The investor provides: nothing.
- Stop: pushed.

**S16 MF look-through.** AMC monthly portfolio disclosures mapped to ISINs for sector, stock and issuer exposure through funds.
- Tests: weights sum ≈ 100%; ISIN joins.
- Accept: look-through for every held fund, or category-only with a reason.
- The investor provides: decision on `openpyxl` (§10 Q2).
- Stop: pushed.

**S17 Targets and rebalancing.** Targets with soft and hard bands; new-money steering of the monthly ₹50K (`fallback.md`'s Momentum 50 fund SIP is a candidate target); sale proposals only beyond hard bands with tax + cost comparison and the min-trade block.
- Tests: steering never proposes a sale inside bands; comparison math.
- Accept: a monthly proposal produced and logged.
- The investor provides: target allocation and bands.
- Stop: pushed.

### IPO and monitoring
**S18 IPO data.** Issue structure, price band, lot size, category subscription snapshots, anchors (BSE announcements), RHP fetch and text, GMP (unofficial, timestamped).
- Tests: parsers on fixtures; GMP label always rendered.
- Accept: a live IPO's page fills.
- The investor provides: GMP site choice (§10 Q5).
- Stop: pushed.

**S19 IPO ledger.** Applications, blocked funds (ASBA/UPI), allotment, refund, listing into lots.
- Tests: blocked cash excluded from available cash; refund releases it.
- Accept: a past application replays.
- The investor provides: past IPO applications, if any.
- Stop: pushed.

**S20 Filings and falls.** Live BSE filings for held and watched names, `red_flags` classification, migrated `issuer_events` and `event_reaction`; market-wide vs company-specific falls via market-model residuals and `shock_betas`.
- Tests: residual math; alert dedup.
- Accept: a historical fall is classified correctly.
- The investor provides: watchlist.
- Stop: pushed.

### LLM
**S21 LLM infrastructure.** Ollama client (migrated), model and prompt registry, numeric guard, citation checker, LangGraph skeleton, GPU job budget, OKF bundle and validator, Graphify trial.
- Tests: the guard rejects an invented number; the citation checker rejects an uncited claim; OKF validation.
- Accept: 9B and 27B pass a smoke run; the 27B pick is registered before its evaluation.
- The investor provides: Ollama installed and models pulled.
- Stop: pushed.

**S22 Laya contest.** Pre-registered split of the A1 labels (251 rows, plus new blind labels via `flag_audit_sample`); Laya zero-shot, then Laya fine-tuned in `.venv-train`, vs the archived Qwen 9B scores; calibration (ECE) reported.
- Tests: no train/test leakage; scorer (migrated `score.py`).
- Accept: the winner is chosen by the pre-registered metric, never after viewing alternatives.
- The investor provides: label ~100 more rows (≈1 h).
- Stop: pushed.

**S23 Classification service.** Chosen classifier on new filings and news; alerts carry evidence and alternatives; `ClassifierScore` typing.
- Tests: score never rendered as a profit probability.
- Accept: a day's filings are classified within the GPU budget.
- The investor provides: news source decision (§10 Q3).
- Stop: pushed.

### Research and decisions
**S24 Fundamentals.** Point-in-time results from BSE (migrated valuation and probe), statements, ratios, implied-expectation (reverse DCF) inputs.
- Tests: point-in-time cut; ratio math.
- Accept: a held company's last 8 quarters load.
- The investor provides: nothing.
- Stop: pushed.

**S25 Theses.** Locked dated theses (OKF note plus hash via migrated `check_lock`), milestones, kill criteria, quarterly checks triggered by results filings, promoter signals.
- Tests: an edited locked thesis fails verification; a check fires on a results filing.
- Accept: one real thesis locked.
- The investor provides: first thesis text.
- Stop: pushed.

**S26 Entry plans.** Buy now / wait / staged / reconsider. Includes:
- probability of touching a level within a window: a GBM barrier formula plus an empirical bootstrap, method and inputs shown as an Estimate;
- cost of missing a rebound;
- valuation assumptions;
- invalidation conditions and a review deadline (`stale_after`).
- Tests: barrier formula vs simulation.
- Accept: a plan rendered for a named stock.
- The investor provides: names.
- Stop: pushed.

**S27 Company research report.** LangGraph workflow covering business, financials, valuation and implied expectations, risks, contrary evidence, scenarios and portfolio effect; numbers from code; every claim cited; output to an OKF note.
- Tests: guard and citation checks enforced end-to-end.
- Accept: one report passes the guard.
- The investor provides: company choice.
- Stop: pushed.

**S28 IPO report.** As S27, plus "listing" and "ownership" answered separately; GMP labelled.
- Tests: both answers present; GMP label.
- Accept: one live or recent IPO report.
- The investor provides: nothing.
- Stop: pushed.

**S29 Journal and scoreboard.** Every proposal logged with evidence SHA and the investor's choice; each pick shadowed by the same cash flows into the Momentum 50 fund (real NAV), after tax.
- Tests: shadow-flow math.
- Accept: scoreboard since May 2026.
- The investor provides: pick the fund scheme.
- Stop: pushed.

### Service
**S30 Dashboard I.** Holdings, cash, P&L, tax, recon status, Kite login button; 127.0.0.1 only.
- Tests: views render from fixtures; no external calls from pages.
- Accept: daily use works.
- The investor provides: feedback.
- Stop: pushed.

**S31 Dashboard II + monthly note.** Risk, targets, plans, theses, IPOs, journal, research; the monthly note (OKF + PDF/HTML) covering holdings, returns, tax, proposals, scoreboard.
- Tests: every number in the note traced to an attested computation.
- Accept: September 2026 note produced.
- The investor provides: feedback.
- Stop: pushed.

**S32 End-to-end month.** Full reconcile of a real month, a backup restore test, the runbook (`docs/RUNBOOK.md`) and failure drills (no Kite token, stale prices, parser break).
- Tests: drills scripted.
- Accept: a clean month with zero unexplained breaks.
- The investor provides: one month of statements.
- Stop: pushed.

### Capability coverage

| capability (brief) | sessions |
|---|---|
| 1 Data | S4, S5, S6, S8, S10, S11, S18, S24 |
| 2 Ledger | S3, S4, S5, S6, S7, S19 |
| 3 Tax | S2, S12, S13 |
| 4 Calculations | S14 |
| 5 Risk and allocation | S15, S16, S17 |
| 6 Entry plans | S26 |
| 7 Theses and monitoring | S20, S22, S23, S25 |
| 8 Research | S21, S27, S28 |
| 9 Journal and scoreboard | S29 |
| 10 Service | S9, S30, S31, S32 |

## 10. Risks and open questions

**Risks**
- **Parser drift:** CAS, contract-note and SBI formats change without notice. Mitigation: quarantine plus an alert, fixtures from real files, and reconciliation catches silent errors.
- **Kite daily login:** the access token needs a manual login every day; automating TOTP is against Zerodha's terms. A missed login means EOD only, flagged.
- **Tax law churn:** a new Finance Act every February. S2's tables are re-verified each April, and a stale `verified_on` (over 13 months) fails a test.
- **Laya on small labels:** 251 rows is a thin training set. Mitigations: more labels (S22) and a pre-registered split. If Laya cannot beat the 9B model, the 9B stays.
- **Laptop as server:** sleep, updates and disk failure. Mitigations: catch-up jobs, nightly backups, a monthly restore test.
- **Local research quality:** a 27B model at Q4 with CPU offload is slow (a few tokens a second). Reports run overnight within a budget; the numeric guard keeps quality failures from becoming wrong numbers.
- **GMP and IPO pages:** unofficial sources, scraping terms, layout changes.
- **Young specs:** OKF is v0.2, and Graphify is new. Both are used behind our own validator and are replaceable.

**Amendment A1 (2026-10-06, S2): rule coverage starts 2024-07-23, not 2018-04-01.** The
2018–2024 regimes (10%/15% equity, 36-month non-equity units, indexation) need their own
primary-source verification and nothing in the investor's ledger sells before FY2026-27. Prior-year
losses to carry forward come from his filed returns, not from these tables. Transfers before
2024-07-23 raise `RuleGap`. Surcharge cap, cess and basic exemption start 2025-04-01 (the
Finance Act 2026 text covers AY 2026-27 on). New-regime slabs and the 87A rebate move from S2
to S13. Revert by adding dated rows; no code change needed.

**Decisions, the investor, 2026-10-06 (recorded same day)**
1. Dashboard: **FastAPI** (S30). Added to CLAUDE.md "planned" list; pinned when first installed.
2. **`openpyxl`: yes**, for AMC Excel portfolios (S16).
3. CAS: **manual download** for now; no email fetching (was Q6). Contract notes the same.
4. Dormant demat: **imported and reconciled read-only, flagged dormant, included in totals** (was Q7). `accounts.dormant` and `accounts.read_only` exist from S1.
5. `PFLAB_PM_DIR` = `D:\portfolio_lab\pm` (default in code, set in `.claude/settings.json`).
6. Stack stays Python (was Q8).
7. News source (Q3, S23) and GMP site (Q5, S18): decided in the session that needs them, with options, cost and reliability proposed there. They block nothing earlier.

**Amendment A2 (2026-10-06, S9): Telegram is sent over the Bot API with `requests`.** `python-telegram-bot` is
not added: S9 only sends notifications (no incoming commands), so a framework adds an event loop and a
dependency for one HTTP call. Every message goes through a durable outbox first. If commands from Telegram
are ever wanted, adopt `python-telegram-bot` then. The planned-dependency list in CLAUDE.md keeps it as optional.

**Amendment A3 (2026-10-15, S33): fixed deposits are holdings.** The investor's SBI cumulative FDs are most of his
money and mature in batches over the next few years; he wants the
proceeds redeployed into a diversified portfolio, so the allocator, net worth and tax must see them. Added
`pm/fd.py` (SBI quarterly convention, verified on the real deposits), `ingest/sbi_interest_cert.py`
(certificate rows must add up to its TOTAL), migration 14 (`fds`, `fd_interest`), FD interest and TDS fed
to `tax.proposed.year_tax`. Bank values and certificate rows are facts; projections are `Estimate`s. The
deposit file (`PFLAB_PM_DIR/fd_holdings.toml`) is the investor's data and stays out of git. Recurring deposits and
interest-payout FDs are not modelled and are refused.

**Amendment A4 (2026-10-15, S34-S38): agents around a centre.** The investor's design: build specialist agents
around the ledger, then put an AI at the centre that routes his questions to them and explains. Each agent is
deterministic code with tests; the centre (local LLM, S21 guard: no invented numbers) only calls agents and
cites their outputs, never places orders.
- Data agent: `collect_daily` (NSE/BSE prices, corporate actions, dividends, surveillance, indices), ledger rebuild.
- Guard agent (S34/S35): validated safety filters (`plan.safety`, study in docs/research), NSE surveillance
  (`data.nse_surveillance`), market-dip state; alerts to the S9 outbox (`plan.guards`, `pflab pm guards|alerts`).
- Allocation agent (S17/S33): targets, FDs as locked debt, deployment schedule.
- Risk agent (S36): Monte Carlo with a 12-month block bootstrap (main) and GBM (reference), efficient frontier
  of 5,000 simulated portfolios; Estimates only.
- Ask agent (S37): `pflab ask`, LangGraph over the agents' read-only tools.
- Knowledge agent (S38): time-aware graph (Graphiti-style validity intervals) of GDELT GKG context, filings,
  results and the portfolio.
Telegram stays pending (The investor, 2026-10-15): alerts wait in the outbox.

**Amendment A5 (2026-10-15): the next sessions (quant research and the agents' brains).** Built so far around
the centre: S33-S38 (FDs, dip-rule study, guards and alerts, Monte Carlo and frontier, the ask centre, the
knowledge graph). Next, one session each, same rules (branch, tests, STOP updates):
- **S39 Pairs trading (research).** Prerequisite: re-run the dip-rule study with protocol amendment 1 (F3 not
  for financials) and report it. Then: candidate pairs within a sector from the point-in-time Nifty 500
  universe; Engle-Granger and Johansen tests on a formation window (statsmodels, to be pinned), hedge ratio
  re-estimated walk-forward; trade the spread's z-score (entry, exit, a stop when the spread breaks, a max
  holding period) only on data after formation; Zerodha costs; the short leg costed as stock futures (or SLB),
  since cash shares cannot be held short overnight; pre-registered protocol like S34; 2022-2025 reported as
  spent. Portfolio use: a research result and a "relative value" view of two holdings, not an order path.
- **S40 Hawkes processes.** Univariate and bivariate exponential Hawkes fitted by maximum likelihood (scipy),
  goodness of fit by the time-rescaling theorem (KS on compensator residuals). Data we have: BSE filing
  dissemination times per company (event clustering), and daily large-move exceedances of the Nifty 500 and
  of held stocks (crash clustering). Portfolio use: a clustering-aware alert ("the self-excitation after today's
  fall is high") and a stress input for the risk agent.
- **S41 Limit order book simulator.** Event-driven matching engine (price-time priority; limit, market, cancel),
  order flow from the S40 Hawkes fits; metrics: spread, depth, price impact, fill probability. Synthetic inputs
  until live market depth is recorded from Kite's websocket (5 levels), which becomes the calibration source.
  Portfolio use: expected impact and slippage of the investor's own order sizes (monthly tranches) per stock.
- **S42 The agents' brains.** (a) `pflab list add SYMBOL` already runs guards and the graph; extend it with a
  research brief written by the research model from the graph (filings, results, news), guarded and cited.
  (b) Models: centre = qwen3.5-9b (works, tested); research = qwen3.5:27b after its pre-registered evaluation
  (The investor pulls it: `ollama pull qwen3.5:27b`, ~17 GB); a decision-model slot (Laya, open-weight, Apache 2.0)
  trialled for routing and news tagging against the current model on the same labelled questions before it
  replaces anything. (c) Tuning per task: build a labelled evalset per agent first (routing, news materiality,
  brief quality), then LoRA in `.venv-train` only where the evalset shows a gap.

**Amendment A6 (2026-10-15): models removed; choose by measurement on a 12 GB GPU.** At the investor's request
every local model was deleted (the 6 Ollama models, 19 GB). Until a model passes the evaluation below,
`pflab ask` runs in its safe mode (keyword routing, facts only, no written answer). The S21 pick of a 27B model
is withdrawn: on this GPU (RTX 5070 Ti Laptop, 12 GB VRAM) a 27B model only runs with CPU offload (slow).

What fits: model weights plus the context cache plus overhead must stay under about 12 GB, so roughly an 8-9B
model at 8-bit (Q8_0), a 12-14B model at 5-6 bit (Q5_K_M / Q6_K), or 14B at 4-bit (Q4_K_M).

How much accuracy quantization costs (published experience, to be MEASURED here, not assumed): 8-bit is
usually indistinguishable from full precision; 6-bit is very close; 5-bit loses a little; 4-bit loses
noticeably on multi-step maths and reasoning, more so for smaller models; below 4-bit degrades sharply.

Why this matters less here than elsewhere: no model computes a number in this system. Code computes every
value and the S21 guard rejects any number or date in a model's text that is not in the facts or a cited
source. A weaker model therefore shows up as more rejected drafts, fallbacks and wrong routing, not as wrong
numbers. Those are exactly what the evaluation measures.

**S42 becomes: pre-registered model evaluation, then the agents' brains.** Before any download, register in
`docs/llm/` (like S34): candidates (3-5 open models that fit, each at Q8_0, Q6_K and Q4_K_M where it fits),
tasks with labelled answers built from this system's real outputs (routing a question to the right agents;
guarded answers: first-draft pass rate, final pass rate, numbers the guard had to reject; extraction of
fields from filings; news materiality and sentiment tagging), and pass thresholds fixed in advance (for
example routing >= 95%, final guard pass >= 98%, extraction F1 >= 0.95, answer within 20 seconds). Choose the
smallest, fastest model and quantization that passes everything; ties go to the higher-bit version. The investor
runs the downloads (several GB each). A decision model (Laya) is tested in the same harness for routing and
tagging. Fine-tuning (LoRA, `.venv-train`) only where the measured gap justifies it.

Other local models: `D:\hf-cache` holds Llama 3.1 8B Instruct, a small sentence-embedding model, and the investor's
own `shramik-saathi` fine-tunes (another project). The investor asked for it to be deleted too; a Claude Code safety
check blocks such a removal, so he deletes the folder himself (`Remove-Item -Recurse -Force D:\hf-cache`).

**Amendment A7 (proposed 2026-10-16, AGREED by the investor 2026-10-17): a working team of agents, local, through Telegram.**
The investor's aim: not a repo but a usable system that works without being asked: researches the watchlist, keeps
everything current, checks trades after they happen and asks what it needs, plans buys (quantities, prices,
splitting), manages risk, and answers any question at any time, all locally through a two-way Telegram bot. It
never places an order (PLAN section 1). Principles: code computes every number; the local model only reads,
routes, tags, extracts and explains through the S21 guard; every new claim is a pre-registered study first; what
fails is not wired in (memory: research-must-feed-agents).
- **Agents** (each: trigger, inputs, outputs, tests): data (built); trade-check (daily after Kite login: new trades
  into the ledger, questions for anything missing); researcher (watchlist filings, results, news; material-change
  flags; briefs kept current; any IPO on request); risk manager (guards, market state, concentration, distance from
  the 35% limit); advisor and allocator (per-stock quantities and prices on top of the bucket plan); trader planner
  (split buys and limit prices, only after a pre-registered "split / limit below market vs buy at once" study);
  tax (built); quant researcher (on demand: maps an idea to a library of tested study templates and runs them;
  scheduled re-tests of every adopted rule on new data with drift flags); memory (decisions, reasons, outcomes,
  feedback); supervisor (data freshness, failed jobs, model pass rates); the centre (answers, weekly report).
- **Two-way Telegram**: long-polling `getUpdates` over `requests` (no new library), only the investor's chat id accepted,
  read-only commands and questions routed to the centre.
- **No paid compute by default**: one local model shared by all agents (chosen by S42); prompt tuning on a split
  of each eval set, then QLoRA in `.venv-train` only for a measured gap; an optional larger overnight model with
  CPU offload (for example a ~35B mixture-of-experts model, 3B active, about 22 GB, which fits 12 GB VRAM + 31 GB
  RAM) for long research jobs, registered and evaluated like S42; cloud only if a measured gap remains and the investor
  agrees.
- **Companion workflows** (The investor 2026-10-16, two examples): (1) *event research*: The investor sends news ("pharma X
  has a cancer-drug deal") -> check primary sources (BSE filing, regulator) and label it confirmed / unconfirmed;
  map competitors (NSE industry, co-mentions in filings and news); historical analogues by a tested event-study
  template (how the company and its rivals moved after similar events); a plan computed by code (quantity within
  the risk caps, a maximum price, staged buys) -> Telegram price-level alerts, a ready GTT ticket that the investor enters
  in Kite himself (the SDK has no alert API and GTTs are orders: they stay forbidden), then the watcher and the
  trade-check agent take over after the fill. (2) *thesis tracker*: The investor states a thesis the prices cannot show
  ("AI is a bubble of circular financing") -> evidence for and against from filings and news, indicators tracked
  over time, the portfolio's exposure to it, and a conditional action with an expiry (e.g. keep part of new money
  in a liquid fund for 12 months for a dip, else redeploy or move to another sector), its cost and protection
  measured with the Monte Carlo engine; the investor approves. The unused cash in the Kite account (`margins()`,
  read-only) is part of every plan.
- **Research tier via API (The investor 2026-10-17)**: a larger hosted model as the analyst for deep, open-ended research
  on PUBLIC information only (filings, news, prices, sector and regulator data); its notes (dated, cited) go into
  the local knowledge graph and memory for the local model. Personal data never leaves the PC: an egress gate in
  code builds every request from public sources and rejects ledger content (amounts, quantities, account and FD
  ids, names, statements), proven by a test; every call is logged locally; a hard monthly budget cap set by the investor.
  Residual exposure: the companies asked about (research by sector, or mixed with others, if wanted). Adopted only
  after a pre-registered comparison with the local model on the same public questions shows a clear gain.
  **The investor 2026-10-17: Claude Opus 5.5 as the analyst, called only through a "doorbell"**: the local model takes
  every question first and answers it when it can (facts, agents, existing notes); it rings the API only for deep
  research, after checking memory for a recent note on the same topic (reused, not re-bought), with a prepared
  request (precise question, the public documents, the output format) that passes the egress gate; non-urgent work
  goes to the overnight batch (half price); every answer is stored as a dated, cited note for the local model to
  reuse. **Monthly cap: set by the investor 2026-10-17 (the amount lives in PFLAB_PM_DIR, not in git)**, warning at 80%,
  calls stop at 100%. His own questions ring
  automatically and report the cost afterwards; self-started research runs in the overnight batch within the cap;
  any single expensive job (above a per-job limit he sets) asks him first.
- **Maths audit first (The investor 2026-10-17: "the agents must be right in stats, maths, probability, risk")**: S43 opens
  with an independent check of every number-producing agent, recomputed by a second method on fixed cases: Monte
  Carlo (block bootstrap and GBM against closed-form GBM drawdown and return quantiles), allocator and deploy
  (hand-built portfolios), risk stats (volatility, beta, drawdown against textbook formulas), market state (Hawkes
  chance against simulation), FD, tax and lots (already cross-checked against the bank and Console). Each finding
  is fixed before the agents are built on it.
- **Proposed order**: S43 trade-check + memory + two-way bot; S44 researcher; S45 advisor quantities + the split
  study + trader planner; S46 quant researcher templates and drift loop, event research and thesis tracker;
  S47 model tuning per agent (round 2 of S42 first); S48 the
  "who is buying" study; S49 memory comparison (ours vs supermemory, local).

**Amendment A8 (2026-10-22): the sessions to switch-on, then filing and the US sleeve.** The investor's order (HANDOFF
2026-10-21; memory `autonomous-loop-vision`): the system complete in November, working on its own, him in the loop
when he wants. Built through S53 plus S52 live (Q5 turnover, Q6 results ranges). Each session: branch, tests, STOP.
- **S54 Dashboard and watches.** Local web app (FastAPI + uvicorn, pinned when added; 127.0.0.1 only; no email):
  Today (the conductor's fact sheet: mode, sync check, asks; market state with the volatility chance; guards; alerts
  held and sent), Portfolio (net worth, holdings and lots, tax so far, FD ladder), Plans (advise, deploy, propose; the
  tickets with the S52 size line), Research (flags, briefs, analyst notes, results ranges and surprises, theses),
  Forecasts (the S52 scoreboard), Inbox (The investor's questions answered here or on Telegram, one store path), System (jobs,
  health, API spend). Read-only apart from answers, watches and the Kite login button. **Streak-style watches** (ideas
  from Streak, not its code): a condition in plain words ("X closes below 2,400", "Nifty down 2% today", "X's RSI(14)
  under 30") is mapped to a fixed template (the local model may pick the template and fill it; code checks the fields
  and evaluates it); watched in market hours by the Kite read-only poller within its rate limits; a hit goes to
  Telegram and the dashboard inbox, never an order. A watch is a watch: a rule that claims an edge needs its own
  pre-registered study. A technicals view per stock (moving averages, RSI, ATR, 52-week range, volume against its
  average), labelled as description. Acceptance: The investor opens it, sets a watch, sees it fire on a replayed day.
- **S55 Ready plans.** Plans kept current for the next money (FD maturities, the monthly amount): what to buy, how,
  and why, ready before he asks; the "outer ring" shown as an idea, not a rule.
- **S56 Escalation chain.** Local model -> agents -> Opus (doorbell) with the reason at each step. **Tijori check
  first** (any time, before he buys; no code): its plans and prices, the Excel export in Premium, and its terms on
  using the data with an AI, each fact from Tijori's own pages, dated, in `docs/data/tijori_check.md`. Bought: exports
  go into `pm\inbox\market\` (the inbox reads them already).
- **S57 Knowledge-graph cleanup and the Graphify trial** (installing a Claude Code skill needs the investor's OK). DONE 2026-10-23, A11 (Graphify not adopted).
- **S58 Restart drills** (power cut, offline days, a killed job, a full disk), then **switch-on** (`docs/SWITCH_ON.md`).
- **S59 Filing pack for Quicko** (Quicko replaces a CA; official routes only). From the tax engine: capital gains by
  schedule (111A/112A, dated bands), interest, dividends, TDS, both regimes, in the form Quicko takes (its import format
  checked against its own documentation first); each year a line-by-line check of Quicko's figures (his export into the
  inbox) against ours. The year-round view stays ours (tax so far, advance-tax dates, LTCG exemption headroom shown,
  never acted on). Check, sourced: does Quicko cover Schedule FA and the foreign tax credit (Form 67)? Due before the
  FY 2026-27 return (July 2027).
- **S60 US-stocks sleeve** (Zerodha's GIFT City account; IFSCA, money out under LRS; diversification only, a small
  share; the PhD plan unchanged). Research first: every fact sourced and dated (IFSCA framework and the broker's terms,
  LRS limit, TCS, Indian tax on foreign shares, US withholding and the treaty credit, Schedule FA, US estate tax on
  US-situs assets, all costs), Opus through the doorbell, public sources only; nothing from memory until a source
  confirms it. Then the Monte Carlo in rupees with the sleeve at 0/10/15/20% against the 35% fall limit (labelled
  estimates; the share is the investor's), the ledger (a USD account, lots at the dated FX rate, foreign tax credit, Schedule
  FA report), US prices and USD/INR, SEC filings, then tickets, guards and research for US names. The research and
  the Monte Carlo (steps 1-2) may run before S54-S58 finish.
- **Later, small:** Coin mutual funds read through Kite Connect's read-only mutual-fund API when he starts SIPs.
  smallcase and Sensibull stay out of the system.

**Amendment A9 (2026-10-22): the agent roster, autonomy and the small-numbers rule.** The investor: a system that decides,
calculates and specialises, and works without waiting to be asked. Each agent: tested code at its core; a model only for
a narrow job with its own evaluation; a fixed autonomy level (acts / proposes / asks). New maths is written by Opus as
code from the schema alone (never the rows), kept "not reviewed" until promoted. The local qwen3:8b routes, tags and
writes guarded text; it never writes maths (2026-10-22: it misread a drawdown question on every try). No new providers
(Perplexity, a larger local model) until a named job fails its test and the replacement wins a measured comparison.

| agent | duty | when | model | checked by | autonomy |
|---|---|---|---|---|---|
| collector | prices, actions, dividends, surveillance, indices, VIX, news, NAVs, gold, world markets | 19:30-22:45, 07:30 | none | sync check, counts | acts |
| filings monitor | BSE filings for held and list names | hourly 08-22 | local tag (S47 v2) | red-flag rules, S47 | acts (alerts) |
| portfolio keeper (S54) | value, P&L, weights, distance to targets and to the 35% limit, tax so far | every 15 min in market hours (Kite read-only quotes), close | none | S43 maths audit | acts (shows) |
| risk manager | guards, Hawkes market state, volatility chance, concentration, dip and FD alerts | 20:45, on a state change | none | S34, S40, S51; drift | acts (alerts) |
| simulator | Monte Carlo of the current mix and the frontier | nightly, weekly deep run, on a state change or a new plan | none | closed forms (S43) | acts (shows) |
| forecaster | S52 turnover and results ranges | 21:00 | TimesFM | live scoreboard | acts |
| researcher | flags and briefs per company | 23:30 | local (tag, guarded brief) | S42/S47 | acts |
| analyst | deep notes on public documents | overnight batch; live for his questions | Opus | adopted comparison; sourced numbers | acts within the cap |
| advisor | the next money: buckets, stocks, quantities | nightly, FD maturity, his amount | none | S45, maths audit | proposes |
| trader planner | tickets with the size check | with each plan | none | split study, S52 Q5 | proposes (never orders) |
| trade check | Kite trades and holdings against the ledger | 16:00 with a Kite login | none | reconciliation | asks |
| event research / thesis tracker / quant researcher | his news, his theses, his ideas; drift of adopted rules | on demand; nightly; monthly | local routing, Opus deep | event-study templates, drift | proposes, asks |
| tax keeper | tax so far, advance-tax dates, LTCG headroom; the filing pack (S59) | nightly | none | Act text, Console parity | shows |
| workshop | new calculations as code | on demand | Opus (local only as labelled fallback) | sandbox; acceptance 10/10, ~Rs 51 (2026-10-22) | proposes until promoted |
| centre and bot | his questions | on demand | local routing, guarded answer | S42 round 3 | answers |
| watches (S54) | conditions in words, market hours | live | local maps words to a template | template tests | acts (alerts) |
| conductor | runs and catches up jobs, asks for files, wake and closing notes | every 15 min | none | sync check | acts |

**Autonomy (The investor 2026-10-22).** Without asking: collect data; research; update plans and research; do the maths;
keep the current portfolio's numbers live; run simulations on a schedule; message him; spend API money within his cap.
Never: place an order or a GTT, change targets, limits or the stock list, move money, send personal data out.

**Small numbers (The investor 2026-10-22: the law of large numbers holds at scale, not at small n).** Every statistic shown
carries its n. A rate or average from fewer than 20 observations is shown as a count ("3 of 7") and never drives an
action; an annualised figure needs at least 250 sessions; a Monte Carlo tail chance is shown with its standard error,
with paths raised until that error is at most 0.5 percentage points; an event study needs at least 5 events; a forecast
scoreboard acts only with half its window matured (S52). Enforced in one helper used by every agent's text and the
dashboard, with tests.

**Known gaps:** briefs pass the guard 36% of the time live (S47 pass 3: the writing harness reached 0.77, under its
0.85 bar), so many fall back to facts: S56 decides whether Opus writes them in the nightly batch; no split / limit plan
was adopted (tickets buy at once); no Kite depth recordings yet (impact); some list companies lack 8 consecutive quarters (no Q6 range yet).

**Amendment A10 (2026-10-23, S56): the escalation chain, and the decisions A9 left open.**
- **One road per question** (`agents/escalate.py`, the AI centre's default "Auto" mode): local (tools + guard) ->
  agents (the workshop for a calculation; a reused analyst note on the same company question from the last 14 days)
  -> Opus (deep research on public documents, or web search for the world outside our data), each step with its
  reason, shown as the answer's route. The kind (own / calc / company / outside) is set by fixed word rules and the
  companies named, never by a model. A question about his own portfolio stops at the local facts: his data never
  leaves. Spending stays in the doorbell (cap, `ask_above`, his yes).
- **Opus writes calculations: yes**, through the workshop (acceptance 10/10, ~Rs 51), as a step of the chain; the
  local model stays a labelled fallback. Calculations stay "not reviewed" until promoted (S53).
- **Briefs (A9 known gap): no second paid writer.** A brief that fails the guard shows its facts, and Opus's nightly
  note on the same company (already queued for every flagged name, batch price) is shown beside it; no Opus spend on
  briefs as such.
- **Falls** (`researcher.fall_flags`): the S20 classifier, live, over the last 5 and 20 sessions; a company-specific or
  mixed fall is a research flag with its numbers (a description, not a reason to sell), which sends the name into the
  night's Opus note queue; once the investor has Tijori, he is asked for the company's export first (once a month a name).
- **Tijori** (`docs/data/tijori_check.md`): checked (prices, downloads, terms). The investor 2026-10-23: its exports are public
  company data, not his; they go to the analyst and the research (`tijori_to_analyst = false` stops it).

**Amendment A11 (2026-10-23, S57): knowledge-graph cleanup; Graphify not adopted.**
- `kg/clean.py`, run by the nightly `kg` job and logged on the Inbox screen (The investor's rule: automatic when exact, ask
  when unsure; nothing deleted). Names: organisations that are one name once a leading "the"/"company" and trailing
  legal endings are taken off merge; one that is a graph company by the same rule merges into the company; a name with
  one extra word after one of his companies ("... Group") is asked once, his answer holds (store v30 `kg_aliases`; new
  articles map through it). Copies: the same headline on the same day points at the earliest (`kg_docs.dup_of`); the
  graph view, news spikes, timelines and the analyst's documents use originals only. Memory: per company the newest
  analyst note is current, earlier ones end (and each new note now supersedes the last). First run on the real graph:
  85 names merged (23 into his companies), 393 copies set aside, 21 notes ended, one question; a second run changes
  nothing.
- **Graphify: not adopted.** It is a Claude Code skill that maps a folder (code by tree-sitter; documents sent to Claude
  for extraction): it would serve the coding assistant during the build, not the running system, the investor will remove
  Claude Code after the build, and his documents must not leave the PC. The anti-drift memory is the system's own:
  the dated graph, the superseding memory rows and the guard.

**Amendment A12 (2026-10-23): the buy-zone wait study fails; the zone never says "wait".** Pre-registered
(`docs/research/buyzone_wait_protocol.md`), run once (`buyzone_wait_results.md`): limits at the zone's top held 1, 3 or
6 months lost against buying at once in every period (validation: -63, -237, -496 bps; t about -1). Not adopted: the
plans buy at once; the verdict WAIT is replaced by ABOVE ZONE (a description with the finding) and RICH (a caution,
untested); "check my idea" says yes above the zone, check when rich.

**Amendment A13 (2026-10-23): reusable calculations; the Sonnet comparison set up.** The workshop searches its kept
calculations before paying a writer: the same question re-runs its kept code on today's data; a similar question
(sharing 40% of its words) with a calculation the investor promoted is answered by it, the local model only reading the
parameter values from the question (each checked against its type; a text value must appear in the question); a miss
goes to the writers. New calculations name their changeable values as parameters. Promotion stays the investor's (CLI or the
AI centre's Calculations panel). Sonnet 5.5 vs Opus 5.5: protocol `docs/llm/sonnet_vs_opus_protocol.md` (amendment 1:
both models on the current writer prompt); runs are the investor's.

**Amendment A14 (2026-10-24, S58b; the investor: the system is built around the portfolio; the Kite login is a must; the maths
must be right, reused or new).** (1) The portfolio today (`pm/today.py`): each trade check (hourly 08-22 while logged
in, and right after a dashboard login) stores Kite's holdings with T1, Coin funds, today's delivery trades and cash
(store v31); every reader of holdings (screens, plans, simulations, the workshop, the ask tools) uses the ledger with
the Zerodha account replaced by that view; cash Zerodha paid out is shown as moved to the linked bank (an estimate until
the bank statement). Tax keeps the ledger's lots. The conductor asks for the Kite login each trading day from 08:30 and
for last month's statements from the 3rd. (2) Reviewed measures (`calc/measures.py`: fall from a peak, period return
and CAGR, volatility, extreme days, worst run, VaR/CVaR, chance of a fall, correlation and beta), each tested against
worked answers and a second implementation, answer before any writer; the local model only picks the measure and its
values, an index series must be the one the question names (corrected when one fits). (3) New code is never accepted on
its writer's own example: an independent second writing must agree on the real data, else it is disputed (both shown,
neither reused or promoted); only reviewed or confirmed calculations are reused. Fallback: the measures and the second
writing can be bypassed by `library=False` / a failed second writing ("not confirmed", labelled). (4) Tax planning
(`tax/plan.py`) asks the tax engine (`tax.proposed.year_tax`, each sale replayed on a copy of the event log) and writes
no tax maths of its own: per-lot FIFO ladder at today's price, long-term dates from the lot's rule, waiting savings,
the 112A exemption left and the gains that fit in it (checked by replaying the sales together), loss sales; tested
against hand-worked figures. A Kite-only quantity has no tax lots until its statement arrives (said).

**Amendment A15 (2026-10-24; the investor: the system works then and there, autonomous and constantly working).** Schedules
stay only where the data appears at a time (NSE after the close, AMFI at night); new data starts the jobs that use it at
once (`jobs.FOLLOWS`, window open or the night task), filings and the Kite snapshot run every 15 minutes, and the
dashboard picks up new code by itself (a button; a restart after 30 minutes untouched with nothing running). Fallback:
the schedules alone still run every job. **Decision (The investor, 2026-10-24): no backup target for now**; he will say if he
wants one (`configs/service.toml [backup] declined`).

**Amendment A16 (2026-10-24, S59; the investor: a team of agents with a brain over them, used every day, ordered directly).**
Design and decisions in `docs/BRAIN.md`; this amendment records how S59 builds it.
- **Where:** the package `pflab.hq` (`src/pflab/hq/`, the repo's `hq/`): inside the installed package so the jobs, the
  dashboard and the self-update stamp see it. Existing modules are wired in by import; one is changed in place only
  where it must (each change named in STATE).
- **The egress list (The investor 2026-10-24), `hq/egress.py`:** every paid HQ call is checked in code before it is priced:
  PAN, e-mail, phone, account-like digit runs, IFSC and UPI ids, address words, his name (`api_budget.toml [egress]`),
  the ledger's account, depository, folio and FD ids, and any document that is not a public kind or a code-built
  portfolio view (statement files never). Holdings, amounts, weights, gains and goals may go. The older, stricter gate
  stays on the analyst's existing paths (research, web, workshop); loosening it is not needed for them.
- **The spend governor, `hq/governor.py`:** every call priced before it is made (count_tokens, worst-case output,
  cache and batch prices) against tokens per pass, passes per day, rupees per day per layer, the layer's monthly share
  and the system cap (₹2,500, `api_budget.toml`); a call over any limit is not made and is logged as `over_limit`.
  Settings `brain`: off / economy (default) / normal. Agent-to-agent chains: at most 3 hops, then the brain.
- **Models (BRAIN.md):** code for every number; qwen3 8B local for private text and routing; Haiku 5.5 readers;
  Sonnet 5.5 workers (company notes move from Opus, batched; the workshop's independent second writing); Opus 5.5 brain
  and deep research. Fallback: a layer over its limit falls to the one below (brain -> Sonnet -> reflexes alone).
- **One process:** HQ runs on the dashboard's runtime (a worker thread for the board, the Telegram poller, the
  drive watcher) and, with the window closed, as jobs in the scheduled tick; never a second writer.
- **Drive watcher (The investor 2026-10-24):** a local folder for now, `D:\portfolio_lab\drop` (gitignored); files placed
  there reach the inbox by themselves and move to `drop\taken`. Google Drive later (its desktop folder works the same).
- **Laptop off (The investor 2026-10-24):** laptop on = system on; nothing runs in the cloud.
- **Shadow mode:** the brain writes its journal and predictions for two weeks and acts on nothing; the judgement is
  pre-registered in `docs/research/brain_shadow_protocol.md` before its first pass (predictions scored on outcomes
  after them, Brier score against a base rate; Sonnet as the cheaper rival on the same passes).

**Amendment A17 (2026-10-24, after S59's paid check; the investor): one brain with tools, learning from real outcomes.**
- **Architecture:** one brain (Opus) calling tools in a bounded loop; real agents only where the work is reading-heavy
  and separable (the research analyst, the readers, the learner). The other S59 agents become tools; the board stays
  as the task log (design: `docs/BRAIN.md` "Step 2 proposal").
- **Learning:** every suggestion, taken or declined, is scored on what prices and his portfolio then did (declined ones
  on paper); one failure does not retire a kind of suggestion; decision quality is judged apart from luck.
- **What it analyses:** for each held and listed stock, its drift (weight against target, price trend), probabilities
  (moves, zone touches, falls, from the stock's own history) and edge (expected return against its base rate, after
  costs, with n): facts from code, not judgement from a model.
- **Autonomy:** it works on its own; the investor only approves, and what needs him comes to him (Telegram, Needs you).
- **Context:** the stable part cached; near a pass's token budget the brain writes its state to memory (superseding the
  last) and continues on a fresh context.
- **Order:** (1) Haiku vs the local model, done 2026-10-24 (`docs/llm/haiku_vs_local_results.md`: Haiku takes
  routing, guarded answers and extraction; materiality undecided; the local model stays first for live answers, 8 of 12
  vs 7 of 12); (2) the brain with tools, the suggestion ledger, statement redaction, cited-filing fetch (S60);
  (3) the Haiku / Sonnet / Opus slider, measured; (4) the learner; (5) repo clean with a git-history rewrite (The investor's
  written yes; the delete list shown first).
- **Statements:** transaction history may go to Claude once identity details are redacted (`redact()`, S60).
- **Local model:** removed after step 5 if not needed (The investor; this overrides CLAUDE.md rule 11's "never delete").
- **Gmail connector:** later, after the investor has cleaned his mailbox.

**Amendment A18 (2026-10-25, S60; the investor's decisions of 2026-10-24, `docs/S60_KICKOFF_PROMPT.md`): the brain with tools.**
- **Tools (`hq/tools.py`):** one registry. Each tool is a plain function with a strict JSON schema (`strict: true` on the
  API, checked again here), a compact result that names its source, and a kind: `read` (runs), `journal` (the brain's
  own ledgers: predictions, suggestions, its working state; always written) or `action` (ask / tell the investor, order research
  or a calculation, correct memory: in shadow mode recorded as decisions, never carried out). Every call is logged
  (`hq_tool_calls`). The S59 agents stay on the board for the investor's own orders; for the brain they are these tools.
- **Per-stock facts (`hq/stocks.py`), code only:** drift (weight against the advisor's own per-name share, the bucket's
  bands, the price trend), odds (the stock's own windows for moves; bootstrapped touch chances for falls and the buy zone,
  with their errors) and edge (mean forward return against the Nifty 500 over the same windows, after round-trip costs,
  with independent n and t). Edge is a description, never a signal: CLAUDE.md rule 12 still decides what acts.
- **The loop (`hq/brain.py`):** manual tool loop (not the SDK runner: the governor must price every turn): at most 8
  turns, each priced and checked by `hq/governor.py` (the pass is admitted against passes a day on its first turn; every
  turn against tokens, the layer's day and month and the cap). Near the per-call input limit the brain saves its working
  state (memory kind `state`, superseding the last) and continues on a fresh context; the next pass starts from it.
  Sonnet stays the rival on the same tools (protocol amendment 1, `docs/research/brain_shadow_protocol.md`).
- **Suggestion ledger (`hq/suggestions.py`):** every suggestion with its reasoning and the tool results it rested on;
  The investor's answer (taken / declined / none; a trade in the suggested direction seen in the portfolio counts as taken);
  scored at its horizon on the stock against the Nifty 500 (declined ones on paper); hit rates by kind with n (counts
  under 20); decision quality judged by code at the time (against the facts it cited: guard, drift, edge) apart from the
  outcome; no rule retires a kind. The lessons go into the brain's cached part. Scored by the memory keeper.
- **Memory that updates:** the brain's state supersedes its last; a memory correction keeps the old row and the reason;
  the keeper writes each followed-up decision's 30-day outcome back as an `outcome` row.
- **Redaction (`hq/redact.py`):** statement text leaves only through `redact()` (PAN, account / folio / client / DP
  numbers, IFSC, UPI, his name, address, phone, e-mail -> tokens) and the egress check on its output; checked on his real
  statements on this PC (counts only reported).
- **Cited-page fetch (`hq/fetch.py`):** Anthropic's web fetch (basic `web_fetch_20250910`, one fetch, that host only)
  of a URL an analyst note already cites or a filing in the graph; priced and governed (workers layer); every figure of
  the answer must appear in the fetched text.
- **Then (The investor 2026-10-25):** no 14-day shadow trial: the brain acts now, capped a day per action, the rival never
  (protocol amendment 2). Every filing of a held or listed company keeps its attachment's text on this PC as it arrives
  (free, each HQ round, 120 days back). His address words are found in his own statements by code
  (`tools/set_address_words.py`), not typed by him. The scheduled tick must be registered for the system to run with the
  window closed.
- **Not in S60:** moving routing / guarded answers / extraction to Haiku in code (step 1 decided it; S61's slider wires
  it with the measurement), Gmail, the learner (S62). Fallback: Settings brain `off` stops every paid pass; with the
  loop failing, the reflexes alone run the system as before.

**Amendment A19 (2026-10-25, S61; PLAN A17 step 3): the model slider.** One model setting per job (`hq/models.py`,
Settings "Models"): routing, live answers, wording fallback, extraction, materiality, web search, research notes,
company notes, the workshop's writer, the brain, the gatekeeper, cited-page fetch. Defaults by the pre-registered
protocol `docs/llm/s61_slider_protocol.md` (committed before its runs); the investor may move any. Every Claude model a job
uses goes through the governed road (`hq/llm.py`: egress, priced, capped); the local model stays where it wins until
S63 decides its fate. Fallback: a job whose model fails or is refused falls to the next model of its list.

**Amendment A20 (2026-10-25, the investor after S61's results).**
- **Answers on his data, divided:** the local 8B model for basic questions and facts (it runs tools, not insight);
  Haiku when its draft fails (his setting `answers = cascade`); questions that need judgement go to the brain with its
  tools (to wire in S62: the AI centre's Auto mode and Telegram stop sending own-data insight questions to the local
  model only, A10). **Same access for every model:** the ledger's ids go out as letter tokens ([ID-A]) and come back as
  the real ids on this PC (`hq/models.tokens`), so Haiku, Sonnet and Opus see what the local model sees, minus identity.
- **Research notes and the workshop:** left to Claude Code: Sonnet by the measurement (S61), the workshop's check by
  the other model (Opus).
- **Web search:** not measured now (2 questions ever asked); measured on his real questions once 20 exist.
- **His data plan (S63):** the stored data is filtered of identity, or erased, and collected again once the system is
  joined end to end; the system then labels every money movement itself (rent, investment, transfer, ...), asks for a
  GPay screenshot only where a label needs one, builds the knowledge graph and reads the portfolio. What is erased is
  shown to him first (his yes), like the repo's delete list.
- **Sessions:** S62 the learner and S63 the repo clean with the git-history rewrite and the data plan, in a new
  session (`docs/S62_KICKOFF_PROMPT.md`).

**Amendment A21 (2026-10-25, the investor: the system as something anyone could set up; his mailbox is cleaned).**
- **Web search is a system tool:** the brain gets a `web_search` tool (paid, priced, capped a day, the slider's `web`
  model); news keeps arriving free from GDELT and BSE as today.
- **A security agent:** watches the system itself: every request that left the PC re-checked against the egress list
  (his ids, name, address) and any hit raised at once; data flowing as it should (jobs, reconciliations, the ledger
  against Kite); the code healthy (the test suite and the repo's privacy grep on a schedule; a periodic model review of
  new code for bugs and leaks). It reports to Needs you; it never changes code or data itself.
- **Gmail (now allowed: mailbox cleaned):** read-only access to the broker's and banks' statements and contract notes,
  opened with the passwords in `secrets.toml`, through a personal-data filter: only statement attachments from known
  senders are taken, everything else in the mailbox is never read or stored, and statement text leaves the PC only
  through `redact()`. A new library is pinned and recorded in CLAUDE.md when added.
- **First run, written down:** commands for every step a new install needs (adding the keys and passwords, connecting
  Kite, the history backfill of prices and filings, retrieving statements by Gmail or drop folder, building the ledger
  and the graph), in a README. His own data is rebuilt through exactly these commands (A20), which proves them.
- **For now:** Windows and the fixed paths are assumed; making them portable is the last step.
- **Order:** S62 the learner, the brain's web search, own-data insight to the brain, the security agent; S63 the repo
  clean and the git-history rewrite (delete list first); S64 the first run (keys commands, backfill and retrieval
  commands, Gmail with its filter, his data rebuilt through them, the README).

**Amendment A22 (2026-10-25, S62; the investor's answers that day: sources both ways, everything inside the Rs 2,500 cap, the
local model wherever it can do the job, Claude decides the limits).**
- **The learner (`src/pflab/learner/`, job `learner` 22:00):** free sources only (arXiv, OpenAlex, blog feeds in
  `configs/learner.toml`, his files in `drop\learn`); the local model screens and reads, Haiku when its reply does not
  parse (slider job `learner_reading`); a claim must quote its source word for word and fit one of three coded
  templates (cross-section price signals, filing event study, calendar), parameters from closed lists; a protocol file
  with its hash and the code's hash is written before the test (the system's "committed before the run"; studies Claude
  Code runs are still git-committed); one rule for every claim (`docs/research/learner_protocol.md`, registered before
  any run). Passes become live `findings` (the brain's cached part, the `findings` tool with today's quintiles); fails get
  no live feature. Store v34 (`learn_*`, `learned`, `sec_*`).
- **The record half:** code rules with n >= 20 (Wilson intervals, bootstrap Brier); lessons go live at once; daily
  action limits, a dearer model and model-worded instruction changes (slider job `learner_proposals`, Sonnet, weekly
  after 5+ passes) are asked under Needs from you; his yes applies, his no declines; money limits are never proposed. A
  model choice by the learner sits in `pm\learned_models.toml`, below his Settings, above the measured defaults.
- **Own-data judgement to the brain (A20):** fixed word rules (`escalate.INSIGHT`) send "should I / too heavy in / what
  next" questions on his portfolio or a listed name to the brain with its tools, without the rival (a question should not
  cost twice); facts stay local, then Haiku; brain off or failing -> the old road.
- **The brain's `web_search` (A21):** an action tool, 3 a day, its own slider job `brain_web` (Sonnet: the first real
  lookup on Opus cost Rs 23.65, search results being input; Sonnet Rs 4.50), 2 searches, 6,000 output tokens, medium
  effort; the analyst's gate refuses anything personal; the Opus brain judges the cited answer.
- **Found by the security agent's first look back (fixed the same day):** the answers' system prompt named him (7 Haiku
  calls), the brain repeated his name taken from its own tool names (1 call), FD alerts named deposits by number (6
  Telegram messages). Now: the prompt says "the investor"; the tools are `tell_investor` / `ask_investor`; the brain's
  saved state and its own text are scrubbed of his name; FD alerts name bank and amount; and `hq/llm.body_check` checks
  the whole request (system prompt and earlier turns too) for his name and long ids before sending.
- **Learner protocol amendments 1-2 (before any test ran):** a claim's words must name what its test measures; a claim
  that an effect is absent is not tested. First real test (claim #13, "high-volatility stocks earn more", an Indian
  paper): FAIL in both periods (the high-volatility quintile lagged after charges), no live feature.
- **The security agent (`hq/security.py`, A21):** the egress re-check of every paid call's body and every Telegram
  message each HQ round (his ids, name, address words, an individual's PAN; a hit to Telegram and Needs from you, never
  quoting the value); daily job `security` 21:15: health failures, open reconciliation breaks, Kite against stale
  statements, the repo's privacy grep (also ledger amounts of six figures and list names in docs and tests), the test
  suite; Sundays a code review of the week's diff by the slider's `review` model (Sonnet, ~Rs 10), only after the diff
  passes the privacy grep. It reports; it never changes code or data.
- **Fallback:** preset `off` stops both jobs; the learner with no key reads with the local model alone; a failing
  source, test or check is reported and never stops the rest.

**Amendment A23 (2026-10-25, S63; the investor's answers that day).**
- **Removed** (his yes per item): finished or failed studies' runners (TimesFM 1, pairs, zone wait, S48 study, dip rule,
  early warning, Hawkes, height, market-state, S61 slider, workshop acceptance, model comparisons), QLoRA and the harness
  (not adopted), A1 readers and probes, OKF, the order stubs, the old research runner, `calc/whatif`, the theses lock,
  `fo_bhavcopy`, `corporate_actions`, `issuer_events` (its `event_id` moved to `monitor/filings`), used kickoff prompts.
  Results and protocols stay in `docs/`. The full old history is bundled on this PC (`data\backups`).
- **His name and list out of the repo:** prose says "the investor", code ids are `investor` (stored ids renamed on this PC);
  the analyst's gate reads his name from `api_budget.toml`; list companies in tests and docs replaced by invented ones;
  the security agent's privacy grep covers list symbols, names and ISINs in every file; `.githooks/pre-push` blocks a
  push with any hit.
- **Kept and wired:** TimesFM 2 (live) with its refresh path (`timesfm2_*`, `s52_unattended.ps1`); the forecast job asks
  when a refresh is due (weights missing on a fresh install: the registered S52 run rebuilds them; stale or a lost
  scoreboard: a new registered study); missing weights no longer stop turnover and margin. Collectors in the daily
  collect (insider, bulk/block deals, FPI merged into its history, macro, quarterly holdings of held and listed names);
  the graph gets deals and holdings; the brain gets `who_is_buying`, `market_context`, `growth`; the Portfolio screen shows
  the 12-month growth split; the learner gets `holder_event` (protocol amendment 3). GDELT and its BigQuery backfill stay.
- **His data:** not erased (his "not yet"). **Git:** a new private repo for the cleaned tree as one first commit (neutral
  author); the current repo renamed and kept only for `research-archive` and its tags (non-negotiable 1).
- **S64 (his requirement, 2026-10-25):** he will delete the whole project from this PC, clone the repo and rebuild
  everything from its commands: keys and passwords, Kite, every backfill run the way the data was collected here
  (prices, indices, filings, results, shareholding, deals, insider, FPI, macro, GDELT history, the panel, index
  membership), statements by Gmail or the drop folder, the ledger, the knowledge graph, the forecast environment and its
  weights, the learner, starting the system. Bank-account money movements are labelled by the system itself (as was done
  by hand in chat), asking him only where a label needs it.

**Still open**
- **Backup target**: declined by the investor on 2026-10-24 (no external drive or folder for now; he will say if he wants one).
- The 27B model (Q4): registered before evaluation in S21. Any preference?
