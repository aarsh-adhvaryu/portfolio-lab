# S79b item 18A: `construct` against the current sizing rules (pre-registration)

Written 2026-11-08 BEFORE any run of `src/pflab/construct/compare.py`. The SHA-256 of this file is stored in the learner's counter (`learn_tests`, origin `study`,
template `construct_s79`, note `s79:construct`) when the study is registered; `compare.run` refuses to run if the file has changed since, or was never registered. An
amendment is dated, re-registered, and counts as a new test.

## 1. Question and claim

`construct` (portfolio construction) sizes the paper team's decisions: it turns the ensemble's expected return and dispersion plus a shrunk covariance into target weights by
a constrained optimiser (rails as constraints, Zerodha charges and estimated tax in the objective). The current rules size by the amount the team names, cut to the rails and
the cash (`paper/manager.decide`).

**Claim (one, counted once in the learner's counter).** On the same buy list, `construct`'s sizes beat the current sizing rules on a **net-of-charges, after-realised-tax,
risk-adjusted** basis, on (A) a point-in-time monthly-rebalance backtest 2012-2021 on the workshop's market data, and (B) going forward on the system's own paper book.
Tonight only (A) is run. (B) is a monitoring arm (section 7): `construct` is never adopted on (A) alone.

## 2. Data and the point-in-time rule

* Prices: `data/panel/prices.parquet` (`adj_close`, `turnover`, `instrument_type`), read with `date <= 2021-12-31` in the query itself. 2022-2025 is spent and never read.
* A signal made at the close of session `t` uses rows dated `<= t` only (returns, the forecasters' rows, the turnover ranking, the sector label of the latest capture on or
  before `t`). The order fills at the **next session's close** (not at the signal's close).
* A daily return larger than 60% in absolute value is taken as a data break (ETF face-value consolidations are not adjusted in the panel) and set to zero, for both arms.
* A halted or delisted name keeps its last close (forward-filled) for both arms; the 60-most-liquid screen drops it from new selections.
* ETFs are chained by symbol (the ISIN changed in 2019); stocks are keyed by ISIN.
* Sector labels: `data/index_membership/sector_map.parquet`, `sector_at(..., allow_later=True)` (a name whose first capture is later gets that later label; the same labels
  serve both arms, so they bias neither).

## 3. The two arms (the same question for both)

Every month-end session `t` from 2012-01 to 2021-10 (the last signal; the last trade is the next session's close):

* **Candidates.** ETFs NIFTYBEES (the index), JUNIORBEES, BANKBEES, GOLDBEES (when they have 300 sessions of history) and the 60 listed shares with the highest median daily
  turnover over the last 250 sessions (with 300 sessions of history).
* **Direction (the stand-in for the team, identical for both arms).** The BUY list is the ETFs plus the shares among the 60 with a positive 12-1 month return
  (close(t-21)/close(t-252)-1 > 0), the best 20 by that return. A held name outside the BUY list is sold by both arms (the stand-in for "the team says SELL").
* **RULE arm (the current rules).** Equal rupee weight on each name of the BUY list; a share cut to 10% of the book, an ETF to 35%, a sector (shares) scaled so that its
  total is at most 25%; the rest stays in cash. Whole-book rebalance.
* **CONSTRUCT arm.** The optimiser of `construct/optimiser.py` over the BUY list plus the names held, with: expected excess return `mu = 0.05 + tilt` (the 0.05 is a
  stated prior, equal for all; the tilt is the annualised log of the combined 20-session median return of the code forecasters `naive, volatility, momentum, reversion` with
  **uniform Hedge weights**, clipped to +-0.30); dispersion from the same combined 10th-90th range, blended 50/50 (geometric) with the Ledoit-Wolf shrunk covariance's own
  volatility; covariance = Ledoit-Wolf shrunk (identity target) of the last 250 daily returns; risk aversion 2.5; long only, no leverage (sum of weights <= 1); a share <= 10%,
  an ETF <= 35%, a sector <= 25% (or its current weight if already over); a held name not on the BUY list may be sold, not bought; objective costs: Zerodha charges, the
  blended FIFO tax of a full sale of the holding per rupee sold, and a turnover damper of 0.0005 per rupee traded. No allocation target exists in 2012-2021, so
  the target term is zero (the allocation pull is tested only by unit tests and live).
* Both arms: the book starts at Rs 5,00,000 cash on the first trade day; cash earns 7% a year (daily); whole-book trades at the next close; sells first; charges from
  `pm/costs.py` (the paper book's own estimate); tax estimated at each sale by FIFO lots with the paper book's rules and the financial year's running gains (the Rs 1.25 lakh
  long-term exemption applies once a year); the tax is paid from cash at the sale; fractional units are allowed. The parameters above are pinned in `compare.PARAMS` and do
  not follow later edits of `configs/s79b.toml`.

## 4. Statistics

On the daily value path of each arm (after charges and realised tax): daily excess return over cash; annualised Sharpe ratio `S` = mean / std * sqrt(252); the maximum
drawdown `D`; the CAGR; the value after a notional liquidation at the last close (charges and the tax of selling everything, which stops deferral of tax from looking like
a gain) and its CAGR `L`; turnover (purchases per year over average value); total charges and total tax.

Primary: `dS = S_construct - S_rule`. Uncertainty: a paired moving-block bootstrap of the daily excess returns (block 21 days, 2,000 resamples, `numpy.random.default_rng(79)`,
the two arms resampled with the same blocks): `p` = share of resampled `dS` that are `<= 0`.

## 5. Decision rule (fixed now)

* **adopt** (for arm A) if all four hold: `dS >= 0.10`; `p <= 0.05`; `D_construct` is not worse than `D_rule` by more than 2 percentage points; and `L_construct >= L_rule - 0.5` percentage points
  (a higher Sharpe bought by sitting in cash does not count).
* **loses** if `dS < 0`.
* **inconclusive** otherwise.

Whatever the result it is reported as it is, with the numbers of both arms. If it is not "adopt", `[construct] adopt` stays false and the tool remains an advisor labelled
"not adopted". `adopted()` is true only when the config switch is on AND the stored verdict is "adopt" AND this file still has its registered hash. Even then (B) must also hold
before the lead switches `adopt` on.

## 6. One run

`compare.run` is run ONCE for the record. Its result is stored in `construct_runs_s85` (kind `compare`). A rerun with changed parameters is a new registered study.
Known limitations, stated before the run: the direction stand-in (momentum) is not the team; one decade of one market; adjusted prices make the tax basis approximate; the
index and gold ETFs are the only non-share assets, so the allocation pull is not tested here; the forecasters' tilt is small by construction (at most 0.1 sigma), so
`construct` differs from the rule mostly through risk and cost, not through the forecast.

## 7. Arm B, going forward (monitoring, not run tonight)

Each day `construct` advises on the paper book the live ensemble gives (kept in `construct_runs_s85`, kind `advice`). After 60 live sessions the lead compares the advised weights
held to the next advice (net of the same charges) with what the manager's rules actually did, on the same Sharpe, drawdown and liquidation measures; arm B passes under the
same four conditions as section 5 computed on those paths. Until both A and B pass, `adopt` stays false and the current rules decide every live size.
