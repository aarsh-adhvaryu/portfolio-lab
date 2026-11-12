# S84 agent `replay`: T9, the replays and the drills of the thinking loop

Branch `s84/replay` (based on `pm/s84-thinking`, merged with it at the coordinator's message of 17:0x). Files: `tools/replays_s84.py` (data, the world, the day loop, the three replays, the real path),
`tools/replays_s84_model.py` (the scripted model), `tools/replays_s84_drills.py` (the synthetic drills), `tools/replays_s84_cli.py` (the command line), a new accelerated step `thinking_loop` and the drill
`accelerated_thinking` in `tools/drills_s81.py`, `tests/test_s84_replay.py` (12 fast tests), one line in `tests/test_s81_drills_harness.py` (the step list names `thinking_loop`). No table, no migration, no config
key, nothing in `src/`.

## What is built

* `python tools/replays_s84_cli.py data` builds the real bars under `D:\s84_scratch\replay\data` only: a fresh Yahoo download (the repo's own `data/us_prices.fetch`) of NVDA, SPY, QQQ, XLK, the S&P 500, the Nasdaq and
  crude, the Nifty indices and the USD/INR close from the app's data (READ ONLY), the missed-run name (kept out of git) and four auto peers in the panel's layout (the workshop's panel to 6 Nov, the app's bhavcopy files after it, to 11 Nov).
* The WORLD is the drills' synthetic rupee profile (invented names, no holding or amount of his) with the real bars laid over it and REVEALED a session at a time by the world's clock (`reveal`, patched into
  `Env.step` and `sync_data_files`): a US bar after its close + 30 minutes, the Nifty from the NSE files' arrival (20:15), the real headlines of the Nvidia week as `kg2_event` rows at their IST time, source
  "press reports" (Sun 8 Nov US evening = Mon 9 Nov 06:30 IST; Mon 9 Nov US = Tue 10 Nov 00:30; Wed 11 Nov after hours = Thu 12 Nov 03:30). A test pins that no bar after the clock is ever in the world.
* The SCRIPTED MODEL is a stand-in for the SDK client behind `llm/gateway.py` (`gateway.set_client`): Sonnet's read is a tool turn and a text, the answer is JSON from the closed lists, no number in it (a test
  validates every scripted answer with `session.validate_answer`). The real governor, the real egress gate and the real `think_case` run; only the model is scripted.
* Replays: `replay nvda_held`, `replay nvda_not_held`, `replay ather` (day-by-day accounts in `D:\s84_scratch\replay\out\*.txt`, `*.json`). Drills: `drills [name]` (eight, below). The accelerated run:
  `python tools/drills_s81.py run --only accelerated_thinking` (ten sessions, India and US, a weekend and a holiday inside, two names shocked, the app's own `think_loop` job doing the thinking).
* The REAL PATH: `python tools/replays_s84_cli.py real` (see "The real path").

## Decisions (2026-11-12, unattended)

1. The rupee side of every world is the drills' synthetic profile, not a copy of the app's store. A copy holds the book, the runs, the cases and the prices up to 12 Nov: a replay of 5 to 12 Nov in it would
   have the store ahead of its own clock (point in time broken) and the model would read his book. The US sub-book is real in structure (the account opens by a transfer, SPY is bought), NVDA is put in at 8%
   of it at the 6 Nov close out of its SPY and cash (`inject_us_position`), so its value is unchanged. The brief's "on a COPY of the app's store" is NOT done for the real path either, for the same two reasons.
   The cost is that rupee amounts are those of a Rs 11 lakh synthetic book (read the percentages); the gain is that nothing of his reaches the model or this branch.
2. Replay (ii) (not held) needed a stand-in for the S85 wide watch: the watch looks at a skipped or screened name for a missed run only. `wide_watch_standin` records the signal and opens the case when a headline on
   the skipped name is public, then `think_case` runs for real. Marked as a stand-in in the case's opened_by.
3. The kind of the headlines is `leadership_crisis` when the classifier has it (it does after the kgkind merge), else the nearest thesis kind with a note in the ref.
4. The replays run with the loop as the wire ships it (watch and think at the close, the US morning and the catch-up) and report what it did; where it did not do what the prompt expects, that is a finding, not a patch
   (below). The harness has one switch, `--no-morning`, that is only the extra morning pass described in finding 1.
5. Paid calls: the real path was run twice (the first run's gating let the app's own close hooks think other cases and one desk call; fixed). Total Rs 8.0, listed below.

## Findings in the code of the other agents (each reproduced by a replay or a drill; nothing was edited outside the tools)

1. **The Sunday news is not looked at on Monday morning** (think/wire.py `pending_sessions`, think/watch.py `_us_morning`). The watch runs for a US session that has closed since the last pass; Monday morning has
   none, and `watch.run(mode="us_morning")` called by hand treats a weekend morning as a past one (it takes Saturday 08:00 as its clock), so the headline (public Monday 06:30) is invisible. The case on NVDA opens
   on Tuesday 10 Nov 09:00, after Monday's session (the stock opened 7.3% under Friday's close). The prompt asks for a case by the IST morning of 9 Nov. Fix: a US-morning pass with the real `now` on every IST
   morning of a day the US had no session (weekend, holiday), `live` true whenever the pass runs the morning it is for.
2. **A US order from a case waits one session too long** (think/session.py `_act_us`): it is placed with the IST date (`day = now.date()`), `us/book.fill_orders` fills only orders placed on an EARLIER session, so
   an order decided on Tuesday morning IST fills at Wednesday's open, not Tuesday's. The NVDA sale: decided Tue 10 Nov 09:00, filled Wed 11 Nov at USD 172.71 (Tuesday's open was 173.97, the close 168.89). The
   close function places its own orders with the last handled session's day; `_act_us` should do the same (`clock.session_closed_by(now)`).
3. **The pseudo-ISIN of a US stock is an "account-like number" to the egress gate** (agents/analyst `_IDS`: `(?<![\d.])\d{9,18}(?![\d.])` matches the ten digits of `ZZ0001045810`). The first message of a case
   passed, the second look of the same case (Thu 12 Nov 07:00, the follow-up) was refused with `EgressBlocked: not sent: account-like number`, every time. Any US case's follow-up is blocked in the real
   app. Fix: scrub the key to the symbol in everything the case session sends (first message, recall text, tool results), or let the pattern not match a digit run preceded by a letter.
4. **The watch reads no news for a US name** (think/watch.py `_us_pass` has the thesis-event line; the graph has no US events until S85, and a skipped or screened name gets a missed-run signal only): replay (ii)
   needs the stand-in of decision 2. Not a bug tonight, the S85 gap in one sentence.
5. **The thinking loop's order can block the same close's baseline** (found in the accelerated run, `[standing]`: "one close-loop row per session: 10 rows for 11, missing 16 Oct"; the same drill without the
   thinking step passes the standing checks). A case that sells at 21:00 puts a paper order in before the core loop of that close; `core.loop.run` waits when an order is open ("orders from an earlier session
   have not filled yet"), so that session's baseline decision is never made and the session has no `core_runs_s80` row. Fix: the case's order belongs after the core loop of the close (the wire runs the sweep after
   `core_loop` in the same job slot), or the core loop's wait counts only its own orders.
6. **A case that the rule refused on a timing guard is not looked at again when the guard clears** (replay (iii), think/session.py `follow_up`/`_changed`): Ather's case said "nothing" (the new-low guard: three
   sessions above the 5-session low), the look on 4 Nov found "changed: false" and nothing was bought or re-decided up to 11 Nov, with the name 27 points ahead of its index. A refusal by guard needs its own look
   date (the day the guard clears) or must count as "changed".
7. **The answer validator refuses index names with digits** (think/session.py `validate_answer`): "S&P 500", "Nasdaq 100", "Nifty 500" in `happened` are "figures the sources did not give" unless the first message
   holds them; a scripted answer failed twice for it before the first message gained the name. The real Opus did not trip on it (it avoided them), a real Sonnet might: whitelist the index names or say so in the system prompt.
8. **A non-security case (market, macro) stores only the rule's track** (`MACRO:USDINR`: options rows `rule` only), so T8 cannot score a model track for them. Minor.
9. The two base drills that exist before tonight FAIL at the head of `pm/s84-thinking`, without my step (`--only accelerated`, `--only accelerated_picks`): `allocation_proposed_and_adopted` (the drill's split
   "gold, international and cash add up to 50% but the core is 44.88%": the S83 caps refuse it) and `picks_learning_book` (the share now starts at 55.1%: F1's start-by-decision, the step still asserts 40% -> 35%).
   Their assertions need the F1/S83 numbers (the fixa agent's change); everything else in both drills passes (48 and 59 checks). Also in every drill's strategist job: `allocation: BinderException: Referenced
   column "open" not found` (the allocation replays read an `open` column the drill's panel does not have).

10. **The Telegram text of a sale shows only the sale's own outcome** (think/session.py `tell`): "NVDA: sell. If it goes badly -Rs 16, most likely -Rs 16, if well -Rs 16" (a sale's worst, likely and
   best are its charges). What he needs is beside it: what HOLDING risked (the stored `hold` row: worst -Rs 1,164, likely -Rs 16, best +Rs 1,032 on that stake). Add the hold row to the text of a sale.

## The Nvidia week, day by day (real bars and headlines; the rupee book is synthetic, read the percentages)

NVDA at 8% of the US sub-book from the 6 Nov close (USD 99.22 of 1,240; 0.8% of the whole book). Closes: Fri 6 Nov 186.64; Mon 9 Nov open 173.07 (-7.3%), close 178.67; Tue 10 Nov open 173.97, close 168.89
(9.5% under 6 Nov, the prompt's figure); Wed 11 Nov open 172.80, close 173.73; after hours about 8% lower (159.83 stands in: a stated level, not a bar).

| IST | what the loop did (replay i, the loop as the wire ships it) |
|---|---|
| Fri 6 / Sat 7 | nothing noticed; the sub-book holds SPY and NVDA |
| Sun 8 US evening = **Mon 9 06:30** | the chief executive's disclosure and the board's investigation are public (`leadership_crisis`, high). **Not noticed**: no US session has closed since the last pass (finding 1) |
| Mon 9 (US session) | gap down at the open, class action filed after the open (`regulatory_action`, medium) |
| **Tue 10 09:00** | the US pass for Monday: `thesis_event` x2 (high, medium), `rel_1d` -6.6% (3.4 usual moves), `rel_5d` -11.7%: one case on NVDA (0.7% of the whole book: under the 2% line, so in the scripted run Sonnet answers; the real path lowered the line so that Opus decided). Class **damage**, pending "the board's decision on the chief executive"; options table: sell (worst/likely/best Rs -16 each: its charges, no tax: the lot is at a loss), hold (worst -1,164, likely -16, best +1,032), buy in parts (worst -12,098 = 1.00% of the book, expected -882: refused). Rule: **sell the whole position** (thesis break); model (scripted) agreed. US order placed with date Tue 10 |
| Tue 10 US session | open 173.97, close 168.89. The order does NOT fill (finding 2) |
| Wed 11 US open | the sale fills at **USD 172.71** (Wed open 172.80 less the slippage) |
| Thu 12 03:30 | second relationship reported, board said to prepare to oust him, about 8% lower after hours (estimate 159.83). The follow-up look (07:00) fails on the egress gate (finding 3). Nothing else to decide: the position is gone |

What it saved or cost, on the stake of USD 99: sold at 172.71 against holding to the after-hours level the Wednesday headline names: **+8.1% of the stake, +USD 6.85 (0.55% of the sub-book)**; against holding
to Wednesday's close: -0.6% (-USD 0.54); against the Friday close before the news: -7.5% (the gap at Monday's open was already in the price when the loop first looked: nobody trades on Sunday evening news before the
open). With the morning pass of finding 1 (`--no-morning` off; stands in for the fix) the case opens **Mon 9 07:00**, the order is dated Mon 9 and fills at Tue 10's open, **173.88** (+8.8% against the after-hours
level; with finding 2 fixed as well it would fill at Monday's open, 173.07). Replay (i) output: `D:\s84_scratch\replay\out\nvda_held_wireonly_final.txt` (as shipped), `out\nvda_held.txt` (with the morning pass).

Replay (ii), NVDA not held (a skip of 5 Nov in `skips_s83`, so it is in the watch's scope; the wide watch is a stand-in, decision 2): case on **Mon 9 07:00** (the stand-in has no weekend problem), class
unclear, pending the board's decision; model wait, rule wait ("Not yet clear: no new money until it is"); a freeze on NVDA until 16 Nov is stored. At the look (Thu 12 07:00, pending date 12 Nov) the case should be thought
again and the scripted model says "buy in parts": the rule would refuse (damage class and pending: no buying until the outcome is public and 10 sessions after it; it still makes new lows). The look failed
on the egress gate (finding 3), so that second decision is **not shown**; the guard logic itself is tested by the drills (`missed_exit`, `bet_sizing`) and by the odds agent's tests.

Replay (iii), Ather Energy (real NSE closes; the synthetic profile around it): the first stored day it closed near Rs 1,400 is 29 Sep (1,407); a skip is recorded that day ("valuation: trailing earnings negative and the
price already well up: not worth it yet"). It closed 1,380 on 23 Oct, then jumped to 1,674 on 27 Oct: **27 Oct 21:00 the case opens, the name 20.6 points ahead of the Nifty 500 total return** (19.0% against -1.6%; the
threshold is 20: it opens the first close it is over). Outcome table for it (Rs, on the synthetic book of Rs 11 lakh): buy in three parts, size 74,557 in all: worst -12,140 (exactly 1.00% of the book), likely -177,
best +11,244, expected -312; wait (for a pullback) 0; nothing 0 (the table has no value for "wait for a pullback to a level": it is valued as nothing). Model (scripted) buy in parts; **rule: nothing**:
"it still makes new lows (its close on 23 Oct was the lowest of the last 5 sessions, three sessions above it are needed)". Two lines for the report: "Ather Energy ran 20 points past the index after the system passed on it at Rs 1,407.
Code would put at most 1% of the book at risk in three parts, but its own range gives a negative expected result and the name had only just left its 5-day low, so it bought nothing." In hindsight a buy at the 27 Oct close made
+11.6% to 11 Nov (the Nifty 500 +9.5%): the guard's wait cost about 2 points over the index on a bet that was never placed; the case was never re-decided (finding 6). Scoring at 20 sessions: the decision is dated 27 Oct, 20 sessions later is
after 11 Nov: not scored (no bars after 11 Nov).

## Drills (synthetic; scripted model; `python tools/replays_s84_cli.py drills [name]`)

| drill | result | what it showed |
|---|---|---|
| three_cases | PASS | four held names fall 25% on one session: 3 cases thought through, the others stored `noticed` (5 that day with the macro series), Today's block counts them; never more than 3 a day |
| missed_exit | PASS | a held name falls 22% over two sessions with no exit: case after the fall, rule **freeze** (unclear, result pending), a freeze row, no buy order for the name from the freeze on, looked at again at the date, the later decision is the rule's (hold: the model said buy in parts) |
| bet_sizing | PASS | with room and a positive expectation the bet is sized and its worst case is within 1% of the whole book; a deeper bad case sizes the bet down and it then loses exactly the limit; 3,000 of free reserve or none refuses it |
| disagree | PASS | model hold, rule sell on a damage case with a regulator's notice: the rule acts (a sale order "case #N"), both tracks stored |
| failing | PASS | the model API down: the case stays open with a stored `failed` step, no decision, no order; the exit manager's thesis-break sale of another name still acted; with the cap at zero the same |
| follow_up | PASS | one case re-thought at its date, another when a new event on the name arrives (3 answers each) |
| calibration | PASS | 6 scored decisions: the word table does not move; 24: "unlikely" and "likely" each move by exactly 0.05 toward the observed rate; a second correction inside the month does not |
| advisory | PASS | 10 scored: live; 22 with the rule behind "do nothing" (Rs -96,062): advisory; the rule's track ahead again: live |

`accelerated_thinking` (`python tools/drills_s81.py run --only accelerated_thinking`, ten sessions, the app's own `think_loop` job and close hooks thinking through the scripted gateway): the thinking step's checks pass
(cases opened, at most 3 a day, every model step stores engine/model/thinking, decisions with both tracks for every security, scripted answers only, Today carries the block, the job ran) and `standing` FAILS on finding 5.
The step is not part of the default `accelerated` drill (it shocks two names); it runs by its own name.

## The real path (the only paid calls of the night)

Run on the replay world of (i), NOT on a copy of the store (decision 1), by `python tools/replays_s84_cli.py real` (it sets PFLAB_PAID, restores the secrets file, lifts the drills' network block only around a model call,
caps the calls at 5 and replaces the `think_loop` and `strategist` jobs and any other case's thinking by no-ops; the stake is under 1% of the book, so the line `opus_exposure_share` is lowered to 0.5% for this run so that
Opus decides). Scratch cap Rs 70, the real governor and egress gate.
* Run 1: 5 calls, **Rs 4.65**: the app's own close hooks thought the first synthetic case with the real model (Sonnet read x2, Opus answer, accepted at the first ask) and a desk call; this is why the gating exists. Not the Nvidia case.
* Run 2: **3 calls, Rs 3.37**: Sonnet read (tools: outcome table, base rates) Rs 0.35, Sonnet read 2 Rs 0.79, **Opus (high thinking) decision Rs 2.24**. Cached tokens 1,612 / 2,408 / 1,565.
  What the real model did (Tue 10 Nov 09:00, case on NVDA): read the stored headlines, the signals and the tables; class **damage**; pending: the board's findings and any decision on the chief executive, any US
  regulatory view on the China link, further disclosures, the class action; choice **freeze** ("selling now would act before the board investigation reports"), worst unlikely, likely even, best unlikely, base-rate set 20 (no
  past cases: own range). The answer was valid at the first ask. **The rule sold** (damage on a held name is a thesis break), the case says so ("the model chose freeze, the rule chose sell; the rule acts"): the order is the
  rule's, both tracks stored. The real Opus sided with caution but not with the sale: T8 will score the two tracks.
* Total paid tonight by this agent: **Rs 8.02** (calls 1-5 of run 1, 1-3 of run 2; both runs' `api_calls` rows are in the scratch stores, not in the repo). The Rs 60 line and the night's Rs 300 were not approached.

## Shared files touched

`tools/drills_s81.py` (the step `thinking_loop`, the drill `accelerated_thinking`; the default `accelerated` drill excludes the step), `tests/test_s81_drills_harness.py` (the step name in one list). Nothing in `src/`,
`configs/`, `docs/PLAN.md`, `docs/BUILT.md` or `CLAUDE.md`.

## Exposed for screens

Nothing new: the tools read the store and write JSON/text files under `S84_REPLAY_OUT`. The text blocks of the day-by-day account (`replays_s84.account`) are what the morning report can quote.

## What is OFF / not built

Nothing is behind a switch. Not built: the replay of the 5-6 Nov India rotation, an Indian governance case and March 2020 (S85); the exposure of NVDA through SPY (S85); a scoring of the replays' decisions at 5/20/60
sessions beyond what the drills do (the Nvidia and Ather windows end on 11-12 Nov, the bars end there).

## What I could not verify

* A copy of the app's store as the real path's world (decision 1). The real model's behaviour on a Rs 11 lakh synthetic book is the model's behaviour on that card; the real book's card has more holdings.
* The second look of any US case (blocked by finding 3) and a Monday-morning case in the loop as shipped (finding 1): both shown only with the stand-ins named above.
* The kgkind classifier on these headlines: the rows are written with the kind the classifier gives them (the kind list has `leadership_crisis`); the classifier itself did not run on them.

## Decisions needed (his or the coordinator's)

1. Findings 1, 2, 3 and 5 are bugs in the loop as built; 3 (egress) and 2 (the order's day) are one-line fixes, 1 and 5 need a small change in the wire/watch. They change what the loop does on the first real US case, so they should go in before the release.
2. Finding 6 (a refusal by a timing guard never re-looked) changes the rule's follow-up: his call whether the missed-run case should be re-looked when its guard clears (my default would be yes).
3. Whether the outcome table should value "wait for a pullback" (a level by code) instead of zero: the prompt asks for the three-way comparison; today two of the three are zero.
