# S83 tools agent notes (L2: what the strategist may look at to choose)

Branch `s83/tools` (from `pm/s82-gaps` 1960e33). Migration 190 (`pm/mig_s79/m_tools83.py`; 191-194 spare). Written 2026-11-11 night.

## What is built
- `src/pflab/lab/screen.py` (new): `screen_stocks(con, now, market, filters=None, sort="momentum_126", n=40, root=None, fetch=None, get=None, detail="full")` and
  `company_card(con, now, market, symbol, root=None, get=None, fetch=None)`. Also public helpers: `features`, `rule_verdicts`, `labels_text`, `brief_row`, `fit_card`, `us_universe`,
  `refresh_us_universe`, `us_download`, `parse_company_facts`, `us_facts`, `india_liquidity`, `india_closes`, `shareholding`, `memberships`, `red_flag_table`, `announcements`, `deals`.
- `src/pflab/us/picks_floor.py` (new): `check(con, symbol, day, root=None)` -> `{"ok","reason","price","median_value_usd","sessions","last_bar","symbol"}`; `floor_from_bars(sym, df, day, max_age_days=10)`;
  `tradable_note(symbol, root=None)`; `on_list(symbol, root=None)`; `gift_list(root=None)`.
- `data/us_prices.py`: `held_symbols(con)`, `picked_symbols(con)`, `tracked_symbols(con, pm_dir=None)` (ETFs + SPY + held + picked/skipped + his list).
- Tools `screen_stocks` and `company_card` registered in `lab/tools.py` (descriptions say every number is code and what the labels mean). `propose_picks`, `withdraw_pick`, `skip_idea` are NOT written (strategist agent).

## Decisions (dated 2026-11-11)
1. **India universe = every NSE-listed share (INE key) with a median traded value of at least Rs 5 crore over the last 60 sessions** (a session with no trade counts as 0; series EQ and BE), read from the raw
   bhavcopy (`data/bhavcopy`, complete to the last session, unlike the research panel which ends 2026-10-23). The floor is also the L1 pick floor, so a screen never shows a name a pick would be refused for;
   `min_traded_value_inr` can raise it, never lower it. About 1,030 names pass on the real data.
2. **Prices**: the research panel's adjusted closes joined to the store's `prices` at their last shared date (the `app/research.closes` method, in bulk). A name whose closes show a one-day move beyond 35% in the last
   year (a possible unadjusted split or bonus) is LEFT OUT of a screen (counted in `note`, `include_suspect_prices` shows them, the card flags it). Without this the default momentum sort was topped by split artefacts.
3. **Shareholding** (promoter, FPI, DII = all institutions less FPI, pledged share of promoters) from `bse_shareholding`; a quarter counts from 21 days after its end (the files carry no usable filing date).
   Market cap = shares outstanding of the last public quarter x the last close, labelled an estimate (wrong after a split since that quarter); else "unknown".
4. **Sector**: the dated sector map (never a later capture), else the instruments table's sector, else "unknown". **Index membership**: the point-in-time tables (Nifty 100, 200, 500, Midcap 100).
5. **Insider and bulk deals** are counts and shares in the last 90 days, labelled "context, never a signal (the S48 study failed)". **Results**: the date of the latest BSE "Result" announcement disseminated by `now`.
   **Graph events** from `kg.events.material_events` (empty while the graph is off: the note says so). **Red flags** from `red_flag_events` (usable on or before the day, last 12 months, de-duplicated).
   **Forecast range**: the newest stored range (as_of on or before the day) of the serving plain-statistics method; only held and listed names have one (the card says so otherwise). **Storylines**: open ones that
   have an exposure row for the name, or whose claim names its symbol, company or sector. **Fundamentals**: filed P/E and EPS growth (point in time); the card carries the full `hq/valuation.facts` page.
6. **Rule labels**: `rule_verdicts(con)` uses the learner's claim when the store has one, else the S64 verdicts of `docs/STUDIES.md` (the store copy of 2026-11-11 holds NO rule claims: all "not tested"). Only
   "below the 200-day average earns less" is a reading (an AVOID reading, put on a row that is below its average); P/E above 50 is "narrowly failed", the other five "failed"; momentum and trend are described as
   descriptions; deals as context; US history as survivorship-biased (once in `note`, and `history_warning` per US row). A test asserts no failed rule ever labels a row.
