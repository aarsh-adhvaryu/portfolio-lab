# S82 us: the US sub-book is ONE book with the rupee book (A56-A59), notes of the `us` agent, 2026-11-11 night

Branch `s82/us`. Brief: `D:\s82_scratch\briefs\us.md`. Tests: `tests/test_s82_us.py` (26, synthetic), `tests/test_s81_us.py` (rewritten where behaviour was retired).

## What is built
- `us/transfer.py` (new): the transfer out of the rupee book's cash. `debit_rupee` writes, in the system's own account, two ledger `withdrawal` events (fake bank first, then fake broker, ref `us_transfer:<id>: ... moved to the US paper sub-book`),
  in the paper-only mode a `paper_cash` row of kind `us_transfer`. `fund` = debit the rupee book, credit the sub-book `inr / (rate x (1 + 0.4%))` dollars at the day's rate (source stored), one row in `us_transfers_s82`
  (migration 144, `pm/mig_s79/m_us82.py`). The whole book loses the funding markup (an estimate, `us/costs.py`) and nothing else. `convert_seed` = fault 1's safeguard. `rupee_flows` = the transfers as money OUT of the rupee book.
- `book.open_account(con, now, day, first_inr, fx, share)` opens by the first transfer (it raises, writing nothing, if the rupee cash is short). The 'seed from nothing' is gone.
- `us/wholebook.py` (new): `whole_book_inr(con, day)`, `international_share(con, day)`, `plan_tranche`, `attach(con, state)`, `returns(con)`; `us/report.py` (new): `holdings(con, day)`, `card_summary`.
- `us/policy.py`: the 13-ETF baseline is retired; the policy holds the broad index ETF(s) (`[us] broad_index_etfs = ["SPY"]`) at `invested_share` (95%) of the sub-book. Caps are the sub-book's own through `state["caps"]`:
  broad index ETF `broad_index_cap` 1.0, other ETF `etf_cap` 0.35, a company `stock_cap` 0.10 (of the sub-book). `decide(state, extra=None)` is open to extra names (S83).
- `us/adapter.close_us` handles every pending US session, oldest first (`pending_sessions`); the first run ever handles the latest session only. It opens the account by transfer, converts an old seed, funds a tranche, marks, decides on the last close and
  places orders that fill at the next US open (+5 bps). `service/catchup.py` runs the same step for market US (so a catch-up after days off runs it once per US session; the `us_close` job is the same function and is idempotent per session).
- `us/instruments.py` (C12 SEC part): `refresh_ciks` already used `sec_edgar.get_json`, which builds the contact User-Agent from `PFLAB_SEC_USER_AGENT` or `[sec] user_agent` of the secrets file (never printed). New: `sec_contact_configured()`,
  `refresh_if_due()` (the job calls it once a month; the close function never touches the network, so no test reaches SEC), `map_symbol_keys()` (alias row `US:SYMBOL` -> `ZZ`+CIK, or its real ISIN, from the date the symbol key was first used; no key column changes;
  idempotent), `canonical()` follows a chain, `key_for()` prefers a mapped ZZ key.
- Gap risk text (`adapter.GAP_RISK`): "... a stop acts at the next open, so a gap can pass it ..." in every close result, `report.holdings` and the card.

## Decisions (dated 2026-11-11, nobody awake)
1. `[us] fund_day_share = 0.05`: a tranche is at most 5% of the whole book a day (so the 10% target takes two days), also inside the rails' daily and monthly turnover caps (the rupee book's trades that day and the month's transfers count), and never more than the rupee cash NOT claimed by the rupee book's own open buy orders. One transfer per rupee day.
2. `topup_below_share = 0.08`: after the target was reached once (`share_after` of a transfer, or the share now >= target) the sub-book is topped up only below 8% of the whole book, back toward 10%. Never sold down.
3. The India-listed international ETF's value counts toward the 10%; the US target is 10% of the whole book minus that value. While MON100 is blocked (premium over 2% or unknown) the reason says its share is the US book's to fund. NOT done: the rupee baseline (`core/baseline_v2.py`) still wants `international_pct` in MON100 when it is allowed, so international exposure could exceed 10% if MON100's premium falls under the rail. Decision for the coordinator (a one-line change in `core/sleeves.py` / `baseline_v2.py`).
4. `core/state.py`: `state["value"]` stays the rupee book's (the policy's weights are weights of the book it can trade; changing the denominator would change every rupee order). The whole book is beside it: `state["whole_value"]`, `state["us_book_inr"]`, `state["whole"]`.
5. A transfer is dated, on the rupee side, the IST day it ran (`now.date()`); the dollars are credited on the US session day (so the decision on that close can use them). The whole book counts them from the rupee day (`us_value_usd` subtracts transfers whose rupee day is later), so there is no double count on the day in between.
6. Money out of the rupee book: `paper/book.catch_up` adds `transfer.rupee_flows` to `paper_days.flows`, so the rupee book's time-weighted return and the circuit breaker (`cadence.level_path`) are not hurt by a transfer. `wholebook.returns` is the whole book's return (transfers inside the book, only top-ups outside). `paper/benchmark.status` gets key `whole_book` (value, return, excess against the same benchmark).
7. Conversion of an old seed (`convert_seed`): rupees = seed dollars x start rate x (1 + 0.4%) = the account's `start_inr`; debited on the opening day, or on the first day the rupee cash could pay (a past-dated ledger withdrawal that would overdraw a later event is refused by the replay and retried today). No sub-book row is changed or removed; the rupee book's marked days from the debit day are restated (value, cash) and the first one carries the outflow in `flows`. Recorded once by `rupee_ref = seed_entry:<id>`. Table `us_transfers_s82` is created on the spot if the store is still at the S81 schema (`transfer.ensure_table`). An S81 store that already bought the retired 13 ETFs keeps them (never sold down just for this; an ETF above 35% is not bought more) and the policy simply adds SPY.
8. A tranche (or a fresh account) is "deploying": the sub-book's own daily turnover cap is 100% of it that session (`state["funded_today"]`), else the settled caps (10% a day) would take weeks to invest a tranche.
9. No `us/clock` change. `[us] universe` stays only as the list the collector tracks; `start_share` and `start_inr_fallback` are removed from `[us]`.

