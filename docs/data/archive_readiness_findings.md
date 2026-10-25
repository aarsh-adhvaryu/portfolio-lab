# Data findings excerpted from research-archive readiness notes

Verbatim data sections only (copied 2026-10-06, S0; sources in `docs/MIGRATED.md`). Charter-specific "what cannot be run" sections were left out. The 2022–2025 period is spent; nothing here is out-of-sample.

## E2-B (2026-09-27): macro/factor coverage and the point-in-time sector map

### 1. Data coverage

| §3 factor | series on disk | first month-end value | first beta (24 of 36 months) |
|---|---|---|---|
| Brent crude, USD | `data/macro/BRENT.parquet` (FRED DCOILBRENTEU, from 1987) | before 2004 | **2007-01** |
| USDINR | `data/macro/USDINR.parquet` (FRED, from 1973) | before 2004 | **2007-01** |
| US 10-year yield | `data/macro/US10Y.parquet` (FRED DGS10, from 1962) | before 2004 | **2007-01** |
| India VIX | `data/indices/INDIA_VIX.parquet`, from **2008-03-03** | 2008-03 | **2010-03** |
| Net FII equity flows | `data/macro/FPI_DAILY.parquet` (NSDL daily, Equity / Sub-total), from **2009-12-01** | 2009-12 | **2011-11** |
| Nifty 500 (index beta) | `data/indices/NIFTY500_TRI.parquet`, from 2004-01-01 | — | 2007-01 |

Stock returns come from the panel (2004-01-01 onward), so a name's first
beta is 24 months after its first month-end close.

### 2. The point-in-time sector map (built)

`pflab/data/sector_map.py`, written to
`data/index_membership/sector_map.parquet`: **10,653 (capture, ISIN, industry)
rows** from the `Industry` column of every captured constituent list (Nifty
500, 100, 200, Midcap 100, 50, Next 50) — the same 72 Internet Archive
captures E1b's membership build is anchored on. The usable-from date is the
capture date. Eleven tests (`tests/test_sector_map.py`), including one that a
capture dated after M cannot change an answer at M.

#### Three findings

**(i) NSE changed taxonomy twice**, so "the sector" is three different things:

| taxonomy | captures | vocabulary |
|---|---|---|
| A | 2006-11-06 → 2013-08-18 (11 dates) | ~72 fine industries: `BANKS`, `FINANCE - HOUSING`, `TEXTILES - COTTON` |
| B | 2014-01-22 → 2021-06-15 (27 dates) | 18–20 sectors: `FINANCIAL SERVICES`, `IT`, `SERVICES` |
| C | 2022-07-28 → 2026-09-04 (17 dates) | NSE's 2023 macro sectors: `Financial Services`, `Capital Goods` |

**Validation (2017–2021) is entirely taxonomy B. Development switches from A
to B in January 2014**, so a 30%-per-sector cap (S4) would bind on
`BANKS` alone until 2013 and on all of `FINANCIAL SERVICES` after. The
crosswalk from ISINs captured on both sides (2010-01-02 → 2014-01-22) maps
A onto B with **weighted purity 0.924** (68 labels; 11 below 0.8), so
harmonising A to B is defensible; B → C is only 0.832 (`CONSUMER GOODS`
splits, purity 0.46), which matters only after the sealed period.
`sector_map.crosswalk` produces the table; nothing harmonises by default.

**(ii) Coverage of held names is low**, because E1's universe is the 500
most-traded names, not the index, and momentum buys names on their way *in*:

| E1 base, from its regression decisions | point-in-time only | also using a later capture |
|---|---|---|
| held names, development | **52.8%** | 77.2% |
| held names, validation | **69.5%** | 86.9% |
| top-200 ranked names, development | 84.0% | 94.2% |
| top-200 ranked names, validation | 93.0% | 97.2% |

Issuer matching (ISIN up to the security type, so a face-value split's new
serial still matches) is included and contributes 5.8 pp in development.
About 170 of the ISINs E1 ever held appear in **no** capture at any date.

**(iii) A later capture is lookahead in a way that matters.** The
instruction declares the map approximate before a name's first capture. The
label itself barely moves, but *having* a later capture means the name went
on to enter a big index. Under S4, a rule that caps mapped names and not
unmapped ones would treat names differently according to their future. So
`sector_at(..., allow_later=)` has **no default**: the charter chooses.

One source error, handled rather than guessed: the 2006-11-08 Nifty 500 file
lists Ramco Systems under Ramco Industries' ISIN (INE614A01010) with two
labels. That pair is dropped from that capture and reported.


