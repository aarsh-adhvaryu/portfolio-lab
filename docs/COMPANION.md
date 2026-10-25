# The companion: what the system is for (the investor's picture, 2026-10-25)

## In one paragraph
The investor is an employee, not a trader, quant or hedge fund. He has a portfolio and invests by feel. The system is
his companion, the "big guy from a quant firm" at his side: it works all the time the laptop is on, whether he asks or
not; it researches, calculates, forecasts and simulates; it looks for ways to earn more over the long run within his
plan; and it talks with him around his portfolio. It never places an order: it brings a reasoned suggestion with a
price, and he decides. Models read, connect and explain; **mathematics decides** (models can hallucinate or drift, most
dangerously on crash days).

## The frame it works inside (his, fixed)
His allocation (stocks-heavy, debt, gold 10-15%, the future international split), the 35% fall limit, the monthly
amount and the FD tranches (`targets.toml`, his answers of 2026-10-15). His answers of 2026-10-25:
- **Reaching him:** Telegram only when it matters today (a crash, a buy price reached, a big risk); the rest on the
  screen and in a morning and an evening summary.
- **Money for dips:** his monthly amount and FD tranches, plus a liquid reserve the system may propose keeping for dips;
  never beyond the targets and the fall limit.
- **Theme limits (AI, IT, ...):** the system measures exposure and proposes a limit with evidence; it applies after his
  yes and the system then holds itself to it.
- **IPOs and missed winners:** a small separate opportunity pot with its own limit; each idea with a reason, a buy price,
  an exit, and a score afterwards.
- **F&O:** the data yes (open interest, put-call ratio, futures premium: what large traders are positioned for); trading
  no (SEBI: about 9 in 10 individual F&O traders lose money); hedging only if a later study shows it pays.
- **Kite:** read-only; buy prices are our own price watches (a message with a ready ticket), never a GTT.

## A day
1. **Wakes** with the laptop and his Kite login: the portfolio, idle cash in Kite, the market, the night's news.
2. **Watches** all day: prices, filings, deals, insider trades, FII flows, VIX, oil, the rupee, world markets.
3. **When something moves, it investigates** instead of reacting: what is happening, why, to which of his names.
4. **Research:** filings, results, news (checked to be recent), the web, Tijori exports asked from him when a company's
   detail is missing; every fact with its source and date.
5. **Connects the dots** in the knowledge graph ("the war raised fuel costs -> the market fell -> this stock fell"); a
   suspected cause is recorded as a hypothesis and later confirmed or refuted by the data.
6. **The mathematician:** keeps what is relevant, then works the numbers: history (highs, past falls, how the company
   behaved), valuation (P/E and results), risk, the reviewed measures; nothing from a model's opinion.
7. **Simulations:** what happens to *his* portfolio in scenarios, including chains from abroad (a US crash reaching India).
8. **Forecasts as ranges:** "between X and Y in a year, most likely Z", each scored when it comes due.
9. **Sentiment and themes:** it cannot see a bubble, but it measures his exposure to a theme and investigates his own
   theses (e.g. AI companies funding each other) with evidence for and against; if they hold, a plan (a reserve for the
   dip, or the money elsewhere).
10. **A suggestion** only when the facts support it: what, how much, the highest price, why, and what would prove it
    wrong; then a price watch; after he buys, the holding is followed with the rest.
11. **Crash days:** careful, maths first: what history says happens after falls like this, how much to buy within the
    dip money, and what not to do.
12. **After the close and on quiet days:** the day's and the past's analysis, how companies move together, the US market
    in the evening (context now, its own sleeve later), its own past suggestions replayed ("this would have failed"),
    taxes, cleaning its memory (old facts superseded, the graph and journal keep the history).

## How it gets better without being asked
It forms its own ideas (from what it watches, its journal, papers), writes each as a test before running it, checks it
on data it never saw, puts what passes into its suggestions and keeps what fails as "tried, did not work". Over months
its record shows which of its ideas work, with their count (no conclusion under 20). An "edge" is only one that passed
such a test; a crash is never "predicted", only described by probability ("conditions resemble the run-up to past falls;
in those, a 20% fall within a year happened k times in n").

## What it may not do
Trade or move money; change targets or money limits; edit its own code or run commands. It may write calculation and
study code in the sandbox (checked by a second independent version) and propose new tools or fixes, which a Claude Code
session reviews with him.

## Build order (the investor, 2026-10-25: "most of it is built; I need this done", before his money comes in January)
Most of the companion exists (the brain with 31 tools, event wake-ups, readers, the analyst, web search, simulations,
price watches, ready plans, the suggestion ledger, the learner, the security agent, Telegram). Nothing is rebuilt; two
sessions finish it.
- **S64 finish:** wire the seven gaps into what exists, each run on the real path: (1) morning and evening summaries on
  Telegram; (2) news recency check and a Tijori ask the moment a company's detail is missing; (3) cause hypotheses in the
  graph, confirmed or refuted later; (4) theme exposure (AI, IT, ...) with a proposed limit, the dip reserve, the
  opportunity pot; (5) price ranges and the highest buy price on every suggestion (the stock facts' statistics); (6)
  scenario chains (oil, rupee, a US crash) through `risk/shock_betas` and the macro data; (7) F&O data restored as
  information. Then the investor switches the system on (tick registered), so the record builds before January.
- **S65 last:** after some weeks of running, a short sync check (what broke, the record so far), then the first run from
  a fresh clone (keys, Kite, every backfill, Gmail statements, ledger, graph, forecast environment, bank labelling by the
  system) and the final clean. The US sleeve comes after, in its own sessions.
