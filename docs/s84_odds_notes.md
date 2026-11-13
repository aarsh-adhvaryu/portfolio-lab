# S84 odds agent: T4 outcomes, T5 the registered rule, T8 scoring and calibration, the live protocol

Branch `s84/odds` (worktree `D:\s84_wt\odds`), based on `pm/s84-thinking` (e2551bc). Written 2026-11-12.

## What is built

| file | what |
|---|---|
| `docs/protocols/s84_thinking_live_protocol.md` | the live test, committed FIRST (3e161a1). The JSON block `rule` is the rule's numbers; `tests/test_s84_odds.py` pins it to `rule.RULE`, to `[think]` in `configs/core.toml` and to `think.WORD_P`. |
| `src/pflab/think/odds.py` | T4: `base_rates`, `outcomes`, `option_table`, `bet_size`, `weights`, `norm_answer`, `position`, `closes`, `own_range`, `whole_book`. |
| `src/pflab/think/rule.py` | T5: `decide`, `needs_big_trade_check`, `option_row`, `cfg`, `reserve`, `new_low_guard`, `stretched`, `RULE`. |
| `src/pflab/think/score.py` | T8: `score_due`, `calibrate`, `scorecard`, `advisory`, `tally`, `protocol_ok`, `register`. |
| `src/pflab/learner/s84.py` | `register_thinking_live(con, now)` (one counted test, note `s84:thinking_live`, SHA of the protocol, idempotent), `protocol_ok(con)`. |
| `tests/test_s84_odds.py` | 24 tests (below). |

Shared file touched: `src/pflab/app/runtime.py` (two lines next to the S83 registration: `s84.register_thinking_live`). No migration (the tables are the shared 230-233; I added none). No edit of `cases.py`.

## The shape the other agents must use (contract details the brief left open)

- **The model's answer** (what `option_table` and `rule.decide` read; `odds.norm_answer` accepts `class`/`klass`, `choices`/`options`/`names`/`holdings`, `words`/`likelihood`):
  `{"class": "damage"|"market_fear"|"temporary"|"unclear", "pending": text|None, "pending_resolved_on": "YYYY-MM-DD"|None,
    "choices": [{"isin", "symbol", "option": one of think.OPTIONS, "words": {"worst": W, "likely": W, "best": W}, "base_rate_set": "history"|"own range"|an event kind, "reason"}]}`.
  A word not on `think.WORDS` is dropped (never guessed); missing words give weights 30/40/30 (Swanson).
