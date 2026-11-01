"""One GPU, one local call at a time, the most important first (S71).

The laptop has one graphics card: two local calls at once do not run in parallel, they fight (and a sustained load drops the card off the bus). The
local model is also used by many things at once now: the chat front, document routing, the nightly notes, the learner's reading. `GATE.slot(purpose)` is
the one door: a call waits for its turn in order of how much a person is waiting for it (his chat first, the learner's reading last), a wait is bounded
(a call that cannot get its turn in time raises `Busy` and its caller falls back to the cloud or tries later), and a call that fails releases the door.
A running call is never interrupted: priority orders the waiting, it does not preempt. `client.chat` goes through it, so every local call is covered.
"""
from __future__ import annotations

import heapq
import itertools
import threading
import time
from contextlib import contextmanager

PRIORITY = {"front": 0, "answers": 0, "routing": 1, "playbook": 1, "brief": 2, "workshop_filler": 2, "workshop_writer": 2,
            "learner_reading": 3, "experiment_code": 3}
DEFAULT_PRIORITY = 2
WAIT_S = {0: 120.0, 1: 300.0, 2: 600.0, 3: 1800.0}      # how long a call of each priority may wait for its turn


class Busy(RuntimeError):
    """The local model did not become free in time."""


class Gate:
    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._busy = False
        self._heap: list = []
        self._seq = itertools.count()

    def waiting(self) -> int:
        with self._cv:
            return len(self._heap)

    @contextmanager
    def slot(self, purpose: str = "", wait_s: float = None):
        prio = PRIORITY.get(purpose, DEFAULT_PRIORITY)
        limit = WAIT_S[prio] if wait_s is None else wait_s
        me = (prio, next(self._seq))
        end = time.monotonic() + limit
        with self._cv:
            heapq.heappush(self._heap, me)
            try:
                while self._busy or self._heap[0] != me:
                    left = end - time.monotonic()
                    if left <= 0:
                        raise Busy(f"the local model stayed busy for {limit:.0f} s (waiting for: {purpose or 'a local call'})")
                    self._cv.wait(left)
            except BaseException:
                self._heap.remove(me)
                heapq.heapify(self._heap)
                self._cv.notify_all()
                raise
            heapq.heappop(self._heap)
            self._busy = True
        try:
            yield
        finally:
            with self._cv:
                self._busy = False
                self._cv.notify_all()


GATE = Gate()
