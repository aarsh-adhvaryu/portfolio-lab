# S85 cards (C5): E5 questions with a default as cards

Branch `s85/cards` (on `s85/chat`). Not touched: PLAN.md, BUILT.md, CLAUDE.md.

## What is built
- `src/pflab/entrance/cards.py`: `post_question_card(con, now, question_id)`, `post_decision_card(con, now, kind, payload, text, on_yes, *, expires_hours=48)`, `answer_card(con, msg_id, answer, channel)`, `ensure_cards`, `ensure_question_card`, `deliver`, `sync`, `sweep`, `register_handler`.
- Table `cards_s85` (migration 330, `pm/mig_s79/m_cards85.py`): card -> chat message, question or handler, state (open | answered | defaulted | expired), who answered and from which window, the Telegram outbox message.
- A card is a chat message of kind `card`, `actions=[{"id","label"}]`: ids `yes`, `no` (the question's first and second option; labels are the option texts, the first marked "(default)"), `opt3`.. for a third option and on. Telegram buttons carry `card:<msg_id>:<action id>` (what `tg_entrance` calls `answer_card(con, msg_id, answer, "telegram")` with).
- Every `voice` question has ONE card (key `card:q<id>`), on the screen at once even when voice's daily cap holds Telegram back; Telegram gets the buttons when voice's cap lets the question out (`voice.dispatch` -> `cards.deliver`). The question's own answer path stays (`questions.answer`, memory row, `voice.effective`: the system runs on the default until he answers).
- Answer: stored once; a second tap (either button, either window) says "Already answered" and changes nothing. The card then shows "Answered: X (from Telegram|the laptop)" with no buttons; an answer by any other road (`/answer`, the old route) updates the card too (hook in `questions.answer`).
- Default applied after its deadline (job `voice` already runs `sweep` every 5 minutes): the card shows "Default applied: X ... You can still answer", buttons kept (voice already lets a later answer replace a default).
- Decision cards (for `rules`: "change my target to X"): `on_yes` is a handler name registered with `register_handler`, a `module:function` string, or a module-level callable; it runs ONLY on Yes, once, as `fn(con, now, payload) -> dict | str`. No, or no answer within `expires_hours` (default 48): the card closes with no change. A handler that raises changes nothing and Yes can be pressed again. One card per (kind, payload). A closure/lambda handler only lives until the app restarts (the card then says it cannot apply and asks to be asked again); use a module-level function.
- Return of `answer_card`: `{"ok","state","answer","applied","text"[, "already", "result"]}`; `ValueError` for a message that is not a card or an answer the card does not offer (the route turns it into 400).

## Decisions (2026-11-13)
- "Yes" = the question's first option (its default), "No" = the second; a third option is `opt3`. Questions with a single option have only Yes.
- The outbox kinds `question` and `decision` are no longer mirrored into the chat as plain text (`NO_MIRROR` in `entrance/store.py`): the card is the chat copy.
- If the card path ever fails, `voice.dispatch` falls back to its old `q:<id>:<i>` buttons; `voice.handle_callback` still serves them (old messages in Telegram keep working).

## OFF / not done
- Nothing switched off. Editing the Telegram message itself after an answer in the other window (removing its buttons) is not done here: it needs the Bot API's `editMessageReplyMarkup` in `tg`'s code; `cards_s85.tg_outbox_id` holds the outbox id and `answer_card`'s reply text is what Telegram should answer with. A second tap on Telegram is harmless (answered "Already answered").
- The `rules` agent must call `post_decision_card` itself for "change my target" (this module only provides it).

## Shared files touched
`agents/voice.py` (3 small hooks: card on dispatch, `deliver` instead of the direct button send with fallback, `ensure_cards`/`sweep` at the end of `sweep`), `agents/questions.py` (`cards.sync` after an answer), `entrance/store.py` (`NO_MIRROR`). Test changed: `tests/test_s79_voice.py::test_question_goes_out_at_once_with_buttons` (the callback data is now the card's `card:<msg>:yes|no`).

## Exposed for screens
Cards appear in `GET /api/assistant` messages (kind `card`, `actions`); buttons call the existing `POST /api/assistant/messages/{id}/action {action}` (now served; 501 gone). Functions: `cards.answer_card`, `cards.card_of_question`.

## Lines for the coordinator's docs
BUILT.md: `entrance/cards.py`, table `cards_s85`, migration 330, voice questions as cards, callback ids `card:<msg>:yes|no|opt3`.

## Tests
`tests/test_s85_cards.py`: one card per question (and once on Telegram with the card's buttons), answers stored once and double tap harmless, answer elsewhere updates the card, default applies after its time and the card shows it (and a later answer replaces it), cards made at start for open questions, held question on screen but not Telegram, "change my target" waits for Yes, No and expiry change nothing, a failing handler changes nothing.
