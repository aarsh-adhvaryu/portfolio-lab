# S83 score agent notes (L4 pick scorecard, L7 stress scenarios)

Branch `s83/score` (based on `pm/s82-gaps` 1960e33). Migrations 175 (`m_score83.py`) and 185 (`m_stress83.py`); 176-179 and 186-189 spare.

## What is built
- `src/pflab/core/pick_score.py` (L4): `score_all(con, now, root=None)`, `scorecard(con, market, day=None)`, `scorecard_text(con, market)`, `sleeve_record(con, market, day=None, window=None)`,
  `update_sleeve_daily(con, now, root=None)`. Tables `pick_scores_s83` and `pick_sleeve_daily_s83` (the contract's columns, plus trailing `index_raw_pct, symbol, detail_json` and
  `index_return_raw, detail_json`; nobody else writes them).
- `src/pflab/core/stress.py` (L7): `scenarios(root)`, `run(con, day, market="ALL", root=None)`, `store`, `run_and_store`, `latest(con, scope=None)`. Table `stress_s83` (the contract's columns).
- Jobs `pick_score` (`service/tasks_s79_pickscore.py`) and `stress_daily` (`service/tasks_s79_stress.py`): due when `core_loop` or `us_close` finished after their last run; they set
  `ondemand.AFTER[...]` on import, so `service/ondemand.py` is NOT edited. `pick_score` also reports `failed` when a market's sleeve update fails.
- Card hook (`core/card.py`): `facts["picks_score"] = {"IN": scorecard, "US": scorecard}` and one text block "PICKS SCORE (after estimated tax, against the index)" appended after the
  CHANGED line. The picks agent's `picks` key and PICKS section are not touched.
- Tests `tests/test_s83_score.py`: 21 tests, all green; `test_s80_core.py` and `test_s81_ondemand.py` still green.

## Decisions (dated 2026-11-11, mine, with the reason)
1. **Start of a pick**: the first session AFTER the day it was proposed (a pick made after the close cannot buy at that close). A horizon `h` is `start + h calendar months`; it is scored once that
   date has passed AND the index has a close on or after it; the end is the last close on or before the horizon date. Point in time: nothing later is read.
2. **A pick that ended early** (withdrawn, stopped, broken) is measured to the day it ended at every later horizon too, so a pick cut early never leaves the record (a survivorship bias that
   would flatter the rate). Its sale is scored separately.
3. **After tax, like with like**: a pick is valued as if sold on the end date (sell charges from `book._charges`, buy charges in the cost; the tax at the rate of the engine's dated row for the
   holding period via `tax_rows.rates`: India 20% short-term, 12.5% long-term, listed non-equity and slab buckets as the book classifies them; US via `us/tax.py`: slab to 24 months, 12.5%
   after, with `us/costs.py` charges and slippage). The INDEX is taxed and charged the same way over the same dates, because an index fund is sold too; `excess_pct` = pick net - index net.
   The raw index figure is kept in `index_raw_pct`. (The literal reading "pick after tax against the raw index" is harsher on picks; it is one line to switch, `_finish`.)
4. **No exemption per pick**: the Rs 1.25 lakh yearly long-term exemption is shared by all of the year's sales, so no exemption is taken per pick (the engine's figure is kept in the detail as
   `exemption_not_taken`). A loss earns no tax credit in a pick's figure. Cess and surcharge are not added. Everything is labelled estimate.
5. **A sale** is scored on the shares it sold, as if kept: the engine's own `exits._score_one` gives what they would have netted on the end date after tax and charges; `return_pct` = that over
   the sale's after-tax proceeds; the index is what the same proceeds would have made. A POSITIVE excess means the sold shares went on to beat the index (selling cost something); the sentence
   says so. A sale with a split or bonus inside its window is not scored (the lots are in the old share basis) and is listed under `unscorable`. A US sale is price only (labelled).
6. **A skip is price only** (no tax, no charges; index raw).
7. **India stock returns are total returns**: raw store close, the corporate-action factors of `data/corporate_actions/factors.parquet` (ex-date inside the window) and the cash dividends of
   `data/dividends/dividends.parquet` brought to the end share basis. US: Yahoo `adj_close` (dividends reinvested, gross of the 25% withholding) in rupees at `us/fx.rate_for` for the start and
   end dates (source stated in the detail). The stock must have a close within 10 days of each end date or it waits ("unscorable" with the reason).
