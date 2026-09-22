# HANDOFF — 2026-09-22

Written at session close for whoever picks this up next. Everything here is
state, not opinion. Where something is unknown or unfinished it says so.

`pytest -q` at close: **437 passed, 0 failed.**

## Start here (2026-09-22)

1. **E1b re-run is DONE: INCONCLUSIVE** (was REJECT), recorded in
   `docs/reviews/E1b-verdict-rerun.md`. **The BSE backfill may still be
   running** in Aarsh's terminals (two ranges, §5/§9): check with
   `python tools/backfill_bse.py --check 2010-01-01 2026-09-21` and resume
   with the §9 commands if it stopped.
2. **Measurement correction of 2026-09-21 (E1 §15):** buys are sized net of
   costs instead of being skipped when costs don't fit, and expense drag
   compounds by calendar days; B3 and B5 both carry 0.30% a year. **The
   stack is now read from `experiments/E1/regression/`** (E1 base re-run
   under the correction): development **8.97% / 55.40%**, validation
   **27.36% / 39.82%**. Every stored number that moved is in
   `docs/STATE.md`.
3. **Repo:** github.com/aarsh-adhvaryu/portfolio_system (PRIVATE), branch
   `master`. A fresh clone passes all 425 tests. Until 2026-09-22 the
   unanchored `data/` in `.gitignore` also hid `src/pflab/data/` and
   `docs/data/`, so they had never been committed; the pattern is now
   `/data/`. Never re-widen it.
4. **Next experiment: E1d** (`docs/strategies/E1d.md`, draft). Four small
   code pieces before its first run: `docs/notes/E1d-readiness.md`. E1b is
   classified, so the code is free to change.

## 2026-09-19 session, in one paragraph

`PFLAB_DATA_DIR` is now set explicitly (CLAUDE.md "Repo layout"). Both E1b
sweeps were re-run with the corrected equity/cash decomposition and with
per-row equity curves, trade ledgers and decision records persisted; **every
row reproduced to within 1e-12, so E1b's REJECT is untouched.** E1c was
slotted after E1-P in `ROADMAP.md` and `GATE.md`, and E1b's S7 (sell-to-cash
during RISK_OFF) was added to E3 §7 as S6. **E1-P is finished** — §3's rule,
N1/N2, the sweep rows, the GATE wrapper and both missing §7 extras — and
**E1c is prepped** — the volatility-scaled 6+12 score, semi-annual rebalance,
capped score-tilted weights and eleven rows. Neither has been run; both wait
on Aarsh's lock, and each has a readiness note listing exactly what the lock
must settle. Sealed period untouched; `research/journal.jsonl` still absent.

**2026-09-19 — repo consolidated; paths in this file are current.** The
repository root is now `D:\portfolio_lab`. Previously the code sat two levels
down in `portfolio-lab/portfolio-lab/` while the charters, ROADMAP and GATE
also existed as separate top-level copies outside version control, so an edit
could land on the copy that was not law. Everything is now single-copy inside
the repo: charters and `GATE.md` in `docs/strategies/`, `docs/ROADMAP.md`, and
the superseded 2026-09-16 pre-lock E1 draft in `docs/archive/` clearly marked
as not law. E1 §2–§13 and E1b §3–§7 were verified byte-identical to commit
`0ae301e` through the move, and `pytest -q` re-ran green (362) from the new
root. See CLAUDE.md "Repo layout".

---

## 1. Current stack and every verdict so far

**The adopted stack is E1 base.** Nothing has replaced it.

### E1 — INCONCLUSIVE (2026-09-17)

Charter LOCKED 2026-09-17. Sweeps in `experiments/E1/sweeps/`.

| | development 2007–2016 | validation 2017–2021 |
|---|---|---|
| base CAGR (after tax, liquidation-adjusted) | 9.34% | 26.12% |
| base MaxDD | 55.38% | 39.55% |
| turnover/yr | 1.6952 | 1.3131 |
| B2 (Nifty 500 TRI) | 8.07% | 14.79% |
| B3 (Nifty 200 Momentum 30 TRI, 0.3% drag) | 13.48% | 20.25% |

