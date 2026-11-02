"""S78: New chat. A clean conversation, the old one kept under 'Earlier', pins carried over, no empty chats piling up, going back to an earlier one, and the screen's button."""
from __future__ import annotations

import json
import os
from datetime import datetime

import pytest

from pflab.app import assistant, chat, context
from pflab.pm import store
from tests import _edge

NOW = datetime(2026, 11, 2, 15, 0)


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "n.duckdb")


def _say(con, cid, text, role="me"):
    return chat._add(con, cid, role, "ask", text, "done", NOW)


def test_the_first_new_chat_with_nothing_said_changes_nothing(con):
    cid = assistant.thread(con, NOW)
    out = assistant.new_chat(con, NOW)
    assert out == {"chat_id": cid, "new": False} and con.execute("SELECT count(*) FROM chats").fetchone()[0] == 1


def test_a_new_chat_keeps_the_old_one_under_earlier_with_what_he_first_asked(con):
    old = assistant.thread(con, NOW)
    _say(con, old, "Look into the AI bubble for the paper portfolio, please.")
    _say(con, old, "Here is what the team found.", "ai")
    out = assistant.new_chat(con, NOW)
    assert out["new"] is True and out["chat_id"] != old and assistant.thread(con, NOW) == out["chat_id"]
    assert chat.messages(con, out["chat_id"]) == []
    e = assistant.earlier(con)
    assert [x["id"] for x in e] == [old] and e[0]["title"].startswith("Look into the AI bubble")
    assert len(chat.messages(con, old)) == 2                                                  # nothing was lost


def test_no_empty_chats_pile_up_and_pins_come_along(con):
    old = assistant.thread(con, NOW)
    for i in range(14):
        _say(con, old, f"Never buy in sector {i} please" if i == 3 else f"question number {i} about a holding")
        _say(con, old, f"answer {i}", "ai")
    context.build(con, old, 10 ** 6, NOW)                                                    # folds the old messages: his rule is pinned
    pins = context.state(con, old)["pins"]
    assert any("Never buy in sector 3" in p for p in pins)
    new = assistant.new_chat(con, NOW)["chat_id"]
    assert context.state(con, new)["pins"] == pins and context.state(con, new)["summary"] == ""
    again = assistant.new_chat(con, NOW)                                                      # nothing said in the new one: no second empty chat
    assert again == {"chat_id": new, "new": False} and con.execute("SELECT count(*) FROM chats").fetchone()[0] == 2


def test_going_back_to_an_earlier_chat_swaps_and_drops_an_empty_one(con):
    a = assistant.thread(con, NOW)
    _say(con, a, "First conversation, about gold.")
    b = assistant.new_chat(con, NOW)["chat_id"]
    _say(con, b, "Second conversation, about banks.")
    assistant.open_chat(con, a, NOW)
    assert assistant.thread(con, NOW) == a and [x["id"] for x in assistant.earlier(con)] == [b]
    c = assistant.new_chat(con, NOW)["chat_id"]                                                # an empty new one
    assistant.open_chat(con, b, NOW)
    assert assistant.thread(con, NOW) == b and con.execute("SELECT count(*) FROM chats WHERE chat_id=?", [c]).fetchone()[0] == 0
    with pytest.raises(ValueError):
        assistant.open_chat(con, b, NOW)                                                       # the active one is not 'earlier'


def test_history_lists_the_earlier_chats_for_the_screen(con):
    a = assistant.thread(con, NOW)
    _say(con, a, "Something about the account.")
    assistant.new_chat(con, NOW)
    h = assistant.history(con, NOW)
    assert h["messages"] == [] and h["earlier"][0]["title"].startswith("Something about the account")


from tests.test_s68_ui import server  # noqa: E402,F401  (the fixture)


@pytest.mark.ui
@pytest.mark.skipif(not os.path.exists(_edge.EDGE), reason="Microsoft Edge is not installed here")
def test_the_new_chat_button_clears_the_thread_and_lists_the_old_one(server, tmp_path):
    rt, port = server
    con = rt.cursor()
    cid = assistant.thread(con, NOW)
    _say(con, cid, "Tell me about the gold bonds in the account.")
    _say(con, cid, "They are a diversifier.", "ai")
    steps = [("(document.getElementById('thread') || {}).innerText", 3.5),
             ("document.getElementById('newChat').click(); 1", 1.8),
             ("document.getElementById('thread').innerText + ' || ' + document.getElementById('chatBar').innerText", 0.2)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/assistant", str(tmp_path / "n.png"), 1400, 900, 5, steps)
    assert errors == [], errors
    assert "gold bonds" in res[0]
    after = res[2]
    assert "gold bonds" not in after.split("||")[0] and "Tell me about the gold bonds" in after.split("||")[1]
