from datetime import datetime

import duckdb

from pflab.pm import store
from pflab.service import outgoing

NOW = datetime(2026, 11, 8, 8, 0)


def test_a_dropped_message_is_queued_once(tmp_path):
    con = duckdb.connect(":memory:")
    store.migrate(con)
    d = tmp_path / "outgoing"
    d.mkdir()
    (d / "morning_20261108.txt").write_text("Morning report: green.\nLine two.", encoding="utf-8")
    (d / "kinded.txt").write_text("kind: reminder\nCall me.", encoding="utf-8")
    (d / "empty.txt").write_text("   ", encoding="utf-8")
    assert sorted(outgoing.drain(con, tmp_path, NOW)) == ["kinded.txt", "morning_20261108.txt"]
    rows = con.execute("SELECT kind, status, text FROM outbox ORDER BY msg_id").fetchall()
    assert [(r[0], r[1]) for r in rows] == [("reminder", "pending"), ("summary", "pending")] or [(r[0], r[1]) for r in rows] == [("summary", "pending"), ("reminder", "pending")]
    assert outgoing.drain(con, tmp_path, NOW) == []                      # renamed: never queued twice
    assert (d / "morning_20261108.queued").exists() and (d / "empty.empty").exists()


def test_no_folder_is_nothing(tmp_path):
    con = duckdb.connect(":memory:")
    store.migrate(con)
    assert outgoing.drain(con, tmp_path, NOW) == []
