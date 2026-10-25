# Insider (PIT) disclosures — two sources, and where they disagree

Collected and compared 2026-09-23/24. Both sources are on disk.

- **NSE structured PIT** — `pflab/data/nse_insider.py`,
  `data/nse_insider/<year>/<year>-<month>.parquet`. 127 months,
  **338,986 rows**, 2015-11-19 → 2026-05-02. 0 months failed.
- **BSE insider/SAST announcements** — read out of the existing
  announcements backfill by `pflab/data/bse_insider.py`. **272,021 rows**,
  2015-08-12 → 2026-09-22 *as usable records* (see §3 — the earlier rows
  exist but have no dissemination timestamp).

## 1. A defect in NSE's API that only a second question exposes

The endpoint publishes no row count, so there is no ROWCNT to check a month
against the way `bse_announcements` checks a day. The check used instead is
**partition additivity**: a month's rows should equal the union of its two
halves.

It mostly holds — March 2017 whole = 9,218 = 2,273 + 6,945, and twelve
monthly requests for 2017 reproduce a single whole-year request exactly
(56,841 rows, 56,837 unique). But over 2015–2026 it **failed in four
months**, where the whole-month answer omits rows that a request for either
half returns:

| month | whole | halves | rows the whole answer lost |
|---|---|---|---|
| 2023-09 | 2,461 | 1,278 + 1,190 | 7 |
| 2023-12 | 2,653 | 1,473 + 1,175 | 1 |
| 2024-10 | 869 | 555 + 316 | 2 |
| 2025-03 | 1,920 | 819 + 1,161 | **64** |

Nothing in the response says so. A single request per month would have
dropped 74 real disclosures with no sign that it had. So a month is written
as the **union** of the whole window and its halves, and the deficit is
counted. The union only ever adds rows the source itself served for a
sub-window of the same period, so nothing is invented. Locked down in
`tests/test_insider.py`.

## 2. Coverage by year

| year | BSE rows | BSE companies | NSE rows | NSE companies |
|---|---|---|---|---|
| 2015 | 6,359 | 2,535 | 3,549 | 286 |
| 2016 | 15,639 | 3,117 | 43,541 | 868 |
| 2017 | 17,580 | 3,028 | 56,837 | 1,004 |
| 2018 | 19,409 | 3,151 | 58,542 | 1,021 |
| 2019 | 27,353 | 4,017 | 38,371 | 1,016 |
| 2020 | 26,492 | 4,041 | 30,667 | 973 |
| 2021 | 27,021 | 4,103 | 34,325 | 1,033 |
| 2022 | 27,595 | 4,198 | 19,280 | 956 |
| 2023 | 27,367 | 4,371 | 18,816 | 902 |
| 2024 | 28,735 | 4,564 | 16,991 | 954 |
| 2025 | 29,975 | 4,905 | 13,609 | 1,006 |
| 2026 | 18,496 | 4,913 | 4,458 | 579 |

Two structural gaps, in opposite directions:

- **NSE begins 2015-11-19** and has nothing before it. SEBI's PIT
  Regulations, 2015 created the feed.
- **NSE stops 2026-05-02.** June, July, August and September 2026 return
  zero rows while March 2026 returns 2,057. Probed repeatedly; it is a real
  gap in the source. The same tail decay affects NSE's results archive
  (`xbrl_results_finding.md` §3).

BSE therefore covers four to five times as many companies and runs to the
present; NSE covers about a thousand companies a year but parses them.

## 3. BSE has no dissemination timestamp before 2016 — this matters for E2-A

Checked against the raw API, so it is the source and not the collector:

| year | insider rows | with `DissemDT` | with `NEWS_DT` |
|---|---|---|---|
| 2010–2014 | 135,279 | **0 (100% null)** | all |
| 2015 | 29,127 | 6,359 (21.8%) | all |
| 2016 onward | — | 97–99.7% | all |

`api.bseindia.com` returns `DissemDT: None` for every pre-2016 announcement
and a populated `NEWS_DT`.

**This is a problem for E2-A, not only for insider data.** E2-A §3 says:
*"Point-in-time key: BSE `DissemDT`. An announcement disseminated after
15:30 is usable from the next session."* That key does not exist for
2010-01-01 → 2015-12-31, which is six of the seven years of E2-A's own
development window (§6: development 2010-01-01 .. 2016-12-31).

`NEWS_DT` is the obvious substitute, and it is a very good one. Over 222,419
announcements in the 2016–2022 overlap where both exist:

| statistic | `DissemDT − NEWS_DT` |
|---|---|
| median | **5.1 seconds** |
| p75 / p90 / p99 | 6.8 s / 8.2 s / 10.3 s |
| within 5 minutes | **99.77%** |
| crossing a session boundary (≥ 1 day) | **0.009%** |
| negative (disseminated before the news date) | 0.199% |

So substituting `NEWS_DT` would misdate roughly one announcement in 11,000
across a session boundary. That is small, but **E2-A §3 names `DissemDT`
explicitly and the charter is law**, so this is the investor's call, not mine. The
options are to amend §3 to name `NEWS_DT` (or "`DissemDT`, falling back to
`NEWS_DT` where absent, declared per row") with a dated §15 line, or to
shorten E2-A's development window to 2016 onward. I have changed nothing.

## 4. Where the two sources disagree

Joined on ISIN through `data/bse_scrip_isin/map.parquet`. The join is sound:
98.2% of NSE's ISINs are in the map and 99.8% of BSE insider rows resolve,
so what follows is content disagreement, not a broken key.

Over the common span 2015-11-19 → 2026-05-02:

- BSE: 240,018 company-days across 6,095 securities
- NSE: 96,809 company-days across 2,121 securities
- **92.2% of NSE's securities also appear in BSE's insider feed** — the two
  agree about *which companies* have insider activity.

But they do not agree about *when*:

| matching tolerance | NSE company-days found in BSE |
|---|---|
| same day | **15.7%** |
| ±1 day | 25.5% |
| ±3 days | 33.5% |
| ±7 days | 42.8% |
| ±30 days | 67.8% |
| ±90 days | 84.8% |

Same-day agreement is only 15.7%, and the match rate climbs smoothly with
tolerance rather than saturating — the signature of two feeds carrying
related events on systematically different dates, not of one feed missing
data. Even at a quarter's tolerance, 15% of NSE disclosure-days have no BSE
insider announcement for that security at all.

**What this means practically.** The two cannot be used to validate each
other at day level, and they are not interchangeable:

- **NSE is the one E2-D §3 needs.** Its row is a parsed disclosure carrying
  quantity, value, and holding before and after — which is what a rule
  phrased as "net insider transactions exceed 1.0% of market cap" requires.
  BSE's row is an announcement with a headline and no parsed quantity.
- **BSE is the only source outside 2015-11 → 2026-05**, and the only source
  at all for 2010–2015 — but without `DissemDT` before 2016 (§3) and
  without quantities, so it can answer "was something disclosed" and not
  "what was disclosed".

E2-D's development window (2010–2016) is therefore covered by a source that
cannot support its stated rule, and its validation window (2017–2021) by one
that can. That asymmetry should be settled in E2-D's charter before it runs.
