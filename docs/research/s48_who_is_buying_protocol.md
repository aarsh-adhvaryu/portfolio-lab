# S48 "Who is buying": pre-registered protocol

Registered 2026-10-20, before any return was computed on these signals. The investor asked for all four kinds of buyer.
The research archive (`origin/research-archive`, read 2026-10-20 with the investor's permission, nothing copied) shows no
buyer-side test: E2-D1 (promoter selling), E2-D2 (insider selling) and E2-E (retail crowding) were drafts never run;
E2-A tested red-flag announcements. So 2016-2021 is fresh for these signals; 2022-2025 stays spent.
Code: `tools/s48_study.py`. Changes after the first run of an arm need a dated amendment.

## Common design (fixed now)
- **Universe at month-end M:** Nifty 500 members on M (`data/index_membership/NIFTY500.parquet`), with a price on M.
- **Outcome:** the stock's price return (split- and bonus-adjusted close) over the 63 sessions after M, minus the equal-
  weight average of the universe over the same sessions (excess return).
- **Monthly spread:** mean excess return of the arm's signal stocks at M (at least 5 stocks, else the month is skipped).
- **Periods (signal month-ends):** development 2016-06 to 2019-09; validation 2019-12 to 2021-09 (outcomes end by
  2021-12, before the spent years); holdout 2026 month-ends with data and a complete outcome (described only).
- **Rule per arm:** development mean spread > 0 AND validation mean spread > 0 with a one-sided Newey-West t-test
  (lag 2, overlapping 3-month outcomes) at p < 0.0125 (four arms: Bonferroni, whether or not every arm runs).
- **Point in time:** a disclosure counts at M only if disseminated by 15:30 on M or earlier.
- **Use if an arm passes:** a researcher flag ("who is buying: ...") and a fact in the company's brief, shown by the
  advisor as information. Any change to which names are bought is the investor's decision after the results. Fails: nothing.

## The four arms
1. **Promoters and insiders (runs now; NSE insider-trading disclosures on disk).** Rows with person category Promoters,
   Promoter Group, Director, Key Managerial Personnel or Immediate relative, and mode Market Purchase (+value) or Market
   Sale (-value), disseminated in the 90 days to M; ISIN from the price panel by symbol on the trading day. Signal:
   net market buying of at least 0.05% of market capitalisation (shares outstanding from the latest usable BSE
   shareholding filing, usable from its filing date, else quarter end + 21 days, times the close on M).
2. **Institutions, quarterly (needs data: BSE detailed shareholding, institutional categories).** Signal: top decile of
   the increase in combined foreign and domestic institutional holding (percentage points) between the two latest
   filings usable at M.
3. **Mutual funds, monthly (needs data: AMC monthly portfolios; deferred, may never run).** Signal: top decile of the
   one-month increase in aggregate mutual-fund holding (percent of shares outstanding), usable from the 10th day after
   month end.
4. **Bulk and block deals (needs data: NSE bulk and block deal archives).** Signal: net buying in bulk and block deals
   by parties other than promoters over the 30 days to M of at least 0.05% of market capitalisation.

## Amendment 1 (2026-10-22, before the first run of arms 2 and 4)
- **Arm 2:** institutional holdings outside 0-100% are parse errors and are dropped (3 rows, three companies, all in
  the 2025-09-30 quarter: they touch only the described 2026 holdout).
- **Arm 4, a known limit, no change of method:** NSE's deal answer stops at 70 rows; 201 day-and-kind answers hit it
  (2016-2021: 89; 2025-2026: 112) and are kept as they are. Rows come back in symbol order (15% start with A on the
  capped days), so a cut-off day loses later-alphabet symbols' deals: missing by name, not by what follows, which
  weakens the test without biasing it. The 2026 holdout (described only) is the most affected.
