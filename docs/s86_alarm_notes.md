# S86: the alarm lane, the US session loop, the fast-forward: what was measured and what it does

His words, 2026-11-13: "As a human trader does, even if Nvidia had not crashed, the trader would keep an eye on it ... An action that turned bad makes sense. An action delayed does not."

## 1. What the real path did before tonight (read from `main` at v2026.11.13; each confirmed in code)
1. News was a day late by design: GDELT's DAILY file, usable from the NEXT day (`kg2/news.py`), topped up every 12 hours, then the nightly rebuild, then at most 40 leads confirmed by the local model.
2. US names had no news at all: `kg2/scope.py` is built from Indian lists; `merge_held` was never called. The US loop saw only SEC 8-K items 5.02, 4.01, 4.02.
3. US names had one price look a day (the IST morning on the last close).
4. `think/watch` did not read same-day Indian filings (only `kg2_event`, after the nightly rebuild); the exit manager had its own fast path.
5. He was told only when a case acted or was over 2% of the book.
6. Nothing said when the system was blind or what happened while it was off.
All six were as the prompt listed them. One correction: `merge_held` exists and is now called by the lane's scope step for the daily collection too (tonight it is NOT wired into the GDELT daily collector's scope file, see "What is not done").

## 2. The sources, measured (13 Nov 2026, about 22:45 to 23:30 IST)
| source | what it returned | speed / limits | carried the Nvidia board-investigation story? | state |
|---|---|---|---|---|
| Google News RSS, one request per company name | up to 100 items a query, minute timestamps, the outlet; `when:6h` keeps a run small | about 1 s a request; no refusal in 60+ requests | yes: the week search returned 100 items for 8-13 Nov, every outlet, from CNBC at 01:42 IST Mon (the first headline the rule calls serious) to Friday | ON |
| Yahoo Finance per-ticker RSS (the host the US prices already use) | the newest 17-20 items for a ticker, no outlet name, minute timestamps | about 0.7 s a request | only the newest items (Friday's for Nvidia): it cannot show an old week, it is a second pair of eyes on today | ON |
| GDELT DOC 2.0 article search | 429 "one request every 5 seconds" on the very first request of each run, from this PC | held names only, at most 6 a run, a 429 stops it for the run | not measurable tonight | ON as a third, often refused (a Problems line, never a failure) |
| BSE announcements (the `filings` job, every 15 minutes 08:00-22:00) | the company's own filings | read by the lane since H3 (no new request) | not applicable (Indian names) | ON |
| SEC EDGAR 8-K items 5.02 / 4.01 / 4.02 (the `sec_8k` job, every 2 hours) | the company's own filings | needs his SEC contact (set) | Thursday's "NVIDIA Announces CEO Transition" | ON (existing) |
Two independent free news sources are ON (Google News, Yahoo); GDELT is a best-effort third. Politeness: one name per request, a pause per host, back-off after a failure (15, 30, 60, 120 minutes), at most 6 GDELT asks a run, a run bounded to 110 seconds.
Median published-to-first-seen over the live hours: see section 5.

## 3. The Nvidia week, honestly: the lane through the real collector, the raw responses at their real times
Harness: `tools/s86_nvidia_week.py` feeds the RAW Google News response of 8-13 Nov (`tests/fixtures/s86/gnews_nvda_week.xml`, public data fetched 13 Nov) to the collector one 15-minute tick at a time from Sunday 8 Nov 18:00 IST, on a scratch store; no finished event is written; no model is called (a stub decides "hold"); nothing is sent. Times are IST.

| | lane OFF (derived from the code's own rules: it never sees a headline) | lane ON, the book HOLDS Nvidia | lane ON, the book does NOT hold it |
|---|---|---|---|
| first serious headline published | Sun 8 Nov 23:36 (CNBC "bipartisan scrutiny", not serious by the rule); the first one the rule calls serious is Mon 9 Nov 01:42 (CNBC "Nvidia investigates CEO ... Chinese spy") | same | same |
| heard | never from a headline (a US name has no news path). Its only path is Thursday's 8-K (filed about 19:26 IST on 12 Nov), the `sec_8k` job within 2 hours, the watch at the next US morning pass: **Fri 13 Nov about 08:00, 12.5 hours after the company's own filing, 4 days and 8 hours after the first story**. The daily price look would have shown the Thursday after-hours fall in the same Friday close | **Mon 9 Nov 01:45, 2.9 minutes after that headline**; Thursday's "Huang resigns" (NBC, 19:23) heard at 19:30, 7.0 minutes | no message (a name the book does not hold is AMBER, stored, in `recall`) |
| case opened | Fri 13 Nov morning | Mon 01:45 (same run), and Thursday 19:30 | none |
| decided | Fri 13 Nov, after the close loop's thinking pass | the case is thought through in the same run (here a stub: the real model's minutes come on top, 30-minute target) | none |
| what it did | a damage case on the Friday after a 27% slide | read, froze new buying until the decision, then the case's own rule decides (sell / hold / wait); an unconfirmed headline never sells by itself | nothing |
Result: first serious headline to "heard" on the book that holds it: **2.9 minutes (Mon) and 7.0 minutes (Thu)**, inside the 20-minute target. First STORY (Sunday 23:36) to heard: 2 hours 9 minutes, because the rule needs a serious word and CNBC's first headline did not have one: that is the limit of rules without a model, and why the local model is asked in the same run for leads the rule cannot place (the model path is wired in `classify.model_classify` for the graph's nightly use; the lane itself stays code-only tonight, see "What is not done").

## 4. The US session loop (H4)
`core/us_session.py`, job `us_session` every 5 minutes (15 in pre-market and after-hours; nothing while the US market is closed), switch `[us] session_loop`. Quotes: Yahoo chart, 1-minute bars with `includePrePost`. Measured delay on the real feed (13 Nov 23:18 IST, regular hours): SPY, NVDA, AAPL, QQQ all 0.0 minutes (the quote time is the minute's end, capped at the moment of the fetch). Fills and the live run: section 6.

## 5. The live hour (the lane against the real sources)
Section filled in from `docs/s86_test_findings.md` after the run: see there.

## 6. What the fast-forward does tonight, and what it does not
Built and tested: the what-caused-what split (beta x index, own part; the sector part is NOT separated: no sector series is stored for one name), the ghost record (`ghost_s86`) of every RED item in the gap (code decisions: a HIGH break sells, a medium one freezes), fills at the first close after the decision minus 5 bp, the cost of being off in the "while off" message, scoring at 5/20/60 sessions in the column `replayed_while_off` (pre-tax), once per (gap, release), no replay for a gap that began before the release.
NOT built tonight (switched off by absence, listed for Saturday): the replayed MODEL look (at most 3 cases a gap, no live web); minute-by-minute steps for sessions with minute bars (a gap is replayed on closes); after-tax ghost scoring.
