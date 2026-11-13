"""S85 `cards` (E5): voice questions and decisions as cards in the chat. Synthetic data only."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from pflab.agents import questions, voice
from pflab.entrance import cards, store
from pflab.pm import store as pm

NOW = datetime(2026, 11, 13, 10, 0)


@pytest.fixture
def con(tmp_path):
    c = pm.connect(tmp_path / "ledger.duckdb")
    yield c
    c.close()


def _card_msgs(con):
    cid = store.latest_chat(con, NOW)
    return [m for m in store.messages(con, cid) if m["kind"] == "card"]


def _ask(con, key="gap:1", **kw):
    return questions.ask(con, "auditor", key, "Is the gold sleeve to stay as is?", NOW, default="keep as is", options=["keep as is", "change"], **kw)


def _tg_buttons(con):
    rows = con.execute("SELECT o.msg_id, o.kind, m.markup_json FROM outbox o JOIN outbox_markup_s79 m USING (msg_id) ORDER BY o.msg_id").fetchall()
    return [(r[0], r[1], [b["callback_data"] for row in json.loads(r[2])["inline_keyboard"] for b in row]) for r in rows]


def test_question_becomes_one_card_with_telegram_buttons(con):
    qid = _ask(con)
    msgs = _card_msgs(con)
    assert len(msgs) == 1
    m = msgs[0]
    assert "keep as is" in m["text"] and "If you do not answer" in m["text"]
    assert [a["id"] for a in m["actions"]] == ["yes", "no"] and m["actions"][0]["label"].endswith("(default)")
    # asking again, a sweep and a repost make no second card
    assert _ask(con) is None
    voice.sweep(con, NOW + timedelta(minutes=1))
    assert cards.post_question_card(con, NOW, qid) == m["id"]
    assert len(_card_msgs(con)) == 1
    # Telegram carries the card's buttons, once; the outbox copy is not also mirrored as a second chat message
    bt = _tg_buttons(con)
    assert len(bt) == 1 and bt[0][2] == [f"card:{m['id']}:yes", f"card:{m['id']}:no"]
    assert len([x for x in store.messages(con, m["chat_id"]) if "Is the gold sleeve" in x["text"]]) == 1


def test_answers_stored_once_and_double_tap_harmless(con):
    qid = _ask(con)
    mid = _card_msgs(con)[0]["id"]
    out = cards.answer_card(con, mid, "no", "telegram", NOW + timedelta(minutes=5))
    assert out["ok"] and out["answer"] == "change" and "will go with" in out["text"]
    assert con.execute("SELECT status, answer FROM questions WHERE q_id=?", [qid]).fetchone() == ("answered", "change")
    n_mem = con.execute("SELECT count(*) FROM memory WHERE kind='answer'").fetchone()[0]
    again = cards.answer_card(con, mid, "yes", "laptop", NOW + timedelta(minutes=6))       # a second tap, even the other button: nothing changes
    assert again["already"] and again["answer"] == "change"
    assert con.execute("SELECT status, answer FROM questions WHERE q_id=?", [qid]).fetchone() == ("answered", "change")
    assert con.execute("SELECT count(*) FROM memory WHERE kind='answer'").fetchone()[0] == n_mem
    m = _card_msgs(con)[0]
    assert m["actions"] == [] and "Answered: change" in m["text"] and "Telegram" in m["text"]
    assert voice.effective(con, "gap:1") == ("change", "him")
    with pytest.raises(ValueError):
        cards.answer_card(con, mid + 999, "yes", "laptop")


def test_answer_elsewhere_updates_card(con):
    qid = _ask(con)
    questions.answer(con, qid, "keep as is", NOW + timedelta(minutes=2))         # /answer in Telegram, or the old route
    m = _card_msgs(con)[0]
    assert m["actions"] == [] and "Answered: keep as is" in m["text"]


def test_default_applies_after_time_and_card_shows_it(con):
    qid = _ask(con)
    deadline = con.execute("SELECT deadline FROM question_terms_s79 WHERE q_id=?", [qid]).fetchone()[0]
    assert voice.effective(con, "gap:1") == ("keep as is", "pending-default")        # the system runs on the default meanwhile
    voice.sweep(con, deadline - timedelta(minutes=1))
    assert "Default applied" not in _card_msgs(con)[0]["text"]
    voice.sweep(con, deadline + timedelta(minutes=1))
    m = _card_msgs(con)[0]
    assert "Default applied: keep as is" in m["text"]
    assert voice.effective(con, "gap:1") == ("keep as is", "default")
    assert m["actions"], "a defaulted question stays answerable"
    out = cards.answer_card(con, m["id"], "no", "laptop", deadline + timedelta(hours=1))      # his later answer replaces the default
    assert out["answer"] == "change" and voice.effective(con, "gap:1") == ("change", "him")
    assert "Answered: change" in _card_msgs(con)[0]["text"]


def test_open_question_without_card_gets_one_at_start(con):
    qid = _ask(con)
    con.execute("DELETE FROM chat_messages WHERE kind='card'")
    con.execute("DELETE FROM cards_s85")
    new = cards.ensure_cards(con, NOW + timedelta(minutes=3))
    assert len(new) == 1 and len(_card_msgs(con)) == 1
    assert cards.ensure_cards(con, NOW + timedelta(minutes=4)) == []


def test_held_question_shows_on_screen_but_waits_on_telegram(con):
    for i in range(voice.DAILY_CAP):
        questions.ask(con, "a", f"cap:{i}", f"Q{i}?", NOW, default="d", options=["d", "x"])
    questions.ask(con, "a", "cap:late", "Held question?", NOW, default="d", options=["d", "x"])
    assert len(_card_msgs(con)) == voice.DAILY_CAP + 1                                # all on the screen
    assert len(_tg_buttons(con)) == voice.DAILY_CAP                                    # the cap still holds Telegram back


def test_change_my_target_waits_for_yes_and_nothing_changes_before(con):
    applied = []
    cards.register_handler("t:target", lambda c, now, p: applied.append(p) or {"text": f"target set to {p['value']}"})
    mid = cards.post_decision_card(con, NOW, "target_change", {"name": "gold", "value": 12}, "You asked to change the gold target to 12.", "t:target")
    assert applied == []
    m = [x for x in _card_msgs(con) if x["id"] == mid][0]
    assert "Nothing changes unless you press Yes" in m["text"] and [a["id"] for a in m["actions"]] == ["yes", "no"]
    assert cards.post_decision_card(con, NOW, "target_change", {"name": "gold", "value": 12}, "again", "t:target") == mid     # once per request
    assert _tg_buttons(con)[-1][2] == [f"card:{mid}:yes", f"card:{mid}:no"]
    out = cards.answer_card(con, mid, "yes", "telegram", NOW + timedelta(minutes=1))
    assert out["applied"] and applied == [{"name": "gold", "value": 12}] and "target set to 12" in out["text"]
    assert cards.answer_card(con, mid, "yes", "laptop")["already"] and len(applied) == 1       # double tap: applied once
    assert "You said Yes" in [x for x in _card_msgs(con) if x["id"] == mid][0]["text"]


def test_decision_no_and_expiry_change_nothing(con):
    applied = []
    cards.register_handler("t:x", lambda c, now, p: applied.append(1))
    a = cards.post_decision_card(con, NOW, "target_change", {"v": 1}, "Change A?", "t:x")
    b = cards.post_decision_card(con, NOW, "target_change", {"v": 2}, "Change B?", "t:x", expires_hours=1)
    out = cards.answer_card(con, a, "no", "laptop", NOW)
    assert out["applied"] is False and applied == []
    cards.sweep(con, NOW + timedelta(hours=2))
    assert applied == [] and cards.answer_card(con, b, "yes", "laptop", NOW + timedelta(hours=3))["already"]
    assert applied == []
    assert "nothing was changed" in [x for x in _card_msgs(con) if x["id"] == b][0]["text"]


def test_decision_handler_failure_changes_nothing_and_can_retry(con):
    state = {"n": 0}

    def boom(c, now, p):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("x")
        return "done"
    cards.register_handler("t:boom", boom)
    mid = cards.post_decision_card(con, NOW, "k", {"v": 1}, "Do it?", "t:boom")
    assert cards.answer_card(con, mid, "yes", "laptop")["ok"] is False
    assert cards.answer_card(con, mid, "yes", "laptop")["applied"] is True
