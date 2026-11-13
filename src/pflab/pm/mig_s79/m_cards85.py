"""S85 `cards` (E5 questions with a default as cards in the chat): versions 330-334 (330 used). Additive only.

330  cards_s85: one row per card in the chat (a voice question, or a decision such as "change my target to X"): which chat message shows it, the question or the handler it applies on Yes,
     its state (open | answered | defaulted | expired), who answered and from which window, the Telegram message that carries its buttons.
"""
MIGRATIONS = [
    (330, "cards_s85", """
    CREATE TABLE IF NOT EXISTS cards_s85 (
        card_id BIGINT PRIMARY KEY, msg_id BIGINT, chat_id BIGINT, kind VARCHAR, q_id BIGINT, options_json VARCHAR, payload_json VARCHAR, on_yes VARCHAR, expires_at TIMESTAMP,
        state VARCHAR, answer VARCHAR, answered_by VARCHAR, answered_at TIMESTAMP, result_json VARCHAR, tg_outbox_id BIGINT, created_at TIMESTAMP
    );
    """),
]
