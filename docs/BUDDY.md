# The portfolio buddy: what this project is

Decided 16 Nov 2026. This page is the definition. What is not on it is not part of the project, and is **deleted, not switched off**.

**In one line:** a workbench on his laptop that knows his holdings and his watchlist, keeps clean market data, runs any calculation on them, remembers what it found and whether it was right, and watches while he is away, with Claude in the app's chat as the one he talks to and plans with.

**Why this page exists.** The repo grew through six designs. Each rebuild switched the previous design off instead of deleting it, and the old parts leaked into the new ones (`docs/AUDIT_S92.md`). One example that matters: the chat's `portfolio` tool reads `pm/today.build`, which is built on the ledger, and in the app the ledger is the system's own account; the screens read his real holdings (`app/s89.mine`). Two "portfolios", and the numbers he is told may be about the wrong one.

## The four jobs

1. **Know.** His India holdings from the Kite login (read-only, the latest snapshot), his US holdings entered by hand, and a **watchlist** of names he does not own (up to 25). Prices, company facts, filings, news and market series are collected and kept point-in-time. One reader, `pflab/holdings.py`, is the only place any code asks "what does he hold, what does he watch".
2. **Compute.** On his holdings and watchlist, by code on the laptop, free and fast:
   - ranges: where the portfolio could be in 1, 3 and 12 months (worst, likely, best, in rupees);
   - stress: named scenarios and a shock to one name, sector or factor;
   - together: which names move together, pairs, concentration by name, sector and theme;
   - what-if: add, trim or replace a name and see the change in all of the above before he does it;
   - forecasts with a scored record;
   - a backtest of an idea he states;
   - **search**: many combinations (weights, baskets, pairs) tried by code. Every search says how many it tried and is judged on data it did not see. A search result is a claim, so it is a registered test and counts in the learner's counter. Search enough and something always looks good by luck; this rule is what makes the numbers worth having.
3. **Remember.** Every study, view and decision of his is stored with its date and scored later against what happened. The graph (`kg2/`) links filings and news to names. "What do you know about X" answers from the store, with dates.
4. **Watch.** Big moves, results, filings and serious news on what he holds and watches. A serious one is shown at once on Home and in the chat, with a desktop notification while the app is open.

**Talk.** Claude answers in the app's chat on his plan (no paid API): a quick road and a full road. Work with several steps is a plan card he starts, once or on repeat. What the model may start by itself is a standing order he can switch (`oper/standing.py`).

## Views, not trades

The model's judgement on a name is a **view** from a closed list. For a holding: hold, add, trim, sell, wait. For a watched name: buy in parts, wait, skip. Code adds the worst, likely and best case in rupees on his real position. The view is stored and scored at 5, 20 and 60 sessions against simply holding (before tax, and it says so: Kite gives no purchase dates). The scores calibrate the likelihood words. Nothing is bought or sold anywhere, on paper or for real; an order "ticket" is text for him.

## What it is not (each removed, with the reason)

| Removed | Why |
|---|---|
| The system's own paper account: the close loop, the promoted policy, the strategist, policy promotion, fills, exits, the US paper sub-book, the opportunity reserve, standing money rules | A system that invests by itself to beat the index is a second, harder project. It produced most of the pivots, most of the code, and a second "portfolio" beside his. What it was for, learning whether calls are right, is kept as scored views. |
| Telegram (bot, outbox, summaries, cards on Telegram) | He does not need it. Consequence, accepted: a serious alarm reaches him only on the laptop, while the app is open. |
| Statements, the ledger, deposits, bonds, the tax pack, money plans, guards on targets | Kite shows his holdings. |
| The agent teams, the brain and missions, the v1 graph, the conductor, the old screens' back end | Earlier designs, already switched off. |
| The paid API engines and the rupee budgets | Everything runs on his plan; tokens are the only budget. |

Kept on purpose: fixing a bug from the chat on his word (a build on a branch, a Yes/No card before any merge), offered as a card after a repeated fault and never started by itself.

## Rules that stay

Point-in-time data. ISIN is the security key. Maths decides; models read, connect and explain, and no number in a reply comes from a model. No trading path. No paid API. Any new claim is a registered test that counts. His identity and banking details never reach a model, and no real data enters git. The engine tests pass unchanged.

## Screens

Home (what changed, what needs him, what is running), My portfolio, Watchlist, Stock, Lab (studies as charts with a verdict, not pages of text), Memory, Chat, Engine (standing orders, models, tokens used), Settings.

## Done when

1. `python tools/reach.py` reports nothing unreachable beyond the research-engine files named in `docs/BUDDY_CUT.md`, and no configuration switch exists for a deleted feature.
2. The packages `core`, `paper`, `ledger`, `plan`, `tax`, `kg`, `conductor` are gone, and so are Telegram, the paid engines and the statement readers.
3. Every tool and screen that says "your portfolio" reads `pflab/holdings.py`.
4. On a synthetic store, each of these is answered by tools with numbers and dates, in a test: what do I hold and what changed today; where could my portfolio be in 3 months; what if a named stock falls 20%; which of my holdings move together; what if I trim one name and add another; what do you know about a watched name; how did your last views score; which pair on my watchlist is worth a study; search weights for my holdings and tell me how many you tried.
5. The full suite passes on his PC.
6. The app starts, every screen draws at 1366 and at 390 pixels wide with no error and no model call on load.
7. A serious alarm on a held or watched name is on Home and in the chat within the alarm lane's own limits.
8. `CLAUDE.md`, `README.md` and `docs/BUILT.md` describe only this page's system.
