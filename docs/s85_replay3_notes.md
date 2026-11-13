# S85 replay3 (L3): the India-rotation, Indian-governance and March-2020 replays, and the scoring of market/macro cases (branch s85/replay3, 2026-11-13)

Based on `pm/s85-entrance` (the wide watch merged). A SCRIPTED model everywhere: no paid call, no key read. Full day-by-day accounts (the loop's own output, step by step) are in `docs/s85_replay3_accounts/`.
Every episode is a DRILL, never a result: history is not evidence (rule 2); each proves that the machinery does what its rule says on a real tape.

## What is built
1. **Market/macro scoring (S84 flag closed).** `think/score.py`: `proxy_closes(con, isin, symbol, asof, root)` (new function at the end of the file) gives a `MARKET:<IN|US>` case the closes of the watch's own index
   (`watch._index`: Nifty 500 total return index, SPY) and a `MACRO:<KEY>` case the stored series (`story.series.load`), cut at the day (point in time); `_path` calls it (3 lines) only when the name has no closes of its own.
   Tests (`tests/test_s85_replay3.py`): proxy reads the right index and nothing after the day; a market case is scored at 5 and 20 sessions on the index path (waiting is the baseline, buying beat it when the index rose; scored once only);
   a macro case on its series; no stored series gives 0 rows and no error. (A market case whose choice is the index ETF was already scored on the ETF's own closes; this covers a hold/wait/nothing on the pseudo-name itself.)
2. **The harness** `tools/replays_s85.py` (+ `tools/replays_s85_select.py`): the S84 world (the drills' synthetic rupee profile, `replays_s84.py`) seeded on a REAL past date, its names given REAL closes from the stored panel
   (`lay_real`: rescaled so the seed close is the profile's own, every later percentage real), the real Nifty 500 TRI revealed by the world's clock (REVEAL root = a folder of real series), the profile's lots re-dated before the start
   (the profile's lots are dated 2024-25: in a world of 2018 or 2020 they would come from the future and the exit manager would ignore events "before the plan opened"). Scripted answers: class, option, likelihood words, no number.
   `python tools/replays_s85.py drills --only replay_rotation|replay_governance|replay_march2020` (about 7-10 minutes each; `S85_REPLAY_REUSE=1` re-evaluates the checks on the stored result of the last run, for changing a check only).
   `python tools/replays_s85.py select` writes `selection.json` (the choices below, by code). Output: `S85_REPLAY_OUT` (default `D:\s85_scratch\replay3\out`).

## Verdicts (each drill PASSES; checks in the drill's evidence)
| drill | result | choice (by code) |
|---|---|---|
| `replay_rotation` | PASS (real run, 418 s) | 12-27 Nov 2018: METALS basket -9.2% (16 members), IT basket +9.8% (10), Nifty 500 TRI +1.4% in 10 sessions |
| `replay_governance` | PASS (real run, 524 s; held and not held in one drill) | Manpasand Beverages, statutory auditor resigned, stored 28 May 2018 |
| `replay_march2020` | PASS (real run, 521 s) | Nifty 500 TRI first 20-session fall past -10% on 9 Mar 2020 (-13.6%) |

### (1) India rotation, why this window
Chosen by `select_rotation`: equal-weight industry baskets of at least 6 members from the stored sector map (Nifty 500/200/100 members), the panel's split-safe closes, every 5th session from 2012 except Feb-Jun 2020; a window where one basket fell
at least 5 points and another rose at least 5 in 10 sessions with the index within 1.5 points; the largest min(fall, rise) wins. The six most liquid members of each basket are the names. The profile's three held names carry the real closes of
the falling basket (SHANKARA, PRAKASH, TATASTEEL); four real names of the rising basket (63MOONS, VAKRANGEE, NIITLTD, HCL-INSYS) are added with their real closes and are what the wide watch looks at (the Nifty 500 membership/weights are not in a
synthetic world: `wide.universe` is replaced by these names, `wide.scan`/`commit`, the watch, the cases, the rule are the real code).
Day by day (the run starts 2 Nov, ten days before the window): 5 Nov the wide watch notes 63MOONS 23 points ahead of the index in 20 sessions (`wide_run_20d`), a case opens, class temporary, the model says buy in parts, **the rule says nothing: "it is 2.6 of its usual daily moves
above its 20-session average (limit 2.5): wait for a pullback towards Rs 23.54"**. 6 Nov HCL-INSYS: case, the rule buys part 1 (Rs 12,411 of Rs 37,232, bad case within 1% of the book). 12 Nov (the window's first day) 63MOONS bought (part 1, Rs 12,450) and NIITLTD case opens and is
bought; 26 Nov NIITLTD part 2. Every part keeps its bad case under 1% of the whole book (0.07% to 0.3% a part). In two lines: "63MOONS was noticed by the wide watch while metals fell and IT rose with the index flat; the scripted model said buy in parts. The rule waited
for a pullback on 5 Nov (stretched by 2.6 against a limit of 2.5) and put in the first part of Rs 12,450 on 12 Nov." The held metals stand-ins fell 5-27% but opened no case (under every line of the watch: the fall line is 20% in 10 sessions or 15 points against the market).
A VAKRANGEE case (real: it fell 31% in 10 sessions before the window on its own news) is the one non-rotation case; the rule refuses to buy while it makes new lows.

### (2) Indian governance, why this event
Chosen by `select_governance` from the stored red-flag events (FRAUD, FORENSIC_AUDIT, REGULATORY_ACTION, AUDITOR_RESIGNATION with a usable time): the largest 5-session fall after the event among names with above-median traded value and 250 sessions of history, with the
stored closes running through the five sessions (a first choice, Vakrangee 2018, was thrown out: the panel has no closes for it after 26 Apr 2018, which made "five sessions" weeks; the code now requires the closes to be continuous). Manpasand Beverages, Deloitte resigned as statutory
auditor (filing dated 28 May 2018; the stored time is the date only, so by A58 it is used from the next trading day's open, Tue 29 May 09:15); the shares fell 20% on 28 May, 20% on 29 May and were 64% under the 25 May close by 12 Jun. The kind is the stored flag (`auditor_resignation`, high),
the case is a thesis-break kind; no clearer stored event of a promoter/leadership kind exists in the red-flag table (it has no such flag), so the best stored governance event is used, as the brief allows.
HELD (a stand-in holding carries its closes): the exit manager's thesis break fires at the close of 29 May (the day the event is usable) and sells the remaining 65 shares, filled at the 30 May close, Rs 859 against Rs 1,492 on 25 May and Rs 540 on 12 Jun: **holding on instead would have lost a further 37%
of the sale value by 12 Jun (Rs 20.8k on this synthetic stake); the sale price is itself 42% under the 25 May close, the last before the news**; no buy after the event. (An unrelated 22 May rail trim of 15 shares is in the same list.) The thinking case on the name (opened 21 May on a +11.7% move) was thought again only on 4 Jun (finding 3) and agreed: wait/freeze.
NOT HELD (the system had passed earlier; SYNPICK1 carries the closes): the wide watch stores the `thesis_event` signal on 29 May with the day's falls and joins it to the case open on the name; on 4 Jun the model says damage/nothing and **the rule says wait ("no buying until the outcome is public and 10 sessions after it; looks again at the company's reply and the new auditor's
appointment")**, a freeze on the name is stored (4 Jun, renewed 11 Jun), nothing is bought or sold: passed and watched.

### (3) March 2020
World seeded 2 Mar 2020; the whole profile carries real closes (large caps for the stocks, NIFTYBEES, GOLDBEES, JUNIORBEES for the funds); the real Nifty 500 TRI is revealed by the clock. Day by day: the market case ("Nifty 500 is down 14% in 20 sessions") opens at the close of **9 Mar**, the first close past the 10% line;
the scripted model reads market fear and says buy the index fund in parts; the rule says hold at 9, 16, 23 Mar because the fund "still makes new lows (a buy needs 3 sessions above the low)" (read-only probe each close, the rule's own reason is not shown for a held fund, finding 1); the guard clears on 26 Mar; **part 1 (Rs 6.8k, a third of a bet sized by the 1% limit) is bought on 30 Mar**
(the case looks again weekly: 9, 16, 23, 30 Mar, 6 Apr); part 2 waits "0 to 4 of 5 sessions" then the fund makes a new low on 3 Apr; 9 Apr the guard clears again (so part 2 would follow at the next look, outside the window). Base rates: "history, n=20" on 9-11 Mar, then "own range" from 12 Mar as the point-in-time history thins (n=2, then 0): the fallback shows. (The history is that of the eight real-shaped names of the world, so its count is an artefact of the world, not a finding.) Never more than 3 parts, at least 5 days apart, within half the reserve.
Scoring: 0 rows (nothing is 5 sessions old yet at 9 Apr).

## Findings in the code of others (reproduced by the replays; nothing was changed outside the tools except the drills' NoThread)
1. **`think/rule.py _decide_one`: a refused buy of a name the book already HOLDS is reported as a sale test.** For a held fund or stock the buy branch's guard text (new lows, the stretch limit, the gap between parts) is dropped and the reason reads "Hold: no sale beats holding by 1% ...". The stored decision cannot say why a part waited (seen 3 times in March, and for 63MOONS' part 2). Fix: when the model's option is buy_in_parts and `_buy` refuses, return its guards as the reason. The replays read it with a read-only probe of `rule._buy`.
2. **The core baseline sells the index fund soon after a case buys it.** In March 2020 the case bought part 1 on 30 Mar (Rs 6.8k); the baseline sold 89 units of the same fund at the 1 Apr close (it had sold 89 and 91 on 6 and 9 Mar before the case existed): a sale of the same order of size as the part, the next session but one. Two layers act on one fund against each other; the reserve bet is supposed to be extra, not netted out.
3. **A case is thought again by its calendar, not by a new thesis event.** Manpasand: the thesis event and a 40% fall were joined to the open case on 29 May, the model was asked again only on 4 Jun. March: the guard cleared 26 Mar, the next look was 30 Mar (S84 finding 6, still open). The exit manager (held) and the "no buying while a case is open" kept the money safe; a not-held name's damage reading came a week late.
4. **`tools/drills_s81.py` `NoThread` had no `is_alive`**, so the S85 chat intake logged "did not start" in every world after the first of a process. Fixed here (3 lines).
5. **`session.validate_answer` refuses names with digits** (`SYNFMCG1`, `S&P 500`) unless the first message holds them (S84 finding 7, still open): tests pass the names as known text.
6. **`odds.closes` has no price path for MARKET:/MACRO: names** (its guards for a case on the pseudo-name itself see nothing); closed for scoring here, not for the rule's guards (a market case buys the index ETF, whose closes exist, so the rule is unaffected).
7. The panel can lack a name's closes after a date (Vakrangee after 26 Apr 2018); the stored `usable_from` of a red-flag event is a date only (00:00). Both are handled in the selection, not in the data.

## Shared files touched
`src/pflab/think/score.py` (a function at the end of the file and 3 lines in `_path`), `tools/drills_s81.py` (`NoThread.is_alive`). New: `tools/replays_s85.py`, `tools/replays_s85_select.py`, `tests/test_s85_replay3.py`, `docs/s85_replay3_accounts/`. No migration (280-284 unused), no config key, no `core/*`.

## Tests
`tests/test_s85_replay3.py` (6): proxy closes and point in time; market case scored at 5/20 on the index path; macro case on its series; no series -> 0 rows; every scripted answer of the three replays passes `session.validate_answer` with no figure; `lay_real` keeps the seed close and makes later moves the real ones.
Also run green with it: `test_s84_odds.py`, `test_s84_integration.py`, `test_s81_drills_harness.py` (see the report). The three drills are minutes long and are run by command, not by pytest.

## Exposed for screens
`score.proxy_closes` (a Series); the accounts are plain text (`replays_s85.R.account` blocks) the morning report or a "how did it behave" page may quote.

## What is OFF / not built
Nothing is behind a switch. Not built: a real-model path for these replays (no paid call by instruction); the replays' scoring at 20 and 60 sessions (the windows end soon after the decisions); the exam's reference answers for the new replays (the `exam` agent reads the six it has).

## What I could not verify
The wide watch's Nifty 500 membership/weight path in a world (replaced by a stand-in universe: its own tests cover it); the rotation's held side (no case opened for the held metals names: the fall is under every line); the real model's reading of any of these (scripted).

## Decisions needed
1. Finding 2 (the baseline selling the fund the reserve bet buys): his or the coordinator's call whether a reserve buy should be protected from the fall gauge for some sessions.
2. Finding 3: re-look a case when a new thesis event joins it (my default: yes), and at the date a timing guard clears.
3. Finding 1 is a one-line change in `rule.py`; left for the owner.

## Lines for the coordinator
BUILT.md: `think/score.py proxy_closes` (a market/macro case is scored on its index/series); drills `replay_rotation`, `replay_governance`, `replay_march2020` (`python tools/replays_s85.py drills --only <name>`). PLAN.md "What remains": findings 1-3 above.
