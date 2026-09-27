# E2-B — readiness note (2026-09-27)

E2-B (`docs/strategies/E2-B.md`, DRAFT) caps the portfolio's beta to each of
five macro shock factors at 1.5× the Nifty 500's own, skipping buys that
would breach. **All five factor series are on disk**, and the point-in-time
sector map the 2026-09-26 instruction asked for is now built. **Six lines of
the charter cannot be run as written**, and two of them change what the rule
does, not only a number.

**NOT READY TO LOCK** — §3 lists what the lock must settle.

**Change-log entries that apply** (CLAUDE.md non-negotiable 1): the
2026-09-16 draft only. The 2026-09-26 instruction to build the sector map
from the captured lists is not yet in the change log; §3(e) is where the
lock records it.

## 1. Data coverage

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

## 2. The point-in-time sector map (built)

`pflab/data/sector_map.py`, written to
`data/index_membership/sector_map.parquet`: **10,653 (capture, ISIN, industry)
rows** from the `Industry` column of every captured constituent list (Nifty
500, 100, 200, Midcap 100, 50, Next 50) — the same 72 Internet Archive
captures E1b's membership build is anchored on. The usable-from date is the
capture date. Eleven tests (`tests/test_sector_map.py`), including one that a
capture dated after M cannot change an answer at M.

### Three findings

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

## 3. What cannot be run as written

### (a) "Five, full-window" factors are three for most of development

FII flows begin 2009-12, so the FII edge exists from **2011-11**; VIX's from
**2010-03** (§6 says "from 2009"). Development's first ~3 years run with
three factors, the next ~2 with four. §3's own fallback (a missing edge
makes a name index-like) handles individual names, but with the *index*
edge missing there is no cap at all — `shock_betas.breaches` skips such a
factor, which the charter should confirm. §7's S5 ("VIX removed, full window
without gaps") is not gap-free either: FII still starts late.

An earlier FII source exists (NSDL publishes monthly FPI figures back into
the 2000s); collecting it is a source decision, not taken.

### (b) Two of the five caps are degenerate as written

`|β_portfolio(f)| ≤ 1.5 × |β_Nifty500(f)|` assumes the index has a material
beta to each factor. Measured over 2007–2021 on 36-month windows:

| factor | index beta changes sign | smallest \|β\| as a share of the median \|β\| |
|---|---|---|
| Brent | **16 times** | **0.4%** |
| US 10-year | **11 times** | **1.8%** |
| USDINR | 0 | 52% |
| VIX | 0 | 57% |
| FII | 0 | 59% |

Around each crossing the cap is close to zero, and a 25-name portfolio can
meet it only by accident. For those months the rule is not "cap the
exposure", it is "block nearly every buy". Whether that is the rule — or
whether the cap needs a floor, or those factors a different bar — is the
charter's to say; I have not added anything (non-negotiable 3).

### (c) What "a buy that would breach" means for a book already in breach

Held names are never sold for a breach (§4), so the book can drift into
breach on price moves alone. Read literally, every subsequent buy "would
breach" — including one that *reduces* the breach — and the portfolio stops
buying until prices drift back. Three readings, each a different rule:

1. skip a buy if the post-buy book breaches (literal; can freeze buying);
2. skip a buy only if it makes a breached factor worse, or creates a breach;
3. evaluate the whole planned set, then drop candidates in reverse rank
   order until no breach.

And where unspent cash goes when every candidate is skipped (E1's sleeve,
presumably — say so).

### (d) Four definitions the betas need

1. **"The factor's monthly change"**: percent change for Brent and USDINR,
   level difference for the yield (pp) and VIX (points), and the month's
   **sum** of daily net flows for FII (a flow is already a change). Built
   this way in `shock_betas.month_end_values`, as a reading to confirm.
2. **One regression per factor, or all five jointly?** §3 reads as five
   univariate slopes. Brent, USDINR and flows are correlated, so the two
   give different betas.
