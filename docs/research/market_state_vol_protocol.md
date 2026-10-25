# Market state: Hawkes chance vs plain volatility (S51): pre-registered protocol

Registered 2026-10-20, committed before any number on the indices below was computed. Code:
`tools/market_state_vol_study.py`. Changes after the first run need a dated amendment.

## Why
The S50 TimesFM study's exploratory note (`timesfm_results.md`) found that on the Nifty 500 a plain EWMA volatility
ranks the sessions before a -2% fall better than the live Hawkes chance in every period (2026: AUC 0.63 vs 0.47).
That was found by looking at the Nifty data, so the Nifty cannot confirm it. This study tests it where nobody has
looked: other markets' indices, with each market's own Hawkes fit.

## Data
Daily closes (`data/global`, Yahoo Finance via `data.global_markets`) of ten markets, one index each: US_SP500,
UK_FTSE100, DE_DAX, JP_NIKKEI225, HK_HANGSENG, KR_KOSPI, TW_TAIEX, AU_ASX200, CN_SHANGHAI, BR_BOVESPA. Returns are
close-to-close; sessions with a missing or zero close are dropped.

## Scores and event (as live)
- Event at session t: at least one session of -2% or worse in t+1..t+10.
- Hawkes chance: an exponential Hawkes process fitted per index on its -2% sessions of 2005-01-01 to 2014-12-31 (session
  number plus a uniform position, seed 20261021; `quant.hawkes.fit`), then the chance of another fall within 10
  sessions at each close (`quant.drift.chances`), as the Nifty market state computes it.
- Plain volatility: EWMA of r^2, lambda 0.94, 22-session warm-up (`quant.vol_study.ewma`).
- Both use only data up to the close of t.

## Measure and rule (fixed now)
AUC of each score for the event, per index, on validation 2015-01-01 to 2019-12-31; d = AUC(EWMA) - AUC(Hawkes).
**Plain volatility wins** if the mean of d over the ten indices is above 0 with one-sided p < 0.05 (bootstrap: within each
index, moving blocks of 20 sessions, 2,000 replications, seed 20261021; p = share of replications with mean d <= 0)
AND d > 0 in at least 7 of the 10 indices. 2020-2026 per index and the Nifty 500 are described only.

## Use, fixed now
- Wins: amendment 3 to the market state: the chance becomes a logistic map of ln(EWMA) to the event, fitted on the
  Nifty 500 for 2005-2014 and frozen; T1 re-chosen as in amendment 1 (the highest threshold on a 0.01 grid with at
  least 90% recall of 2005-2014 follow-on falls); T2 0.80 unchanged; the same states, messages and drift check (on
  the new chance). Regular tranches and the dip rule do not change.
- Loses: the Hawkes chance stays as it is.

## Amendment 3 as applied (2026-10-20, AFTER the result; the investor's decision)
Volatility won the ranking test, but at its T1 it warned before 68% of 2020-26 follow-on falls against Hawkes' 82%, and
the state's purpose (amendment 1: miss no clustering episode) and drift floor (80%) are about follow-on falls. The investor
chose: Hawkes keeps driving calm / elevated / high and its alerts; the volatility chance (`configs/market_state.toml`)
is shown beside it in guards, propose and ask, as information (`guards.vol_chance`). Nothing else changes.
