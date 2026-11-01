"""The worker pool (S69): independent worker tasks run at the same time, on their own threads, while the HQ round, the chat and everything else go on.

`Runtime.start` starts WORKERS threads that each loop: take the oldest due worker task (an atomic claim, `board.claim`), run it, and look again. A task
whose dependency is not done is parked, never queued, so it takes no thread; it is queued again by `board.wake` when the task it waits on finishes. The
HQ round keeps the other agents' tasks and the mission state machine (`missions.tick`), which only reads the store.

The pool also drives the experiments a mission is waiting for (`missions.drive_experiments`): the learner's nightly cycle would otherwise take days.
Pause holds it (his own orders only). The pool is optional: with no pool (tests, the verifier's worker) `service.drive_missions` runs the same tasks on
threads of its own, so every path uses the same claim.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("pflab.pool")

IDLE_WAIT_S = 4.0
WAKE = threading.Event()


def wake() -> None:
    WAKE.set()


def worker_loop(rt, index: int) -> None:
    from pflab.hq import board, missions, roster, service
    first = index == 0
    while not rt.stop.is_set():
        try:
            hold = service.paused(rt)
            ran = board.run_one(rt, roster.runners(), service.deliver(rt), his_only=hold, prefix="w_")
            if ran is None and first and not hold:
                if missions.drive_experiments(rt):               # one thread also carries the experiments missions wait for
                    continue
            if ran is None:
                WAKE.wait(IDLE_WAIT_S)
                WAKE.clear()
            elif hasattr(rt, "wake_hq"):
                rt.wake_hq()                                      # a task ended: the mission state machine looks at once
        except Exception:                                         # logged, never fatal: the loop goes on after a pause
            log.exception("worker %d failed a round", index)
            rt.bump("health")
            time.sleep(5)


def start(rt, n: int = 0) -> list:
    """Start the pool's threads on a runtime (idempotent). `n` defaults to board.WORKERS."""
    from pflab.hq import board
    if getattr(rt, "pool_active", False):
        return []
    rt.pool_active = True
    out = []
    for i in range(n or board.WORKERS):
        t = threading.Thread(target=worker_loop, args=(rt, i), name=f"worker-{i + 1}", daemon=True)
        t.start()
        out.append(t)
    return out
