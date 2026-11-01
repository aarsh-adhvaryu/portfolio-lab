"""S70: a quick question is not held behind a long answer; the number answered at once is bounded."""
from __future__ import annotations

import threading
import time
from datetime import datetime
from types import SimpleNamespace

from pflab.app import assistant, chat

NOW = datetime(2026, 11, 2, 12, 0)


def test_questions_are_answered_at_the_same_time_up_to_a_bound(monkeypatch):
    release, lock = threading.Event(), threading.Lock()
    running, peak = [], [0]

    def slow(rt, con, cid, aid, q, context=""):
        with lock:
            running.append(aid)
            peak[0] = max(peak[0], len(running))
        release.wait(10)
        with lock:
            running.remove(aid)
        return {"text": "ok", "route": [], "meta": "", "status": "done", "cost": None}
    monkeypatch.setattr(assistant, "answer", slow)
    monkeypatch.setattr(chat, "_finish", lambda *a, **k: None)
    rt = SimpleNamespace(cursor=lambda: SimpleNamespace(execute=lambda *a, **k: None), clock=lambda: NOW, bump=lambda *a: None)
    threads = [threading.Thread(target=assistant._work, args=(rt, 1, k, "q", ""), daemon=True) for k in range(1, 7)]
    for t in threads:
        t.start()
    deadline = time.time() + 5
    while peak[0] < assistant.AT_ONCE and time.time() < deadline:
        time.sleep(0.02)
    time.sleep(0.2)                                              # the others must be waiting, not running
    assert 1 < peak[0] == assistant.AT_ONCE and len(running) == assistant.AT_ONCE
    release.set()
    for t in threads:
        t.join(10)
    assert not running and peak[0] == assistant.AT_ONCE