- **Store the validated answer** in a case step as `payload={"answer": answer}` (the `understand` step): `score.tally` reads the words from there to calibrate. Without it nothing is tallied (no error).
- **`pending_resolved_on`**: the day a pending outcome became public (the `follow_up` sets it in the answer it re-asks for). The rule needs it to apply "no buying of a damage name until 10 sessions after its pending outcome is public"; without it a former-damage case waits.
- **Store both tracks, all options**: `cases.add_option` for EVERY row of `odds.option_table` (the model's choice has `track` "model", `chosen` true; the others "alt"), and for the rule's choice
  `cases.add_option(con, cid, now, track="rule", chosen=True, **rule.option_row(d))` (a buy's rupees are scaled to the part decided now). `score.score_due` values every stored option at the realised move, so an option that was never stored is never scored.
  `cases.record_decision(..., rule_option=d["rule_option"], model_option=<the model's choice>, acted_option=<what was done>, advisory=<bool>)`.
- **Cost of the history scan**: `base_rates` reads the collectors' panel (3 to 8 s on the real 8-million-row file). Pass ONE `cache={}` dict to `option_table(..., cache=c)` and `decide(..., cache=c)` of the same case so it is scanned once.
- **Advisory**: `score.advisory(con, day)`; `decide(...)["thesis_break"]` is True only for the held-name "damage" sale: those are the only sales that may act while advisory.
- **Big-trade check**: `decide(...)["big_trade_check"]` is True for a sale over `[think] big_trade_share` of the whole book and for every `buy_in_parts`; `rule.needs_big_trade_check(con, option, size_inr, asof)` is the same function.
- **The reserve**: `rule.reserve` calls `think/reserve.py::reserve_status` (the case agent's); unreadable = nothing may be spent. Tests pass `reserve_free_inr=`.
- `decide(...)` returns the case's own name's decision plus `all`: one dict per choice (`rule_option, size_inr, parts {n, this_part, part_inr, total_inr, gap_sessions}, reason, guards, refused, thesis_break, klass, pending, held, base_rates_basis, big_trade_check, outcome`).

## Decisions (2026-11-12, each recorded as the brief asked)

1. **Worst / likely / best** are the 10th / 50th / 90th percentile of the move over a 20-session horizon, labelled "a bad case (1 in 10), not the worst that can happen". The index's own drift is taken as zero.
2. **Valuation** of an option = the position's value after tax and charges as if liquidated at the END of the horizon, minus today's marked value. A sale realises its tax now; a hold pays it at the horizon on the lots' holding period then (so the 12-month rule is respected); a loss earns no credit. A trim sells half (`trim_fraction`); the half kept is valued on top of the trim's gains in the same year's base, with the lots the sale used removed from the queue, so the yearly exemption is not used twice (tested by hand).
3. **History** = the collectors' adjusted-close panel (`data/panel/prices.parquet`, 2004 on) plus the store's own closes after it (and every day of a name the panel lacks). The store alone holds only the last ~7 weeks, so without the panel every case would fall back to the own range. A move is a case only for a name that traded at least `[picks] min_liquidity_inr` (Rs 5 crore) that day, 0.7 to 1.4 times the move, same sign, one case per name per 14 days. Added to the protocol before any live case.
   On the real store (copy of 2026-11-12): a -9.5% day gave 9,632 cases, 20-session spread against the Nifty 500 total-return index -14.2% / -0.7% / +18.8% (10th/50th/90th). Event kinds: `regulatory_action` 308 cases, `guidance_cut` 12 (own range), `leadership_crisis` 0 (own range: the kind is new, kgkind builds it).
4. **US**: no US history panel, so US cases always use the name's own range (from its bars); US sales use `us.book.plan_sale` with a stated fallback (today's FX stands in for the tax FX rate) and a label; a US trim does not carry the exemption/year base across (the US has no exemption). The US stock rail is 10% of the SUB-BOOK (A62).
5. **Probabilities**: the three scenario weights are the words' probabilities from `cases.probabilities` normalised to 1; default 30/40/30.
6. **Rule**: held + damage = sell (thesis break, overrides the 12-month guard as `exits.guard_thesis_override` does; the guard's sentence is kept in `guards`); held + unclear + pending = freeze; held otherwise = best expected of sell/trim/hold, a sale needs to beat hold by 1% of the position; adding to a held name only if the model chose `buy_in_parts`. Not held: damage or unclear = wait (pending) / nothing; market fear or temporary = evaluate a buy (independent of the model's option: the class and words are inputs).
7. **The buy**: size = 1% of the whole book / the bad case's loss per rupee (after charges and short-term tax), capped by the stock rail (10% of the whole book, or of the sub-book for the US; a market fall into the core index ETF: the 60% broad-ETF rail) and a third of the reserve (a market fall: half); parts = total/3, at least 5 sessions apart, a later part only while the class is still market fear or temporary; refused (`nothing`, `refused` true) when expected <= 0, the part is under `[rails] min_trade_rupees`, or the reserve has nothing free; timing guards (damage wait, new lows, stretched on a missed run, the gap) give `wait`, `refused` true. The sector rail (25%) is left to the order's own rails.
8. **Scoring** reads each option off the curve the decision STORED (worst/likely/best at the three moves of its own day, recomputed point in time) at the move the stored closes show after 5/20/60 sessions. This needs no lots (a sale may since have removed them), uses the tax the decision saw, and scores EVERY stored option (rule, model, alt). "Do nothing" = the stored hold/freeze/wait/nothing, else 0. Estimates, labelled.
9. **Advisory** is a pure function of the data: >= 20 decisions scored at 20 sessions and the rule's summed `vs nothing` < 0; back to live when the sum is >= 0 (no stored state, so no flip-flop bookkeeping; the decisions made while advisory are still scored, which is how it can return). `[think] mode = "advisory"` forces it (his to set).
10. **Calibration**: stateless tally from scored decisions with a stored answer; a scenario "came true" when the 20-session move reached its point (worst at or under the 10th percentile, best at or over the 90th, likely within the midpoints); a word with >= 20 cases and no correction in 30 days moves toward its hit rate by at most 0.05, inside [0.02, 0.98]. A missing table row is seeded with `updated_on` 60 days back (so the first correction is allowed when 20 are scored).
11. **The model-vs-rule line** (`scorecard()["model_vs_rule"]`): the paired t of (model - rule) `vs nothing` at 20 sessions over decisions where they chose differently, against `counter.t_needed(N)`; `beats` needs >= 20 such decisions. The text says it; it never changes who decides.
12. **Registration**: ONE counted test (`s84:thinking_live`), not two (one loop, not one per market).

## What is OFF / not built
- Nothing is behind a switch of mine. `think_misses_s84` and the nightly "what did I miss" job are S85 (as the prompt says); `scorecard` does not read the table.
- The case agent's calls to `rule.decide`/`odds.option_table`/`score.*` are not wired (their modules); the replay agent's drills should use the contract above.

## Exposed for screens (plain functions returning JSON-able dicts)
- `score.scorecard(con)` -> `{"scored", "vs_nothing_inr", "rule_track", "model_track", "by_word", "skips_ran", "skips_fell", "skips_scored", "skips_total", "model_vs_rule", "advisory", "text", "label"}`; `text` is the plain-words block for Today and the reports (it says "under 20: a count, not a rate").
- `score.advisory(con, day)`, `score.calibrate(con, day)`, `score.protocol_ok(con)`.
- `odds.option_table(...)` rows: `option, worst_inr, likely_inr, best_inr, expected_inr, worst_pct_book, tax_inr, size_inr, basis, weights, probabilities, notes, label`.
- `odds.base_rates(...)`: `{5, 20, 60: {n, p10, p50, p90}, basis, history_n, detail, index_adjusted}`; `detail` is one plain sentence ("9,632 cases of ..." / "only 12 past cases (under 20): the name's own range ...").
- `rule.decide(...)["reason"]` is a plain sentence in rupees for the Telegram text / the morning report.

## Tests (`tests/test_s84_odds.py`, 24; all pass; with `test_s84_cases.py` and `test_s83_picks.py` 49)
protocol JSON pins; base rates from history with the count and no look-ahead; the long panel is the history and the store the recent days; under 20 cases the own range; a sale and a hold and a trim worked by hand (charges, 12.5% over the exemption, the exemption not used twice); a buy worked by hand (charges, 20% short-term); the 1% bet size and a wider bad case sizing it down; the option table with the store's probabilities moving the weights; damage = sell and unclear+pending = freeze; the 1% bar of a sale; the three caps of a bet; refusals (too small, not positive, no reserve); the timing guards each way (new lows, damage wait 4 vs 11 sessions, stretched missed run); three parts 5 sessions apart and the market-fall half reserve; both tracks stored and differing; the big-trade check; the US stock rail; scoring at 5/20/60 with the curve worked by hand, once only, not before due; the scorecard; the advisory fallback on at 20 scored when behind and off when ahead; the forced advisory; calibration (no move at 19, bounded monthly steps after 20, floor and ceiling, weights follow); skips that ran/fell; the registration once with the protocol's hash and a changed protocol seen.

## Not verified
- US paths (`_sale_us`, `outcomes` for a held US name) are written against `us.book.plan_sale` but only the US stock rail is tested; no US account exists in a test store.
- Real-store run on a COPY (D:\s84_scratch\odds\real): `option_table` and `rule.decide` on a held name returned plausible rows (sell, trim, hold, buy sized by the 1% limit; damage = sell; unclear = freeze) at ~5.5 s per case with the cache; the reserve was "unreadable" there because `think/reserve.py` is the case agent's and not in this branch.
- `leadership_crisis` history is empty until the kgkind classification is rebuilt.
