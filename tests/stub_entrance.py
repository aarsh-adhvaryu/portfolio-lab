"""Test-only stand-ins for the `chat` agent's entrance modules (`entrance.intake`, `entrance.store`, `entrance.cards`) and the gateway's picker functions, with the
signatures of the S85 contract. They live only in tests (injected into `service/tg_entrance.Entrance` through `_Mods`); no competing implementation is committed under src/."""
from __future__ import annotations


class StubIntake:
    """`submit(rt_or_con, channel, text, *, chat_id, attachments, model, thinking, reply)`: records the call; `script(call)` may answer through call['reply']."""

    def __init__(self, script=None, raises=None):
        self.calls = []
        self.script = script
        self.raises = raises
        self.queue = []

    def submit(self, rt_or_con, channel, text, *, chat_id=None, attachments=None, model=None, thinking=None, reply=None):
        if self.raises:
            raise self.raises
        call = {"target": rt_or_con, "channel": channel, "text": text, "chat_id": chat_id, "attachments": attachments, "model": model, "thinking": thinking, "reply": reply,
                "msg_id": 900 + len(self.calls)}
        if attachments:
            from pathlib import Path
            call["seen_bytes"] = [Path(a["path"]).read_bytes() for a in attachments]          # the file is there while the intake works
        self.calls.append(call)
        if self.script:
            self.script(call)
        return {"chat_id": 1, "msg_id": call["msg_id"], "item_id": len(self.calls)}

    def queue_status(self, con):
        return self.queue


class StubStore:
    def __init__(self):
        self.new_chats = []

    def new_chat(self, con, now, title="New chat", channel="laptop"):
        self.new_chats.append((title, channel))
        return 50 + len(self.new_chats)


class StubCards:
    def __init__(self, raises=None):
        self.answers = []
        self.raises = raises

    def answer_card(self, con, msg_id, answer, channel):
        if self.raises:
            raise self.raises
        self.answers.append((msg_id, answer, channel))


class StubGateway:
    def __init__(self, models=None, engine="claude"):
        self._models = models or [{"key": "haiku", "model": "claude-haiku-5-5"}, {"key": "sonnet", "model": "claude-sonnet-5-5"}, {"key": "opus", "model": "claude-opus-5-5"}]
        self._engine = engine

    def current_engine(self):
        return self._engine

    def models_of(self, engine):
        return self._models