§13 arithmetic: C1 (≥2 pp over B2) failed in development (+1.27 pp), passed
in validation. C2 (≥2 pp over B3) failed in both. Verdict INCONCLUSIVE
because C1 did not fail in *both* periods, which is what REJECT requires.

Diagnostic at `docs/notes/E1-diagnostic.md`, including the 2026-09-17
correction: finding 6 (under-diversification as capital grows) is **not**
supported by the validation extras — names held recovered to 17.7–29.2 in
2017–2021. Finding 3 (universe rank 240–340 in both periods) stands.

### E1b — REJECT (2026-09-18)

Charter LOCKED 2026-09-18. Verdict at
`experiments/E1b/sweeps/validation-4eaf560fb1319d16/verdict.json`.

GATE vs E1 base:

| period | G1 | G2 | G3 | G4 | CAGR gap | MaxDD gap | rows holding | turnover |
|---|---|---|---|---|---|---|---|---|
| development | ✗ | ✓ | ✗ | ✓ | +0.13 pp | −0.70 pp | 5/14 | 1.16 vs 1.70 |
| validation | ✗ | **✗** | ✗ | ✓ | **−10.73 pp** | **+4.02 pp** | 0/14 | 1.00 vs 1.31 |

REJECT because G1 fails in both periods **and** G2 (do no harm) is violated
in validation.

E1 §13 C1–C4, reported because E1b was a candidate base: C1 fails both
(+1.40, +0.59 pp over B2); C2 fails both (−4.01, −4.87 pp vs B3); C3 passes
development, fails validation (+5.65 pp); C4 **0 of 14 rows** in both.
Verdict REJECT.

E1b base: development 9.47% / 54.67%, validation 15.38% / 43.58%.

**What it means.** E1b confined E1's rules to the Nifty 200. In development
that changed almost nothing (+0.13 pp). In validation it cost **10.7 pp**.
E1's 26.12% in 2017–21 came from holding small caps *outside* the Nifty 200
during a small-cap boom. The diagnostic's "universe drift to rank 240–340"
was not a defect to correct — it was where the money came from. E1b is
mechanically healthy (zero ADV skips in validation, turnover 1.00, 24–32
names held, median turnover rank 100–122, no delistings) and simply earns
less.

Development review at `docs/reviews/E1b-development.md`.

**Both sweeps re-run 2026-09-19** with decomposition v3 and persisted
artifacts: `development-1996387124c166df` and `validation-14c240592c8fc806`.
**All fourteen rows and all four benchmarks reproduced to within 1e-12 in
both periods**, so every number above stands and the REJECT is untouched.
The originals (`development-26b23d4fbc273fea`,
`validation-4eaf560fb1319d16`) were NOT overwritten — the run id now carries
a source fingerprint, so changed code lands in a new directory. The verdict
still lives in the original validation directory.

---

## 2. Built and tested vs stubbed

**Built, tested, used in a real run:**
`tax/india_lots.py`, `execution/costs.py`, `eval/periods.py` (incl.
`truncate_end`, `truncate_membership`, seal + journal), `eval/metrics.py`,
`eval/artifacts.py`, `eval/sweep.py`, `eval/classify.py` (§13 C1–C5 and
GATE G1–G4), `signals/momentum.py`, `portfolio/crash_rule.py`,
`portfolio/construct.py`, `backtest/engine.py`, `backtest/hooks.py`,
`backtest/runner.py`, `data/` — `bhavcopy`, `panel`, `universe`,
`instruments`, `symbol_isin`, `indices`, `calendar`, `corporate_actions`,
`nse_corporate_actions`, `dividends`, `red_flags`, and this session's
`index_changes`, `index_captures`, `index_membership`, `name_map`.

**Stubs raising `NotImplementedError` (only these two):**
`execution/paper.py`, `execution/kite.py`. Both are Phase 4, on ADVANCE
only, and nothing has ADVANCED.

