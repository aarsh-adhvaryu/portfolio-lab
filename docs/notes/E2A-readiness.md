# E2-A — readiness note (2026-09-25)

E2-A (`docs/strategies/E2-A.md`, DRAFT) is E1 with one change: a name
carrying a frozen red flag in the trailing 12 months is ineligible, and a
held name that receives one is sold at the next open.

**NOT RUN. Stopped for Aarsh's lock.** One finding below is serious enough
that the charter should probably move before it runs — §5, the window.

**Change-log entries that apply** (CLAUDE.md non-negotiable 1): E2-A §3 and
§7 as amended 2026-09-24 (draft, not locked) — the point-in-time key is
`DissemDT` where present and `NEWS_DT` otherwise, with the after-15:30 rule
applying to either, and S13 was added.

---

## 1. Data: the announcement feed joined to the panel

BSE announcements 2010-01-01 → 2026-09-22, 6,109 of 6,109 days verified
against the API's own `ROWCNT`. Joined to panel ISINs through
`data/bse_scrip_isin/map.parquet` (date-ranged, per CLAUDE.md rule 8).

| year | announcements | scrips | scrip→ISIN | →panel ISIN | announcements about panel names |
|---|---|---|---|---|---|
| 2010 | 81,457 | 4,156 | 99.4% | 44.8% | 65.5% |
| 2011 | 86,360 | 4,294 | 99.6% | 44.9% | 67.3% |
| 2012 | 90,637 | 4,357 | 99.5% | 45.1% | 66.7% |
| 2013 | 98,927 | 4,352 | 99.6% | 45.3% | 67.3% |
| 2014 | 118,126 | 4,466 | 99.6% | 44.3% | 63.8% |
| 2015 | 122,502 | 4,621 | 99.6% | 43.9% | 60.3% |
| 2016 | 149,105 | 4,690 | 99.7% | 44.2% | 58.4% |
| 2017 | 209,969 | 4,711 | 99.7% | 45.0% | 57.1% |
| 2018 | 219,210 | 4,739 | 99.7% | 45.2% | 58.1% |
| 2019 | 280,621 | 4,584 | 99.8% | 46.5% | 59.7% |
| 2020 | 278,976 | 4,511 | 99.7% | 47.2% | 59.2% |
| 2021 | 286,680 | 4,545 | 99.7% | 48.1% | 60.4% |
| 2022–2026 | 298k–343k | 4,557–5,258 | 94.2–99.6% | 47.3–49.8% | 62.2–64.0% |

**The join is sound.** 99.1–99.8% of scrip codes resolve to an ISIN in every
year but 2025 (94.2%, new listings the master has not caught up with).

**Only ~45% of BSE filers are in the panel**, and that is correct, not a
defect: BSE lists roughly 4,700 filing companies, the NSE-derived panel
holds 1,500–2,900 tradeable equities, and a name the strategy cannot buy
does not need a flag.

### Unresolved names, for Aarsh's review

362 scrip codes never resolve to any ISIN. **The largest are InvITs and
REITs**, which have no equity ISIN because they are not equities — correct
behaviour, not a gap:

| scrip | name | first seen | announcements |
|---|---|---|---|
| 540565 | IndiGrid Infrastructure Trust | 2017 | 930 |
| 542602 | Embassy Office Parks REIT | 2019 | 905 |
| 543217 | Mindspace Business Parks REIT | 2020 | 697 |
| 540526 | IRB InvIT Fund | 2017 | 600 |
| 543261 | Brookfield India Real Estate Trust | 2021 | 586 |
| 541300 | INTERISE TRUST | 2018 | 525 |
| 543385 | National Highways Infra Trust | 2021 | 443 |
| 543913 | Nexus Select Trust | 2023 | 442 |
| 523031 | A D S Diagnostics Ltd | 2015 | 321 |

By year first seen: 13 in 2015, 2–5 a year to 2023, then 26 in 2024 and
**275 in 2025** — almost all recent listings and trusts. Only one
(A D S Diagnostics) looks like an equity the map should have resolved.
Full list: `bse_scrip_isin.unresolved_by_year()`.

## 2. The frozen red-flag rules

`src/pflab/data/red_flags.py`, **freeze commit `77abb08`** (2026-09-22),
source SHA-256 `5bf5e683f84f7778ec2b5e661c7b96bb…`, 5,096 chars.

