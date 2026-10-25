# Data sources, formats and known gotchas

Everything below is free. Nothing below is verified against the live
endpoints from inside this repo yet; Phase 1 task 1.1 is to run each
collector and fix whatever the endpoints have changed.

## NSE daily bhavcopy (prices, volume, turnover; all listed names incl. later delisted)

- Archive host: `archives.nseindia.com`. Two file formats:
  - **Old** (until roughly 8 July 2024, VERIFY exact date):
    `/content/historical/EQUITIES/{YYYY}/{MON}/cm{DD}{MON}{YYYY}bhav.csv.zip`,
    columns `SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,
    TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN` (trailing comma; ISIN column
    absent before ~2011).
  - **New UDiFF** (from mid-2024):
    `/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip`,
    columns include `TradDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,
    SctySrs,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,
    TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd`.
- NSE blocks default user agents; send a browser User-Agent and a Referer.
  Sleep between requests. A 404 on a weekday is usually a holiday; record it.
- Keep only series `EQ` for the strategy (store everything).
- Symbols get renamed. Key on ISIN. For pre-2011 rows build a
  symbol->ISIN map from later bhavcopies plus NSE's symbol-change file.
- Alternative bulk sources if the archive is hostile: the `jugaad-data`
  Python package (bhavcopy downloader), or NSE bhavcopy compilations on
  Kaggle. Whatever the source, normalise to the schema in
  `pflab/data/bhavcopy.py`.

## NSE corporate actions (splits, bonuses, dividends)

**The primary source for adjustment factors AND dividends** since charter §15,
2026-09-16. Verified 2026-09-16; collected by `pflab.data.nse_corporate_actions`.

- `GET https://www.nseindia.com/api/corporates-corporateActions`
  `?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY`, with a browser
  User-Agent and the corporate-filings page as Referer, after one GET of it.
  A whole year per call.
- Rows carry **`isin` directly**, so no symbol join: `exDate`, `series`,
  `faceVal`, and the free-text `subject` (the PURPOSE field).
- Coverage is good from 2006. 2004 has 0 split/bonus rows and 2005 has 1, so
  the §11 warmup is thin; development from 2007 is covered.
