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
| Local model as the front of the chat (S71, `docs/protocols/s71_front_protocol.md`) | qwen3:8b recognises the common turns and carries them out safely | development set **FAIL** (85.0% accuracy; 4 unsafe acts at confidence 0.95-1.00; start 57%, decline 67%, amend 80% precision), so those intents were switched off and the model's words checked by code; unseen holdout of 24 on the shipped configuration **PASS** (12 handled locally, 0 wrong, 0 unsafe). The model's confidence is no safety signal; the number guard cannot see a wrong label (found in the first end-to-end run), so facts are rendered by code | yes: status, portfolio, approve, fall, deploy, remember (`app/front.py`) |
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

## The paper portfolio (S76; a record of the system's own judgement, not a test)
From 2026-11-02 the system runs a copy of his portfolio (without FDs) by itself (`paper/`, PLAN A35). Every decision states a claim (7, 28, 84 and 182 days, against
the Nifty 500 with beta; keeping cash against what cash earned); the record shows the count and, from 20, the rate and the skeptical rate. After 40 sessions a gate
(his choice of about two months): its time-weighted return after tax above the Nifty 500 total return and a smaller worst fall over the same days; then its new
decisions also reach him as proposals for his real money, each waiting for his yes. Two months is short and partly luck: the gate opens a door to his yes, nothing more.

## S76 learner families (registered 2026-11-01, `docs/protocols/s76_learner_protocol.md`, committed before any run)
Twelve claims, tested by the app's learner three a night, counted in `learn_tests` (the bar rises with N): after a fall (30% below the one-year high, confirmed over
0, 20 or 60 sessions; hold against sell, three months ahead) and rebalancing bands with gold (60/20/20 and 70/30 equity/gold/cash; bands of 5, 10 or 20 points
against never and against monthly; checked at month ends or daily; after charges and tax; a worst-fall guard). The code was run before the tests only on the
spent years 2022-2025 (that it runs; no 2010-2021 figure seen). Verdicts: pending.

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

<!-- s79-llm-results:begin -->
## S79 item 13: local model sampling and a larger MoE (protocol: docs/protocols/s79_local_model_protocol.md)

Diagnosis (counts only): the app's `llm_runs` (a copy of its ledger, 31 calls, 2026-11-02 to 11-03) shows no failed call and no labelled loop; two `workshop_writer` replies used the whole 2,500-token cap (truncation risk). The table keeps no text, so from S79 on `client.chat` writes the `diag` label (ok, truncated, empty, loop, format) into `note` and keeps Ollama's `done_reason`.

| arm | model | routing | answers_final | answers_first | extraction_f1 | materiality | answers_median_s | answers_p90_s | routing_call_median_s | tokens_per_s | text_fail_rate | json_fail_rate | gpu_peak_mib |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A old default | qwen3:8b-q8_0 | 0.867 | 1.000 | 1.000 | 1.000 | 0.780 | 6.041 | 6.392 | 4.471 | 24.066 | 0.000 | 0.000 | 11008.000 |
| B Qwen sampling | qwen3:8b-q8_0 | 0.867 | 1.000 | 1.000 | 1.000 | 0.780 | 6.779 | 7.100 | 4.748 | 20.550 | 0.000 | 0.000 | 10639.000 |
| A FAST candidate | gemma4:12b | 0.933 | 0.340 | 0.330 | 1.000 | 0.835 | 15.818 | 16.243 | 4.497 | 27.301 | 0.000 | 0.000 | 10710.000 |
| A FAST candidate | qwen3.5:9b | 0.983 | 1.000 | 0.950 | 1.000 | 0.760 | 6.480 | 7.021 | 4.765 | 26.502 | 0.000 | 0.000 | 10059.000 |

**Sampling decision:** adopted kinds none; text checks {'final_not_lower': True, 'first_not_lower': True, 'latency_ok': True, 'fewer_failures': False}; json checks {'routing_not_lower': True, 'materiality_not_lower': True, 'extraction_not_lower': True, 'fewer_failures': False}.

**FAST seat (S79b item 17, docs/protocols/s79_seats_protocol.md):** qwen3:8b-q8_0; per candidate: gemma4:12b not chosen {'not_worse_routing': True, 'not_worse_answers_final': False, 'not_worse_extraction_f1': True, 'not_worse_materiality': True, 'better_overall': False, 'latency_p90': True, 'vram': True, 'failures_not_above': True}; qwen3.5:9b not chosen {'not_worse_routing': True, 'not_worse_answers_final': True, 'not_worse_extraction_f1': True, 'not_worse_materiality': False, 'better_overall': True, 'latency_p90': True, 'vram': True, 'failures_not_above': True}.

**THINKER seat, guarded window (S79b item 17, Amendment 1: matched subset routing 60 / answers 20 / extraction 40 / materiality 60):**

