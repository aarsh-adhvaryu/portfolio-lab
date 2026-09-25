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

## 0. The locked span, for future verification

**E2-A LOCKED 2026-09-25.**

    E2-A §3–§8a at the 2026-09-25 LOCK
    chars   5819
    sha256  f2972309a9793cd53c07551e19408112fef56543baf90b43aa4708e1541bf0b9

Recompute with the same section-span extractor used for E1, E1b, E1-P, E1c
and E1d (from `## 3.` up to, but not including, `## 9.`, trailing whitespace
stripped and one newline restored).

**Change-log entries that apply** (CLAUDE.md non-negotiable 1 — a locked
span is always read with its change log):

- **2026-09-24, §3** — point-in-time key is `DissemDT` where present,
  `NEWS_DT` otherwise, after-15:30 applying to either.
- **2026-09-25, §6** — window moved to development 2017–2019, validation
  2020–2021, on input availability; low-power limitation declared.
- **2026-09-25, §7** — S13 removed.
- **2026-09-25, §8** — suspension/delisting lead-time extra added.
- **2026-09-25, §8a** — pre-registered event study added, **required for
  ADOPT alongside GATE**; and its truncation rule: each period reads data
  only through its own end, horizons running past it are excluded and
  counted, and no forward return may read a price after 2021-12-31.

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

**DECIDED 2026-09-25 (Aarsh): option 1.** §6's development window moves to
**2017-01-01 .. 2019-12-31** and validation to **2020-01-01 .. 2021-12-31**,
with the reason recorded in the charter's change log *before any return on
the new window was computed*: the window is set by when the rule's inputs
exist — IBC from December 2016, SEBI encumbrance and default disclosures
from 2019 — and choosing a window from input availability is not choosing it
from results.

Two consequences went into the charter with it:

- **§6 declares the low-power limitation.** Five years split three and two,
  on a 25-name portfolio. A null result means *not shown*, never *no
  effect*.
- **§8a was added, and ADOPT now requires it alongside GATE.** A
  pre-registered event study on every flagged name, not just the handful
  the portfolio held, with its pass condition written before the study was
  implemented. That is the second line of evidence: GATE asks whether
  acting on flags helps the fund, §8a asks whether the flags carry
  information at all, and only together can they separate an uninformative
  flag from an undetectable one.

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
| §3 ineligible on a trailing-12-month flag | **BUILT** — `eligible_at(..., exclude=)`, fed by `[red_flags]` |
| §3 held name sold at the next open after dissemination | **BUILT** — `hooks.red_flag_exit`, wired as `intra_month_exit = "red_flag"` |
| §3 point-in-time key `DissemDT` else `NEWS_DT`, after-15:30 rule | **BUILT** — `red_flag_events.usable_from`, the only code that reads a timestamp; zero lookahead on the real 2019+ table |
| §4 the nine frozen flags | **yes** — `red_flags.RULES`, freeze commit `77abb08` |
| §5 BSE announcements from 2010, daily thereafter | **yes** — complete and verified |
| §5 NSE announcements if BSE coverage < 95% on a 200-name sample | **MEASURED — 97.0%, so not required** (§6 below) |
| §6 window, stack re-run on the same window | **yes** — §4 above |
| §7 sweep rows S1–S12 | **yes** — existing knobs plus a flag-window parameter |
| §7 S13 | **REMOVED 2026-09-25** — §6 now begins inside the `DissemDT` era, so S13 would duplicate the base row |
| §8 suspension/delisting lead time | needs the extra, reading `red_flag_events` against the delisting list |
| §8a event study | **BUILT** — `eval/event_study.py`, pass condition frozen in the charter |
| §8 reported extras | **yes** once the rule exists |

### The four pieces (all now built — see §6)

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

## 6. What was built (2026-09-25)

All four pieces, plus §5's check. **E2-A is still NOT RUN.**