- `subject` phrasing is inconsistent and must be parsed defensively. All of
  these are live strings: `Bonus 1:1`, `Bonus 1 : 1`, `Bon-1:1` (pre-2010
  abbreviation), `Face Value Split (Sub-Division) - From Rs 10/- Per Share To
  Rs 2/- Per Share`, `Face Valus Split` (NSE's typo), `From Rs 10/- Each To
  Rs 2/- Each`, `From 10/- To Face Value 2/-` (no currency), `Spl-Rs10tors2`,
  `Fv Spl-Rs2 To Re1/Bon-2:1`. A compound row carries both legs and they
  multiply.
- Factors: bonus `a:b` -> `b/(a+b)`; sub-division FV X->Y -> `Y/X`. Applied to
  every price strictly before the ex-date.
- **Excluded on purpose:** `Bonus Debentures` (issues debt, share count
  unchanged) and face-value *consolidations* (reverse splits), which are left
  to surface as plausibility halts rather than risk a wrong adjustment.
  Rights issues are logged and ignored in E1 (declared simplification).
- Validation: for 713 factors testable on adjacent sessions, the actual
  close-to-close jump matches the factor within 20% in 98.5% of cases; the
  median 3.1% residual is just that day's own return. Only 3 are >35% off.
- Dividends come from the same `subject`, two ways: `Rs X Per Share`
  (95-98% of rows from 2010) and `Dividend-N%` of `faceVal` (91% of rows
  2004-2009). Cross-checked against yfinance: agreement within 1% on 111 of
  114 common ex-dates, after correcting yfinance's basis (below).
- BSE corporate actions can cross-check; disagreements go in the manifest.

## Index total-return series

Collected by `pflab.data.indices`; no manual download. Verified 2026-09-16.

- The niftyindices.com historical-data form caps a range at one year, but that
  check is **client-side only** (`if (diffDays > 365) alert(...)` in
  `IISLComponet.js`). The endpoints behind the form take any range:
  - `POST https://www.niftyindices.com/BackPage/getHistoricaldatatabletoString`
    -> price index, `OPEN/HIGH/LOW/CLOSE`, key `HistoricalDate`
  - `POST .../BackPage/getTotalReturnIndexString`
    -> TRI, keys `Date`, `TotalReturnsIndex`, `NTR_Value`
  - `POST .../BackPage/getpepbHistoricaldataDBtoString`
    -> `pe`, `pb`, `divYield`, key `DATE`
- Body is `{"cinfo": "{'name':..,'startDate':..,'endDate':..,'indexName':..}"}`
  with dates as `dd-MMM-yyyy`; send a browser User-Agent, `X-Requested-With:
  XMLHttpRequest` and the historical-data page as Referer, after one GET of
  that page. Dates come back as `dd MMM yyyy`.
- Index names must match exactly: `NIFTY200 MOMENTUM 30` returns rows,
  `NIFTY 200 MOMENTUM 30` returns `[]`. Momentum 30 starts 2005-04-01 at
  1000.00 (NSE's backfill base). Momentum 30 has no valuation history.
- Stored as `data/indices/{KEY}.parquet`: `date, close` for TRI, plus
  `open/high/low` for the price index, and `pe, pb, div_yield` for valuation.
- **Valuation is not an E1 input** (§2 ranks by traded value, §3 is pure price
  momentum). It is kept out of `indices.SERIES` on purpose and used only to
  cross-check TRI against price: over 2004-2026 the annual
  `TRI return - price return` matches dividend yield to a mean of 0.10pp.
- The Nifty 50 price calendar is the reference for
  `pflab.data.calendar.check_against_index` (task 1.4). It found 27 weekend
  sessions the bhavcopy collector had skipped -- NSE trades some Saturdays and
  Sundays (Budget days, Diwali Muhurat).
- India VIX history from NSE (E2): `POST .../BackPage/BindHistoricalIndiaVixData`.

## Index constituent history (E1b)

**Verified 2026-09-17.** Collected by `pflab.data.index_changes`.

### The wrong source, recorded so nobody tries it twice

NSE's F&O circular series "Change in the Constituents of Indices"
(`nseindia.com/api/circulars`, subject match, filed under the Futures &
Options department) looks like the source and is not. Those circulars exist
because an index change moves the F&O contracts, so they cover only
derivative-eligible indices. Across all 98 of them, 2006–2026:
**Nifty 200 appears zero times**, Nifty 500 three times (2006–07), Nifty 100
ten times (2006–08). Nifty 200 and Nifty 500 have no derivatives.

### The right source

NSE Indices Limited publishes every index change as a press release:

- Listing: `GET https://www.niftyindices.com/media` — plain HTML, the links
  are `/Press_Release/ind_prs<DDMMYYYY>.pdf` (sometimes `_1`, `_2` suffixed
  for several on one day). **1,486 releases, 1998–2026.**
- The file date is the ANNOUNCEMENT date. The date that matters is the
  effective date inside the text ("w.e.f. …", "shall become effective from
  …"), typically three to five weeks later, and it is routinely split across
  a line break.
- Needs a browser User-Agent; no session cookie required.
- Ten releases are listed but not served: the server returns its 404 page
  with HTTP **200**, so the bytes must be checked for `%PDF` rather than the
  status code.

### Gotchas in the PDFs, all of them silent

- **Reading order.** `pypdf` returns some older releases with whole sections
  ahead of their own headings, which parses cleanly into the wrong answer.
  `index_changes.validate` detects it; `pdfplumber` is the sanctioned
  fallback (CLAUDE.md 7) and reads them correctly.
- **Faux-bold doubling.** pdfplumber renders bold runs as doubled glyphs
  ("IInnddiiaabbuullllss"). De-doubling must be decided per LINE, not per
  word, or "77," survives and "December 77, 2011" silently falls back to the
  announcement date.
- **The noun changes.** "company/companies", "security/securities" and
  "scrip/scrips" are all in use, sometimes in the same year. Matching only
  the first drops whole review years.
- **The verb changes.** "is being excluded", "are being excluded" and
  "will be excluded" are all in use.
- **The third column is not always the symbol.** Releases up to about 2009
  print `Sr. No. | Company Name | Industry`. Reading that as a symbol takes
  "BANKS" for Bank of Punjab. The header decides; pre-2011 rows are keyed
  through `pflab.data.name_map` instead.
- **Unrecognised headings still close a section.** "4) CNX Realty Index" is
  not one of ours, but if it does not end the section above it its companies
  are read as part of that index.

### Current constituent lists (the anchor the history is walked back from)

`archives.nseindia.com/content/indices/<file>`, all carrying ISIN directly.
NSE has no single naming rule, so the filename is stored per index:
`ind_nifty200list.csv`, `ind_nifty500list.csv`, `ind_nifty100list.csv`,
`ind_niftymidcap100list.csv`, `ind_nifty200Momentum30_list.csv` (note the
underscore on the last one only).

### Methodology

`niftyindices.com/Methodology/Method_NIFTY_Equity_Indices.pdf` defines
Nifty 200 as "Constituents forming part of Nifty 100 and Nifty Midcap 100",
with no further selection and no replacement cap. That is what makes the
pre-2011 reconstruction derivable rather than guessed (E1b §4).

## BSE corporate announcements (E2-A)

- The bseindia.com announcements page is backed by a JSON API
  (`api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w`) taking a
  date range, category and page number. Requires `Referer:
  https://www.bseindia.com/` and a browser User-Agent. Response rows
  carry scrip code, company, headline, category, sub-category, news date,
  dissemination timestamp and PDF attachment name.
- **Point-in-time key is the dissemination timestamp.** An announcement
  disseminated after 15:30 is only usable from the next session.
- Backfill day by day; the API pages at 50 rows.

## GDELT 2.0 (E2-B, E2-C)

- Backfill: BigQuery public dataset `gdelt-bq.gdeltv2.events` (and `gkg`).
  Free tier is enough to pull rows where any actor country is `IND` or
  action country is `IN`, aggregated daily. Needs a Google Cloud account.
- Daily job: 15-minute files at
  `data.gdeltproject.org/gdeltv2/{YYYYMMDDHHMMSS}.export.CSV.zip`
  (96 per day), filtered the same way. Column positions verified against a
  live export 2026-09-16: **`ActionGeo_CountryCode` is column 53, not 51**
  (51 is `ActionGeo_Type`, a 0-5 enum). Reading 51 matched no India rows and
  silently dropped 63% of the feed -- most domestic India news codes no actor
  country, so the ActionGeo clause is the only thing that finds it.
- Backfill SQL: `tools/gdelt_bigquery.sql` (The investor runs it, drops the CSV in
  `data/gdelt/backfill/`).
- GDELT starts February 2015. Its real test is the live-forward period.

## Macro (E2-B)

- Brent, USDINR, US 10-year: FRED (free, CSV).
- FII/DII flows: NSE / NSDL daily reports.
- RBI DBIE for anything Indian-macro.

## Dividends via yfinance (cross-check only)

- `yfinance` reports dividends on the **current** share basis. Widget Co paid
  Rs 29.50 on 2015-06-15; yfinance returns 7.375, having divided by the 4x of
  two later 2:1 events. The engine holds the share count of the day, so using
  that directly understates §8 dividend income, silently and with no error.
- `pflab.data.dividends.unadjust` reverses it with the same factors the panel
  uses. The ex-date bound is **inclusive**: a bonus and its dividend routinely
  go ex on the same day, and an exclusive bound recovers only half.

## Cash sleeve

- E1 declares a flat 6% p.a. A liquid-fund NAV or 91-day T-bill series is
  a declared data upgrade only if adopted before the first run.