| arm | model | routing | answers_final | answers_first | extraction_f1 | materiality | answers_median_s | answers_p90_s | routing_call_median_s | tokens_per_s | text_fail_rate | json_fail_rate | gpu_peak_mib |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AM (matched subset, incumbent) | qwen3:8b-q8_0 | 0.867 | 1.000 | 1.000 | 1.000 | 0.733 | 6.045 | 6.392 | 4.471 | 24.350 | 0.000 | 0.000 | 11008.000 |
| AM (matched subset) | qwen3:30b-a3b | 0.383 | 0.000 | 0.000 | 1.000 | 0.633 | 34.433 | 34.817 | 4.545 | 42.735 | 1.000 | 0.000 | 11536.000 |
| AM (matched subset) | qwen3.6-35b-a3b | 0.950 | 0.650 | 0.650 | 1.000 | 0.867 | 2.737 | 6.842 | 0.720 | 52.739 | 0.000 | 0.000 | 11044.000 |
| AM (matched subset) | gemma4-26b-a4b | 0.950 | 1.000 | 0.850 | 1.000 | 0.833 | 2.199 | 4.055 | 0.865 | 43.192 | 0.000 | 0.000 | 11284.000 |

- qwen3:30b-a3b: not chosen {'beats_on_score': False, 'not_significantly_worse': False, 'answers_final_threshold': False, 'answers_p90': True, 'routing_p90': True, 'ram_headroom': True, 'stable': True, 'failures_not_above': False}; completed; load 15.0 s; generation 57.02505966246867 tok/s, prompt 876.1742562051089 tok/s; peak GPU 11536.0 MiB, peak temp 53.97 C, min free RAM 2.88 GB, free RAM after load 7.92 GB
- qwen3.6-35b-a3b: not chosen {'beats_on_score': False, 'not_significantly_worse': False, 'answers_final_threshold': False, 'answers_p90': True, 'routing_p90': True, 'ram_headroom': True, 'stable': True, 'failures_not_above': True}; completed; load 16.3 s; generation 46.161184598577215 tok/s, prompt 861.3915133465059 tok/s; peak GPU 11044.0 MiB, peak temp 58.72 C, min free RAM 6.11 GB, free RAM after load 6.31 GB
- gemma4-26b-a4b: not chosen {'beats_on_score': False, 'not_significantly_worse': True, 'answers_final_threshold': True, 'answers_p90': True, 'routing_p90': True, 'ram_headroom': True, 'stable': True, 'failures_not_above': True}; completed; load 12.9 s; generation 39.406292355282986 tok/s, prompt 973.6515980815457 tok/s; peak GPU 11284.0 MiB, peak temp 59.19 C, min free RAM 9.63 GB, free RAM after load 9.71 GB

<!-- s79-llm-results:end -->

<!-- s79-wave-sentiment-results:begin -->
## S79b items 15, 15b, 7b: market waves, rotation, crude falls, sentiment, value area and POC migration (protocol: docs/protocols/s79_wave_sentiment_protocol.md)

Each test ran once, 2004-2021 only (2022-2025 is spent), non-overlapping events, moving-block bootstrap (block = horizon, 10,000 draws, seed 20261108), gate: n >= 20, one-sided p <= 1 - Phi(t_needed(N)) with N read from the counter at run time, same sign in both halves, |effect| - 0.2% cost >= 0.5%. A pass reads "followed through"; anything else "no reliable follow-through". A description of history, not a forecast.

| test | market | events (raw) | effect [95% interval] | p (one-sided) | bar t / N | halves same sign | verdict |
|---|---|---|---|---|---|---|---|
| crude_fall_20 | IN | 35 (69) | -0.72% [-3.24, +1.78] | 0.2726 | 3.07 / 47 | True | no reliable follow-through |
| crude_fall_5 | IN | 52 (69) | +0.16% [-1.14, +1.52] | 0.4164 | 3.07 / 47 | False | no reliable follow-through |
| extreme_sentiment_20 | IN | 68 (319) | +0.00% [-1.87, +1.73] | 0.5178 | 3.07 / 47 | False | no reliable follow-through |
| extreme_sentiment_5 | IN | 132 (319) | +0.07% [-0.58, +0.71] | 0.4052 | 3.07 / 47 | False | no reliable follow-through |
| poc_migration_5 | IN | 348 (1499) | +2.3 pts [-3.1, +7.7] | 0.2107 | 3.07 / 47 | True | no reliable follow-through |
| rotation_20 | IN | 4 (4) | - | - | 3.07 / 47 | - | n too small, no conclusion (4 non-overlapping events; 4 before the non-overlap rule) |
| rotation_5 | IN | 4 (4) | - | - | 3.07 / 47 | - | n too small, no conclusion (4 non-overlapping events; 4 before the non-overlap rule) |
| value_area_return_1 | IN | 1335 (2379) | -4.5 pts [-7.7, -1.0] | 1.0000 | 3.07 / 47 | False | no reliable follow-through |
| value_area_return_5 | IN | 562 (2379) | -1.5 pts [-6.0, +3.0] | 1.0000 | 3.07 / 47 | False | no reliable follow-through |
| wave_20 | IN | 47 (111) | -1.15% [-3.57, +1.01] | 0.1632 | 3.07 / 47 | True | no reliable follow-through |
| wave_5 | IN | 71 (111) | -0.06% [-1.24, +1.14] | 0.4639 | 3.07 / 47 | False | no reliable follow-through |
| rotation_20 | US | 0 (0) | - | - | 3.07 / 47 | - | not available |
| rotation_5 | US | 0 (0) | - | - | 3.07 / 47 | - | not available |
| wave_20 | US | 0 (0) | - | - | 3.07 / 47 | - | not available |
| wave_5 | US | 0 (0) | - | - | 3.07 / 47 | - | not available |

