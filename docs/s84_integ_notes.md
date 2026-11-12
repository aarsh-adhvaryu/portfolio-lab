# S84 integ: the real modules of the thinking loop, together (branch `s84/integ`, 2026-11-12)

The modules were built in parallel against a written contract with fakes for each other. `tests/test_s84_integration.py` (11 tests) runs the REAL `watch -> wire -> session -> odds -> rule -> act -> score -> calibrate`,
the desk, recall and the gateway on a synthetic store and synthetic bars, with a SCRIPTED vendor client injected through `gateway.set_client` (no paid call, no real data).

## Mismatches found and fixed (cause, and where)

1. **The answer shape (`session.py`).** The case's validated answer has ONE `likelihood` for the case and choices with only `symbol`; odds and the rule read `choices[{isin, symbol, option, words, base_rate_set, reason}]`.
   `_normal` now builds exactly that (`words` from the likelihood, the ISIN of each symbol from the store, `pending_resolved_on`), and maps the model's base-rate set ("5"/"20"/"60") to odds' vocabulary ("history"; "own range" stays).
   Before this a choice with no ISIN took the case's own name (wrong for a second name), and "20" was read as an EVENT KIND by `odds.option_table`. `pending_resolved_on` is now an optional field of the answer schema (the rule's "10 sessions after the outcome is public" guard had no way to be fed).
2. **Option tracks (`session._decide_all`).** The case stored the table rows as track "table" and the model's row a second time; `odds` and `score` say: every row of the table is stored (the model's choice "model", the rest "alt") and the rule's choice is track "rule" via `rule.option_row`.
   Now so. The rule's hold/freeze/wait/nothing rows (no outcome of their own) take the table's rupees for that option (a zero row would have corrupted the "do nothing" baseline of the scorer).
3. **Rule decision per name (`session._decide_all`).** The case called `rule.decide` once per choice and always read the case's own name's decision; it is now called ONCE with all choices and each name reads its entry of `decide(...)["all"]`.
4. **One cache for the history scan.** `option_table(..., cache=c)` and `decide(..., cache=c)` now share one dict per case (the scan takes 3 to 8 s on the real panel): one scan per case (tested).
5. **A buy's size (`session`).** The rule's `size_inr` for a buy is the PART due now (`parts["total_inr"]` is the whole bet); `act` divides the whole bet by the parts, so a part was bought at one ninth. `act` now gets the whole bet (`_bet_total`). The 1% check uses the rule's own outcome (`outcome.worst_pct_book` of the whole bet), not the table's default-sized row.
6. **Parts of a market case (`session.follow_up`).** A market-wide case has the pseudo-name `MARKET:IN` as its own name but buys an ETF; the follow-up looked for the parts of the case's own name, found none and never bought parts two and three. Parts are now followed by the name actually bought
   (`_part_plans`; the part step carries the symbol), the case closes only when every buy is complete, and a part bought at a follow-up is told on Telegram.
7. **Case kinds (`odds.py`, `rule.py`).** The watch's case kinds are `market`, `overnight`, `event`, ...; odds and the rule knew `market_fall`/`market_down`: a market-wide fall was not recognised (a third of the reserve per name instead of half, no index-ETF rail). `market` and `overnight` are now move kinds in odds, `market` a market-fall kind in the rule,
   and a case of kind `event` reads its base rates by the EVENT's own kind (`leadership_crisis`, `fraud_investigation`, ... from the `thesis_event` signal's detail), not by the word "event".
8. **Scoring was not wired (`wire.py`).** Nothing called `score.score_due` or `score.calibrate`. `wire.sweep` now ends with `_learn`: once a day (and again when a new session was watched), after the close and in the catch-up (the catch-up calls the sweep), never raising (a failure is a visible "thinking failed: score" line).
   The marker is a `paper_acts` row `learn <day>`.
9. **Cost of scoring (`score.py`).** `score_due` scanned the history for EVERY decision on every run, and `calibrate` for every scored decision every day. A decision with everything due already scored now returns before the scan, and the moves a decision saw are kept once as a `moves` step of the case
   (dated the decision day, so it is never "a step today"): one scan per decision for ever (tested).
