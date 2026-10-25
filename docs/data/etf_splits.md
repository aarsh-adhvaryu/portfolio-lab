# ETF unit splits and ISIN changes — scan, 2026-09-27

Tool: `python tools/scan_etf_events.py` (read-only; exits 1 if an ETF a
charter uses has an unexplained move). Repair: `pflab.data.etf_events`,
applied only when a config sets `data.etf_events`.

## Findings

1. **NIFTYBEES 1:10 and GOLDBEES 1:100 (ex 2019-12-19, new ISINs from
   2019-12-20) are stitched and adjusted.** After the repair each is one
   ISIN. Largest one-day moves: NIFTYBEES 14.63% on 2009-05-18 (election
   day, Nifty 50 +17.7%), GOLDBEES 10.52% on 2026-01-30 (the precious-metals
   fall; silver ETFs −20% that day), LIQUIDBEES 3.13%. None unexplained.
2. NIFTYBEES vs Nifty 50 price, 5,636 sessions: daily return gap median
   0.14%, 99th percentile 1.91%. Across the split: +0.73% vs +0.31% on the
   ex-date, no step. Largest gap 2006-03-30 (+8.0% vs +1.9%, reversed
   −5.6% next day): a thin-market print, not an event.
3. **The pattern is widespread and unrepaired elsewhere**: 32 split-like
   one-day falls (>75%, volume >1,000) in 31 other ETFs (1:10, 1:100, 1:5,
   1:50), and 72 same-symbol ISIN successions. All 443 INF ISINs are typed
   `ETF`, so **no E1-family run is affected** (E1 §2 admits STK only).
4. **Benchmarks read index series only**: B1–B3 and B5 through
   `engine.run_benchmark` on `data/indices/*`; B4 is the STK-only E1b
   universe from the panel. No ETF row reaches any benchmark.
5. **No dividends are recorded for NIFTYBEES, GOLDBEES or LIQUIDBEES.**
   NIFTYBEES paid dividends before 2019, so E3-R's high gear is slightly
   understated (E3-R §11 (c) asks for this to be stated in the verdict
   note). LIQUIDBEES's return is paid as daily dividend units, so its panel
   series earns ~0; moot under E3's 2026-09-27 decision (cash treatment).

## Decisions needed

- None for current charters. If a future charter uses any other ETF, its
  split and ISIN change must be declared in `etf_events.DECLARED` first;
  the tool's split-like list is the starting point.
