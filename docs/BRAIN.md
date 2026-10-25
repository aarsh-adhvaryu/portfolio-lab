# The brain: a design for thinking, working and reporting agents (proposal, 2026-10-24)

Status: PROPOSAL for the investor's decisions (end of file). Nothing here is built yet. Prices from Anthropic's price list as
cached 2026-10-06 (per million tokens, input / output): Opus 5.5 $4 / $20, Sonnet 5.5 $2 / $10, Haiku 5.5 $0.10 / $0.50
(prompts up to 100K tokens). Cached input is read at about a tenth of the input price (Opus and Sonnet $0.20); the batch
API halves the price of anything that can wait. At the system's rate (about ₹90 a dollar) one Opus thinking pass of
8,000 tokens in and 1,200 out is about ₹5.

## What is missing today

The system has memory (knowledge graph, notes, the fact sheet), hands (jobs and agents) and reflexes (fixed rules:
the conductor, `jobs.FOLLOWS`, guards, keyword routing). Nothing holds the investor's goals, looks at everything together,
decides what matters, and learns whether it was right. The local 8B model words answers from facts; it cannot reason
across the whole picture, and the 12 GB laptop GPU cannot hold a model that could.

## The principle

Thinking is expensive only when it is wasted. Most of the work needs no model at all; a model is for judgement and
for reading language. So each kind of work goes to the cheapest thing that does it well, and only the brain uses the
most capable model, and only when something has changed.

## The layers

| Layer | What does it | Cost | Sees | Its jobs |
|---|---|---|---|---|
| 0 Code | Python on this PC | free | everything | every number: ledger, today's portfolio, tax, measures, guards, simulations, data |
| 1 Reflexes | rules on this PC | free | everything | what is due, what new data starts (`FOLLOWS`), flags, asks, escalation rules |
| 2 Local model | qwen3 8B (kept) | free | everything | private documents (statements never leave the PC), wording answers from facts, routing |
| 3 Readers | Haiku 5.5 | ~₹0.05 a filing | public data only | read every filing, results, concall, news item, Tijori PDF: tag materiality, extract figures with their page, summarise |
| 4 Workers | Sonnet 5.5 | ~₹4-8 a company note (batched / not) | public data only | company notes, event analysis, thesis checks, the workshop's independent second writing (a different model makes a better check) |
| 5 Brain | Opus 5.5 | ~₹5 a pass | composition (names, weights %, gains %, lot terms), goals, limits; never rupees or account details | decide what matters, send the agents, prepare plans, tell or ask the investor, keep and score its predictions |
| Claude Code | interactive sessions with the investor | his plan | the repo | building and maintaining the system; a monthly review with him. Not in the unattended loop (subscription usage limits; the unattended path uses the API key, priced and capped) |

The Haiku readers replace a bigger local model: they cost less than the electricity worry and read far better than
the 8B, on public data, where privacy is not at stake. The local model stays for what must not leave the PC.

## How the brain works

1. **It wakes on events, not a clock.** A material flag, a result on a holding, a fall past a limit, cash arriving,
   a plan coming due, an answer from the investor, a worker's finished note. Plus one morning review on trading days and one
   weekly reflection. A daily cap on passes keeps a noisy day from spending the month.
2. **What it reads** (built by code each pass): a stable part, cached (its instructions, the investor's goals and limits, the
   portfolio's composition, theses, its open predictions), and a short changing part (what happened since its last
   pass, already summarised by the readers and workers). It never reads raw documents itself.
3. **What it may call** (read-only tools): today's portfolio, the reviewed measures, the tax planner, research flags,
   notes, knowledge-graph search. Numbers come only from these.
4. **What it returns** (structured, checked by code): decisions, each one of nothing / investigate (which agent, what
   question) / prepare a plan / tell the investor / ask the investor, with the reason and a priority; predictions, each a claim with
   a measurable check, a due date and a confidence; and a short note.
5. **Code carries the decisions out** through the existing agents and doorbell (spend priced first, the investor's yes above
   his per-job limit). Their results come back as events, and the brain thinks again if they matter.
6. **It learns in the open.** Every prediction is scored when it falls due (calibration, Brier score); the weekly
   reflection reads its own scorecard. The journal is on the dashboard: what it decided, why, and how its calls turned
   out.
7. **It cannot trade, move money or change targets** (as today). A plan stays a ticket the investor enters himself.

## The token problem, answered

- **Caching:** the stable part (about 20,000 tokens) is cached, so a pass pays a tenth for it (about ₹0.40 instead
  of ₹7 on Opus). Passes in a burst share the cache (one-hour cache for the morning).
- **Batch:** anything that can wait (overnight company notes, the weekly reflection) runs at half price.
- **Summaries before thinking:** Haiku and Sonnet read the documents; the brain reads their summaries. The brain's
  input stays small.
- **Effort per task:** routine passes at low or medium effort; the weekly reflection at high.
- **A governor:** a monthly budget per layer. When the brain's share runs out, the brain falls back to Sonnet, then
  to the reflexes alone; the investor is told, never surprised.

Rough month (22 trading days): readers about ₹100 (2,000 documents); workers about ₹400-800 (around 100 company notes,
batched); brain about ₹550 (a morning review a day, about three event passes a trading day, four weekly reflections,
mostly cached). About ₹1,000-1,500 in all, the current cap, if the workers move from Opus to Sonnet.

## How we know it works (pre-registered before it runs)

- Its predictions, scored on outcomes after each prediction was made (no memory of the past can help).
- Recall: of the changes the investor marks as mattering, how many did the brain act on, how fast.
- A cheaper brain as the comparison: Sonnet 5.5 against Opus 5.5 on the same passes (the queued Sonnet vs Opus protocol
  extends to this). The cheaper one is adopted when it is not worse.
