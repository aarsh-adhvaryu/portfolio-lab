# PLAN: intent, frame, decisions, and what remains

(Condensed 2026-10-28, S65. The old build plan, the session log and the handoffs are in git history; what exists is in `docs/BUILT.md`, the tests and
verdicts in `docs/STUDIES.md`, how to install and run in `README.md`.)

## Intent: the investor's companion
He is an employee, not a trader, quant or hedge fund; he has a portfolio and invests by feel. In his words (2026-10-25): *"They say AI can't trade... but AI
and LLMs, if used correctly with their power, can work... what if I had a companion: web search, calculating, recommending, forecasting... The system turns on.
I am logged in to Kite. Now the autonomous part starts... Let's not panic, let's research... I have to make sure the news is current, not old... let me provide
this to a mathematician... the maths is a language; we use it to be sure of what happens... it can hallucinate or drift; the maths works better... there will be
days the user is not providing me tasks; it is my job to keep on looking... I saw today that if I had bought this, it would have failed. An idea didn't work
here; I will try it in some other situation... Consider me a normal guy, and the system the big guy who works at Jane Street or D. E. Shaw... So regardless of
what I say or not, it should work on its own, build on its own, find strategies to get returns in the long run."*
And (2026-10-28): *it must run by itself like an app, from a clean reset, updated like software; Claude Code and its memory are for development only.*
**Maths decides; models read, connect and explain.** It never places an order: it brings a reasoned suggestion with a price and he decides.

## The frame (his, fixed; changes only on his written word)
- Allocation in `targets.toml` (stocks-heavy, debt, gold 10-15%, a future international split); the **35% fall limit**; the monthly amount and FD tranches;
  FD money over 8-12 months; PhD maybe 2028. The system proposes, with evidence; his yes applies; it then holds itself to it (theme limits, dip reserve,
  opportunity pot, the US sleeve share).
- **Reaching him:** Telegram only when it matters today (a crash, a buy price reached, a big risk) plus a 09:00 and a 21:45 summary; the rest on the screen.
- **Kite read-only.** Buy prices are our own price watches (a message with a ready ticket), never a GTT. F&O: data yes, trading no. IPOs and missed winners:
  a small separate pot with its own limit, each idea with a reason, a buy price, an exit and a score.
- **Cost:** everything inside Rs 2,500 a month; local wherever good enough; paid calls priced first.
- **What it may not do:** trade or move money; change targets or limits; edit its own code or run commands. It may write calculation code in the Docker sandbox
  (a second independent version checks it) and propose tools, which a Claude Code session reviews with him.
- **Taxes:** Quicko files his return; the system prepares its inputs (`pflab pm quicko`) and reconciles; it files nothing.
- **US sleeve:** BETA until January or February 2027 (Zerodha GIFT City; approved; no money sent, no US holdings). Collection runs so history builds.
- **Two installations (2026-10-28):** the APP runs his money, installed from a release tag in its own folder, updates like an app with backup and rollback; the
  WORKSHOP (the repo checkout) is the beta where Claude Code develops, sends nothing outward and makes no paid call unless told. His record (the store) is his:
  an update never wipes it.

## How it improves (the research rule)
It forms ideas from what it watches, its journal and papers, writes each as a test before running it, checks it on data it never saw, wires in what passes and
keeps what fails as "tried, did not work". An "edge" is only what passed such a test, counted in the learner's counter (the bar rises with every test). A crash is
never predicted, only described by probability with its n. Research principles that stay: point-in-time or it does not exist; survivorship is a data error (the
universe includes every name that traded); taxes and costs are in the objective; LLMs never decide; a single backtest, or one live year, is not evidence.

## Design decisions, one line each
- 2026-10-06: Portfolio Manager scope (Indian shares, IPOs, funds, gold, bonds, cash); tax rule tables sourced and dated; both regimes shown, he chooses; Kite Connect read-only;
  maintained libraries over hand-written code; capital-gains rule coverage starts at transfer date 2024-07-23 (earlier raises).