3. **FII flows are nominal ₹ crore**, whose scale roughly quadruples over the
   window. A beta per ₹ crore is not stable across it; scaling by market
   cap or using a z-score is a charter choice, not mine.
4. **Portfolio beta over equity holdings only, or over the whole book with
   cash at zero?** In a RISK_OFF month the two differ by the cash share.

Also: stock returns from the panel's adjusted close are price returns
(dividends are a separate cash flow in this engine), while the index beta
is estimated on Nifty 500 **TRI**. Either is defensible; one should be named.

### (e) The sector node

§3 says "current mapping applied to history — declared simplification". The
2026-09-26 instruction replaces it with the point-in-time map above. The
lock should record that and settle:

1. taxonomy: per-capture labels as published, or A harmonised to B by the
   declared crosswalk;
2. `allow_later`: whether a name with no capture on or before M takes its
   first later label (flagged approximate), given §2(iii);
3. **unmapped names under S4's 30% cap**: their own bucket (capped at 30%
   like any sector), uncapped, or ineligible for purchase while S4 binds.
   This is roughly half of development's holdings, so it decides S4.

The sector→factor edge (median member beta) is reporting only (§8); it
inherits whatever (1)–(3) say.

### (f) §8 reports the 2022 episode, which is sealed

"per-episode drawdown (2008, 2011, 2013, 2016, 2018, 2020, **2022**)".
2022 is inside the sealed period (2022–2025) and cannot be reported by a
development or validation run. §2's hypothesis also names 2022. The episode
list at lock should end at 2020.

## 4. Engine support

| E2-B line | supported? |
|---|---|
| §3 factor series, point-in-time month-end values | **built** — `signals/shock_betas.month_end_values` |
| §3 36-month betas, min 24 obs, index-like fallback | **built** — `rolling_betas`, `portfolio_beta` (7 tests, incl. lookahead) |
| §3 company→sector | **built** — `data/sector_map` (11 tests) |
| §4 skip a breaching buy **and try the next candidate by rank** | **not as written.** `hooks.pre_buy_constraint` exists, but `_execute` calls it *after* the ADV loop and a rejection just drops the order: the next candidate is never tried, contrary to the hook's own docstring. It must move inside the candidate loop, as the ADV skip does. Inert for E1, so E1's bytes need not move; a byte-identity re-run of E1 base confirms it |
| macro series through `truncate_end` | **needs code.** Non-negotiable 2: the factor series must be truncated at the period end on the same path as prices, not read raw in the hook |
| §5/§6 window, benchmarks | **yes** |
| §7 S1–S5 | **yes** once the rule exists (S4 needs §3(e)) |
| §8 per-factor portfolio vs index beta over time; skipped buys and why | **needs code** — a per-month record from the constraint |
| `classify_e2b` — GATE against the stack plus the mandate block | **needs code**, small (same shape as `classify_e2a`) |

## 5. Readiness

**Not ready to lock.** The data is complete and the two new modules are
built and tested. The lock must settle:

1. **§3(b)** — what the cap means when the index's beta is near zero
   (Brent, US 10-year). This is the one that decides whether the rule is a
   cap or a buying freeze.
2. **§3(c)** — which of the three breach readings, and where unspent cash
   goes.
3. **§3(d)** — transforms (confirm pct / diff / sum), univariate vs joint,
   FII scaling, beta over equity or whole book, price vs total return.
4. **§3(a)** — confirm that a factor with no index edge imposes no cap
   (VIX before 2010-03, FII before 2011-11), and S5's wording.
5. **§3(e)** — sector taxonomy, `allow_later`, and unmapped names under S4.
6. **§3(f)** — drop 2022 from §8's episodes.

After that the remaining build is small: the hook fix, the truncation path,
the constraint and its record, `classify_e2b`, `configs/e2b.toml` and
`sweep.e2b_rows()`.