## E2-D (2026-09-26): shareholding and insider data

### 1. The data is there

**Shareholding** (`data/bse_shareholding/summary.parquet`): 135,098 usable
scrip-quarters over 2,893 scrips; every one carries promoter percent and
pledged shares.

| year | scrips | all in panel | carry a filing date |
|---|---|---|---|
| 2010 | 1,851 | yes | **0%** |
| 2013 | 1,947 | yes | **0%** |
| 2015 | 2,023 | yes | 25.1% |
| 2016 | 2,036 | yes | **100%** |
| 2019 | 2,096 | yes | **100%** |
| 2021 | 2,140 | yes | **100%** |

Median promoter holding runs 54.1% (2010) to 58.8% (2021), which is the
right shape for Indian listed equity and is the sanity check that the
C1C2 parser fix held across the whole backfill.

The undated years are exactly what §4's amendment anticipated: 2010–2015
has no filing timestamp anywhere, so the charter's **second-month-end
convention** carries them. 53.9% of the 2010–2021 window is dated.

**Insider PIT** (`data/nse_insider/`): 262,283 rows over 1,726 symbols in
2016–2021, of which 261,075 carry a quantity and 260,335 a value. The limb
applies from 2016-01-01 per the amendment, and the data starts 2015-11-19,
so there is no gap at the boundary.


## E3 (2026-09-27): ETF coverage and the 2019-12-19 unit split

### 1. Data coverage

| §3 candidate | in the panel | window notes |
|---|---|---|
| LIQUIDBEES | INF732E01037, 2004-01-01 → 2026-09-16, one missing session in 2008–2021 | price pinned at ₹1,000 (999.51–1,000.88); the return is paid as daily dividend units. **No dividend rows** |
| GOLDBEES | **two ISINs**: INF732E01102 2007-03-19 → 2019-12-19, INF204KB17I5 2019-12-20 → | 10-month return defined from 2008-01; E1's first RISK_OFF month is 2008-03, so gold is available at every RISK_OFF decision. No dividend rows (gold ETFs pay none) |
| NIFTYBEES | **two ISINs**: INF732E01011 2004-01-01 → 2019-12-19, INF204KB14I2 2019-12-20 → | full window. **No dividend rows** — see §3 |

All three are typed `ETF` and excluded from E1's universe, as §3 of E3 and
E1's 2026-09-16 §15 entry intend.

E1 base is RISK_OFF in **40 of 120** development months and **11 of 60**
validation months (its regression decisions), so the sleeve exists often
enough in development for §4 to matter, and in validation it is mostly
2020.

### 2. Data error: the 2019-12-19 unit split

| | 2019-12-18 close | 2019-12-19 close | `adj_factor` | 2019-12-20 |
|---|---|---|---|---|
| NIFTYBEES | 1,292.54 | **130.20** | 1.0 | new ISIN INF204KB14I2 at 130.34 |
| GOLDBEES | 3,359.60 | **33.55** | 1.0 | new ISIN INF204KB17I5 at 33.65 |

A 1:10 split for NIFTYBEES and 1:100 for GOLDBEES (the Gadget Co → Nippon
scheme transfer). The panel's adjustment factors come from NSE's *equity*
corporate-actions feed, which does not carry ETF unit splits, so the
adjusted series show a **−89.9%** and **−99.0%** one-day fall, and the
engine would then see the old ISIN stop trading — a delisting.

Every other one-day move above 8% in the three series over 2004–2021 is a
real market day (2004-05-17, 2008-10, 2009-05-18's +14.6%, 2020-03-23).

**Why it matters here and not before:** no past result touches it — E1's
universe is stocks only and the benchmarks use index series. But E3 holds
these ETFs, and **S3 ("hold the sleeve through RISK_ON until it breaks its
own 10-month average") would very likely hold gold across December 2019**:
E1 was RISK_OFF in 2019-07/08 and gold was in an uptrend. E3-R's high gear
holds NIFTYBEES too (its decision (c) asks for exactly this check).

**The fix** (to be built with E3-R, which needs it first): a declared ETF
event table — the two splits with their factors, and the two ISIN
successions — applied to ETF rows only, on the path after
`truncate_end`. Stock rows are untouched, so E1's bytes cannot move; a
byte-identity re-run of E1 base proves it. Logged in the charter's change
log when E3 locks, per `GATE.md` ("fixed, logged, re-run from scratch").

