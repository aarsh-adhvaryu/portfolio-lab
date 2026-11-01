# STUDIES: every pre-registered test, its verdict, and what is live

The rule (CLAUDE.md 10): a protocol is committed before the run, the rule is in code, the result is counted, and only what passes is wired in.
A pass is a description of the history tested, not a forecast. The 2022-2025 period is spent; 2010-2017 is the development period and 2018-2021 the
validation period of the learner's tests. The learner's counter holds **38 tests** (33 before S65, the forward tests F1-F5 counted at registration) (the next development bar is t >= 3.02: it rises with every test,
`learner/counter.py`; a fresh install starts from the same count, `counter.CARRIED`). Frozen protocols and results of the live tests are in
`docs/protocols/` (never edited: a claim's protocol is hashed when it is registered).

## Verdicts
| study (session) | claim tested | verdict | live? |
|---|---|---|---|
| Hawkes clustering (S40) | big Nifty falls cluster (each triggers ~0.75 more) | **pass** | yes: market state and crash gauges (`quant/hawkes`) |
| Hawkes wait-on-dip (S40) | waiting after a dip in an elevated state helps | fail | no |
| Height of the ride | a high ride warns of a 15% fall | fail (the other way) | no |
| Early warning | combined signs warn of first falls | fail | no |
| Dip-buy rule (S34) | extra buys on a 10% market dip into safe stocks | **pass** | yes: `plan/safety.py`, dip alerts |
| Buy zone (S54c, wait for the zone) | waiting for the zone beats buying at once | fail (t -0.04 / -0.91) | no: plans buy at once; the zone is shown as information |
| Pairs trading (S39) | cointegrated pairs, entry |z| 2, exit 0 | fail (t 1.82 / 0.71) | no (`comove` descriptive only) |
| TimesFM zero-shot and fine-tuned (S50, S52) | volatility, fall ranking, ranges, return forecast | fail on every question; turnover and results ranges passed | removed in S64; baselines kept (`quant/baselines.py`) |
| Market state vs plain volatility (S51) | Hawkes chance beats EWMA | fail | no |
| Split / limit buying (S45) | splitting or limit-below-market beats buying at once | decided by the registered rule (`quant/execution_study`) | yes: trader tickets follow its decision file |
| Who is buying (S48) | insiders, institutions, bulk deals predict 3-month excess | all three arms fail (t 1.19/1.58, -0.10/-0.42, -2.84/0.06) | no (shown as context only) |
| Memory retrieval (S49) | hybrid retrieval beats word matching (recall@5 0.575 vs 0.425) | **pass** (+0.15 over +0.10) | yes: `memory find` |
| Analyst vs local, Sonnet vs Opus, Haiku vs local (S43-S60) | which model for which job | by the registered rules: qwen3:8b for routing and guarded answers, Haiku readers, Opus writes research and the workshop's calculations (10 of 10 correct), cheapest model that passes per job | yes: the slider (`hq/models.py`) |
| Harness search (S47) | tuned prompts beat the base | materiality adopted; research adopted; routing and writing not; QLoRA not adopted | yes: `llm/adopted.py` |
| Reversion (S64, claims 16-17) | sector reversion; short-term reversal | fail (t +1.47; the reversal went the other way, t -2.07) | no |
| Price ranges calibration (S64) | plain stationary-bootstrap ranges cover 75-85% | plain **passes** coverage in all four cells; EWMA-scaled fails | yes: `stats_plain` ranges, scored when due |
| Rule tests (S64, claims 18-24) | seven rules of thumb earn more or less next month | **one passes**: below the 200-day average earns about 0.6-0.75% a month less in both periods (an *avoid* rule); P/E above 50 narrowly fails (t -2.86 vs 2.89); cheap P/E, near the low, volume spike, 40% below the high, RSI below 30 fail (four the other way) | yes: avoid rule as a `learned` finding |
| PEG multibagger (S64) | PEG below 1 tripled within five years more often | fail (24.3% vs 19.8%, ratio 1.22 under 1.5); about one Nifty 500 stock in five tripled in five years whatever its PEG | no: context, labelled tested: failed |
| Learner claims 13, 16-24, others | claims read from papers and blogs | 1 passed, 9 failed, 2 withdrawn, 12 untestable (no template fits) | the passed one |
| Reviewer and planner seats, Sonnet 5.5 vs Opus 5.5 (S70, `docs/protocols/s70_roles_protocol.md`) | Sonnet catches planted faults as Opus does, and plans as well | **Sonnet takes both seats** by the registered rule: both caught 24 of 24 planted faults (95% interval 86-100%), both flagged both clean controls, 4 of 4 plans passed all six checks for each; per call Rs 1.34 vs 4.11 (review), Rs 0.95 vs 3.3 (plan). The test is at its ceiling: it shows no loss on these faults at dossier size of about 700 tokens (production ones are ten times larger); it cannot rank them. | yes: reviewer and the coordinator's planning step on Sonnet; Opus keeps the final answer and the review of any proposal of Rs 25,000 or more (`hq/workers.seat_model`) |
| Restart drills (S58) | the system survives a kill mid-job | passed after fixes (settings save races, collect reporting ok on a failed news step) | n/a |
| Workshop acceptance (S64 Phase 4) | model-written calculations in the Docker sandbox are right and contained | 10 of 10 correct, `contained: True` | yes |

## Leads, not findings (not registered; same data was seen)
The reversed sides of the failed buy-the-dip rules (underperformance after a volume spike, near the 52-week low, far below the high), the alpha-sign and
build-up scans, other P/E cut-offs. They can only be tested on data the system has not seen: the live record from 2026 on.

## Forward tests (registered 2026-10-28, run by the system on live data as it accumulates)
See `docs/protocols/s65_forward_protocol.md`: the leads above, tested forward only, with the counter's bar, evaluated by the learner as months complete.
No result before the first complete months exist (about December 2026); none is read early.

## F5: the stress-gauge hedge, forward on paper (registered 2026-10-28, `docs/protocols/s65_hedge_forward_protocol.md`)
From the investor's Q_Alpha_Research (its one positive result). A cross-asset stress gauge (eight measures, causal, US data lagged a session) switches a paper
short of Nifty futures worth half the book on after 5 sessions at 0.70 or more. Kept daily from 2026-10-29 (`quant/stress_hedge.py`); decided once after 24
months and 2 completed episodes: pass if the worst fall is at least 5 points shallower and the yearly return no more than 1 point lower. On the history (not
evidence here) the gauge was on in Oct 2008, Mar 2020 and Jun 2022 and on about 5% of sessions since 2010; it is coincident, never a forecast.

## The scoreboard (not a test: a record, `plan/twin.py`)
Your book, the brain's own suggestions on paper, the equal-weight Nifty 500 (the bar) and the Nifty 500, all given the same money on the same days. Values only
until 60 sessions; afterwards the gaps are descriptions. It is how the companion's usefulness is seen over months, beside the suggestion ledger's per-suggestion scores.

## Results from the investor's other projects (not re-run here; context, never a live feature by themselves)
- **portfolio_system_archive** (the earlier research harness, shelved 2026-10-01): 13 strategy verdicts; one ADOPT, E1d (volatility-scaled 6+12-month momentum, the
  Nifty 500 Momentum 50 index's own method), which is live here only as the Momentum 50 fund in his targets; E1, E1b, E1-P inconclusive; E1c, E2-A, E3-R and
  others rejected.
- **Q_Alpha** (an AI paper investor, 2026-09): trading less beat trading more net of cost and tax in every walk-forward period it tested; equal-weighting explained
  most of the apparent edge over the cap-weighted index; rule-based selling to manage risk lost to the tax it realised. Its tax engine matched a Zerodha tax P&L
  once; this system's matched a Console tax P&L for FY2027 to 3 paise on 4 stocks (2026-10-28).
- **Q_Alpha_Research**: crash prediction by LPPLS found nothing on Indian large caps; an HMM sell-overlay trailed buy-and-hold because of the tax; QUBO (quantum)
  selection lost to 1/N on a clean point-in-time universe (trailing-year means are too noisy); the futures hedge was positive and is F5 above.
The common lesson, consistent with this system's own failed timing rules: in a taxable book, selling to time the market costs more than it saves; hedge, do not sell.

## The learner's protocol
`docs/protocols/learner_protocol.md` (with Amendments 1-4: claims must quote their source and name what the template measures; absent-effect claims are
not run; the test counter and deflated Sharpe; an extra feature must beat the simpler model on unseen data and counts as a test). Local models screen
and read; code decides. Protocol file and code hashes are fixed at registration: a changed template means register again.

## New protocols go here, committed before the run
Add a row above with the claim, the protocol file in `docs/protocols/`, the rule in code, and after the run the verdict and t's (development / validation),
and whether a live feature follows. Register through `pflab learner register-*` so the counter counts it.
