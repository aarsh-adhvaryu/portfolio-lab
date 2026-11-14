# S87 — the operator: Claude Code on his plan (notes, 2026-11-14 night)

Built on `pm/s87-operator`. No schema migration: the new tables are created on first use. No paid API call was made tonight and none can be made by the system while `[engines] force_in_use = "claude_plan"`
(`analyst.make_client` refuses; the child process of every session has every key variable blanked; the sign-in must be his claude.ai subscription).

## What each real path measured (real engine, his plan, this PC; "tokens" = input incl. cache reads + output as Claude Code reports them)
| real path | result | tokens in / out | time |
|---|---|---|---|
| sign-in guard (`claude auth status`, with a planted `ANTHROPIC_API_KEY` in the parent) | signed in by claude.ai; the planted key never reached the child | - | <1 s |
| quick reply through the gateway (Haiku 5.5) | "12 times 12 is 144" | 636 / 64 | 3.3 s |
| chat question with tools, no file change (Auto: Sonnet 5.5 medium; tools `picture`, `paper_book`) | a plain answer about the paper book; sentences with numbers no tool returned were removed by the existing number check | 97,780 total | 64 s |
| same chat, new process (resume by session id) + "add a skill" | found the existing `case_review` skill, added nothing, and remembered the earlier question (the session survived a restart) | 210,110 total | 9.7 s |
| a PDF read (gateway, Read tool on a saved copy) | "quarterly revenue was 420 crore" | 18,643 / 127 | 5.1 s |
| a case step with the caller's tool (capture) and the closed-list answer | tool call captured, then `{"class": "sector_move", ...}` as structured output | 1,119 / 61 then 1,393 / 150 | 3.0 s + 3.3 s |
| RED case, the Nvidia-week headline (`tools/alarm_real_think_s86.py`, scratch store) | heard 3.0 min after publication, decision "NVDA: wait" 3.6 min after (38 s of it the model), cost Rs 0 | 9,785 / 2,636 over 4 calls | 38 s |
| a planted bug (scratch clone: `week_key` comparison inverted) | the build session found the root cause and fixed it on `fix/2026-11-14-...`, committed; my gate then wanted a changed test file and said "no_fix" because the existing test already covered it; the gate now runs the existing tests that name the changed module (they passed: 14) and says so on the card | 398,080 total | 44.5 s |
| usage limit (simulated with the scripted SDK) | thinking paused until the reset time, the chat says so, code-only parts go on, a build waits and is not lost | - | - |
| the daily desk (india_close) on the scratch copy of the app's store | status done, 3 of 3 agenda items worked, cost Rs 0; (a first try stopped on "his monthly cap has no room": the rupee cap is meaningless on the plan, `desk.cap_left` now returns None there; fixed) | 12,762 / 1,087 over 3 calls | 17.7 s |

**Appetite, honestly:** a chat answer with tools is about 100k tokens, almost all of it Claude Code's own system prompt, tool list and cache reads re-sent on each step (a resumed turn re-reads the whole session). A weekly
limit that is already 70% used can feel this. Levers, none applied yet: Auto keeps short questions on Haiku (it does); `[operator] budget_chat` (1.5M tokens a day) caps it; fewer tools in the session (the 40 chat tools
could become a core dozen); keep short replies on the old gateway loop (no Claude Code prompt: ~1k tokens). Decide after a week of real use.

## What the operator can do (and what it cannot)
- Answers with the system's tools (the chat's registry, plus `pair_study`, `lab_policies`, `problems_list`, `usage_so_far`, `decision_log`, `log_my_decision`, `my_decision_scores`, `request_build`); skills (`case_review`,
  `pair_study`, `backtest`, `stress_review`, `monthly_review`, `add_skill_or_tool`) and subagents (`researcher`, `quant`, `reviewer`) are in its folder.
- Cannot: place any order (no tool exists), write outside `notes/` and `research/` in an answer, run shell outside the allow-list, reach the network except the tools (the NSE MCP is wired but OFF until `[operator] nse_mcp_url` is set:
  the address was not given). Refusals are enforced by the SDK's permission callback (`oper/perms.py`, tested: a write to `src/` and a `git push` are refused).
- `backtest`: through `lab_policies` (the lab's registered policies against the index after tax). A NEW rule is not registered from the chat tonight: it is a candidate in `notes/`, then a registered study (rule 10).
- Weekly introspection (`operator_weekly`): facts from code -> what worked / did not / calibration / three candidates, into the strategist's note (`core_notes_s80`) and `operator_weekly_s87`. It does not write graph evidence
  (the graph's evidence rows are per security; the note is what the strategist and `recall` read). Candidates never become live changes.
- His decisions: `log_my_decision` + `learn.score_due` (job `operator_weekly`): 5/20/60 sessions against the Nifty 500, point-in-time; a sale's excess does NOT include the tax on the sale (the lot record is not read there): said in every line.

## Off / not done
- NSE MCP (no address). The graph "who else is touched" is `exposure_shock` + `comovement` (existing tools), not a new graph query.
- Weekly introspection's graph evidence (above). A registered study is not created automatically from a candidate.
- Everything was built in the workshop and tried on a scratch copy of the app's store (`D:\s87_scratch`, deletable); the app was not started and its store was only copied.

## For the screens (API only; no front-end work was done)
All JSON. Existing chat endpoints are unchanged (`/api/assistant`, `/api/assistant/files`, `/api/assistant/prefs`, `/api/assistant/new`, `/api/assistant/open/{chat_id}`, `/api/assistant/queue`,
`/api/assistant/messages/{msg_id}/action` (the Yes/No cards, including a build card), `/api/usage`, `/api/problems`, `/api/engines`); the operator is behind them.

`GET /api/operator` (state for Home and Settings)
```json
{"signed_in": true, "method": "claude.ai", "detail": "", "thinking": "running", "paused_until": null,
 "tokens_today": {"desk": {"used": 0, "budget": 600000}, "cases": {"used": 9785, "budget": 900000}, "chat": {"used": 97780, "budget": 1500000}, "build": {"used": 0, "budget": 1200000}},
 "open_cards": [{"msg_id": 412, "state": "open", "text": "A fix is ready for: ..."}],
 "builds": [{"build_id": 1, "status": "card", "problem": "...", "branch": "fix/2026-11-15-...-1", "tokens": 398080}]}
```
`thinking`: `running` | `paused` (with `paused_until`, local time) | `off` (not signed in). `builds[].status`: requested, running, card (waiting for his Yes), no_fix, failed, merged.
`POST /api/operator/terminal` -> `{"ok": true, "cwd": "<data>/operator"}` or `{"ok": false, "detail": "..."}`: the menu item "Open the operator in Claude Code" (also `pflab operator open` and the desktop shortcut
"Portfolio Operator (terminal)" made by `tools\install_shortcut.ps1`). Each chat reply's `meta_obj` now carries `engine: "claude_plan"`, `price: "plan"`, `tokens`, `seconds`, `session` and the model.
When thinking is paused the chat reply says "Thinking is paused until HH:MM ..." with status `done`.