10. **Text blocks (`session.py`, `wire.py`).** `thinking_text` joined its parts without a full stop ("...looks again 2026-11-06 India reserve: ..."); `wire.today_block` and `report_lines` showed the reserve twice (once inside `thinking_text`, once as its own line); a Telegram text for a SALE said "if it goes badly -Rs 174, most likely -Rs 174, if well -Rs 174" (a sale's own rupees are only its cost):
    it now shows what HOLDING would have meant (worst, likely, best after tax).
11. **Desk (`desk.py`).** The desk's text about a case it thought through read `r["summary"]`/`r["status"]`, keys `think_case` never returns ("... thought through again: done"); it now says the class and the state, or that the session did not finish.
12. **Tests rewritten to the right contract (`tests/test_s84_case.py`).** The scripted `Odds.option_table` now has the `cache` keyword and returns rows with `track`/`chosen` as the real one; the scripted `Rule.decide` has `cache` and checks the answer reaches it in odds' shape (`choices` with `words`); the tracks asserted are `alt`/`model`/`rule` (not `table`). The contract the tests pinned was the one the integration proved wrong.

## Checked and found right (no change)
- (c) `rule.decide` reads `reserve.reserve_status` and `pending_resolved_on`; (e) `think_case` is guarded by its callers (wire: new/unthought cases only; follow-up: `_last_think_day`; desk: "a step today"): a case is thought once a day (tested with the desk after the sweep);
- (h) every model call of `think/*.py` is `gateway.call` with `agent="think"` (session) or `"desk"` (desk); the gate's scan test passes; (i) `app/runtime.py` registers `s84.register_thinking_live` (once, idempotent), `think_loop` is in `jobs.REGISTRY` and in the "thinking" world node.

## What the integration proves (tests)
1. a held name falls 10% in a day: the close sweep notices it, opens a case, Sonnet reads (three tools), Opus answers (class damage), odds builds the table in rupees, the rule sells (the model said hold), the sale goes through the exit manager with the reason "case #N", both tracks and the decision are stored, a Telegram text and Today's `think` block and the 15:45 lines are composed and render; a second sweep does nothing; 25 sessions later `score_due` scores the rule's sell, the model's hold and the options not taken
   (5 and 20 sessions), at 62 sessions the 60-session look; `calibrate` does not move under 20 scored and moves (bounded) once 20 are scored.
2. a market-wide fall, a name not held: a reserve buy in three parts at least 5 sessions apart (follow-ups), at most half the reserve, every part past the independent check, a fourth part never.
3. a bet is sized down so its worst case is 1% of the whole book; `act` refuses a decision whose worst case is over 1%; a name whose range is too wide is refused (nothing bought).
4. the model says sell, the rule says hold: the rule acts; both are scored, the model's sale beats the rule's hold when the price kept falling and the scorecard says so.
5. the thinking session fails (a scripted error): visible "thinking failed", the case stays open, nothing is ordered, the session is still watched; the real close loop still runs and the exit manager sells the name on the filing (thesis break); the follow-up thinks the case through the next session.
6. advisory (forced by `[think] mode`, and by itself after 20 scored decisions behind doing nothing): only the damage sale of a held name acts; a buy and a freeze only report.
7. a freeze from "not yet clear, pending" is read by `core.state` (the baseline), and released when the case closes; the desk works the agenda through the real gateway, recall and session and does not think a case twice a day; recall reaches the case's first message and is counted as used; the history is scanned once per case and once per decision.

## Not proven / known limits
- US paths (`_act_us`, US `outcomes`, the US morning sweep) are not run here: no US account or bars in the synthetic store (as in the other modules' tests).
- The panel-based base rates ("history") run only on a tiny synthetic scale here (the store's own closes); the real 8-million-row panel is the odds agent's real-store run.
- A real vendor call (the structured answer through `output_config.format` on Opus/Sonnet 5.5) is not made: the client is scripted at the vendor's SDK boundary, so the request shape is exercised but not accepted by the vendor.
- `core/loop.py` is still not hooked (the coordinator's); the close is watched by the `think_loop` job after `core_loop` and by the catch-up.
- Watch fires on a held name that OUTPERFORMS a falling market (relative signals are two-sided): in a market-wide fall each held name can open a case of its own (up to the daily cap of 3). By the written design ("also against its market"); say if one-sided is wanted.

## Shared files touched
`think/session.py`, `think/odds.py`, `think/rule.py`, `think/score.py`, `think/wire.py`, `think/desk.py` (all S84 modules); `tests/test_s84_case.py` (the fakes, one track name). No migration. No change to `core/*`, `service/*`, `app/*`.