## Real path (a COPY of `D:\PL_backup\s82_pre_20261111` at `D:\s82_scratch\us\store`; workshop bars and USD/INR read only)
See the report. The real store has rupee cash 500,000, rupee book 1,123,220 on 2026-11-09, no US account. The real bars end 2026-11-06 (SPY), USD/INR to 2026-11-07, so run 1 is session 2026-11-05 and run 2 session 2026-11-06 (the latest bar has no later open). SEC: no `[sec] user_agent` was available to this agent, so no fetch was made and the keys stayed `US:SPY` (stated by `refresh_if_due`). Dividend re-check on the real bar of 2026-09-18 (SPY USD 1.889): 10 shares -> gross USD 18.89, US withholding 25% = 4.7225, credit and residual Indian tax from the dated rows. No split exists in the 13 ETFs' data (the bars carry no split column and history is restated; no day-to-day round-ratio jump in any of them).

## OFF / not built
- Nothing is behind a switch: `[us] on = true` as before. The stock picks are S83 (policy open to them via `decide(extra=)`).
- The SEC mapping needs the secret: until `[sec] user_agent` is set the US keys stay `US:SYMBOL` (mapped automatically the day the CIK map exists).
- No `us` stops exist yet in the sub-book; the gap-risk sentence is exposed for when they do.

## Shared files touched (minimal hooks)
`core/rails.py` (`clip_weights(..., caps=None)`: 3 lines; the rupee path passes nothing), `core/state.py` (`wholebook.attach` before the return), `core/card.py` (two lines `WHOLE BOOK` and `US SUB-BOOK`, `facts["us"]`), `paper/book.py` (`catch_up`: transfer flows), `paper/benchmark.py` (`status`: key `whole_book`),
`service/catchup.py` (US step), `service/tasks_s79_us.py` (monthly CIK refresh before the close), `configs/core.toml` (`[us]` only).

## Exposed for screens
`us.report.holdings(con, day)` -> {open, on, day, holdings[{symbol, isin_key, shares, price_usd, price_date, value_usd, value_inr, fx_rate, fx_source, cost_usd, after_tax{cost_inr, gain_inr, estimated_tax_inr, return_after_tax_pct, label:"estimate"}}], cash{usd, inr}, open_orders, funding[{transfer_id, us_day, rupee_day, rupees, dollars, fx_rate, fx_source, markup_pct, markup_rupees, phase, reason}], international_share, whole_book, gap_risk, label}.
`us.report.card_summary`, `us.wholebook.whole_book_inr(con, day)`, `international_share(con, day)`, `plan_tranche`, `returns(con)`, `us.adapter.close_us`, `state_us`, `pending_sessions`. Card JSON key `us`; benchmark status key `whole_book`.

## Tests added (tests/test_s82_us.py)
transfer debits exactly (paper-only and ledger modes), no cash writes nothing, seed conversion (no row lost, idempotent, retried, own account, S81 schema, inside the close), SPY 100% / second ETF 35% / stock 10% / rupee rail 35% unchanged, caps from config,
gradual funding inside the turnover cap and the free cash, top-up under 8% and never sold down, blocked India ETF reason, state hook, rupee and whole return, catch-up flows, catch-up after days off once per session (adapter and catch-up stage), decide on the last close and fill at the next open, wait with no rupee cash,
report JSON, card lines, ZZ+CIK with a fake SEC file and `US:` mapping, no fetch without the contact, refused fetch keeps the old map, `market="IN"` unchanged.

## Left
Rupee baseline vs the US share (decision 3); the stock picks and stops (S83); the SEC secret; screens wiring (coordinator).