`RULES` holds exactly the nine flags E2-A §4 names, and no others:
`INSOLVENCY`, `REGULATORY_ACTION`, `FORENSIC_AUDIT`, `AUDITOR_RESIGNATION`,
`DEFAULT`, `RATING_DOWNGRADE`, `PROMOTER_ENCUMBRANCE`, `RESULTS_DELAY`,
`FRAUD`. §4 and the code agree.

## 3. Flagged announcements — and the finding that matters

Classified over the whole backfill, restricted to panel names: **15,976
flagged announcements, 10,554 of them on names the strategy could hold.**

| year | INSOLV | REGUL | FORENS | AUDITOR | DEFAULT | RATING | ENCUMB | DELAY | FRAUD | total | names |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2010 | 0 | 4 | 0 | 5 | 0 | 1 | 0 | 1 | 14 | 25 | 12 |
| 2011 | 0 | 7 | 0 | 4 | 0 | 1 | 0 | 1 | 7 | 20 | 16 |
| 2012 | 1 | 8 | 0 | 11 | 0 | 2 | 0 | 1 | 7 | 30 | 18 |
| 2013 | 4 | 7 | 0 | 9 | 0 | 6 | 0 | 2 | 2 | 30 | 28 |
| 2014 | 12 | 23 | 1 | 8 | 0 | 7 | 0 | 0 | 4 | 55 | 45 |
| 2015 | 11 | 38 | 0 | 6 | 0 | 12 | 0 | 0 | 9 | 76 | 48 |
| 2016 | 11 | 41 | 1 | 8 | 0 | 65 | 0 | 0 | 9 | 135 | 98 |
| 2017 | 183 | 46 | 2 | 23 | 2 | 68 | 0 | 12 | 12 | 348 | 173 |
| 2018 | 372 | 108 | 9 | 77 | 1 | 77 | 0 | 6 | 60 | 710 | 266 |
| 2019 | 406 | 21 | 2 | 85 | 48 | 138 | **423** | 29 | 47 | 1,199 | 446 |
| 2020 | 401 | 27 | 3 | 99 | 120 | 97 | 436 | 64 | 17 | 1,264 | 369 |
| 2021 | 469 | 14 | 7 | 114 | 66 | 59 | 330 | 36 | 22 | 1,117 | 372 |
| 2022 | 713 | 21 | 31 | 83 | 89 | 57 | 215 | 37 | 19 | 1,265 | 327 |
| 2023 | 650 | 35 | 5 | 100 | 36 | 101 | 218 | 59 | 17 | 1,221 | 367 |
| 2024 | 482 | 44 | 9 | 193 | 46 | 132 | 258 | 44 | 9 | 1,217 | 417 |
| 2025 | 344 | 58 | 3 | 162 | 37 | 117 | 240 | 53 | 31 | 1,045 | 433 |
| 2026 | 274 | 45 | 8 | 138 | 7 | 74 | 257 | 36 | 24 | 863 | 362 |

### The share of the universe a flag could touch

| year | panel names | flagged | share |
|---|---|---|---|
| 2010 | 1,490 | 12 | **0.8%** |
| 2011 | 1,571 | 16 | 1.0% |
| 2012 | 1,611 | 18 | 1.1% |
| 2013 | 1,602 | 28 | 1.7% |
| 2014 | 1,594 | 45 | 2.8% |
| 2015 | 1,628 | 48 | 2.9% |
| 2016 | 1,659 | 98 | 5.9% |
| 2017 | 1,707 | 173 | 10.1% |
| 2018 | 1,685 | 266 | 15.8% |
| 2019 | 1,700 | 446 | **26.2%** |
| 2020 | 1,744 | 369 | 21.2% |
| 2021 | 1,927 | 372 | 19.3% |

**This is the line E2-A cannot support as written.** §6 sets development at
2010-01-01 .. 2016-12-31. Over those seven years the rule would make
**0.8% to 5.9% of the universe ineligible** — twelve names in 2010. A rule
that touches one name in 120 cannot produce a measurable effect on a
25-name portfolio, so development would return a near-null result, and the
gate would read that as "no effect" when the correct reading is "no data".

**The cause is regulatory, not economic.** Three of the nine flags did not
exist as disclosures for most of development:

