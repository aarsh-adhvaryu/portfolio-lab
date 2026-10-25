# Maths audit (S43, PLAN A7), 2026-10-17

Every number-producing agent was recomputed by a second, independent method on fixed synthetic cases
(`tests/test_maths_audit.py`, 37 tests) and the suspect spots were measured on real data. Findings are fixed below
before any agent is built on them. The investor's own figures (target mix, chances on it) are in the local session notes,
not here.

## Second methods used
| agent | second method | result |
|---|---|---|
| Monte Carlo, GBM | terminal quantiles vs the lognormal closed form; chance of a 35% fall vs a deterministic drawdown chain (D' = max(D - x, 0) on a grid, absorbed at the limit; the chain itself checked against all 4,096 paths of a coin-flip walk) | agrees (2% / 1.2 points) |
| Monte Carlo, block bootstrap | block length 1 vs the chain on the empirical distribution; draw frequency of every month | agrees after fix 2 |
| max drawdown, frontier, point | plain loops; pandas recomputation; any-day falls never milder than month-end falls on a consistent daily history | agrees after fix 3 |
| lump vs staged | hand formula on a riskless asset | exact |
| allocator (steer) | hand-worked 3-bucket case; 2,000 random splits never land closer to target | exact / optimal |
| months to cure | closed form 80/(100 + 10m) | exact |
| deploy | hand-worked schedule and projection | agrees after fix 4 |
| risk stats | volatility by the textbook sum, beta by least squares with intercept, drawdown by loop, HHI by hand | exact |
| Hawkes | compensator and 10-session chance vs numerical integration of the intensity; simulated rate vs mu/(1-alpha) | exact / 5% |
| tax, lots, FD, charges | already reconciled to SBI and Console statements (S12, S33) | not repeated |

## Findings and fixes
1. **Falls were measured only at month-ends (material).** Real data: Nifty 500 TRI 2020, -38% close to close but
   -29% month-end to month-end; Momentum 50 -37% vs -25%. The chance of a fall beyond 35% therefore understated the
   fall a person sees on a daily statement. On the investor's target mix the any-day chance is about 1.3-1.4x the month-end
   chance (block engine; about 1.6x under GBM). Fix: `history_daily` and any-day engines (252-session circular
   blocks; GBM per session); `pflab pm simulate`, the frontier page ("best within a 35% fall") and the ask risk tool
   now report the any-day chance, with the month-end one alongside. **Decision for the investor**: his 35% limit was set
   against the month-end figure; whether to keep the mix is his call.
2. **Block bootstrap was not circular.** The first and last 11 months of history were drawn at 9-96% of a fair
   weight (the 2007-08 start and the latest year). Fix: circular block bootstrap (Politis and Romano 1992).
   Effect on the target mix: fall chance -0.3 points, median return +0.6 points a year.
3. **Frontier and point ignored a fall in the first month** (the start value was not a peak). Fixed; on the real
   history only gold fell in the first month (-2.7%), less than every mix's later worst fall, so no mark moves.
4. **Deploy dropped a batch the day after it matured**, with its remaining tranches (`pflab pm deploy` and the
   ask plan tool). Fix: tranches are kept until deployed; money already in the bank is counted once.
5. **Fund mapping by list order.** `target_mix` read the first equity_fund buy as Nifty 500 and the second as
   Momentum 50. Right today, silently wrong if reordered. Fix: mapped by fund name; refused if a name is unknown.

## Checked and found right (no change)
Equal-weight stock returns (dividends added once: `adj_close` is split-adjusted only); gold ISIN switch (no
overlapping dates); point-in-time Nifty 500 membership; TWR with start-of-day flows for the NAV (deposits are not
returns); market state uses the frozen 2005-2019 fit and events up to the session; steering never overfills
(shortfalls always cover the contribution); measured impact walks the recorded ladder correctly.

## Known limits, labelled not fixed
- Sharpe on the frontier uses the compound return over arithmetic volatility (a ranking aid, not a reported number).
- Measured impact excludes snapshots too thin to fill the order from the median (counted apart as "too thin").
- Constant-mix rebalancing (monthly, or daily for the any-day engines) stands in for steering with new money.
