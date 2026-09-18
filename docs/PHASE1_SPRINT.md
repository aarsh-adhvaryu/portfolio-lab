# Phase 1 sprint — minimum data for E1, in 2–3 days

Only what E1 needs. Everything else moves behind the first development run.
Wall time is downloads and one review; coding is a few hours of Claude Code.

## Day 1 (Aarsh: 30 min; Claude Code: rest)

1. **Bhavcopy backfill, 2004-01-01 → today.** Start the collector and let it run
   (about an hour at 0.7 s/request). If NSE refuses more than a few hundred
   requests, switch to the `jugaad-data` package's bhavcopy downloader for the
   backfill and keep our normaliser for the parquet output. Log holidays.
2. **Index series (Aarsh, 10 min).** Download from NSE Indices historical data:
   Nifty 50 TRI, Nifty 500 TRI, Nifty 200 Momentum 30 TRI, Nifty 50 (price).
   Drop the CSVs in `data/indices/raw/`. Claude Code ingests.
3. **Split/bonus factors from the bhavcopy itself — no corporate-actions
   scraper.** On an ex-date NSE publishes an adjusted `PREVCLOSE`, so
   `factor = prev_close(t) / close(t-1)` on rows where the two differ by more
   than 2% and the name traded both days. Snap to common ratios (1/2, 1/3,
   1/5, 1/10, 2/3, 1/1.5 ...) when within 1%, keep the raw ratio otherwise,
   and write every candidate with its raw ratio to
   `data/panel/adjustment_candidates.parquet`. **Verify** on three known
   events before trusting it (a 1:1 bonus, a 10→2 split, a 1:2 bonus) and
   put the check in a test.

## Day 2

4. **Symbol → ISIN for pre-2011 rows.** Build the map backwards from the first
   bhavcopy that carries ISIN, joined with NSE's symbol-change file. Unmapped
   rows are dropped and counted in the manifest. If the count exceeds 2% of
   rows in any year, stop and show Aarsh.
5. **Dividends, fast path.** Pull dividend histories via `yfinance` for every
   ISIN still listed (symbol + `.NS`); delisted names get zero. This
   understates E1's return relative to the TRI benchmarks by roughly the
   dividend yield of the names that later died — a bias **against** E1,
   which is the acceptable direction. Declared in charter §9.
6. **Panel + plausibility.** `panel.build()` writes `data/panel/prices.parquet`;
   `panel.plausibility()` writes `docs/data/plausibility_findings.md`.

## Day 3 (Aarsh: 30 min)

7. **Review** the plausibility findings and the adjustment candidates that did
   not snap to a common ratio. Decide: accept, or mark a name as data error.
8. **Start the daily collector** (bhavcopy + BSE + GDELT) on a schedule. This
   is the only E2 item on the critical path; it must be running before the
   live period, and it costs nothing now.

## Deferred until after the first development run

- BSE announcements backfill (E2-A)
- GDELT BigQuery backfill (E2-B/C)
- NSE corporate-actions scraper (only if the PREVCLOSE method fails verification)
- Rights-issue handling

## Definition of done

`pytest -q` passes including `tests/test_adjustment_known_events.py`;
`data/panel/prices.parquet` covers 2004 → today; four index parquets exist;
`docs/data/plausibility_findings.md` has been read by Aarsh; the daily
collector has run once. Then Phase 2 starts.
