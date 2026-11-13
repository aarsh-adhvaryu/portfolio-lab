"""S85 `chat`: the entrance and the loop do not wait for each other (A69). Scripted model, synthetic store (rule 7)."""
from __future__ import annotations

import threading
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

from pflab.entrance import intake, store
from pflab.pm import store as pm
from tests.test_s85_chat import FakeGate, wait_done  # noqa: F401

NOW = datetime(2026, 11, 13, 10, 0)


@pytest.fixture
def con(tmp_path):
    c = pm.connect(tmp_path / "ledger.duckdb")
    yield c
    c.close()


@pytest.fixture
def rt(con):
    return SimpleNamespace(cursor=con.cursor, clock=lambda: NOW, bump=lambda *t: None, settings={"brain": "normal"}, secrets=None, pm_dir=None, data_root=None)


@pytest.fixture(autouse=True)
def _clean():
    intake.stop()
    intake.gateway_call = None
    intake.handler = None
    yield
    intake.stop()
    intake.gateway_call = None
    intake.handler = None


class Ticker:
    """A stand-in for the session loop: one tick every 50 ms on its own thread, holding none of the intake's locks; records how late each tick was."""

    def __init__(self, con):
        self.con, self.late, self.stop, self.n = con, [], threading.Event(), 0
        self.t = threading.Thread(target=self.run, daemon=True)

    def run(self):
        nxt = time.monotonic()
        while not self.stop.is_set():
            nxt += 0.05
            time.sleep(max(0.0, nxt - time.monotonic()))
            self.late.append(time.monotonic() - nxt)
            self.con.execute("SELECT count(*) FROM chat_messages").fetchone()          # the loop's own read of the store
            self.n += 1


def test_a_hung_intake_does_not_stop_the_loop_ticks(con, rt, monkeypatch):
    monkeypatch.setitem(intake.DEFAULTS, "item_timeout_s", 60.0)
    release = threading.Event()
    intake.handler = lambda r, it, p: release.wait(30) or {"text": "late", "status": "done"}
    intake.start(rt)
    tk = Ticker(con.cursor())
    tk.t.start()
    for _ in range(4):                                                                  # every worker is hung
        intake.submit(rt, "laptop", "thanks")
    time.sleep(1.0)
    tk.stop.set()
    release.set()
    tk.t.join(2)
    assert tk.n >= 12 and max(tk.late) < 0.5


def test_a_message_is_acknowledged_in_two_seconds_while_the_loop_is_busy_and_a_haiku_answer_comes(con, rt):
    """The loop busy in a long run (a thread holding the store busy with writes): the acknowledgement is in the chat at once and a Haiku answer arrives within 30 seconds."""
    stop = threading.Event()

    def lab_run():
        c = con.cursor()
        i = 0
        while not stop.is_set():
            c.execute("CREATE TABLE IF NOT EXISTS lab_busy_t (i INTEGER)")
            c.execute("INSERT INTO lab_busy_t VALUES (?)", [i])
            i += 1
    th = threading.Thread(target=lab_run, daemon=True)
    th.start()
    intake.gateway_call = FakeGate([{"text": "Good morning."}])
    intake.start(rt)
    t0 = time.monotonic()
    out = intake.submit(rt, "laptop", "good morning")
    assert time.monotonic() - t0 < 2.0
    assert store.message(con, out["msg_id"])["text"].endswith("…")
    assert wait_done(con, out["item_id"], 30) == "done"
    stop.set()
    th.join(2)
    assert store.message(con, out["msg_id"])["text"] == "Good morning."


def test_fifty_messages_while_a_writer_runs_lose_nothing_and_do_not_deadlock(con, rt):
    stop = threading.Event()

    def close_writer():
        c = con.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS close_busy_t (i INTEGER)")
        i = 0
        while not stop.is_set():
            c.execute("INSERT INTO close_busy_t VALUES (?)", [i])
            i += 1
    th = threading.Thread(target=close_writer, daemon=True)
    th.start()
    intake.handler = lambda r, it, p: {"text": "ok", "status": "done"}
    intake.start(rt)
    ids = []
    errs = []

    def send(k):
        try:
            ids.append(intake.submit(rt, "laptop" if k % 2 else "telegram", f"message {k}"))
        except Exception as e:                                                          # a lost write would show here
            errs.append(e)
    senders = [threading.Thread(target=send, args=(k,)) for k in range(50)]
    for s in senders:
        s.start()
    for s in senders:
        s.join(30)
    assert not errs and len(ids) == 50
    for o in ids:
        assert wait_done(con, o["item_id"], 30) == "done"
    stop.set()
    th.join(2)
    cid = store.latest_chat(con, NOW)
    texts = [m["text"] for m in store.messages(con, cid) if m["role"] == "me"]
    assert len(texts) == 50, (len(texts), sorted(set(f"message {k}" for k in range(50)) - set(texts))[:5], len(set(texts)))
    assert sorted(texts) == sorted(f"message {k}" for k in range(50)) and len({o["msg_id"] for o in ids}) == 50


def test_the_api_down_leaves_the_loop_untouched_and_says_so(con, rt, monkeypatch):
    monkeypatch.setitem(intake.DEFAULTS, "retry_pause_s", 0.0)

    def down(con_, role, system, messages, **kw):
        raise ConnectionError("no route to the provider")
    intake.gateway_call = down
    intake.start(rt)
    tk = Ticker(con.cursor())
    tk.t.start()
    out = intake.submit(rt, "laptop", "thanks")
    assert wait_done(con, out["item_id"]) == "failed"
    tk.stop.set()
    tk.t.join(2)
    assert "did not answer" in store.message(con, out["msg_id"])["text"] and tk.n >= 1 and max(tk.late) < 0.5
