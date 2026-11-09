# S81 B8 (A53): the US leg, notes of the `us` agent, 2026-11-09 night

Branch: the worktree branch of agent `us` (based on `pm/s81-loop`). Research first (`docs/US_LEG_S81.md`, every row labelled primary / secondary / estimate), then Phase A, then Phase B.

## Decisions (dated 2026-11-09, nobody awake to ask)
1. Research before code; the research file is the deliverable that survives even if the sub-book is never switched on. Primary sources opened and read: the Income-tax Act 2025 (Gazette), the Finance Act 2026
   (Gazette), the US-India treaty and IRS Table 1, the Embassy of India's DTAA page, the RBI press release on FBIL and the RBI LRS FAQ, NYSE's hours page, the SEC fee advisory, FINRA's fee schedule and the **NSE
   press release of 2026-09-25** on international ETFs. The Income Tax Department's own site answers 403 to every automated request, so Rules 115/206/128/76, Form 67/44 and the CBDT FAQ stay **secondary**.
2. The premium rail's default is **2.0% (no buying) with a taper from 1.0%** (an estimate, in `configs/core.toml [premium]`, his to change). It looks at the `international` class only; `classes = ["international", "gold"]` extends it.
3. The sub-book is a separate paper account **in dollars**, starting at **5% of the system's book** (rupees at the start FX rate, less a 0.4% funding markup that is itself an estimate). Baseline policy: the 13 US ETFs the repo
   already collects (SPY, QQQ, the 11 SPDR sector funds) at equal weights, 95% invested, inside the SAME rails as the rupee book (`core/rails.clip_weights` reused as it is: ETF 35%, company 10%, no borrowing, no shorting, a 12% breaker).
   Not enforced: the 25% sector rail (no sector map for US stocks; ETFs only).
