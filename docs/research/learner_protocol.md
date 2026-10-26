# The learner's tests: protocol (registered 2026-10-25, before any claim is run; PLAN A22)

The learner (`src/pflab/learner/`) turns claims from papers, books and blogs into tests on this system's own data. This
protocol fixes, before the first run, how every such claim is tested and decided. Each claim gets its own protocol
file written by code before its test (below); this document is the rule all of them follow (CLAUDE.md 12).

## What a claim may be tested as
Only one of three coded templates (`learner/templates.py`), with parameters from closed lists. A claim that fits none is
recorded as untestable with the data it would need, and gets no live feature.
- **cross_section**: a price signal (momentum 12-1 and 6-1, one-month reversal, 12-month volatility, 52-week high, the
  largest day in a month, Amihud illiquidity), direction (high or low values earn more), holding 1 or 3 months. At each
  month end the point-in-time Nifty 500 members with at least 200 of the last 252 sessions are ranked; the claimed
  quintile's equal-weighted total return over the next h months minus all members', less the round-trip charges
  (`pm.costs` on a Rs 50,000 order) on the share of names that changed. A name that stops trading keeps its last value.
  Newey-West t with max(1, h) lags.
- **event_study**: a filing kind (the frozen red-flag rules or a registered materiality subcategory), direction up or
  down, CAR over 1, 5 or 20 sessions against the Nifty 500 TRI (the S46 template, dissemination time point in time).
  The cost: one round trip.
- **calendar**: turn of the month (last session and first three), Mondays, Fridays, January, the first half of the month;
  Nifty 500 TRI daily returns on the effect's days minus the other days (Welch t), scaled to the effect's window. The
  cost: an index ETF round trip, 0.10% (stated, not measured).

## Periods
Development 2010-2017, validation 2018-2021 (filings: 2015-2018 and 2019-2021; BSE announcements start in 2015). 2022-2025
are spent (CLAUDE.md 2) and are never used. 2026 onward is the live record.

## The decision (`templates.decide`, the same for every claim)
PASS only if, in both periods: the effect is in the claimed direction; t >= 2.0 in development and >= 1.65 in
validation (one-sided: the direction is fixed before the run); at least 36 months (20 events for filings) in each; and
the mean effect exceeds its cost. Anything else FAILS, with the first reason. No parameter is tuned after a run; a
re-test of the same template and parameters is not run twice (the later claim points at the first).

## Registration (the system's equivalent of "committed before the run")
Before a claim's test, code writes `PFLAB_DATA_DIR/learner/protocols/claim_<id>.json` once: the claim, its verbatim
quote and source, the template and parameters, the periods, this rule, and the SHA-256 of `templates.py`. Its hash is
kept in `learn_claims`. The test refuses to run if the file changed, or if `templates.py` changed since registration.
Every claim must quote its source word for word (code finds the quote in the text), so a model cannot invent one.

## What a result does
A PASS becomes a live `finding`: the brain reads it in its cached part, and the `findings` tool shows, for a stock
signal, each held and listed name's quintile today. A FAIL is kept as tested-and-failed and gets no live feature. A
finding is history, never a forecast; it never trades. Results are judged again on the live record as it grows.

## Amendment 1 (2026-10-25, before any claim was tested)
The first real read (2 arXiv papers, the local model) attached tests at random (a claim about LLM portfolios filtering
old news was mapped to the 52-week-high signal). Added: a claim fits a test only when its own words (claim and quote)
name what the test measures (`claims.NAMES`: e.g. "52-week" for high_52w, "dividend" for Dividend filings, "Monday" for
Mondays). Checked when the claim is read (else untestable) and again before its test (a claim registered before this
check that fails it is withdrawn, not run). The decision rule is unchanged.

## Amendment 2 (2026-10-25, before any claim was tested)
The second real read registered a claim that an effect is absent ("returns are not influenced by the January effect") as
a directional claim. Added: a claim whose words deny an effect (`claims.ABSENT`: not, no, cannot, insignificant, ...) is
not tested (a pass could wire nothing); checked at reading and again before the test (withdrawn). The reading prompt
asks only for claims that an effect exists. The decision rule is unchanged. Corrected the same day, before any test
ran: the denial is read in the claim sentence only (a quote may deny another effect on its way: "no low-volatility
anomaly; the high-volatility quintile gives high returns"); claim #13, withdrawn by the first version and never run, was
restored to registered.

## Amendment 3 (2026-10-25, S63, before any claim on it is tested): who buys and sells
The investor asked for the collected holder data to be wired in, the learner's tests included. A fourth template,
`holder_event`: kinds insider_sast (BSE announcements in "Insider Trading / SAST", trading-window notices left out, dated
by dissemination), bulk_buy / bulk_sell / block_buy / block_sell (NSE deals; published after the close, so the next
session; the symbol mapped to its ISIN as it traded that day), promoter_up / promoter_down (a quarter's promoter holding
changed by 0.5 points or more) and pledge_up (the pledged share of it up 1 point or more), both dated 21 days after the
quarter end (SEBI's filing deadline). Direction up or down, CAR over 1, 5 or 20 sessions against the Nifty 500 TRI;
periods 2015-2018 and 2019-2021 (deals exist from May 2016); the same decision rule (20 events each, t, cost of a round
trip). A claim fits it only when its words name the kind (`claims.NAMES`). The thresholds are in `templates.py`.

## The record half (proposals)
Rules in `learner/record.py` (docstring table), each needing n >= 20: lessons go live at once (text in the brain's
cached part); daily action limits, a dearer model and any model-worded instruction change wait for the investor's yes; money
limits are never proposed. Nothing retires a kind of suggestion.

## Amendment 4 (2026-10-26, S64, before any further claim is tested): a test counter
Each claim passed alone at t >= 2.0, with nothing counting how many tests had run. Added:
- Every test ever run is counted in one family, "all": learner claims, the S64 studies, and seed rows for the past
  studies (`learn_tests`, `learner/counter.py`).
- The development bar becomes `t_needed(N) = max(2.0, Phi^-1(1 - 0.05/N))`, N counting the tests in the family
  including this one (one-sided Bonferroni): N=20 gives 2.81, N=100 gives 3.29. The N and the bar in force are written
  into the claim's protocol file at registration.
- Validation stays at t >= 1.65: it is an independent replication.
- The deflated Sharpe ratio (Bailey and Lopez de Prado 2014) of the development series is recorded and reported; it
  does not decide.
- Findings that passed under the old rule are re-decided under the new bar; their live feature ends if they fail.
- A feature or covariate enters a model only if a registered comparison shows it beats the simpler model on unseen
  data, and that comparison counts as a test (extra features fit noise).
