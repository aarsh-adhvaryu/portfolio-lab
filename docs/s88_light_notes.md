# S88 — a plain chat answer is cheap (notes, 2026-11-15)

Branch `pm/s88-light`. Measured on a scratch copy of the app's store (`D:\s87_scratch`), through the real engine on his plan, one fresh session per question. "Tokens" = what Claude Code reports for the
session: fresh input + cache reads + output (cache reads count too; they weigh less against a plan, but the plan does not say how much less, so they are shown).

## Where the 100k came from (measured with Claude Code's own `/context` breakdown, `ClaudeSDKClient.get_context_usage`)
One call of the old operator carried about 36-45k tokens before any question: Claude Code's system prompt 2.4k, its built-in tools 4.3k, **MCP tools 13-25k**, skills 2.4k, memory 0.8k, plus the messages (tool results).
A plain answer made 2-5 calls, so 75-117k. The single biggest item was NOT our tools: **his account's connectors (mail, calendar, drive, docs...) were loaded into every session** (about 12k tokens of tool
definitions per call). `strict_mcp_config` (only the servers we name) removed them for every session, the desk, the cases and the builds included. (An earlier S87 note said "~100k, mostly the system prompt":
the prompt is 2.4k; the cost was the tool definitions, our 60 and his connectors.)
A measurement trap, fixed: my first S88 run re-used one chat id and so one resumed session for all questions (the numbers grew 97k, 210k, 343k, 485k). The table below is one fresh session per question.

## Before and after (same 7 questions, same copy of the store)
| # | question | before: tokens (in+out) | before: s | after: tokens | after: s | road after |
|---|---|---|---|---|---|---|
| 1 | How is my book today? | 117,070 (3 turns) | 66.1* | **6,220** | 12.6 | quick (book_card, today_card) |
| 2 | What did Nvidia do this week? | 110,728 | 8.8 | **4,793** | 5.6 | quick (name_card, graph_name) |
| 3 | Why did the paper book sell a large conglomerate stock? | 76,223 | 12.5 | **6,474** | 12.1 | quick (decisions_card, name_card) |
| 4 | What is my biggest risk right now? | 118,085 | 11.6 | **6,222** | 9.0 | quick (book_card, today_card) |
| 5 | Thanks | 27,274 | 3.4 | **0 (no model call)** | 0.1 | ack |
| 6 | Do two large banks move together? | 110,925 | 9.4 | **33,472** | 7.8 | full (pair_study, comovement) |
| 7 | Read this PDF and tell me the debt (a public filing) | 30,505 | 8.2 | **19,133** | 6.3 | full |
(*the first call of a session includes its start-up.) Fresh-input / cache-read / output / turns per question are in `scratchpad` logs `before.log` and `after.log` of this session (not committed: they hold the store's answers).

Answers, read for sense and sourcing: 1 and 4 give his real holdings and the paper book with the card's date and say the Kite snapshot time is missing (true on the copy); 3 gives the logged reason and the desk's later
doubt about the news item; 2 says plainly it has no data on Nvidia (not in the book or the stock list; the full operator has no web either), which is the honest answer. The numbers pass the same
`only_sourced_numbers` check as before. Pass criteria: Q1-4 each under 15k tokens with a sourced answer: **met** (4.8k-6.5k); Q5 no model call: **met**; Q6 and Q7 by the full operator, each cheaper: **met** (33k vs 111k; 19k vs 31k).
Other sessions, same cause, not re-measured: the gateway PDF read went from 18.6k to 4.9k tokens; a case step with the caller's tool is about 1.1k (unchanged); the desk (14k) and the alarm case (12k) were
measured before the connectors fix and can only have got smaller.

## What was built
- **L1 the quick road** `oper/light.py`: its own short system prompt (15 lines) (not the Claude Code preset), no built-in tool (a built-in call is refused by the callback), no MCP but its own, no skills, no subagents, no CLAUDE.md,
  five tools each cut to about 1,500 characters (`book_card`, `today_card`, `name_card`, `decisions_card` (paper trades with their reasons + the thinking loop's decisions and cases), `graph_name`), at most 4 turns, structured
  answer `{answer, needs_full, why}`, Auto = Sonnet at low thinking (a picked model is honoured). History: the last 6 messages + a 10-line summary made by code per thread (rewritten every 10 messages), never a resumed session.
- **L2 the router** `oper/pathrouter.py` (rules, no model call; tested trigger by trigger): "thanks"-type replies get a fixed reply; a file, a link, "look into / study / backtest / compare / stress / simulate / move together /
  build: / fix / add a skill / add a tool / monthly review" or `/full` go to the full operator; everything else is quick. A quick road that says `needs_full` (or fails) hands the question to the full operator ONCE, with the
  summary; the full road never goes back. Every reply carries its road and tokens (`meta` text and `meta_obj.path` = quick / full / ack, `meta_obj.tokens`).
- **L3 the full operator, trimmed**: 29 default tools (the ones the questions and skills use) and `more_tools` for the other 39 by name; only the skills a request needs are loaded (`skills=`); a session past 60k
  tokens of history starts fresh with the thread summary; the account's connectors are not loaded (`strict_mcp_config`). Permissions, the sign-in guard and the Yes/No flow are untouched (the S87 tests pass unchanged).
- **L4 budgets** (`[operator]`, tokens a day; the old ones were 1.5M chat, 600k desk, 900k cases, 1.2M build and the S87 chat budget would have stopped him after six old-style questions):
  `budget_chat_light` 400,000 (about 60 quick questions at 6.5k), `budget_chat` (full road) 600,000 (about 10-20 full questions at 19-80k, or one long session), `budget_desk` 250,000 (14k a run, two runs a day plus the
  weekly note), `budget_cases` 350,000 (12k a case; three a day plus alarm cases), `budget_build` 800,000 (two builds a day; S87 measured 400k for one build with the connectors loaded). A class that spends its day stops
  until tomorrow; code-only parts go on.

## A normal day of chatting, as a share of his weekly limit (an estimate, labelled as one)
Before: 20 questions of the old kind at 75-117k = about 2M tokens a day. After: 15 quick questions (6k) + 3 full (35k) + a few thanks = about 200k a day: **about a tenth**, 90% less. What share of his weekly limit
that is, I cannot say: the plan does not publish its limit, and cache reads (most of these tokens) are weighted lower than fresh tokens by an amount not stated. Watch `tokens_today` in `GET /api/operator` for a week.

## Off / limits
- Nothing is OFF. `/full` is the way to force the full operator. The quick road cannot run a study, read a file, follow a link or change anything; it says so and the full operator takes it.
- Question 2 shows a real limit of the system, not of the roads: no price or news store for a name outside the book and the stock list (Nvidia on the copy), and no web in either road.
- The full operator's `more_tools` costs one extra call when a rarely used tool is needed.
- `docs/s87_operator_notes.md` still says "about 100k"; this file corrects it.
