# S64 kickoff prompt: the companion's day (paste into a new Claude Code session)

---

You are starting **S64, the companion's day**, for Portfolio Lab, the investor's personal portfolio system (real use,
real money). Read, in this order, before anything else: `CLAUDE.md`, `docs/HANDOFF.md` "Start here", `docs/COMPANION.md`
(the design), `docs/STATE.md` (S62, S63), `docs/PLAN.md` amendments A17-A23, `docs/BRAIN.md`. Then read the investor's
own words below twice: they are the intent of the system, and every design choice is checked against them. Do not ask
him to re-explain anything written here. Branch `pm/s64-finish` from `main` (the repo started fresh on 2026-10-25 as `portfolio-lab`;
the old history is in `data\backups`).

## The investor's own words (2026-10-25; kept as he said them, two company names on his list replaced)

> They say AI can't trade, it has trained on data, it will lose money, but AI and LLMs, if used correctly with their
> power, can work. That is why my own portfolio optimizer. Think of it: I am no trader, I am no mathematician, I am no
> quant researcher, I am no hedge fund, I am no genius. I have a portfolio, I invest based on what I feel right. But what
> if I had a companion. Be it web search, be it calculating, be it recommending, be it forecasting. Humans can predict
> better than machines, I get it, but it can work if used correctly. I am an employee who works. You have my bank
> statements; my debt and gold part was already decided in previous sessions, including the future international split.
>
> Now based on this we create a system. The system turns on, OK, the AI turns on. I am logged in to my Kite account. Now
> the autonomous part starts. OK, this is the portfolio. Today the market has gone a little down and it seems by the end
> of the day it will go even more down. Let's not panic, let's research. OK, let me ask the user for details from Tijori;
> OK, I got the companies' details; OK, let me see beyond this, let me search the web for what is relevant, let me search
> the news, any update I can get; I have to make sure the news is current or recent, not old. OK, it seems the war has
> caused the fuel cost to inflate; that is why the market is down, and [a large oil-and-telecom company on the list] as
> well.
>
> OK, I collected all the material; let me provide it to a mathematician to work on the numbers. The mathematician
> thinks: OK, the current portfolio has this many of its shares, but the market seems to go down; let me check previous
> data; it did have an all-time high; it is such an old company; if bought at a low price it seems right. Let me see the
> risk factor, let me see the P/E script as collected and provided by the user and the researcher; there are many things
> provided; let me see what is relevant and what is not. OK, I have segregated; this is relevant; now let me work on the
> numbers. It seems the price will go down more; the market is a little unstable. Let me provide this to the ones who
> handle simulations. OK, they run simulations. The USA housing market crash also affected India, so let me see. Next
> comes sentiment: I know a model can't see a bubble, but the AI bubble seems to be a big thing; the market is burning
> money; prices seem to go high but it may burst; so while the IT sector is important I need to be careful, not over
> invest, or it is fine if it is low for now. I missed an opportunity: [a recent EV IPO on the list], 390 when the IPO
> launched and right now the price is 1400, but based on reports and the current trend it will come down, it will
> correct itself; let's wait. Regarding IPOs, you have NSE stocks; it is a new stock; let me provide the insight.
>
> OK, there seems to be a crash in the market; let's see what we can do; there are also after-effects of the crash;
> let's not panic; how much can the user buy in the dip. My goal: I want good returns in the long term, but it comes at a
> risk factor; let's see if it works for me. Today the market seems normal, but let me collect data, see what is
> happening, keep on working, understand the market, let me see how companies are moving up and down together. There will
> be days the user is not providing me tasks; it is my job to keep on looking. OK, the user didn't provide anything, but
> I saw today that if I had bought this, or suggested this, or taken this decision, it would have failed. An idea didn't
> work here; I will try it in some other situation. Let me work on the maths and taxes. It works experiments, market on or
> off, backlog or not. OK, this is the current portfolio. I know it can't see the crash, but running all the time gave it
> enough insight: it seems we are at the very edge of a crash; it found an edge in beating the market, to get me returns.
> All systems, all things in sync, running, working.
>
> The mathematician: maths itself is a language; we use it to be sure of what happens. Crash days: it is not calm, but it
> understands; we need to be careful, as it can hallucinate or drift; the maths works better. OK, the market is closed,
> time to work: past market analysis; and when the USA market is open we switch to that. Do we add F&O?
>
> We don't have volumes, we have AIs, and we can use them. I need a companion in this: consider me a normal guy, and the
> system the big guy who works at Jane Street or D. E. Shaw. I see in the morning that a pharma company seems to make a
> drug deal and seems to cure cancer; if that is true, the stock will shoot up. I tell this to my companion; he uses the
> compute, multi-tasks, does the research and provides an outcome: it seems there is a competitor in this; if he releases
> before the company, the other company's stock can crash as well. Let's wait and keep monitoring the price and the news
> on these things. Based on the info I am getting, it seems we should buy X amount of the competitor at this price; if we
> can invest more, good, but the maximum price should be this, at which you can buy; make the alert and wait. Once the buy
> is done it looks at it: the all-time watcher of my portfolio. It also sees the unused funds in my Kite account.
>
> Say I say there is a bubble in AI. Obviously it cannot see it: the prices seem to go high, all are happy, all seems
> good, we can buy. But I say: fine, we can buy, but look into this: each AI startup is an investor in another, they are
> raising money and buying chips, and in a way there is no money in the system; the market will correct itself; look into
> it carefully. Then if it finds anything, it says: what we can do is keep some liquid, reserved for the dip, for a year
> or so; if it happens, good, or we reallocate that money elsewhere, in a different sector.
>
> It auto-cleans: oh, this is very old, new data has this covered, let me remove this. My context window only lets me look
> back this much; the knowledge graph will have it. A journal: this happened when this happened; this seems to be a
> cause, I will check later; OK, this is the cause. In the journal: I took this decision and this happened. Let me go
> through the knowledge graph; it is something the AI builds on its own.
>
> So regardless of what I say or not, it should work on its own, build on its own, find strategies to get returns in the
> long run, and based on how I see it: AI, chatting all around my portfolio.

