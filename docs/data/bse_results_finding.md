# BSE financial results and A5 valuation inputs — probe (2026-10-01)

For E5-A A5 (valuation; §14 2026-10-01). Probes only; nothing large
collected. Tools: `tools/probe_bse_results.py`, `tools/probe_a5_valuation.py`.
Raw sample: `data/_probe/bse_results_sample.parquet`, `bse_results_spotcheck.parquet`.

## 1. Answer: can A5 have 2011–2016 coverage?

**Yes, for revenue, net profit, EPS, dividend yield and market cap**, once
the results pull runs (§4) and a dating rule is decided (§3). Not for
2007–2009 dating (no announcement feed), which A5's 2011– evaluation does
not need beyond the trailing-four-quarter warm-up from 2010.

## 2. Quarterly revenue, net profit, EPS — BSE

- **Endpoint** (found in bseindia.com's results-page bundle):
  `Corp_detailedResult_Transpose_ng/w?Scrip_cd=<scrip>&Qtr=<id>`, standalone
  results as entered in BSE's template, ₹ million; quarter id Jun-2000 = 26.
  `CorprateResultbeta/w?scripcode=` lists a company's quarters (to 2000).
  `TabResults`/`GetReportNewFor_Result` give only the latest five quarters.
- **Coverage**, E1's universe, 30 random names per year (two draws
  2007–2016), September quarter:

| year | 07 | 08 | 09 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| revenue, NP, EPS | 98% | 98% | 98% | 98–100% | 93% | 96–100% | 100% | 100% | 100% | 98% | 100% | 93–100% | 93% | 90% | 93% |
| dated by an announcement | 0 | 0 | 2% | 100% | 98% | 100% | 89% | 100% | 100% | 100% | 100% | 100% | 97% | 100% | 100% |

  Median filing lag 28–38 days after quarter end; maximum 74. 85–98% of
  U(M) has a BSE scrip.
- **Spot-check, 20 filings 2011–2016** (seed 20261001; the PDFs are scans,
  read page by page): **14 match on all three fields, 1 on net profit and
  EPS (revenue line not found), 0 mismatches.** 5 not checkable from the
  filing: 2 carry consolidated figures only on the pages filed, 1 a press
  release, 1 no PDF at BSE, **1 mis-dated** (below). Revenue is BSE's
  "total income from operations" (net sales + other operating income). The
  values match the original filings, so they are not later restatements.
- **Not point-in-time by itself:** the endpoint has no filing timestamp.

## 3. Dating — a decision for Aarsh

The usable time is the results announcement: `dissem_dt`, or `news_dt`
before 2015-08 (E2-A §3's key). Matched as the first announcement, 1 Oct –
15 Jan, in BSE's category Result / Financial Results (from 2015-08), else a
headline naming results and the quarter's month. **1 of 20 was dated by an
analyst-call notice filed under Result / Financial Results** (Intellect,
2016-10-25; results ~9 days later): that rule can date results **early**,
which is lookahead. Options:
1. first such announcement whose attachment is the results statement
   (needs reading attachments; a data build);
2. the later of that announcement and the board-meeting outcome;
3. the statutory deadline (quarter end + 45 days, + 60 for March): never
   early, up to ~2 weeks stale.

## 4. The pull (Aarsh's, after §3)

1,184 BSE scrips × 61 quarters (Dec-2006 → Dec-2021; nothing later), one
parquet per scrip under `data/bse_results/`, resumable, ~5–7 h at 4
threads. Tested on Reliance (61 quarters). Command in `docs/RUNNING.md`.

## 5. Dividend yield and market cap (from data held)

| year | 07 | 08 | 09 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TTM dividend > 0 | 51% | 53% | **40%** | **34%** | 71% | 71% | 65% | 63% | 64% | 64% | 58% | 59% | 59% | 58% | 50% |
| market cap available | 0 | 0 | 0 | 61% | 93% | 95% | 96% | 96% | 95% | 98% | 99% | 99% | 99% | 99% | 99% |

Shares of names the probe matched to the raw panel (87–98%; the rest are ISIN
successions the engine's panel resolves, e.g. Asian Paints before 2013).
- **TTM yield**: NSE feed dividends (paid per share at the time) with ex-date
  in (M − 12 m, M], restated to M's share basis by the panel's split/bonus
  factor, over M's close. **The feed has a 2009–10 hole** (164 ex-dates in
  2009 against 694–931 either side), which understates 2009–2010 yields and
  the 2010–early-2011 windows. A0's development decisions start 2011.
- **Market cap**: latest usable BSE shareholding quarter's shares outstanding
  (reported from Dec 2015, derived before) × M's close, split/bonus restated.
  From 2010 (shareholding starts 2010-03).

## 6. The queued BSE XBRL 2011–2017 probe

Superseded for A5's fields: BSE's template data above reaches 2000, matches
the filings, and needs no XBRL. `Integratedfinancedata/w` lists XBRL only for
the 2025 "Integrated Finance" format (Reliance: 20 rows, 2025 on). NSE's XBRL
documents still resolve only from 2018 (`xbrl_results_finding.md`). The
template carries no balance sheet, so book value and cash flow stay
unavailable before 2018/2020; E6-V's cash-flow yield is not unblocked.