7. **Brief form**: a tool result is cut at 9,000 characters by `lab/tools.run`, and a full 40-row screen is 60,000. `detail="brief"` (what the tool uses) drops nulls and folds lists into short strings
   (about 500 characters a row); rows are dropped whole (and the note says so) if it still exceeds 28,000 characters. HOOK in `lab/tools.py`: `LIMITS = {"screen_stocks": 30000, "company_card": 16000}`
   and `text[:LIMITS.get(name, 9000)]`; the card is shrunk with `screen.fit_card` (drops the longest optional parts in a fixed order and lists them in `trimmed_to_fit`) so the JSON stays valid.
8. **US universe**: the SEC ticker file kept in its OWN ORDER with titles in `data/us/sec_universe.json` (roughly largest company first; `us/instruments.refresh_ciks`'s `cik_map.json` is alphabetical) plus the
   CIK cache, both from ONE fetch (`refresh_us_universe`, which calls `refresh_ciks` with a capturing getter, so S82's User-Agent fix applies). If neither cache exists the universe is the symbols already under
   `data/us/raw` (no names, no CIKs). Weekly refresh hook in the `us_prices_daily` job (`service/tasks_s79_us.py::_prices`): a failure is reported in the job result, never fatal.
9. **US screen**: a name must clear the A62 floor from daily bars (`floor_from_bars`, price at least USD 5, median close x volume at least USD 2 million over 60 sessions). Names with bars older than 10 days
   (the 2026-10-27 backfill; the daily job only refreshed the 13 ETFs) are refreshed on demand with the last 15 days (the ones that would rank first, at most `fetch_cap` = 20 per call, 12 s timeout, stop after
   three failures in a row = network down), else shown and flagged "refresh before picking". Names not on disk are downloaded whole only when named in `filters["symbols"]` or when `grow_universe` is set (the next
   uncached SEC names in file order, `fetch_cap` per call). Never fails with the network down: cached bars are used and the note says so. No sector, index or red-flag filter for the US (ignored with a note).
10. **US company card**: price and 52-week range, floor reason, tradable note, SEC XBRL facts (revenue and net income of the last two filed fiscal years, long-term debt, shares outstanding, each by its own
    filed date), the filings accepted by `now`, graph events (pseudo-ISIN key), and the A62 rails (stock at most 10% of the sub-book, SPY at least 30%, at most 12 stocks, `max_value_usd_now` from the sub-book's last
    marked value, `stocks_held_now`). Facts are cached under `data/us/sec/`; a cache older than 7 days is refreshed in a card (never in a screen); on a failure the old file is used and the card says so.
11. **Screen log** (migration 190 `screen_log_s83`): every call writes one row (day, market, tool, arguments, symbols shown), best effort, so a pick or a skipped idea can be traced to what the strategist saw.
12. **GIFT City list**: NO Zerodha GIFT City list file exists under `D:\PortfolioLabApp\data\us` or in the repo. `tradable_note` returns "assumed tradable, checked before Phase C"; if a file with "gift" in its
    name (csv, txt, json, xlsx) is dropped under `data/us/`, it is read and the note becomes "on Zerodha's GIFT City list (file)" or "NOT on ... list". `on_list` returns True/False/None.
13. **Daily US collection** (`us_prices_daily` job): now `us_prices.tracked_symbols(ctx.con)`: the 13 ETFs, SPY, every open lot of `us_lots_s81`, every symbol of `picks_s83` (any state: a withdrawn pick is scored
    later) and of `pick_skips_s83` / `skips_s83` if those tables exist (each read defensively; a table with no `market` column is filtered by the key: ZZ or US = US). A name with no file is downloaded whole.
    **The picks agent must keep the table and column names `picks_s83.symbol` and `.market` (or `.isin`), and tell me/the coordinator the skips table's name if it is not one of the above.**

## Shared files touched (minimal hooks)
- `src/pflab/lab/tools.py`: two `@tool` registrations, `LIMITS`, `text[:LIMITS.get(name, 9000)]`.
- `src/pflab/data/us_prices.py`: `held_symbols`, `picked_symbols`, `tracked_symbols`, `PICK_TABLES` added (nothing existing changed).
- `src/pflab/service/tasks_s79_us.py`: `_prices` uses `tracked_symbols` and refreshes the SEC universe weekly.
- New: `lab/screen.py`, `us/picks_floor.py`, `pm/mig_s79/m_tools83.py`, `tests/test_s83_tools.py`, this file.

## Tests (`tests/test_s83_tools.py`, 24, synthetic, no network)
at most 40 rows even when asked for 500 (`test_screen_returns_at_most_40_rows...`); India row fields and values (`test_india_row_fields...`); point in time: a close, a bhavcopy file, a shareholding quarter, a
stored range and a red flag dated after the day never appear, and the same data appears when asked for on a later day (`test_a_row_dated_after_the_decision_day_never_appears`, `test_features_use_only_rows...`);
filters (floor, min_momentum, max_volatility, in_index, exclude_flagged, exclude_held, sector, unknown key) (`test_filters_are_honoured`); sorts; screen log and brief size; no failed rule as a signal
(`test_no_failed_rule_is_presented_as_a_signal`, `test_pe_label_for_a_high_pe_says_the_rule_failed`); India card; `fit_card`; US floor refuses a USD 4 stock, a thin one, too few sessions, a stale last bar, no
bars, and is point in time (`test_us_floor_*`); `tradable_note` with and without a list file; the SEC facts parser on a fake payload, point in time; the universe keeps SEC's order and writes both caches in one
fetch; the symbols-on-disk fallback; US screen floor and survivorship warning once in `note`; on-demand download writes the cache, and with the network down returns cached rows, gives up after three failures
and never raises; stale cached names refreshed or flagged; US card from fakes (facts, filings accepted by `now`, rails, cached facts used when the network is down); the daily collection includes held, picked and
SPY (`test_the_daily_us_collection_includes_held_and_picked_symbols`, `test_a_picks_table_with_no_market_column...`); tools registered, valid JSON within the size limit, no `propose_picks` etc.

## Real path (2026-11-11, a COPY of the backed-up store at `D:\s82_scratch\s83tools\store`, real data read only from `D:\PortfolioLabApp\data`; US writes only to the scratch copy `D:\s82_scratch\s83tools\data\us`)
- `screen_stocks("IN", {}, "momentum_126", 40)`: 3.4 s, 1,032 names clear Rs 5 crore a day, 11 left out for a suspect price jump, 40 rows, 19,000 characters in brief form. The top row of the unfiltered screen
  before the jump rule was a split artefact (STLTECH +551% with a 101% one-day jump): the reason decision 2 exists. Example brief row (a NIFTY 500 screen with `max_volatility 0.35`, `exclude_flagged`, `min_momentum 0.05`, 2.3 s, 22,400 characters):
  `{"symbol": "DIVISLAB", "sector": "Healthcare", "indices": ["NIFTY100","NIFTY200","NIFTY500"], "price": 11565.5, "return_63d_pct": 39.3, "return_126d_pct": 72.3, "return_252d_pct": 70.0, "vs_200dma_pct": 55.2,
  "volatility_250d_pct": 25.5, "from_52w_high_pct": 0.0, "traded_value_cr": 481.2, "market_cap_cr": 307028, "last_result_filed": "2026-11-07", "holders": "promoter 51.88% (+0.0pp), FPI 20.19% (-0.1pp), DII 19.39% (+0.2pp) at 2026-06-30"}`.
  A low-volatility Nifty 100 screen listed NTPC with `"red_flags": ["2025-12-01 INSOLVENCY"]` and `"labels": ["below its 200-day average: the one tested rule that passed ...: an avoid reading"]`.
- `company_card("IN", <a Nifty 50 name>)`: 1.1 s, 8,900 characters: held in the system's book (weight and buy room shown), 63-day range 1,212 / 1,374 / 1,579, shareholding to 2026-09-30, P/E 45.7 (its own 5-year median 25), liquidity Rs 1,640 crore a day, rails
  "one stock at most 10%, one sector at most 25%".
- SEC ticker file: **UNREACHABLE** (HTTP 403: the secrets file has no `[sec] user_agent`; checked by a yes/no test, the value never read or printed). So no CIKs, names or SEC company facts were fetched for real; the
  SEC parts are tested on fakes only. Giving a contact in `%USERPROFILE%\.pflab\secrets.toml` `[sec] user_agent = "Name contact@address"` (his to choose, it goes to SEC with each request) switches them on;
  the weekly hook then fills `data/us/sec_universe.json`.
- `screen_stocks("US", {}, ...)` on the scratch copy of `data/us` (516 files, last single-stock bars 2026-10-27): 25 s (20 on-demand refreshes), 40 rows, 14,800 characters. `note`: "480 names had bars older than 10 days; refreshed
  the 20 that would rank first (cap 20 per call); 462 still have old bars and are flagged ...; 4 names left out ... jump". Top rows (refreshed, price_date 2026-11-11): CRL +115% in 6 months, VEEV +98%, BBY +95%.
- On-demand download of names not on disk (SOUN, RKLB, HIMS, IONQ, CELH, ASTS): 6 s, all six fetched from Yahoo into the scratch folder; 4 rows after the A62 floor and the jump rule (CELH, IONQ, RKLB, ASTS: all
  below their 200-day average, each row labelled with the avoid reading); the app's folder was never written.
- `company_card("US", "AAPL")` with no CIK known: bars refreshed on demand, "no CIK known for this symbol: no SEC facts"; floor and rails sections present.

## Not verified / left
- SEC calls with the real SEC (needs the contact above). The `companyfacts` concept names used (Revenues, RevenueFromContractWithCustomerExcludingAssessedTax, SalesRevenueNet, NetIncomeLoss, LongTermDebt,
  dei EntityCommonStockSharesOutstanding) follow the XBRL taxonomy but were only exercised on a fake payload.
- The `picks_s83` / skips table names and columns are the picks agent's; `picked_symbols` is defensive but its names are a guess (see decision 13).
- The strategist's SYSTEM text does not yet mention these tools (strategist agent). Tool results are large (a 40-row screen about 15-25k characters, 4-7k tokens): `n` can be lowered.
- Forecast ranges exist only for held and listed names; a screen row for any other name has none (the card says so). Computing one on the fly was left out (rule 10: no new number without a study).

## Exposed for screens (plain functions returning JSON-able dicts)
- `pflab.lab.screen.screen_stocks(con, now, market, filters, sort, n, root=None, detail="full"|"brief")` -> `{"rows": [...<=40], "note", "summary", "market", "asof", "sort", "filters", "universe", "after_filters",
  "labels": {...}, "fetch": {...US only}}`. Row fields (India): symbol, name, isin, sector, indices, price, price_date, return_63d_pct / 126 / 252, vs_200dma_pct, below_200dma, volatility_250d_pct, from_52w_high_pct,
  traded_value_inr, traded_days_of_60, market_cap_cr, size, held, data_flags, shareholding{as_of_quarter, promoter_pct, promoter_change_pp, pledged_pct_of_promoter, fpi_pct, fpi_change_pp, dii_pct, dii_change_pp},
  insider_sast_announcements_90d, bulk_block_deals_90d, deals_label, last_result_filed, recent_announcements, events, red_flags, price_range_63d, storylines, fundamentals, labels, says. US rows: symbol, name, cik,
  key, price..., range_52w, traded_value_usd, market_cap_usd, floor, tradable, held, facts, recent_filings, events, history_warning, labels, says.
- `pflab.lab.screen.company_card(con, now, market, symbol)` -> one dict (India: price, liquidity, size, shareholding, deals, announcements, events, red_flags, price_range, storylines, held, rails, fundamentals;
  US: price, liquidity, tradable, size, sec_facts, recent_filings, events, rails, history_warning).
- `pflab.lab.screen.rule_verdicts(con)` / `labels_text(...)`: the legend (which rule passed or failed), for any screen that shows these figures.
- `pflab.us.picks_floor.check(con, symbol, day)` / `tradable_note(symbol)` / `on_list(symbol)`.
- `pflab.data.us_prices.tracked_symbols(con)`.
- Table `screen_log_s83` (what was looked at).