## His answers (2026-10-25; do not reopen)
- Telegram only when it matters today (a crash, a buy price reached, a big risk); the rest on the screen, plus a morning
  and an evening summary.
- Dip money: his monthly amount and the FD tranches, plus a liquid reserve the system may propose; never beyond the
  targets and the 35% fall limit.
- Theme limits (AI, IT, ...): the system measures and proposes with evidence; applied after his yes; then it holds itself
  to them.
- IPOs and missed winners: a small separate opportunity pot with its own limit; each idea with a reason, a buy price, an
  exit, and a score.
- F&O: the data yes (open interest, put-call ratio, futures premium; restore `data/fo_bhavcopy.py` from history), trading
  no; hedging only if a later study shows it pays.
- "Make the alert in Kite": our own price watch (a Telegram message with a ready ticket); a GTT is an order, never placed.
- No terminal access for the system: it writes calculation and study code in the sandbox (checked by a second
  independent version) and proposes new tools or fixes, which a Claude Code session reviews with him.
- The first run from a fresh clone and the final clean come at the very end, after a month in sync (PLAN A23's S64 list
  moves there).

## What Claude must keep true (the rules that make his picture safe)
- Maths decides; models read, connect and explain (CLAUDE.md 9: no model-made numbers). Crash days get more checks, not
  fewer.
- An "edge" is only what passed a test written before the run and checked on data the system never saw (CLAUDE.md 12; the
  learner's protocol). A crash is never predicted; it is described by probability with its n.
- Forecasts are ranges, scored when due. Note: the S52 TimesFM tests of returns and volatility failed (Q1-Q4), so price
  ranges come from calibrated statistics until a registered test says otherwise.
- It never trades, moves money, or changes targets or money limits; Kite stays read-only.

## S64 scope: finish, do not rebuild (the investor: "we had already built most of that; I need this to be done")
Most of the companion exists (see `docs/COMPANION.md`). Start with a one-hour inventory against his words above (what
each part of his day maps to in the code today), then wire only the gaps into the existing brain, tools and jobs, each
run on the real path (paid calls priced, inside the Rs 2,500 cap):
1. Morning and evening summaries on Telegram (the morning review exists; add the evening one; Telegram otherwise only
   when it matters).
2. News recency check on everything the brain reads; a Tijori ask (Needs from you) the moment a company's detail is missing.
3. Cause hypotheses in the graph: the brain records "this seems the cause" with its evidence; later confirmed or refuted.
4. Theme exposure (AI, IT, ...) with a proposed limit (applied after his yes); the dip reserve; the opportunity pot.
5. Every suggestion with a price range, an amount, the highest buy price and what would prove it wrong (from the stock
   facts' statistics), followed by a price watch and, after he buys, the holding and idle Kite cash watched.
6. Scenario chains (oil, rupee, a US crash) through `risk/shock_betas` and the macro data, on his portfolio.
7. F&O data restored as information (`data/fo_bhavcopy.py` from history; open interest, put-call ratio, futures premium).
Then hand him the switch-on (the tick registered) so the record builds before January. S65, the last session: a short
sync check after some weeks of running, then the first run from a fresh clone and the final clean.

Rules of the house apply (CLAUDE.md): reports to him in 15 lines or fewer; long runs are his, with the exact command; no
shell heredocs for code; the privacy grep (`.githooks/pre-push`) before any push; at each STOP update STATE and HANDOFF,
commit.