| piece | where | tests |
|---|---|---|
| flag table, §3's key and the after-15:30 rule | `pflab/data/red_flag_events.py` | `test_e2a.py` × 9 |
| universe exclusion | `engine.eligible_at(..., exclude=)`, `exclude_fn` from `[red_flags]` | × 1 |
| `hooks.red_flag_exit` | `backtest/hooks.py`, wired as `intra_month_exit = "red_flag"` | × 1 |
| `classify_e2a` with the §8a block | `eval/classify.py` | × 4 |
| §8a's event study | `eval/event_study.py` | × 4 |

**The point-in-time rule lives in one place.** `red_flag_events.usable_from`
is the only code that reads a timestamp; the exclusion, the exit hook and
the event study all read `usable_from` and nothing else. That is the only
arrangement in which the rule can be tested once and relied on everywhere.

**The exclusion is applied AFTER the turnover ranking**, not before.
Excluding first would promote a thinner name into the top 500 and change
§2's universe as well as §3's eligibility — which would make E2-A two
changes, and GATE judges one. A test asserts a three-name universe with one
excluded yields two, not three.

**Lookahead, checked on the real table.** Built for 2019+ as a smoke test:
14,034 events, 13,949 keyed on `DissemDT`, 21 on `NEWS_DT`, 64 with no
timestamp. Of 8,783 flags stamped after 15:30, **zero are usable on or
before their own date**, and zero early flags are usable before theirs. The
90 rows with no `usable_from` are announcements with no timestamp or dated
after the last session; they return `None` rather than a guess. The
invariant is now a test over every session and six times of day.

### §5's coverage check — passed, so no NSE feed is needed

§5 requires this *before the first run*: add NSE announcements only if BSE
coverage of NSE-listed names is below 95% on a 200-name sample.

- Sample: 200 names drawn from the 500 most traded over 2017–2021, seed
  `20260925` (fixed, so it is reproducible).
- **194 of 200 carry a BSE scrip code — 97.0%, above the 95% threshold.**
- **The NSE announcement feed is not required.**
- The six misses are `NHIT`, `INDINFR`, `PGINVIT` (InvIT units, not
  equities), plus `AMIORG`, `DAAWAT` and `CDSL`.

### A D S Diagnostics — resolved, and correctly unresolvable

Scrip 523031 is in the BSE master and Active, but **BSE publishes no ISIN
for it** (`ISIN_NUMBER` is empty), market cap ₹2.55 crore, Group Y. It is
not NSE-traded and not in the panel, so it could never be held. Nothing to
fix by hand: the map is right to leave it unresolved.

### To build the full table

The 2019+ smoke test took 195s; the whole feed from 2010 is roughly ten
minutes. It is a prerequisite for running E2-A, not for locking it:

    python -c "from pflab.data import red_flag_events as r; print(len(r.build()))"

## 7. Readiness

**Ready to lock.** The charter's amendments are in (§6 window and its
reason, S13 removed, §8a, the §8 lead-time extra), all four code pieces are
built and tested, §5's precondition is measured and passed, and
`pytest -q` is **522 passed**.

Not run, and nothing about E2-A has touched real returns. The remaining
steps are Aarsh's: lock §3–§8a, build the full flag table, run development
2017–2019, Aarsh writes the development review, run validation 2020–2021,
then `classify_e2a` — which returns **INCOMPLETE until §8a has been run**,
because ADOPT needs both.

Two things to carry into the lock:

- **§6 is a low-power test and the charter says so.** Three years of
  development on a 25-name portfolio. A null result is "not shown". §8a
  exists precisely because GATE cannot tell that apart from "no effect".
- **§8a's pass condition is written and must not move.** Negative mean
  6-month excess with t < −2 (Newey-West, 5 lags) in 2017–2019, and
  negative in 2020–2021. It was recorded in the charter before the study
  was implemented, and no flag may be dropped or weighted on its result.

The sealed period stays shut throughout.
