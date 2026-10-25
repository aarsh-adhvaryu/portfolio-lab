# Hawkes processes study: results (S40)

Run 2026-10-16 with `tools/hawkes_study.py`, as registered in `hawkes_protocol.md` (commit 0c77fa4, before any
fit to real data). No amendment.

## Market: Nifty 500 TRI sessions of -2% or worse (decides the live alert)
| | events | result |
|---|---|---|
| development 2005-14 (fit) | 170 | baseline 0.017 a session, branching ratio 0.75, half-life 14.6 sessions; LR test against Poisson p = 1e-25; KS 0.66 |
| validation 2015-19 (dev parameters) | 19 | log-likelihood +35.3 over Poisson (+1.86 per event); KS 0.10 |
| 2020-26 (not evidence) | 57 | log-likelihood +29.6 over Poisson; KS 0.21 |

**PASSES** (a), (b) and (c). Big market falls cluster: each one triggers about 0.75 more on average, and the
effect halves in about three weeks. Frozen fit (2005-2019, `configs/hawkes_market.toml`): baseline 0.0125 a
session, branching ratio 0.755, half-life 14.0 sessions; average rate 0.051 a session (about 13 a year).

## Stocks: 63 Nifty 100 members (2014-12-31), sessions of -4% or worse (descriptive)
Shares meeting (a) 98%, (b) 83%, (c) 75%; all three 57%. Median branching ratio 0.60, half-life 12 sessions,
out-of-sample gain +0.28 log-likelihood per event. Bivariate (market, stock): median excitation of a stock
by one market fall 0.21; 89% pass both time-rescaling tests. The reverse direction (0.29) is mostly same-day
co-movement: within a session the order of events is unknown and placed at random.

## Filings: 100 Nifty 100 companies (2019-12-31), BSE dissemination times (descriptive)
Bursts are real ((a) and (b) in 100%: median branching ratio 0.20, half-life about 19 minutes: filings come in
same-hour batches), but only 14% pass the time-rescaling test: a constant baseline cannot follow results
seasons and office hours, as the protocol expected.

## Use, and a decision for the investor
Built as registered: `pflab pm guards` shows the market's clustering state, the guards job queues a weekly
alert when the intensity is at least 3 times the baseline, and the risk tool of `pflab ask` carries the
10-session chance. **Problem found after the run:** with a branching ratio of 0.75 the AVERAGE intensity is
about 4 times the baseline, so the 3x threshold sits below average: it would have fired in 58% of weeks in
2005-14, 21% in 2015-19 and 40% in 2020-26, and on 2026-10-15 it reads 3.3x while the model's 10-session
chance (30%) is BELOW the constant-rate chance (40%). Changing the threshold now would be a post-result
amendment; it is the investor's call (for example: alert only when the model's chance is at least twice the
constant-rate chance). Alerts are held anyway until the system is switched on.

## Addendum 2026-10-16: amendment 1 (market state), run with `tools/market_state_study.py`
Registered before computing (commit 009697b). The investor chose to fix the alert rather than drop it, asking for no
missed clustering episodes and a link to the dip rule and the plan.

| period | follow-on falls warned the close before (T1 = 40%) | share of sessions calm / elevated / high | state changes |
|---|---|---|---|
| development 2005-14 (T1 chosen here) | 90% of 124 | 60% / 34% / 6% | 108 in 10 years (2008 crisis included) |
| validation 2015-19 | 57% of 7 (few events) | 92% / 8% / 0% | 16 in 5 years |
| 2020-26 (not evidence) | 82% of 28 | 82% / 17% / 1% | 40 in 6.8 years |

T1 = 40% (the strictest level that warned before at least 90% of clustered falls in 2005-14); T2 = 80% (The investor).
The model cannot foresee the FIRST fall after a calm spell (it warned before 71% of all falls in 2005-14 and
46% in 2020-26); slow declines are covered by the drawdown and the dip rule.

**Dip-tranche wait test: FAILS.** In 2008-14, dip month-ends in elevated/high state had FEWER further falls (60% vs
86%) and a HIGHER median 12-month return (+19% vs -6%) than calm ones: buying the dip while falls clustered did
better, not worse; 2015-19 had too few dip months (1 elevated). As registered, the dip rule stays exactly as in
S34 and the market state is information only.

**Live:** `configs/hawkes_market.toml` (t1, t2). One Telegram message per change of state (calm, elevated, high),
saying the chance, the dip rule's status and that regular tranches do not change; the state is shown in
`pflab pm guards`, at the top of `pflab pm propose`, and in `pflab ask` (guards and risk tools). On 2026-10-15:
CALM (30% against a normal 40%).

## Addendum 2026-10-18: amendment 2 (threshold on the frozen fit), `tools/market_state_study.py --frozen`
Registered before computing (commit 1a073aa) after the S46 drift flag (75% since 2020), which came from T1 having
been chosen on the development fit but used with the frozen one.

| period (frozen fit, T1' = 37%) | follow-on falls warned | calm / elevated / high | state changes |
|---|---|---|---|
| 2005-14 (T1' chosen here) | 90% of 124 | 60% / 34% / 6% | 108 in 10 years |
| 2015-19 | 57% of 7 | 92% / 8% / 0% | 16 in 5 years |
| 2020 on (not evidence) | 82% of 28 | 82% / 17% / 1% | 40 in 6.8 years |

Drift check with T1': KS p 0.416, recall 82% on 28 (floor 80%): **KEEP**. `configs/hawkes_market.toml` t1 0.40 ->
0.37 (written by the tool). The state stays information only; regular tranches and the dip rule are unchanged.