**Collectors written but not exercised at scale:** `bse_announcements.py`
(works; only 2026 collected), `gdelt.py` (works; 4 files).

---

## 3. E1-P — REJECT (2026-09-21)

LOCKED 2026-09-19; both sweeps run on the same code (`source_sha
a3945e6f1bb5b64c`). Verdict computed by `classify.classify_e1p` and written to
`experiments/E1-P/sweeps/validation-708202782ce1ef66/verdict.json`. Verdict
note: **`docs/reviews/E1-P-verdict.md`**; development review (Aarsh's):
`docs/reviews/E1-P-development.md`.

| period | G1 | G2 | G3 | G4 | CAGR gap | MaxDD gap |
|---|---|---|---|---|---|---|
| development | ✗ | ✓ | ✗ (1/6) | ✓ | +0.006 pp | +0.007 pp |
| validation | ✗ | **✗** | ✗ (0/6) | ✓ | **−1.04 pp** | **+3.02 pp** |

REJECT: G1 fails in both periods; G2 also violated in validation.

- The tax saving was not stable (0.24 pp in development, 0.06 pp in
  validation); the return cost was (0.23 pp, then 1.10 pp).
- §7 extra 1 has the same sign in both periods: deferred names underperform
  the names sold at the same month-end (−10.80 pp, −7.33 pp).
- **N1 (stop-loss) did not survive validation**: −4.74 pp against base, and
  the names it sold rose 9.5% afterwards. "If not, it was 2008" — it was.
- N2 (profit-take) was expensive in both periods.

**The stack stays E1 base.**

## 4. E1c — REJECT (2026-09-21)

Verdict computed by `classify.classify_e1c`, written to
`experiments/E1c/sweeps/validation-d1bff14844336e54/verdict.json`; note
**`docs/reviews/E1c-verdict.md`**. Both sweeps on frozen code
`455f61c0803632f2`; the development re-run reproduced all 13 rows exactly.

- **GATE: REJECT** — G2 violated in both periods (−2.54 pp / +14.81 pp
  deeper; then −6.02 pp).
- **C1–C4: INCONCLUSIVE.** **Mandate: not met** (§3 fails in development,
  §5 fails in both, with or without a B5 drag).
- **§6:** the fund's construction as a taxed SIP keeps about half of B3 in
  development (−6.68 pp) and nearly all of it in validation (−0.15 pp). C2
  is not restated. Weighting is worth 1–3 pp a year with no stable sign.
- Held in both periods: E1's raw 12-1 signal costs about 5 pp a year on the
  fund's cadence; E1's monthly band earns 1–2.5 pp over semi-annual.

**Open measurement flaw, not fixed** (E1 §5 buy sizing, Aarsh's call): a
benchmark buy that uses all its cash is skipped when costs don't fit, by
rupee rounding. Development B5 is overstated by 1.23 pp (15.37% should read
about 14.14%), B3 by 0.15 pp; nothing else moves and no verdict depends on
it. The benchmark expense drag also compounds per session over 365, so
B3's 0.30% applies as about 0.21%.

## 5. Background backfills — state at 2026-09-22 13:35 IST

**BSE announcements 2010 → 2026-09-21 (E2-A's input): RUNNING, not complete.**

- Two workers, `tools/backfill_bse.py`, logs `data/_bse/progress_r1.jsonl`
  (2010–2019) and `progress_r2.jsonl` (2020 → yesterday). Idempotent and
  resumable: re-run the same command to continue. Completeness:
  `python tools/backfill_bse.py --check 2010-01-01 2026-09-21`.
- **A first attempt (four workers, 11:49) wrote 529 blank day files** — BSE
  answered throttled requests with one all-null row, and the collector
  saved it as the day. Found by row-count checks, workers stopped at 13:25.
  **Fixed:** `bse_announcements.fetch_day` now keeps a day only if its
  unique announcements equal the API's own `Table1.ROWCNT` (verified: 1,239
  of 1,239 on 2025-07-15) and raises `IncompleteDay` otherwise; a genuinely
  empty day reports ROWCNT 0. A ledger (`_verified.txt`) records every day
  known good: written by the checked collector, or re-checked against the
  API's count. Each pass re-checks the rest and re-fetches any that fail, so
  a throttled answer to a check only delays it; passes after the first wait
  10, 20, 30… minutes. Tests: `tests/test_bse_collector.py`.
- **Throttling recurs.** At 13:40 BSE again answered without the count;
  those days were refused, not written, and wait for the next pass. If it
  persists, run one range at a time.
- **State at hand-over (13:50): workers STOPPED** so Aarsh can run them in
  his own terminals (§9 item 2).
- Expected run time from here: **about 12–14 hours of fetching** across
  the two ranges in parallel, longer if BSE throttles and the retry passes
  wait. Days average ~500–1,000 announcements (peaks ~4,000), ~2 s a page
  of 50; the 2020-onward range is the long pole.

**Collected by code 2026-09-22 (no Aarsh action needed):**

| item | file(s) | coverage | source, module |
|---|---|---|---|
| India VIX | `data/indices/INDIA_VIX.parquet` | 2008-03-03 → 2026-09-21, 4,586 sessions | NSE `historicalOR/vixhistory` (monthly: it caps answers at 70 rows, serves from 2010-07-19) + Yahoo `^INDIAVIX` only before that; overlap 3,971 days agree to median 0.0025 pt. `pflab/data/india_vix.py` |
| Brent, USDINR, US 10y | `data/macro/{BRENT,USDINR,US10Y}.parquet` | 1987 / 1973 / 1962 → mid-Sep 2026 | FRED `fredgraph.csv` (DCOILBRENTEU, DEXINUS, DGS10). NY-close prints: a month-end decision should read the previous day's. `pflab/data/macro.py` |
| FPI (FII) daily flows | `data/macro/FPI_DAILY.parquet` | 2009-12-01 → 2026-09-22, 4,049 report dates, 202 months, none failed; annual equity sums match published FPI totals | NSDL archive form, one post per month; keyed on custodian **report date** (covers trades up to the previous session). `pflab/data/fpi_flows.py` |
| GDELT India daily aggregate | `data/gdelt/agg/*.parquet` (4,216 day files) | 2015-02-18 → 2026-09-21; **18 days absent in GDELT itself** (2017-08-29, and 17 days from 2025-06-15), BigQuery has no rows for them either | Aarsh ran `tools/gdelt_bigquery.sql` 2026-09-22 (daily aggregate, keyed on DATEADDED); `tools/ingest_gdelt_backfill.py` loaded it (provenance `data/gdelt/backfill/_ingest.json`). **Collector fix:** `gdelt.py` now fetches the translingual feed as well as English (BigQuery holds both); English-only had undercounted by ~15%. Re-collected 2026-09-14/15 match BigQuery on every field |
| World markets (Yahoo) | `data/global/*.parquet`, 30 series | S&P 500, Nasdaq, Nikkei from 1970-71; FTSE, DAX, Hang Seng, CAC, ASX, Bovespa, KOSPI, Shanghai, TAIEX 1984-97; US VIX 1990; MOVE, EEM, LQD, TLT 2002-03; HYG, STOXX 50, Brent futures 2007; gold, silver, copper, WTI, gas, wheat 2000; dollar index, US 10y 1970-71; bitcoin 2014 | `pflab/data/global_markets.py`. Dates are the exchange's local date. **Point-in-time:** Asia closes before the NSE (day M usable at M); Europe, US, Brazil close after (use M-1). Cross-checked against FRED: VIX identical on 9,246 days, Nasdaq median difference 0 |
| More FRED (`macro.py`) | `data/macro/*.parquet`, 23 series | US VIX, WTI, broad dollar, 10y-2y and 10y-3m curves, fed funds, TED spread (ends 2022), Nasdaq, 30y mortgage, CNY/JPY/EUR; **REVISED (latest vintage only, not point-in-time):** St Louis stress, NFCI, Case-Shiller, housing starts, mortgage delinquency, unemployment, jobless claims, copper monthly | Revised series are for explanation; deciding on one needs ALFRED vintages (free FRED API key). ICE credit spreads skipped: FRED serves only 3 years; HYG/LQD stand in |
| GDELT world by country | `tools/gdelt_world_bigquery.sql` → `data/gdelt/world_backfill/`, `python tools/ingest_gdelt_world.py` | **waiting on Aarsh** (BigQuery, ~1M rows, save via Google Drive) | |
| GDELT 1.0 India 1979–2015 | `tools/gdelt_v1_bigquery.sql` → `data/gdelt/v1_backfill/` | **waiting on Aarsh**; inspection only, not point-in-time before 2013 | |
| 23 sector indices, price + TRI | `data/indices/SECTOR_*_{PRICE,TRI}.parquet` (46 files) | 2004-01-01 → 2026-09-22 for most; Private Bank, Healthcare, Oil & Gas, Consumer Durables, Chemicals from 2005-04; Media 2005-12; Consumption 2006-01; Realty 2006-12; CPSE 2009-01 | niftyindices, `indices.SECTOR_SERIES` / `collect_sectors()`; not in `SERIES`, so `collect_all()` and the engine are unchanged. Which sectors, and price or TRI, is E1-S's charter to choose |

Re-run any of them: `india_vix.collect()`, `macro.collect()`,
`fpi_flows.collect()`, `indices.collect_sectors()` — each rewrites its files
whole. Not yet in `tools/collect_daily.py`.

**Everything else, unchanged since 2026-09-18 — needs Aarsh:**

| item | state | what it needs |
|---|---|---|
| Shareholding patterns | not started, no module | source decision (E2-D) |
| Point-in-time fundamentals | not started, no module | source decision |
| ETF dividends | not started (`data/dividends/` is equity dividends) | source decision (E3) |

## 6. Index-membership build

Built this session and **passing its gate**. Full write-up:
`docs/data/index_membership_finding.md`.

**Sources.** NSE's F&O "Change in the Constituents of Indices" circulars are
the *wrong* source — Nifty 200 appears in **zero** of all 98, because those
circulars exist to move F&O contracts and Nifty 200 has no derivatives. The
right source is NSE Indices' press-release archive
(`niftyindices.com/Press_Release/`), **1,486 releases 1998–2026**, plus
**72 Internet Archive captures** of the constituent CSVs (69 parsed) used as
anchors.

**State:** 4,203 changes parsed. Exact-list check — **Nifty 200 4/4, Nifty
100 21/21, Midcap 100 10/10, Nifty 500 13/14** (one miss: 2006-11-08,
`INE588A01016` absent, nothing invented). Nifty 100 = Nifty 50 + Next 50 on
the one date all three were captured. **The build exits zero.**

**Re-run:**

    python tools/build_index_membership.py --download   # network, ~20 min
    python tools/build_index_membership.py --parse      # PDFs -> changes, ~20 min
    python tools/build_index_membership.py --captures   # Internet Archive
    python tools/build_index_membership.py --build      # changes -> tables, ~1 min
    python tools/build_index_membership.py --all

Stages are separate and cached; only `--download` and `--captures` touch the
network. `--build` exits non-zero while the exact-list check fails, and the
fix is always more coverage, never a looser check.

**Key finding that shaped E1b §3/§4:** NSE's methodology says Nifty 200 is
"constituents forming part of Nifty 100 and Nifty Midcap 100" — but that is
written in the present tense. The captures show the two parents **overlapped
by 27 names in 2010 and 32 in 2014, and were disjoint only by 2026**. The
union identity became true at the 2016 restructure. So Nifty 200 membership
is published and exact from **2012-01-01**; before that E1b used a declared
**proxy** universe, labelled as such per month-end in the manifest.

---

## 7. Charter and doc lines added, by session

### 2026-09-19

**No §15 line was added to any LOCKED charter.** E1 §2–§13 and E1b §3–§7 were
re-verified byte-identical to `0ae301e` at the close, and neither file was
modified at all.

Changes landed only in DRAFT documents and in the map:
- `docs/strategies/E3.md` §7 — **S6 added** (sell-to-cash during RISK_OFF,
  E1/E1b's S7), on Aarsh's instruction, with two consequences declared and a
  §10 change-log line. E3 is DRAFT, so §7 is not law.
- `docs/ROADMAP.md` — order change **E1c after E1-P**, with the reasoning;
  E1b's entry corrected from "BLOCKED on data" to its REJECT verdict; an E1c
  section added; a broken link to the E1 diagnostic fixed.
- `docs/strategies/GATE.md` — order line corrected. It had carried the
  **pre-2026-09-18** order "E1, E1b, E1-P" since the swap, i.e. it was stale
  against ROADMAP for a day. Now E1, E1-P, E1c, with an "Order, and how it
  has changed" section so a stale copy is recognisable as stale.
- `CLAUDE.md` — `PFLAB_DATA_DIR` made explicit and documented; state section
  refreshed.
- New: `docs/notes/E1P-readiness.md`, `docs/notes/E1c-readiness.md`.

### 2026-09-18

**E1's §15 was NOT touched this session.** E1 §2–§13 are untouched since the
2026-09-17 LOCKED line.

E1b (`docs/strategies/E1b.md`, §10 change log), all dated **2026-09-18**:
- **LOCKED. No changes to §3–§7 after this line.**
- §3/§4 (draft, pre-lock): universe is Nifty 200 from 2012-01-01 and a
  declared proxy (CNX 100 ∪ CNX Midcap, point-in-time) for 2007–2011.
  Development stays 2007–2016, validation 2017–2021, with Aarsh's reasoning
  recorded: *the years being removed are the years the hypothesis is about.*
- §6 (draft): **S13** added — development restricted to 2012–2016 with E1
  base re-run on the same window.
- §6 (draft): **S12 revised** — no longer drops guessed-window names; places
  each guessed start at the latest possible date so base and S12 bracket the
  truth.
- §6 (draft): S12 originally added (superseded by the line above).

`CLAUDE.md` rule 7, 2026-09-18: **`pypdf` added** to the
allowed dependencies for the NSE constituent-change circulars, with
**`pdfplumber` as a named fallback**, permitted only for a circular whose
tables pypdf returns garbled. Declared in `pyproject.toml`.

`docs/ROADMAP.md`, 2026-09-18: order changed to **E1, E1-P, E1b,
E2-A, …** with the reason, the re-run-on-adoption rule, and E1b's
three-working-day time-box (which closed on time).

E1c `docs/strategies/E1c.md` §9: draft, 2026-09-18, written by Aarsh.

---

## 8. Open questions I was not comfortable resolving alone

1. ~~**The invested-equity metric took three attempts…**~~ **RESOLVED
   2026-09-19.** Version 3 shipped and both E1b sweeps were re-run on it.
   The base row reconciles: equity 8.67 pp + cash 1.38 pp = 10.05 against
   10.20% pre-tax (development). The corrected table is in
   `docs/reviews/E1b-development.md`; the version-2 `Invested equity alone`
   table survives only in the two ORIGINAL sweep directories and should still
   be ignored there.
2. ~~**`write_summary` overwrites unconditionally.**~~ **RESOLVED
   2026-09-19**, and the underlying hole was worse than described. A sweep
   now writes a `manifest.json` and **refuses** to overwrite a directory
   whose config, data, code or rows differ (`sweep.SweepConflict`).
   Separately, `run_id` hashed only `git rev-parse HEAD`, so **two different
   working trees at the same commit produced the same run id** — which is
   every session in progress. `artifacts.source_fingerprint()` now hashes
   every `.py` under `src/pflab` and `tools`, and `code_identity()` appends
   it whenever the tree is dirty, so changed code lands in a new directory
   instead of on top of the old one. Principle 9 says a run's identity is the
   hash of its config, data **and code**; it now is.
3. **Momentum-30 overlap (E1b §8) is unavailable and always will be for
   2007–2016.** The Internet Archive has that list only from 2021 and the
   index launched in the 2020s with back-computed levels. Measuring against
   today's 30 names would be a survivorship artefact, so the extras report a
   sentence. Whether that is acceptable for E1c (which replicates the fund)
   is Aarsh's call.
4. **The membership bracket may be wider than anything E1b could measure.**
   In development, base 9.47% vs S12 11.61% — a 2.14 pp spread from
   inclusion-date timing alone. E1b's REJECT rests on validation's −10.73 pp,
   far outside that, so the verdict is safe. But no *small* effect is
   measurable on the 2007–2011 proxy years.
5. **Whether E1's §13 C2 bar is honest at all.** E1c §6 exists to test this.
   If B3's 13.48% / 20.25% does not survive real trading and tax, then C2
   has been failing every experiment against an unbuyable number. I did not
   act on this; it is E1c's job.
6. ~~**E1c's S7 into E3 §7**~~ **RESOLVED 2026-09-19, with a correction.**
   The instruction was for **E1b's** S7 (sell-to-cash during RISK_OFF), not
   E1c's S7 (costs ×2) as this file previously said. E1b's S7 is the one that
   belongs in a charter about where RISK_OFF money goes. Added to E3 §7 as
   **S6**, with its two consequences declared (the sleeve carries realised
   equity gains, so §5's tax module sees a far larger flow; and re-entry is
   capped at six names a month, so a liquidated book takes months to
   rebuild). E3 is DRAFT, so §7 is not law yet. E1c's S7 stays costs ×2.
7. **Nifty 500's membership table is much weaker than Nifty 200's** (56% of
   names have a guessed window; `carry_back` median 676 d,
   `inferred_start` median 1,150 d). E1b's S10 used it. Any future row that
   leans on Nifty 500 membership should be read with that in mind.

---

## 9. The exact next tasks, in order

**1. E1b re-run — DONE 2026-09-22: INCONCLUSIVE** (`docs/reviews/E1b-verdict-rerun.md`).

**2. BSE backfill to completion** (§5). Resume, one terminal per range:

    python tools/backfill_bse.py 2010-01-01 2019-12-31 data/_bse/progress_r1.jsonl
    python tools/backfill_bse.py 2020-01-01 2026-09-21 data/_bse/progress_r2.jsonl

Resumable: stop with Ctrl+C at any time and re-run the same command. Every
pass re-checks days not yet in the verified ledger
(`data/bse_announcements/_verified.txt`) and re-fetches any that fail; the
job ends when nothing is missing and nothing is unverified. Never run two
copies of one range at once.

**3. E1d build, lock, run** (`docs/notes/E1d-readiness.md`).

**4. E3-R**, then **E2-A as soon as the BSE data is complete**, then the
rest (`docs/ROADMAP.md`).

**5. Data sources Aarsh owes** (§5): decisions on
shareholding and fundamentals. GDELT, India VIX, Brent/USDINR/US 10y, FPI flows and
sector indices were collected by code on 2026-09-22 (§5).

### Two notes for whoever runs a sweep next

- **Sweeps now persist per-row artifacts** under `rows/<row>/`:
  `equity.parquet`, `trades.parquet` and `decisions.json`, plus the four
  benchmarks. No future extra should ever need a re-run to recover a curve
  the run already had — three sweeps were lost to exactly that on
  2026-09-18. The two E1b directories re-run on 2026-09-19 carry curves and
  ledgers; `decisions.json` was added a few hours later, so they do not have
  it, and nothing E1b still needs reads it.
- **A sweep now refuses to overwrite a different run.** If you get a
  `SweepConflict`, the inputs genuinely differ — do not force it; look at
  what changed.

## 10. Seal

**The sealed period (2022–2025) has never been opened.**
`research/journal.jsonl` does not exist, which is the proof:
`periods.open_period` creates and appends to it only on a reveal, and only a
sealed period can trigger one. Zero reveal lines.

Re-verified at the 2026-09-19 close. Every run this session used
`development` or `validation`, both unsealed: two E1b sweeps and one single
E1 base run for the byte-identity check. Nothing under `experiments/*/sealed*`
was read or written.
