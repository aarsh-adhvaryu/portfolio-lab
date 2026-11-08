"""S79 item 6: a question carries a default and a deadline, goes out at once with buttons, caps at 3 a day unless urgent, runs on the default."""
import json
from datetime import datetime, timedelta

import duckdb
import pytest

from pflab.agents import questions, voice
from pflab.pm import store
from pflab.service import bot, telegram as tgm

NOW = datetime(2026, 11, 5, 10, 0)


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    store.migrate(c)
    return c


def test_question_goes_out_at_once_with_buttons(con):
    q = questions.ask(con, "paper", "k1", "Hold the gold ETF?", NOW, default="keep", options=["keep", "sell half"])
    row = con.execute("SELECT kind, status, text FROM outbox").fetchone()
    assert row[0] == "question" and row[1] == "pending" and "I go with: keep" in row[2]
    mk = json.loads(con.execute("SELECT markup_json FROM outbox_markup_s79").fetchone()[0])
    assert [b[0]["callback_data"] for b in mk["inline_keyboard"]] == [f"q:{q}:0", f"q:{q}:1"]
    assert voice.effective(con, "k1") == ("keep", "pending-default")


def test_cap_three_a_day_unless_urgent(con):
    for i in range(5):
        questions.ask(con, "a", f"k{i}", f"Q{i}?", NOW, default="d")
    questions.ask(con, "a", "urgent", "Crash?", NOW, default="wait", urgent=True)
    assert con.execute("SELECT count(*) FROM outbox WHERE kind='question'").fetchone()[0] == 4          # 3 + the urgent one
    assert con.execute("SELECT count(*) FROM question_terms_s79 WHERE sent_at IS NULL").fetchone()[0] == 2
    voice.sweep(con, NOW + timedelta(hours=1))                                                          # same day: still capped
    assert con.execute("SELECT count(*) FROM question_terms_s79 WHERE sent_at IS NULL").fetchone()[0] == 2
    voice.sweep(con, NOW + timedelta(days=1))                                                           # next day the held ones go out
    assert con.execute("SELECT count(*) FROM question_terms_s79 WHERE sent_at IS NULL").fetchone()[0] == 0


def test_default_becomes_final_at_the_deadline_and_he_can_still_answer(con):
    q = questions.ask(con, "a", "k", "Q?", NOW, default="keep", deadline=NOW + timedelta(hours=2))
    assert voice.sweep(con, NOW + timedelta(hours=1))["defaulted"] == []
    assert voice.sweep(con, NOW + timedelta(hours=3))["defaulted"] == [q]
    assert voice.effective(con, "k") == ("keep", "default")
    questions.answer(con, q, "change", NOW + timedelta(hours=5))
    assert voice.effective(con, "k") == ("change", "him")
    assert con.execute("SELECT resolved_by FROM question_terms_s79").fetchone()[0] == "him"


def test_button_press_answers_only_from_his_chat(con):
    q = questions.ask(con, "a", "k", "Q?", NOW, default="keep", options=["keep", "sell"])
    sent, acks = [], []
    up = {"update_id": 1, "callback_query": {"id": "cb1", "data": f"q:{q}:1", "message": {"chat": {"id": 42}}}}
    bot.process(con, [up], "42", sent.append, lambda t: "x", NOW, ack=lambda i, t: acks.append((i, t)))
    assert voice.effective(con, "k") == ("sell", "him") and acks and "sell" in sent[0]
    other = {"update_id": 2, "callback_query": {"id": "cb2", "data": f"q:{q}:0", "message": {"chat": {"id": 7}}}}
    bot.process(con, [other], "42", sent.append, lambda t: "x", NOW)
    assert voice.effective(con, "k")[0] == "sell"


def test_flush_sends_markup_only_for_questions(con):
    questions.ask(con, "a", "k", "Q?", NOW, default="keep")
    tgm.enqueue(con, "plain", "reply", now=NOW)
    seen = []
    tgm.flush(con, lambda text, reply_markup=None: seen.append((text[:5], bool(reply_markup))), NOW)
    assert (("Q?\n\nI"[:5]), True) in seen and ("plain", False) in seen


def test_question_kind_goes_at_once():
    assert tgm.goes_at_once("question")
