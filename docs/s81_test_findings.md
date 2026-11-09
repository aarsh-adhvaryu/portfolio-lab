# S81 test findings (the overnight run of 2026-11-09 to 2026-11-10)

Every problem found while building, testing and drilling S81, with what was done. Written by the coordinator from the seven agents' reports and its own runs. "Fixed" means a root-cause fix with a test.

## Found and fixed
| # | Found by | What | Fix |
|---|---|---|---|
| 1 | core-lab | The once-only 2018-2021 final check could never run for real: `engine.monte_carlo(v, 0)` raised IndexError, and the S80 tests had mocked `final_run`. | `monte_carlo` returns {} for n <= 0 (also found independently by the swing agent); a regression test. |
| 2 | drills (kill9) | `core/loop.py` placed decisions, orders and claims one by one and wrote the day's run row last: a kill after the first order left half a close and the restart waited for ever. | One `store.transaction` around the placing block (decisions, orders, claims, sleeve tags, the run row). |
| 3 | drills | The strategist job failed and sent a Telegram alert at every cooldown when there was no cloud client. | `strategist.tick` skips with the reason. |
| 4 | drills | `lab_close` failed and alerted every 15 minutes while Docker was down. | The job skips with the reason and is not re-run every tick. |
| 5 | session agent | `views.merge` added a tactical view's share at EVERY close for a name the policy does not hold (it compounded). | The view asks for its own share as a level; a test. |
| 6 | drills | `core/preopen.gap_estimate`: `np.polyfit` raised LinAlgError on a degenerate series and `preopen_job` failed. | A guard returns no estimate; a test. |
| 7 | drills | `lab/probation.record` had no upper bound on the day (harmless live, wrong in a replay). | A `day` bound. |
| 8 | kg agent | The S80 audit counted filings with no dissemination time as unlinked and compared a timestamp to a midnight valid-to, which dropped every filing on an ISIN's last valid day (the "84.5% link rate"). | Both fixed in `kg2`; the real link rate is 99.94% on listed scrips. |
| 9 | us agent | The settled-book churn caps left every order of a USD 1,051 account under the minimum trade. | A deploy rule for a fresh account. |
| 10 | swing agent | Drawdown sign bug in the first screen of the swing study (false "worst fall" failures). | Corrected after the run; the verdicts did not change; a test pins the sign. |
| 11 | coordinator | The S80 tests expected the loop's latest decision to carry the policy's name; with the exit manager a rail trim is now first. | The tests allow the exit manager's reason. |
| 12 | coordinator | The close loop is now wired to the exit manager and the probation slices (it was not: the agents wrote the modules, the loop is the coordinator's). | `core/loop.py`; tests `test_s81_loop_exits.py`, `test_s81_loop_probation.py`. |

## Found and NOT a bug (behaviour to know)
- After a gap the loop decides ONCE, on the latest closed session; every missed session is marked, filled, forecast and scored in order, once each (asserted by the drills). The prompt's "the loop runs for each missed close" would not be point in time (the lots already hold later fills).
- A kill between the run row and the book card leaves that day without a card (accepted).
- `data_s79b` holds the scheduler thread 163 seconds when the network is down (per-source retries): a short timeout once the network is found down would help (not done).
- The `[fills]` numbers (spread and slippage by liquidity) are an assumption with no fill record to calibrate against; revisit from `session_fills_s81` after the first sessions.
- `paper/book.py` still has a typed `LT_EXEMPT = 125_000` in the fills' own tax estimate (pinned by protected engine tests); the exit manager's harvest room reads the tax engine's dated rows. If the dated row changes the two would disagree: follow-up is to make `book.tax_of` read the row.

## Open, needs him
1. **The international leg.** Every India-listed international ETF trades 3 to 105 percent above its NAV (the premium rail reproduces the premiums printed in the press to the decimal; the lowest, Hang Seng BeES, is 3.3% on 2026-11-06). With the 2% limit the rail blocks all of them, so the 10% international share of the core stays in cash. Waiting, a higher limit, or the US sub-book/GIFT City are his call.
2. **The single-ETF rail (35%).** Under it the system cannot hold the Nifty 500 exactly: index-only lags the index by 1.9 points on the history and 2.6 on the final window. Raising the rail for a broad index ETF is his decision.
3. **The starting split vs his own index rule.** In the lab the default 60/35/5 FAILS his A50 rule (the longterm sleeve, a proxy of 30 liquid stocks, does poorly: 10.9% a year after tax against the index's 14.3%, worst fall -50.8% against -63.8%, and the fall is only 20% smaller where a third is needed); holding the index passes (12.4%, lag 1.9 points). With `[baseline_v2] index_fallback = true` (the default, and A50(b) read literally) the first strategist tick makes the active target index-only (core 100%). On the live book that buys the three index ETFs and gold with the cash and holds the eight stocks. Set it to false to keep his 60/35/5 start.
4. **The swing study failed.** None of the three variants beats the Nifty 500 ETF after tax and charges, and harvesting does not help a monthly-rebalanced stock book: nothing swing acts live. Two optional follow-ups, each a new registered study: a drift overlay on an index core; harvesting limited to buy-and-hold core ETFs.
5. **Tax for the US leg** needs a chartered accountant's reading before real money: whether his GIFT City route qualifies for the IFSC wording of ss.196(3)/198(4), the FX conversion reading, and the Form 44 deadline (`docs/US_LEG_S81.md`).
6. **0.5-point fall tolerance** in the index rule and the **ETF cost estimates** (Nifty 500 TRI minus 0.20%, Nasdaq times USDINR minus 0.60%) are the core-lab agent's; change in `service.INDEX_RULE` and `runner.CORE_SYNTH`.

## Not verified
Live Kite (quotes, bars, login-lost) only with a fake client; the first live day is Wed 2026-11-11. The Opus strategist with the new tools (`propose_allocation`, daily-policy interface) was not run for real tonight (no paid call; scripted fake in tests). `pflab verify --wake-check` and `--hour-check` cannot be done unattended.

## Final results of the night (added at release)
- Full suite on the integrated tree: 3,267 passed, 0 failed. The five protected engine suites are byte-for-byte unchanged since before S80. Privacy grep clean; no control characters.
- `tools/drills_s81.py run --run-name final`: all 14 drills PASS (smoke, accelerated with 10 of 10 steps, accelerated_long, kill_switch, off_fri_mon, off_10_days, net_down, ollama_down, docker_down, kite_logged_out, budget_exhausted, failing_champion, probation_withdrawn, kill9).
- Four more real bugs found and fixed by the merged-tree drills: a sale at a loss after taxed gains gave a negative incremental tax that the ledger rejected (the `paper` job failed and the loop stalled); `kg2_nightly` and `news_s81_topup` failed instead of waiting when the graph's raw inputs were absent; a swing trigger's stop and target were passed to `exits.open_plan` under the wrong keys; harvesting ignored the turnover caps (15% of the book in a close against a 10% cap).
- `pflab verify --offline --app D:\PortfolioLabApp`: every step that can run passes; the migration of a copy of the live store to schema v143 lost no row and the rollback lost no row; the live ledger's hash was the same before and after.
- A real Opus strategist session (scratch store, real Docker sandbox, real 2005-2017 history): 17 turns, 3 lab runs, one challenger, one allocation proposal, one note, Rs 19.31. The new tools and prompt work end to end.
- A preview of the new close loop on a COPY of the live store (the 9 Nov close, 0.43 seconds): it buys three index ETFs and the gold ETF and trims the one stock over the 10% rail; the international ETF has no price in the store, so its 10% stays cash.
