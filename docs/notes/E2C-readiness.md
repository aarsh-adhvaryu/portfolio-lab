# E2-C — readiness note (2026-09-27)

E2-C (`docs/strategies/E2-C.md`, DRAFT) adds a second RISK_OFF trigger to
E1's 10-month trend rule: India VIX above its trailing 3-year 90th
percentile **and** 20-session mean GDELT India tone below its trailing
3-year 10th percentile. Readiness note only, as instructed; nothing built.

**Both inputs are on disk and complete for the window.** But the finding
that matters comes first:

> **Under the plainest reading of §3, the composite adds no RISK_OFF month
> to E1's in either period.** It fires in 1 development month and 2
> validation months, and E1's own trend rule is already RISK_OFF in all
> three. CAND would equal STACK, so the verdict would be determined before
> the run. The lock should know that before it spends a sweep.

**NOT READY TO LOCK** — §3 and §4.

**Change-log entries that apply** (CLAUDE.md non-negotiable 1): the
2026-09-16 draft only.

## 1. Data coverage

| input | on disk | window coverage |
|---|---|---|
| India VIX | `data/indices/INDIA_VIX.parquet`, 2008-03-03 → 2026-09-21 | complete; one gap over 5 days (2014-10, before the window). Trailing 3-year percentile defined from 2011-03 |
| GDELT India daily aggregate | `data/gdelt/agg/*.parquet`, 2015-02-18 → 2026-09-21, 4,216 days | **one missing day in the window (2017-08-29)**; no null tone. 18 days missing in 2025-06/07, outside every window here |
| Nifty 50 (E1 §6 trend rule) | `data/indices/NIFTY50_PRICE.parquet` | complete |

The GDELT day is the UTC date of `DATEADDED` (`tools/gdelt_bigquery.sql`),
so a month-end's tone includes events published up to 05:29 IST the next
morning — before the 09:15 open at which E1 executes. Point-in-time holds
for execution, though the value is not known at the month-end *close*.

**Source drift worth declaring:** the median number of India events a day
falls from 10,944 (2016) to 5,642 (2021), while mean tone stays between
−1.98 and −2.42. The tone is an unweighted mean over a shrinking and
changing set of sources; a trailing percentile partly absorbs a level
shift, not a change in what the series measures.

## 2. What the data can and cannot support

### (a) The tone percentile does not exist for most of development

Tone starts 2015-02-18, so its trailing 3-year percentile first exists in
**2018-03**. Development is 2015-03 → 2019-12: the composite is defined in
**22 of 58 development months**, all of them in the last 22. §5 already
says the window "cannot support a statistical claim"; this is sharper — for
three years of development the composite has no value at all.

E3-R's 2026-09-27 decision (a) — *an undefined signal counts as not
firing* — is the obvious precedent, and it is the reading used for the
count below. It was made for E3-R, so E2-C's lock must adopt it (or not)
explicitly. The alternatives change the development question entirely: a
shorter or expanding percentile window, or a development start of 2018-03
(22 months).

### (b) The composite adds nothing, as I read §3

Reading used — each stated because each is a choice §3 does not make:
percentiles over the **daily** series in the trailing 3 calendar years,
current value included; "20-session" = the last 20 NSE sessions' GDELT
daily tone (minimum 15 present); undefined = not firing.

| | months | composite defined | VIX limb fires | tone limb fires | **both** | E1 trend rule RISK_OFF |
|---|---|---|---|---|---|---|
| development 2015-03 → 2019-12 | 58 | 22 | 5 | 3 | **1** (2019-02) | 18 |
| validation 2020-01 → 2021-12 | 24 | 24 | 5 | 3 | **2** (2020-03, 2020-04) | 5 |

E1's own recorded decisions (`experiments/E1/regression/*/rows/base/
decisions.json`) are RISK_OFF on 2019-02-28, 2020-03-31 and 2020-04-30.
**Incremental RISK_OFF months: zero in both periods.**

Only signal months were counted; no return was computed. I have **not**
tried other readings to find one that fires more: that would be choosing
the rule by what it does. Readings that would differ — month-end samples
(36 observations) instead of daily ones, current value excluded, calendar
rather than session windows — are listed in §3 for the lock to settle on
their merits.

Why it happens is not mysterious: VIX at a 3-year high and tone at a 3-year
low are both crash-*during* signals, and by the month-end a crash is deep
enough to have broken the 10-month average too. The charter's hypothesis
(§2) is that stress shows *before* the average breaks; at monthly
resolution, on these thresholds, it does not.

## 3. Lines the lock must settle

1. **Undefined signals** — adopt E3-R's "undefined = not firing", or change
   the percentile window, or start development at 2018-03.
2. **Percentile sample** — daily values or month-end values over the
   trailing 3 years; current value included or not.
3. **"20-session mean"** — NSE sessions (GDELT's weekend days dropped) or 20
   calendar days of GDELT; and the minimum present when a day is missing
   (2017-08-29).
4. **Whether to run at all given §2(b).** If CAND is STACK, the sweep's base
   row is a re-run of E1 on a new window and every §7 row except those that
   loosen the thresholds (S1 85/15, S3 VIX-only) is also likely identical.
   A verdict computed from that is honest but uninformative. I would not
   pre-judge the rows; the lock can decide to run it as a recorded null, or
   to set it aside with this note as the reason.
5. **§6's exception, made operational:**
   - "MaxDD improves in both periods (G1 on drawdown)" — the ≥ 2 pp bar of
     G1, or any improvement? The parenthesis says the former; confirm.
   - Do G3 (two thirds of rows) and G4 (turnover) still apply? §6 lists
     neither.
   - "Switches per year" — count of transitions in either direction ÷ years
     in the period; confirm.
   - Aarsh's paragraph is an input `classify` cannot compute. It should
     report the numeric conditions and "adoption pending paragraph".

## 4. What would need building (not built)

| piece | size |
|---|---|
| `signals/event_regime.py` — VIX and tone percentile flags, point-in-time, undefined explicit | small |
| engine: OR a second boolean into `_risk_off_series` behind a config flag | small; inert for E1, byte-identity re-run of E1 base |
| GDELT and VIX through `truncate_end` (non-negotiable 2) | small |
| `classify_e2c` with §6's exception and a pending-paragraph state | small |
| `configs/e2c.toml`, `sweep.e2c_rows()` | small |
| E1 base (STACK) re-run on 2015-03 → 2019-12 and 2020 → 2021 | a sweep; Aarsh's to run |

## 5. Readiness

**Not ready to lock.** The data is complete. The blocker is §2(b): as I
read it the rule never acts, and the lock should decide whether that is the
experiment (a recorded null) or whether §3's readings, settled on their
merits and not on firing counts, say otherwise.