4. Orders are placed at a US close and fill at the **next session's open plus 5 bps** (a buy above the open, a sale below it: never better than the quote); charges are the GIFT City route's (`us/costs.py`).
5. A fresh account deploys at once (found on the real path: with a USD 1,051 account the settled-book churn caps left every order under the minimum trade). Once it is half invested the 10% a day / 40% a month caps apply.
6. Tax rows are in `configs/us/tax_s81.toml`, deliberately NOT in `configs/tax/` (that folder's tests read every row; they stay unchanged). Estimates are refused nowhere: they are labelled in every figure that uses them.
7. The US tax figures exclude surcharge and cess (as the rupee paper book's do) and use the rupee book's slab (30%, `paper/book.SLAB`) for short-term gains and dividends.

## What is verified, what is estimated (full table in `docs/US_LEG_S81.md`)
- **Primary (read today):** foreign shares are long-term only after 24 months (Act 2025 s.2(101)); 12.5% without indexation (s.197); no 20% rate and no Rs 1.25 lakh exemption without STT (ss.196, 198); dividends are income
  from other sources (s.92(2)(a)) at the slab; surcharge capped at 15% and cess 4% (Finance Act 2026); US withholding on an individual's dividend is **25%** (treaty Art. 10(2)(b), never 15%), credited at the lower of the US tax and the
  Indian tax (Art. 25(2)(a)); an international or gold ETF is neither an "equity-oriented fund" (s.198(8)) nor a "Specified Mutual Fund" (s.76(5)(b)) so a listed one is long-term after 12 months at 12.5%; LRS USD 250,000; NYSE hours and
  holidays; SEC fee USD 20.60 per million from 2026-04-04; FINRA TAF USD 0.000195 a share; FBIL computes the reference rate; **NSE's 2026-09-25 release** (premium cause, abrupt-fall risk, 2026-09-07 and 2027-04-01 dates).
- **Secondary:** conversion at the SBI TT buying rate of the month-end before the transfer (Rule 115 / 206), Form 67 / Form 44 and their deadlines, TCS 20% above Rs 10 lakh, the GIFT City brokerage schedule (Zerodha, 2026-10-27), the
  per-fund overseas limits, the named premium examples from the press, the 12-month reading for a listed international ETF as confirmed by fund houses.
- **Estimates:** the SBI TTBR itself (the market USD/INR close stands in, or an FBIL row if entered), the funding markup (0.4%, low end of 0.4%-1.4%), slippage 5 bps, the 2.0% premium limit, whether cost and proceeds are converted at
  their own month-ends (two-date reading) or as one gain, and whether his GIFT City route qualifies for the IFSC wording of ss.196(3) / 198(4) (not assumed).
- **Check of the premium series:** run on the repo's real NSE closes and AMFI NAV files it reproduces the six premiums DSIJ printed for 2026-10-14 to the decimal (111.8, 59.5, 58.9, 31.1, 15.3, 4.6). On 2026-11-06 all six are above 2%
  (the lowest, Hang Seng BeES, is 3.3%): **the rail blocks every India-listed international ETF today**, so the core's international leg cannot be bought through them until a premium falls or a limit is raised.

## Built
Phase A, ON (it only ever removes a buy of an international ETF):
- `src/pflab/core/premium.py`: `premium_series`, `premium_at`, `attach`, `premium_rail(state, targets, cfg) -> (targets, notes)` (and `rail_reasons`). Defaults and the `[premium]` table in `configs/core.toml`.
- Hook in `core/rails.py` `check` (six lines): `premium.attach(con, state)`, then the weights pass through `premium.rail_reasons` before `clip_weights`; the reason is appended to that name's `clipped[...]["why"]`, and `was` keeps the
  policy's own wish. With no international ETF in the state it is a no-op that runs no query, and `market="IN"` results are identical (test).
Phase B, OFF (`[us] on = false`), package `src/pflab/us/`:
- `clock.py` (US session in IST, `market=` argument on every function; "IN" answers from the Indian calendar), `fx.py` (FBIL row > market close > FRED, source on every rate; month-end tax rate), `costs.py`, `tax.py`
  (gains classes, set-off, dividend withholding and credit), `instruments.py` (real ISIN, else `ZZ`+CIK, else `US:SYMBOL`; alias from a date; per-market lookup), `data.py` (bars from `data/us/raw`), `book.py` (account, lots, orders,
  fills at the next open, dividends on shares held at the previous close, split detection from restated history, the mark), `policy.py` (state, baseline, rails reused, orders with reasons by code), `adapter.py`
  (`close_us(con, now, root=None, cfg=None, book_value_inr=None)`, `state_us(con, day)`).
- Migrations 131-135 in `src/pflab/pm/mig_s79/m_us.py` (136 is spare): `us_account_s81`, `us_cash_s81`, `us_lots_s81`, `us_trades_s81`, `us_orders_s81`, `us_dividends_s81`, `us_days_s81`, `us_runs_s81`, `us_events_s81`. They touch neither
  `paper_*`, `us_trades` (his real record) nor any rupee lot (test).
- Real path (scratch store, the workshop's real US bars and USD/INR, read only): the account opened with USD 1,051 (5% of Rs 20 lakh at 94.75, source stated), 13 buy orders, 13 fills at the next open +5 bps with charges, then
  held; a second run over September 2026 caught SPY's real ex-dividend date (2026-09-18, USD 1.889 a share): gross USD 0.9024, USD 0.2256 withheld, Rs 21.46 credited, Rs 4.29 of Indian tax after the credit. The SEC refused the ticker
  file (403: it needs the contact User-Agent of `data/sec_edgar.py`), so those runs used the symbol keys `US:SPY`; the ZZ+CIK path is tested with synthetic CIKs.

## OFF, and why; how to switch it on
- `[us] on = false` (the default). Nothing reads the `us_*_s81` tables except `us/`. It ships OFF because the loop does not call it yet and because the numbers it prints are rupee ESTIMATES until the SBI TTBR series is wired.
- To switch it on: (1) the coordinator adds `if us.on(): adapter.close_us(con, now)` after the Indian close loop and in the IST-morning tick (idempotent per session); (2) set `on = true` under `[us]`; (3) `tools/backfill_us.py` or
  `us_prices.collect(...)` must keep `data/us/raw` current (the function says "waiting" when the session's bars are not there); (4) optionally set `[sec] user_agent` so `uins.refresh_ciks()` can cache the CIK map and the keys become `ZZ`+CIK;
  (5) optionally enter FBIL rates in `fx_rates` as pair `USDINR_FBIL` (from the RBI reference-rate archive download).
- Not done on purpose: Phase C (his real GIFT City money, Jan-Feb 2027), TCS and the wire/repatriation costs, a lab policy for the US (the baseline is the only policy), the loop's and lab's `market=` plumbing beyond the functions above, a
  sector rail for US stocks.

## Tests
`tests/test_s81_us.py`, 34 tests, synthetic data, every tax and cost figure worked by hand in the test: the premium series (point in time), the rail (limit, taper, unknown, sells never blocked, classes, off switch, the rails hook), the US session in
IST across both daylight-saving changes and an early close, FX at the stated source and the month-end tax rate, the start conversion, costs, dividend withholding and credit (25% and 30%, a lower Indian tax), long and short gains with set-off, a
US buy, a dividend and a long-term sale end to end, splits, no shorting and no borrowing, ISIN / pseudo-ISIN / alias, `market="IN"` unchanged (calendar, rails, settings, the rupee paper tables), and the whole `close_us` over two sessions. Also run and
green: `test_s80_core`, `test_s80_tactical`, `test_tax_rules`, `test_s64_us_*`, `test_s64_foreign_tax`, `test_markets_s79`. (`test_s80_screens` has one Edge UI test that needs the headless browser from the Bash tool: environmental.)

## Shared files touched
`src/pflab/core/rails.py` (the six-line hook in `check`) and `configs/core.toml` (two new tables, `[premium]` and `[us]`, appended). Nothing else outside the new files. `core/__init__.py` DEFAULTS was NOT edited: the new modules read their own tables.

## What is left / decisions for him
- The international leg of the core: with these premiums it cannot be filled by India-listed international ETFs. His call: leave that part in cash/index, wait for premiums to close, or (Phase C) use the GIFT City route.
- A CA's reading before real money: the IFSC wording of ss.196(3) / 198(4), the two-date FX reading, the Form 44 deadline, the Schedule FA first reportable year (calendar 2027 for money sent in Jan-Feb 2027).
- The SBI TTBR series and an FBIL feed (the RBI archive is a form, not an API): until then every rupee figure is an estimate.
- Dated events to watch: an increase of the overseas limits (no date), 2027-04-01 (price-band base moves to the previous day's NAV), DST on 2027-03-14 (the IST times move by an hour; the code reads the zone).
