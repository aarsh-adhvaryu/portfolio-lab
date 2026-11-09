"""S81 B6: a strategist session asked for in the chat: the request, its limits, and the chat tool. Synthetic store."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from pflab.hq import tools as tl
from pflab.lab import ondemand
from pflab.pm import store

NOW = datetime(2026, 11, 11, 11, 0)


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "ledger.duckdb")


def test_a_request_is_written_deduplicated_and_limited(con):
    assert ondemand.request(con, NOW, "too short")["ok"] is False
    a = ondemand.request(con, NOW, "Is there an AI bubble and should the book hold less of it?")
    assert a["ok"] and a["status"] == "open"
    b = ondemand.request(con, NOW + timedelta(hours=1), "is there an AI bubble   and should the book hold less of it?")
    assert b["duplicate"] is True and b["req_id"] == a["req_id"]
    ondemand.request(con, NOW, "How should the allocation change if rates keep rising?")
    ondemand.request(con, NOW, "Is gold too expensive to add to now?")
    assert "already waiting" in ondemand.request(con, NOW, "Which sector is the most exposed to a weak rupee?")["problem"]


def test_the_reasons_read_as_his_and_the_session_closes_the_request_into_the_chat(con):
    from pflab.core import autonomy
    ondemand.request(con, NOW, "Is there an AI bubble and should the book hold less of it?")
    assert [r.startswith(autonomy.HUMAN_REASONS) for r in ondemand.reasons(con)] == [True]
    ids = ondemand.take(con, NOW, 7)
    assert ids and con.execute("SELECT status, session_id FROM strategist_requests_s81").fetchone() == ("running", 7)
    ondemand.finish(con, NOW + timedelta(minutes=20), ids, "done", "Tested a lower AI weight in the lab; it did not beat the plain baseline after tax.")
    assert con.execute("SELECT status, note FROM strategist_requests_s81").fetchone()[0] == "done"
    assert ondemand.open_requests(con) == []


def test_the_chat_tool_is_registered_for_the_assistant_only_and_writes_the_request(con, tmp_path):
    from pflab.app import assistant
    assert "ask_strategist" in assistant.TOOLS and tl.TOOLS["ask_strategist"].kind == "action" and "ask_strategist" in tl.WORKER_ONLY
    assert tl.validate(tl.TOOLS["ask_strategist"], {"question": "Is there an AI bubble in the Indian market?"}) is None