- A2: Telegram send-only through `requests` (no bot framework); the two-way bot only while the dashboard is closed.
- A7 (S37-S49): a team of agents (researcher, analyst, advisor, trader planner, trade check, event, thesis, memory, questions); the API analyst is the only doorbell.
- A9: the small-numbers rule (under 20 observations: the count, no conclusion).
- A11 (S57): Graphify not adopted; the system's own graph is cleaned instead.
- A16-A18 (S59-S60): agent HQ and one tool-calling brain under a spend governor and an egress gate; its journal, suggestions ledger and predictions are scored later.
- A22 (S62): the learner (sources, claims, templates, protocol hashes, counter); the security agent; web search through the brain.
- A23 (S63): a fresh repo `portfolio-lab` (private); the old research project lives only in a private archive repo.
- A24 (S64): model-written calculations run in Docker (`--network none --read-only`, 2 GB), `contained: True` recorded.
- S64: TimesFM removed (failed every registered test); price ranges come from calibrated statistics and are scored; maths tools (CAPM, process, comove) are descriptive.
- S64: the one picture (`hq/picture.py`) is the brain's first tool; option-implied probabilities, gauges, valuation in plain words, nudges, IPO planner, scanners, replay bench.
- S65: the app/workshop split (`release.toml`, outward guard, `pflab update`, install and seed scripts); the system onboards him (Setup, secrets, content recognition,
  bank labels as questions, IPO and cost forms); the Quicko pack; the US sleeve as a beta feature flag; the learner's counter carried into a fresh install.
- S65: the investor's three other repos (the research archive, Q_Alpha, Q_Alpha_Research) read on his instruction; ported: the twin-books scoreboard and the
  stress-gauge hedge as forward test F5; their results recorded in STUDIES; the repos deleted after.
- S65 amendment: frozen protocols and results of the live tests stay as files in `docs/protocols/` (a claim's protocol is hashed at registration); the other
  protocol and result files were folded into `docs/STUDIES.md`.

## What remains (dated; update at each stop)
1. **Switch-over (S65 Phase 9).** Merge to `main`, tag `v2026.10.28`, clean-room install test in a throwaway folder from README alone, install the app, seed its
   MARKET data (not the store: he asked for a complete reset, so the app starts a fresh record; the learner's counter is carried by code), run Setup, drop his
   documents into Inbox, answer the questions, then self-test, an overnight dry run, one real brain pass (about Rs 10), the two Telegram summaries, the
   `companion` job once. Then the shortcut and the tick point at the app, the user-level `PFLAB_DATA_DIR` is removed, the workshop's scheduled tasks stop.
2. **The forward ledger (S66).** So the app never needs his statements again: Kite captures each day's trades and holdings as they happen; the monthly CAS
   arrives by read-only Gmail and reconciles them; FD intake by form or certificate in Setup; statements only open the books once, then are deleted.
3. **Forward tests and the record (S65).** F1-F4 (`docs/protocols/s65_forward_protocol.md`: the passed avoid rule and the reversed leads) and F5 (the stress-gauge
   hedge on paper, from the investor's Q_Alpha_Research) run by themselves on live data; decided once (F1-F4 at 24 months, F5 at 24 months and 2 episodes). The
   scoreboard (`plan/twin.py`) records his book, the brain's suggestions on paper and the equal-weight bar from the app's first night. Nothing to do but wait and read.
4. **US sleeve (January or February 2027).** A sync check first; the SEC contact (`[sec] user_agent` in secrets); the primary-source check of the foreign-tax rows
   (2027-01-01 or the first remittance); the GIFT City statement parser (opens with his first statement); the sleeve question (share and start month).
5. **Filing time.** The 112A template's own header row and a possible column 1b; check the pack against Quicko's own summary (`pflab pm quicko --fy N --check export`).
6. **Optional, not built:** advance-tax reminders and harvesting suggestions; segment revenue and 3-year peer growth (no data on record); alpha-sign and build-up scans
   (no testable history).