8. **Headline counts use each pick's longest scored horizon**; `by_horizon` has the per-horizon counts; `by_source` splits "system" from "kite". Under 20 scored picks `ahead_rate` is None and
   `note` is "a count, not a rate". Sales and skips are summarised separately (`sold_right`, `missed_chances`).
9. **The sleeve record** (`pick_sleeve_daily_s83`, one row per marked day): India sleeve = positions whose `sleeve_of` is `longterm`; US sleeve = the sub-book's holdings other than SPY. Its day
   return is after estimated tax: value if sold (sell charges, tax on each lot's gain at the engine's rate, no exemption), time-weighted (buys and sales are flows, dividends are income). The
   index is the same: its after-tax liquidation value from the sleeve's first day, so both are net of tax. Fractions in `sleeve_return_after_tax` / `index_return`; `index_return_raw` is the plain
   index. Lots at a past day are taken from the current lots (acquired on or before the day, FIFO up to the day's quantity): exact for the normal one-day step, an estimate for a long catch-up.
   `sleeve_record(...)["points_a_year"]` = annualised sleeve minus annualised index in percentage points, None under 20 sessions; `window=N` gives the last N sessions (L5 uses 120).
10. **Stress**: sign convention is signed returns (negative = a fall). A holding's fall is its own return in the window where its adjusted history (`data/panel/prices.parquet`, else the NAV
    history, US: `data/us/raw`) covers both ends within 10 days; else the estimate `market fall x beta` over the last 250 sessions (weekly returns when the market is the Nasdaq and the share is
    Indian; daily otherwise), floored at -100%; no beta measurable (under 60 daily / 40 weekly returns): 1.0, said so in the detail. A US share's rupee fall adds the dollar-rupee move of the
    window (FRED's longest series). Markets: Nifty 500 TRI (Indian shares), rupee gold (gold funds), rupee Nasdaq (India-listed international funds), SPY (US shares); the AI scenario uses
    the Nasdaq for every share. AI bubble = two windows, each reported under `windows`, the worse by book fall is the headline (`window` says which). The dollar scenario hits only the US
    sub-book including its dollar cash (basis "stated shock"); the India book is "not hit".
11. **Whole book**: `pflab.us.wholebook.whole_book_inr` is used when importable (it is not in this branch: the fallback ran, and `whole_book_source` says so); the fallback is the rupee book plus the
    US sub-book read from `us_account_s81`, `us_lots_s81`, `us_cash_s81` and `data/us/raw` (not `us.report.holdings`, whose shape I could not see in this branch).

## Real path (run on a COPY of `D:\PL_backup\s82_pre_20261111` at `D:\s82_scratch\s83score\store`, real prices read only from `D:\PortfolioLabApp\data`; book day 2026-11-09)
`stress.run` worked on his seeded holdings (8 Indian names, no US sub-book; per-holding output in `D:\s82_scratch\s83score\real_stress_output_empty_us.txt`, kept out of git: it names his holdings).
Windows in the data: all five exist (Nasdaq from 1971, S&P 500 from 1970, Nifty 500 TRI from 2004-01-01, dollar-rupee from 1973); the Nifty 500 does NOT cover 2000-02, so the AI scenario uses
the Nasdaq as the market series for every share (the 2000-03-10..2002-10-09 Nasdaq fall is -77.9%, the 2021-11-19..2022-12-28 one -36.4%).

| scenario | India book (fall of the whole book, cash counted as no fall) | US sub-book (copy, SPY only, 10% of the book put in for this test) | whole |
|---|---|---|---|
| AI spending bubble bursts | -14.5% (2000-02 window; the 2021-22 window gives -9.4%) | -36.1% (SPY in rupees, 2000-02 window) | -16.5% |
| 2008 | -38.0% | -36.6% | -37.9% |
| 2020 | -21.9% | -29.3% | -22.6% |
| the dollar falls 10% | 0.0% | -10.0% | -0.9% |

With the US sub-book empty (as in the app's store today) the US column is 0 and the whole equals India. In the 2008 and 2020 windows 5 and 4 of the 8 Indian holdings had their own history; the others
(shares listed after those dates) are labelled `estimate` (beta to the Nifty 500 of 0.8 to 1.6, or 1.0 where too little history). The worst holding in 2008 and 2020 is a recently listed share whose
estimate is the straight-line beta (about -98% in 2008): this overstates a deep fall for a high beta (the floor at -100% never bites), it is the stated method and labelled estimate.
Also on the copy: `update_sleeve_daily` stored 3 India days (sleeve since 2026-11-06: +0.42% after estimated tax against +0.40% for the index, 2 sessions, too early to annualise), `score_all` scored nothing
(no picks, sales or skips yet), `scorecard_text` says "nothing has been scored yet".

## Exposed for screens (plain functions, JSON-able dicts; nothing here writes except the two jobs)
- `pick_score.scorecard(con, market, day=None)`: `{market, as_of, index, picks_scored, picks_ahead, ahead_rate (None under 20, then note "a count, not a rate"), mean_excess_pct, by_horizon {1,3,6,12: {scored, ahead, ahead_rate, mean_excess_pct, mean_return_pct, mean_index_pct, note}}, by_source {system, kite}, sleeve {return_vs_index_points_a_year, worst_fall_sleeve, worst_fall_index, sessions, sleeve_return_after_tax, index_return, excess_points, since}, recent [{kind, symbol, horizon_months, excess_pct, sentence}], skips {...}, sales {...}, label}`.
- `pick_score.scorecard_text(con, market)`: plain words for the strategist's first message and the reports.
- `pick_score.sleeve_record(con, market, day=None, window=None)`: `{market, sessions, since, to, sleeve_return_after_tax, index_return, index_return_raw, points_a_year, excess_points, worst_fall_sleeve, worst_fall_index, label, note}` (fractions; the picks agent's share rule reads this).
- Book card JSON key `picks_score` = `{"IN": scorecard, "US": scorecard}`.
- `stress.scenarios(root=None)`: the five scenarios with their windows, which series cover each, the Nasdaq fall of each window.
- `stress.run(con, day, market="ALL", root=None)`: `{day, market, scopes: {IN|US|ALL: {value_inr, holdings, scenarios: [{scenario, book_fall_pct, holdings: [{symbol, market, value_inr, fall_pct, basis ("own history"|"estimate"|"stated shock"|"not hit"|"no data"), detail}], worst_holding {symbol, fall_pct, basis, loss_inr}, window, windows (AI only), book_value_inr, loss_inr}]}}, scenario_windows, whole_book_source, us_fx, label, sign}`.
- `stress.latest(con, scope=None)`: the last stored day (`stress_s83`), same shape per scenario.
- Tables: `pick_scores_s83`, `pick_sleeve_daily_s83`, `stress_s83`.

## Shared files touched
`src/pflab/core/card.py` (a 4-line hook before the return plus the helper `_picks_score`). Nothing else shared; `service/ondemand.AFTER` is set from my two job modules.

## Not verified / left
- The picks agent's `picks_s83` / `skips_s83` were not present in this branch: the tests create the contract's columns themselves (`CREATE TABLE IF NOT EXISTS`); after the merge check that their real table
  has `pick_id, market, isin, symbol, source, state, proposed_on, state_changed_on` under those names (read by name in `_score_picks_and_skips`).
- The US sleeve update (`_sleeve_days_us`) and the US dividends path were tested only through the pick score and the stress run, not through a marked sub-book with trades; it is guarded (a failure is
  reported as `failed` in the job, never raised) and the US sleeve starts empty.
- No `pflab.us.wholebook` in this branch: the stress test for its import path uses a stub module.
- The scorecard of a real pick could not be run on real data (no picks yet).

## Decisions needed
None required. Two choices he or the coordinator may want to revisit: (a) taxing the index alike in the scorecard (decision 3), (b) a multiplicative (log-space) estimate instead of `fall x beta`
for high-beta names in deep falls (decision 10).
