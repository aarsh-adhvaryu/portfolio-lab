# S85 chat (C1): the shared conversation, the intake, the router, usage

Branch `s85/chat`. Built: E1 (one store for laptop and Telegram), E2 (intake and gateway use), E8 (usage), the Auto router, the chat's tool registry, the old chat's retirement. Not touched: PLAN.md, BUILT.md, CLAUDE.md.

## What is built
- `src/pflab/entrance/store.py`: chats, messages (channel laptop|telegram|system, model, thinking, cost, kind, actions, attachments, ref), `new_chat`, `latest_chat`, `start_new`, `open_chat`, `add_message`, `update_message`, `messages`, `post_system` (once per key), `mirror_outbox`, `attach`, `attachments`, `get_prefs` / `set_prefs` (the picker's saved choice per chat), `retry` (write-conflict retry). Active chat = the newest chat titled "Assistant" (old ones become "Earlier: ..."): the old S78 behaviour, now for both windows.
- `entrance/intake.py`: `submit(rt_or_con, channel, text, *, chat_id, attachments, model, thinking, reply, context)` returns in milliseconds `{chat_id, msg_id (the pending ANSWER message), user_msg_id, item_id}`; `Worker` (4 threads, queue table `intake_queue_s85`, supervisor restarts a dead worker and puts its item back, resume of queued/working items at start, per-call timeout 90 s, per-item timeout 420 s, one retry then a plain line, after 3 attempts a plain "send it again"); `converse` (the tool loop, max 8 turns, through `llm/gateway.call`, `only_sourced_numbers`); `answer_item`; `queue_status`; `start(rt)` / `stop()`. Telegram answers whose callback was lost go to the outbox as kind "reply".
- `entrance/router.py`: the A70 Auto table in code (`route(text, attachments, override)`), table-driven test.
- `entrance/tools.py`: `REGISTRY` (name -> (Anthropic tool definition, `fn(ctx, args)`)), `register`, `definitions`, `names`, `run`; adds `pick_scorecard`, `picks_book`, `usage_today`, `working_on`. `CORE_RETIRED` lists the v1 tools no longer offered.
- `entrance/usage.py`: `today`, `by_purpose`, `by_chat`, `by_reply`, `month_to_date`, `line` (text for Today and the morning report), `view`.
- Migrations 310-313 in `pm/mig_s79/m_chat85.py` (additive; includes `api_calls.chat_id/reply_msg_id` with IF NOT EXISTS, same as the engines' migration).

## Decisions (2026-11-13)
- Auto: standing-rule wording that changes buying or selling ("pause gold buys", "do not buy that", "from now on...") counts as a decision at stake, so Opus; plain questions needing a tool: Sonnet; short replies: Haiku with no tools. Thinking defaults Haiku low, Sonnet medium, Opus high; the picker overrides either.
- Tools: Sonnet and Opus get every chat tool; Haiku none (so a Haiku reply cannot state a number).
- `intake.submit` returns `msg_id` = the pending answer (what the screen and Telegram edit); `user_msg_id` is his message.
- Gateway use is by signature: `call_model` passes only the keyword arguments the gateway accepts and uses agent "chat" when `gateway.AGENTS` has it, else "think". After `engines` merges nothing here changes; a picked model reaches the gateway as `model=` and `thinking=`. Until then the picker is accepted and recorded but the gateway ignores it (reply meta shows the model that really answered).
- `assistant.answer` / `ask_once` (Telegram /brain, AI-centre Auto road) stay as synchronous doors on the same `intake.converse` (never Haiku).
- Local front: `app/front.py` is no longer called by the chat. Kept (not deleted) because `front_render.inr` is used by `plan/envelope.py` and `tests/test_s71_front.py`, `test_s78_abilities.py`, `tools/s71_eval.py` import it. Its chat-switch test was removed.
- `chat.answer` (ask / web / deep / calc roads) stays for the board agent in `hq/roster.py` (v1 roster, the coordinator's S82 cut); the chat itself no longer uses it. `chat.post(rt, id, text, mode)` validates the mode and maps to `intake.submit`.
- Retired from the chat's tool list: cases, experiments, hypotheses, open_workspace, case_calculate, register_experiment, frame_objective, case_evidence. Their code stays in `hq/tools.py` (strategist/lab and the coordinator own it); nothing in the chat imports them.
- Proactive messages: ONE hook in `service/telegram.enqueue` (`store.mirror_outbox`) posts into the chat everything queued for Telegram except kinds "reply" and "test", once per outbox message (so within the same caps and dedupe). `assistant.notify` posts via `post_system`.
- Fix found by the 50-message test: two windows asking for the active chat at the same moment could each create one; `store.latest_chat` / `start_new` now hold a lock.

## OFF / not done
- Nothing is switched off. The screen and readers calls (`entrance.screen.check_text/check_file`, `entrance.readers.read_attachment`) are used when those modules exist; until they merge, a built-in fallback refuses broker/bank statement file names (`inbox.classify`) and files are kept unread ("no reader is available"). Cards: the laptop buttons call `entrance.cards.answer_card` through `/api/assistant/messages/{id}/action` (501 until the cards module exists).
- Not verified: a real Anthropic round trip (no paid call made), the UI in a real browser beyond `test_s78_screens` / `test_s68_ui`, Telegram.
- Config keys the coordinator may add to `configs/core.toml`: `[intake] workers=4 call_timeout_s=90 item_timeout_s=420 max_turns=8` (defaults in code).

## Shared files touched
`app/server.py` (routes), `app/runtime.py` (start/stop of the intake), `app/assistant.py` and `app/chat.py` (rewritten surface), `app/static/ui.js` (model/thinking picker, queue line, Telegram badge, card buttons, files sent with the message), `service/telegram.py` (the mirror hook in `enqueue`). Tests changed: `test_s68_assistant` (docstring only, passes unchanged on the new path), `test_app_ai` (two tests rewritten), `test_s71_front` (chat-switch test removed), `test_s70_chat` (deleted: the semaphore is gone; replaced by `test_s85_isolation`), `test_s78_screens` (files now go to `chat_attachments_s85`).

## Exposed for screens
- `GET /api/assistant` -> `{chat_id, messages[...with channel, model, thinking, kind, actions, attachments, meta_obj], earlier, queue, prefs, models, thinking, questions}`; `POST /api/assistant {text, context, model, thinking, files}`; `POST /api/assistant/files` (raw body, `x-filename`) -> `{upload_id}`; `POST /api/assistant/prefs {model, thinking}`; `GET /api/assistant/queue`; `POST /api/assistant/messages/{id}/action {action}`; `POST /api/assistant/new`, `/open/{id}` as before; `GET /api/usage?day=`.
- Functions: `store.*`, `intake.queue_status`, `usage.today/by_purpose/line/view`.

## Lines for the coordinator's docs
- CLAUDE.md rule 9: the local 8B model no longer answers the chat (A70). BUILT.md: package `entrance/` (store, intake, router, tools, usage), tables `intake_queue_s85`, `chat_attachments_s85`, `chat_prefs_s85`, migrations 310-313.

## Tests
`tests/test_s85_chat.py` (store, router table, intake, tool loop, retry/timeouts, crash restart, resume, usage), `tests/test_s85_isolation.py` (hung intake vs loop ticks, 2 s acknowledgement under a busy writer, fifty messages, API down).