- **INSOLVENCY** is near-zero until 2017 because the Insolvency and
  Bankruptcy Code only came into force in December 2016. 11 in 2016,
  183 in 2017, 372 in 2018.
- **PROMOTER_ENCUMBRANCE** is **exactly zero until 2019**, then 423. SEBI's
  amended encumbrance-disclosure regime dates from 2019.
- **DEFAULT** is zero until 2017 and negligible until 2019 (48), when
  SEBI's loan-default disclosure requirement took effect.

So a third of the frozen flag set is structurally absent from development,
and a fourth (RESULTS_DELAY) is near-zero before 2017.

**What I did not do:** change the window, drop a flag, or weight anything.
All three would be choosing a parameter after seeing the data. The options
are Aarsh's:

1. **Move §6's development start to 2017** and validation to a later span,
   accepting a shorter test.
2. **Keep 2010 and read the development result as uninformative by
   construction**, recorded in the charter before the run so it cannot be
   mistaken for evidence of no effect.
3. **Drop the three post-2017 flags from §4** and test the six that span
   the window — a different experiment, and one that discards the flags
   most directly tied to permanent loss.

Option 2 preserves the charter as written and is the only one that needs no
amendment; option 1 is the one that actually buys a test.

## 4. E1 base re-run on E2-A's windows

Required because E2-A starts in 2010, three years after E1's development.

| window | CAGR (liq) | MaxDD (liq) | turnover | trades |
|---|---|---|---|---|
| E2-A development 2010–2016 | **6.44%** | 38.40% | 1.77 | 593 |
| E2-A validation 2017–2021 | **27.36%** | 39.82% | 1.31 | 461 |

Validation reproduces the stored E1 base figure exactly (27.36% / 39.82%),
which is the correctness check on the re-run path. Development is a
different number from E1's own 8.97% / 55.40% because the window excludes
2007–2009 — 2008 is in E1's development and not in E2-A's, which is also
why the worst fall is 17 pp shallower.

## 5. Engine support, line by line

| E2-A line | supported? |
|---|---|
| §3 ineligible on a trailing-12-month flag | **needs code** — no eligibility hook reads a flag set; `universe` has no exclusion input |
| §3 held name sold at the next open after dissemination | **partly** — `hooks.intra_month_exit` exists and `engine._intra_month_exits` calls it, but only `stop_loss` and `profit_take` are implemented; a `red_flag` implementation must be written |
| §3 point-in-time key `DissemDT` else `NEWS_DT`, after-15:30 rule | **NOT implemented** — nothing in `backtest/` or `eval/` reads either column. The amendment of 2026-09-24 is drafted in the charter only |
| §4 the nine frozen flags | **yes** — `red_flags.RULES`, freeze commit `77abb08` |
| §5 BSE announcements from 2010, daily thereafter | **yes** — complete and verified |
| §5 NSE announcements if BSE coverage of NSE-listed names < 95% on a 200-name sample | **NOT measured** — §5 requires this check *before the first run* and it has not been done |
| §6 window, stack re-run on the same window | **yes** — §4 above |
| §7 sweep rows S1–S12 | **yes** — existing knobs plus a flag-window parameter |
| §7 S13 (2016 onward, draft) | **yes** — `period.start`, and it now declares its periods per GATE.md |
| §8 reported extras | **yes** once the rule exists |

### Four pieces of code E2-A needs

1. **A flag table**: `(isin, flag, usable_from)` built once from the
   announcement feed, where `usable_from` applies §3's key and the
   after-15:30 rule. Nothing like it exists.
2. **An eligibility exclusion** the universe builder can take, so a flagged
   name drops out at month-end M.
3. **`hooks.red_flag_exit`**, an `intra_month_exit` implementation that
   sells a held name at the next open after a new flag.
4. **`classify.classify_e2a`** — GATE against E1 base, plus the mandate
   block. C1–C4 are not reported: E2-A is a change on the stack, not a
   candidate base.

Plus the §5 coverage check, which is a measurement the charter demands
before the first run, not a code task.

## 6. Readiness

**Not ready to run, and not only for code reasons.** The four pieces above
are a day's work. The window question in §3 is the one that needs Aarsh
first, because building the rule and running it on 2010–2016 would produce
a number that looks like a verdict and is not one.

Recommended sequence: settle §6's window, then build the four pieces, then
run the §5 coverage check, then lock, then run. The sealed period stays
shut throughout.
