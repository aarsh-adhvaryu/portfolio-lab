"""S85 `chat` (E1 one conversation, E2 the intake, E8 usage): versions 310-319 (310-313 used). Additive only: no stored message is ever rewritten or lost.

310  chats / chat_messages get the words of the shared conversation: which window a message came from (`channel` laptop | telegram | system), the model and thinking level that answered, the
     `kind` (text | card | loop | file | note), `attachments_json`, `actions_json` (the Yes/No buttons of a card), `ref` (what a message points at), `reply_to`, the intake item that works on it, and
     `post_key` (a proactive message is posted once per key).
311  chat_attachments_s85 (a file sent in a chat; the readers fill kind/doc fields) and intake_queue_s85 (the intake's own queue: item, kind, state, progress, model, price, error, attempts).
312  chat_prefs_s85: the model and thinking level he picked for a chat (the laptop's picker and Telegram's /model and /think write it).
313  api_calls gets the chat and the reply it served (E8); the same columns are added by the engines' migration (IF NOT EXISTS: either may run first).
"""
MIGRATIONS = [
    (310, "chats_shared_conversation_s85", """
    ALTER TABLE chats ADD COLUMN IF NOT EXISTS channel VARCHAR;
    ALTER TABLE chats ADD COLUMN IF NOT EXISTS label VARCHAR;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS channel VARCHAR;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS model VARCHAR;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS thinking VARCHAR;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS kind VARCHAR;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS attachments_json VARCHAR;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS actions_json VARCHAR;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS ref VARCHAR;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS reply_to BIGINT;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS item_id BIGINT;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS post_key VARCHAR;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS meta_json VARCHAR;
    """),
    (311, "chat_attachments_intake_queue_s85", """
    CREATE TABLE IF NOT EXISTS chat_attachments_s85 (
        attachment_id BIGINT PRIMARY KEY, msg_id BIGINT, chat_id BIGINT, name VARCHAR, path VARCHAR, mime VARCHAR, kind VARCHAR, size_bytes BIGINT, sha VARCHAR,
        document_id VARCHAR, status VARCHAR, note VARCHAR, created_at TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS intake_queue_s85 (
        item_id BIGINT PRIMARY KEY, chat_id BIGINT, msg_id BIGINT, reply_msg_id BIGINT, channel VARCHAR, kind VARCHAR, state VARCHAR, progress VARCHAR, model VARCHAR, thinking VARCHAR,
        price_inr DOUBLE, error VARCHAR, attempts INTEGER, created_at TIMESTAMP, started_at TIMESTAMP, finished_at TIMESTAMP, payload_json VARCHAR
    );
    """),
    (312, "chat_prefs_s85", """
    CREATE TABLE IF NOT EXISTS chat_prefs_s85 (
        chat_id BIGINT PRIMARY KEY, model_key VARCHAR, thinking VARCHAR, updated_at TIMESTAMP
    );
    """),
    (313, "api_calls_chat_s85", """
    ALTER TABLE api_calls ADD COLUMN IF NOT EXISTS chat_id BIGINT;
    ALTER TABLE api_calls ADD COLUMN IF NOT EXISTS reply_msg_id BIGINT;
    """),
]