Recorded in `wave_study_results_s79` (protocol sha a1781a275ec1, code sha a19f5278160e); rows also in `docs/research/wave_sentiment_results_s79.json`.
<!-- s79-wave-sentiment-results:end -->

<!-- s81-swing-results:begin -->
## S81 B5 (2026-11-09 night): the swing sleeve and exemption harvesting (protocol: docs/protocols/s81_selling_swing_protocol.md with A1 and A2)

Pre-registered and committed before any code that runs it; four tests counted in the learner's counter (N 49 -> 53, development bar t >= 3.11); run ONCE on the real 2005-2017 panel (600 liquid
shares, Nifty 500 total-return index held as an ETF with a 0.20% a year cost), in the Docker sandbox (contained), 20 shuffled-signal runs per variant, Rs 10,00,000 each, after charges,
slippage and tax (today's tax rows applied to the whole window; losses carried forward 8 years as the tax engine's loss rule says). Results are stored in `docs/research/swing_study_results_s81.json`
and written onto a store by `swing_study.apply_recorded`. The 2018-2021 final check was NOT run: no variant passed (it is run only for a variant that passes).

**Claim A: not supported.** No swing variant beats holding the index ETF after tax and charges. The index ETF returned 13.4% a year after the tax owed on selling it (L).

| variant | L a year | vs index | paired t (bar 3.11) | shuffled runs as good | real vs shuffled 95th pct | deflated Sharpe | worst fall (index -63.7%) | trades, hit rate | verdict |
|---|---|---|---|---|---|---|---|---|---|
| swing_momentum_continuation | -3.3% | -16.6 pts | -3.30 | 100% | -3.3% vs +2.8% | 0.00 | -59.0% | 1,271, 40% | fail |
| swing_pullback_in_uptrend | -0.1% | -13.5 pts | -2.98 | 0% | -0.1% vs -1.7% | 0.01 | -33.3% | 1,922, 47% | fail |
| swing_post_results_drift | +7.1% | -6.3 pts | -1.31 | 0% | +7.1% vs +5.6% | 0.29 | -7.5% | 161, 54% | fail |

Reading: charges, slippage and tax took Rs 6.6 lakh (momentum), Rs 8.4 lakh (pullback) and Rs 2.5 lakh (drift) of a Rs 10 lakh sleeve over 13 years. Momentum continuation is worse than random picks
(every shuffled run did better): the breakout signal points the wrong way here. The pullback signal is better than random picks (about 3.6 points a year) but not better than cash once costs are paid. The
post-results drift variant carries a real signal (it beats all 20 shuffled runs, an average winning trade of +1.9%) and a very shallow worst fall, but it trades rarely (a few positions at a time, mostly
cash) and earns 0.6 points a year over cash; it does not come near the index. The deflated Sharpe was computed over three trials (a fresh store); in the app's store it can only be lower.
Correction recorded: the first screen read the drawdown difference with the wrong sign; the stored scorecards were re-screened (verdicts unchanged, the reasons corrected).

**Claim B: not supported as registered (both arms must pass).** Exemption and loss harvesting (the minimal A51 rule in `lab/harvest_replay.py`), with versus without, same book:

| arm | liquidation return a year, with / without | change | tax saved | extra charges + slippage | passes |
|---|---|---|---|---|---|
| index ETF held | 13.53% / 13.38% | +0.15 pts | Rs 1,55,688 | Rs 10,888 | yes |
| baseline_lab (monthly rebalanced shares + ETFs) | 8.98% / 9.03% | -0.05 pts | Rs 11,994 | Rs 30,492 | no |

Harvesting helped the buy-and-hold index and cost money in a book that already realises gains at every rebalance. The exit manager should treat harvesting as unproven for rebalanced sleeves (a claim
that harvesting helps buy-and-hold core ETFs only would be a new registered study).

Assumptions (all in the protocol and in `docs/research/swing_study_results_s81.json`): fills at the next close; stop/target from the day's adjusted range; slippage `0.0005*sqrt(1e8/traded value)` (clipped
0.0005-0.005) + `1.0 * 20-day volatility * sqrt(order/traded value)`; today's tax law applied to 2005-2017; results days from BSE announcements (2011 on); survivorship in the 600-name selection.
<!-- s81-swing-results:end -->
