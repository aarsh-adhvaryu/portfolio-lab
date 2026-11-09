"""S68 P6: the assistant is one persistent conversation that answers from tools, starts investigations, remembers, hears what the system does, and is
bound by the same governor, egress gate and tool allow-list as the workers. A scripted model stands in for the API (development test; the calibration
set `tools/assistant_eval.py` is the live check). Synthetic data only."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from pflab.agents import analyst as an
from pflab.app import assistant, chat
from pflab.hq import cases, egress, governor as gv, service
from pflab.hq.desk import Desk
from pflab.pm import store

NOW = datetime(2026, 10, 31, 15, 0)
CFG = {"model": an.MODEL, "cap": 2500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True, "tijori_to_analyst": True}


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


@pytest.fixture
def rt(con, tmp_path, monkeypatch):
    monkeypatch.setattr(an, "config", lambda: CFG)
    monkeypatch.setattr(service, "gate", lambda r: egress.Gate())
    (tmp_path / "pm" / "app").mkdir(parents=True)
    return Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None, {"brain": "normal", "preset": "full", "telegram_send": False}, clock=lambda: NOW)


def _use(*calls):
    content = [SimpleNamespace(type="thinking", thinking="", signature="sig")]
    content += [SimpleNamespace(type="tool_use", id=f"tu{k}", name=n, input=i) for k, (n, i) in enumerate(calls)]
    return SimpleNamespace(content=content, stop_reason="tool_use", model=gv.SONNET,
                           usage=SimpleNamespace(input_tokens=900, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0))


def _say(text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn", model=gv.SONNET,
                           usage=SimpleNamespace(input_tokens=900, output_tokens=120, cache_read_input_tokens=0, cache_creation_input_tokens=0))


class Model:
    def __init__(self, *replies):
        self.replies, self.seen = list(replies), []
        self.messages = SimpleNamespace(count_tokens=lambda **kw: SimpleNamespace(input_tokens=1000), create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.seen.append(kw)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _ask(rt, con, text, model, context=""):
    cid = assistant.thread(con, NOW)
    chat._add(con, cid, "me", "assistant", text, "done", NOW)
    aid = chat._add(con, cid, "ai", "assistant", "…", "working", NOW)
    return assistant.answer(rt, con, cid, aid, text, context, client=model, gate=egress.Gate(), cfg=CFG)


def test_one_persistent_thread_survives_and_is_never_tidied_away(con):
    a = assistant.thread(con, NOW)
    assert assistant.thread(con, NOW + timedelta(days=1)) == a
    con.execute("UPDATE chats SET updated_at=? WHERE chat_id=?", [NOW - timedelta(days=90), a])
    assert chat.tidy(con, NOW) == 0 and con.execute("SELECT count(*) FROM chats WHERE chat_id=?", [a]).fetchone()[0] == 1


def test_a_plain_question_is_answered_from_a_tool_and_numbers_not_read_are_removed(rt, con):
    m = Model(_use(("system_status", {})), _say("Everything is in sync. The system holds 12345 trades."))
    out = _ask(rt, con, "Is everything working?", m)
    assert out["status"] == "done" and "in sync" in out["text"] and "12345" not in out["text"]
    assert any(t["name"] == "system_status" for t in m.seen[0]["tools"])
    assert out["route"] == ["tool: system_status"] and "Sonnet" in out["meta"]


def test_a_goal_he_states_is_remembered_and_changes_no_target(rt, con):
    m = Model(_use(("remember_fact", {"kind": "goal", "text": "survive a 35 percent fall without selling"})), _say("Noted."))
    _ask(rt, con, "Remember my goal: survive a 35 percent fall without selling", m)
    row = con.execute("SELECT kind, subject, text FROM memory").fetchone()
    assert row[1] == "goal" and "survive" in row[2]
    assert not (rt.pm_dir / "targets.toml").exists()


def test_the_assistant_can_not_call_a_tool_outside_its_list(rt, con):
    m = Model(_use(("submit_review", {"case_id": 1, "verdict": "approve", "findings": "x"}), ("change_preference", {"kind": "api_cap", "key": "monthly", "value": "9999", "why": "x"})),
              _say("I cannot change that."))
    _ask(rt, con, "Raise my cap", m)
    rows = con.execute("SELECT tool, status FROM hq_tool_calls ORDER BY call_no").fetchall()
    assert rows == [("submit_review", "refused"), ("change_preference", "refused")]


def test_a_refused_budget_is_said_plainly_not_hidden_and_not_retried_in_a_loop(rt, con):
    for i in range(1, 500):
        con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, question, request_sha, request_json, status, cost_inr, agent, turn) "
                    "VALUES (?, ?, 'live', ?, 'q', '', '{}', 'done', 6.0, 'w_research', 1)", [i, NOW, gv.SONNET])
    # the month's cap is spent: his message is refused with the reason, no call is made
    m = Model()
    out = _ask(rt, con, "How am I doing?", m)
    assert out["status"] == "failed" and "spending limits" in out["text"] and m.seen == []


def test_a_provider_failure_is_said_plainly(rt, con):
    out = _ask(rt, con, "How am I doing?", Model(ConnectionError("down")))
    assert out["status"] == "failed" and "did not answer" in out["text"]


def test_a_private_identifier_never_reaches_the_model(rt, con, monkeypatch):
    m = Model(_say("never sent"))
    out = _ask(rt, con, "My PAN is ABCDE1234F, is my tax fine?", m)
    assert m.seen == [] and out["status"] == "failed" and "ABCDE1234F" not in out["text"]


def test_off_means_off(rt, con):
    rt.settings["brain"] = "off"
    out = _ask(rt, con, "hello", Model())
    assert out["status"] == "failed" and "switched off" in out["text"]


def test_notify_tells_each_state_once(con):
    assert assistant.notify(con, NOW, "Something found.", "filing:x") is True
    assert assistant.notify(con, NOW, "Something found.", "filing:x") is False
    assert assistant.notify(con, NOW, "Something else.", "filing:y") is True


def test_one_message_with_an_identifier_does_not_block_every_later_one(rt, con):
    first = _ask(rt, con, "My PAN is ABCDE1234F, is my tax fine?", Model())
    chat._finish(con, con.execute("SELECT max(msg_id) FROM chat_messages").fetchone()[0], first["text"], [], "", NOW, "done")
    m = Model(_say("Drawdown is how far a value falls from its peak."))
    out = _ask(rt, con, "Explain drawdown in two sentences.", m)
    assert out["status"] == "done" and "peak" in out["text"]
    sent = json.dumps(m.seen)
    assert "ABCDE1234F" not in sent and "[PAN]" in sent                      # the earlier turn went back with the identifier replaced
