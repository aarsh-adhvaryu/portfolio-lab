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


def test_the_strategist_reads_a_chat_request_as_a_reason_and_the_new_triggers_by_code(con):
    from pflab.lab import strategist, triggers_s81
    ondemand.request(con, NOW, "Is there an AI bubble and should the book hold less of it?")
    why = strategist.due(con, NOW)
    assert any(w.startswith(ondemand.PREFIX) for w in why)
    con.execute("INSERT INTO core_sessions_s80 (session_id, started_at, reason, status) VALUES (1, ?, 'weekly', 'done')", [NOW - timedelta(days=1)])
    con.execute("INSERT INTO exit_events_s81 (event_id, market, isin, side, kind, day, emitted_at, status) VALUES (1,'IN','INE1','sell','thesis',?,?,'emitted')", [NOW.date(), NOW - timedelta(hours=3)])
    con.execute("INSERT INTO probation_s81 (change_id, policy_id, changed_on, kind, share, reason, made_at) VALUES (1,'p1',?,'withdraw',0.0,'worse than the champion',?)", [NOW.date(), NOW - timedelta(hours=2)])
    r = triggers_s81.reasons(con, NOW)
    assert any("thesis-break exit" in x for x in r) and any("probation slice of p1: withdraw" in x for x in r)


def test_the_harvesting_window_starts_a_paid_session_only_while_a_harvest_switch_is_on(con, monkeypatch):
    """A60: harvesting is off in the live book (`harvest_core`, `harvest_longterm`), so the January window is no reason for a paid Opus session; with a switch on it is one again."""
    from pflab.core import exits
    from pflab.lab import triggers_s81
    jan = datetime(2027, 1, 5, 11, 0)
    con.execute("INSERT INTO core_sessions_s80 (session_id, started_at, reason, status) VALUES (1, ?, 'weekly', 'done')", [datetime(2026, 12, 20, 11, 0)])
    real = exits.settings

    def with_switches(core, longterm):
        return lambda: {**real(), "harvest_core": core, "harvest_longterm": longterm}
    monkeypatch.setattr(exits, "settings", with_switches(False, False))
    assert not any("harvesting window" in x for x in triggers_s81.reasons(con, jan))
    monkeypatch.setattr(exits, "settings", with_switches(False, True))
    assert any("harvesting window" in x for x in triggers_s81.reasons(con, jan))
    monkeypatch.setattr(exits, "settings", with_switches(True, False))
    assert any("harvesting window" in x for x in triggers_s81.reasons(con, jan))