- If the brain does not beat the reflexes on these, it does not stay (the system's rule).

## Build order (each step tested and usable on its own)

1. Readers: Haiku tags and extracts every public document (replaces the local tagger there).
2. Workers: company notes and the workshop's second writing move to Sonnet; Opus stays for deep research.
3. The brain's loop: events in, decisions out, the journal on the dashboard; predictions recorded.
4. Scoring and the weekly reflection; the Sonnet-as-brain comparison.

## Decisions

1. **What may go to the API (The investor, 2026-10-24):** the portfolio may (holdings, amounts, weights, gains, lots, cash,
   goals and limits). His **identity and banking details never leave the PC**: PAN, account and folio numbers, client
   and DP ids, bank names with account details, addresses, phone, email, and the statement files themselves. The
   egress gate enforces this list in code before every call.
2. **Money (The investor, 2026-10-24):** an API key with $100 for about three months, separate from his other projects (a
   portfolio_lab workspace with its own key and spend limit); the system's cap about ₹2,500 a month. His Claude
   subscription stays for Claude Code (building), never for the system's unattended agents (Anthropic's terms; shared
   limits).
3. **Claude Code:** interactive only.

## Step 2 proposal (2026-10-24, after S59's test): one brain with tools

**Built in S60 (2026-10-25, PLAN A18):** the registry (`hq/tools.py`), per-stock facts (`hq/stocks.py`), the tool loop
(`hq/brain.py`), the suggestion ledger (`hq/suggestions.py`), redaction (`hq/redact.py`) and the cited-page fetch
(`hq/fetch.py`). Not built: Gmail (later), the learner (S62). The prediction scoring, the reflection and the shadow trial
carry on (protocol amendment 1).

The investor 2026-10-24: one brain with tools, agents only where really needed; learning from real outcomes, taken or
declined. The brain (Opus) runs a bounded tool loop per pass (plan, call, check, at most 8 turns, the governor before
every turn); in shadow mode the action tools record instead of acting.

**Read tools (all built, wired as functions):** portfolio today (`pm/today`), drift against targets and guards
(`plan.targets`, `plan.guards`), tax plan (`tax/plan`), reviewed measures (`calc/measures`), simulations
(`app/sims`, `risk/montecarlo`), forecasts (`quant/tfm2_live`), readings and filings (`hq/readers`), knowledge-graph
search and timelines (`kg/graph`), analyst notes, memory and journal and scorecard (`agents/memory`, `hq/keeper`),
ready plans (`plan/ready`), research flags (`agents/researcher`), price history (`prices`), the Kite snapshot.

**Action tools:** ask the investor (`agents/questions`, built), tell the investor (`hq/messenger`, built), order a research note
(the doorbell: Sonnet batch or Opus live, built), a calculation (`agents/workshop`, built), a quant template
(`agents/quant`, built), remember / correct memory with a reason (`agents/memory` supersede, built), record a
prediction (`hq/keeper`, built), **record a suggestion (to build: the suggestion ledger below)**.

**Server tools (Anthropic):** web search, basic cited variant (built through the analyst); **web fetch of a page
already cited, e.g. a filing PDF (to add)**; code execution: no (the data stays here; the local sandbox exists).

**Connectors:** Kite read-only, Telegram, BSE/NSE/AMFI/IBJA collectors (built); **Gmail (optional, to build): the
broker's contract notes and statements fetched from his mail, redacted, into the inbox (needs his consent)**; Google
Drive for the drop folder (later); Tijori and Screener have no API (exports). MCP servers on the API: not needed now
(our tools are local functions: faster, and nothing is exposed); Claude Code plugins and skills are for building.

**Real agents (own context, worth it):** the research analyst (reading-heavy deep dives, returns a cited note; built),
the readers (bulk Haiku reading; built, a worker), **the learner (step 4, to build)**. Everything else becomes a tool:
receptionist (routing code), messenger, watcher, cleanup, graph, memory keeper, simulation, calculation, quant,
portfolio. The board stays as the task log; the office view shows the tools by room.

**The suggestion ledger (to build):** every suggestion with its reasoning, the data it rested on, and the investor's answer
(taken / declined / no answer); scored on what prices and his portfolio did (declined ones as if taken, on paper);
hit rates by kind of suggestion with their n (small-numbers rule: no conclusion under 20), the decision quality at the
time apart from the outcome; the lessons go into the brain's cached context. One loss never retires a kind.

**Statements to Claude, redacted (The investor 2026-10-24; to build):** `redact()` replaces PAN, account / folio / client /
DP numbers, IFSC, UPI, his name, address, phone and e-mail with tokens ([ACCOUNT-1], [PAN]) before any statement text
leaves; the transaction rows go. The egress check must pass on the output; tested on his real statements here first.

**Memory that updates:** graph edges carry valid_from / valid_to, memory rows supersede, journal entries get their
outcomes written back; the brain may correct a memory row, with the reason kept.

## Cost control comes first (his worry: an always-on brain burning tokens)

The brain is not a loop that runs all the time. Code watches for free; the brain sleeps until code finds a material
change, and a Haiku check (about ₹0.05) confirms it deserves a pass. Every call is priced before it is made, against
four limits held in code: tokens per pass, passes per day, rupees per day, rupees per month. A call over any limit is
not made. Worst case with 6 passes a day plus a morning review: about ₹45 a day, ₹1,300 a month; a normal day far less.
Settings get a switch: Brain off / economy / normal. It starts in **shadow mode** for two weeks: it thinks and writes
its journal but acts on nothing, so its real spend and usefulness are measured before it is trusted to act.
