"""S79 item 13: a GPU duty cycle per mode.

The laptop GPU drops off the bus under sustained load, so the local model may hold the card for only a share of wall time (configs/markets.toml
[modes.gpu_duty]: pre_open 0.6, session 0.4, post_close 0.7, deep 0.85). `DutyCycle` keeps a rolling window of (start, end) busy intervals and,
before each local call, says how long to wait so the share of the window the model was busy stays at or under the duty. It is a throttle
on the queue (`llm/queue.py` GATE), not a priority change: the call already waiting still goes in order of importance, it just starts later.

    from pflab.llm import duty
    duty.set_mode("session")                      # the lead calls this on a mode change
    duty.THROTTLE.enabled = False                 # the off switch (also env PFLAB_GPU_DUTY=off)

`client.chat` calls `THROTTLE.before(purpose)` ahead of the queue's door and wraps the call in `THROTTLE.busy()` once it has the card; both are no-ops while the throttle is off (its state until `set_mode` is first called). A priority-0 call (his chat) is never delayed more
than `MAX_FRONT_WAIT_S`, whatever the duty: a person is waiting.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Callable, Deque, Optional, Tuple

WINDOW_S = 600.0              # the rolling window the share is measured over
MAX_FRONT_WAIT_S = 5.0        # the most a person-facing call is held back
MIN_DUTY = 0.05               # a configured duty is never read as below this (a typo must not freeze the model)


class DutyCycle:
    def __init__(self, mode: str = "session", duty: Optional[float] = None, window_s: float = WINDOW_S,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep, enabled: bool = True) -> None:
        self.mode = mode
        self._duty = duty
        self.window_s = float(window_s)
        self.clock, self.sleep = clock, sleep
        self.enabled = enabled
        self._busy: Deque[Tuple[float, float]] = deque()
        self._open: Optional[float] = None
        self._ema = 0.0                     # a running estimate of how long one call holds the card
        self._lock = threading.Lock()

    # -- the share ------------------------------------------------------------------------------------------------------
    @property
    def duty(self) -> float:
        d = self._duty
        if d is None:
            from pflab import markets
            d = markets.gpu_duty(self.mode)
        return min(1.0, max(MIN_DUTY, float(d)))

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self.mode = mode
            self._duty = None

    def _trim(self, now: float) -> None:
        while self._busy and self._busy[0][1] <= now - self.window_s:
            self._busy.popleft()

    def busy_seconds(self, now: Optional[float] = None) -> float:
        """Seconds of the last window the model was busy (a call still running counts up to now)."""
        now = self.clock() if now is None else now
        lo = now - self.window_s
        with self._lock:
            self._trim(now)
            tot = sum(min(e, now) - max(s, lo) for s, e in self._busy)
            if self._open is not None:
                tot += now - max(self._open, lo)
        return max(0.0, tot)

    def share(self, now: Optional[float] = None) -> float:
        return self.busy_seconds(now) / self.window_s

    def wait_needed(self, expected_s: float = 0.0, now: Optional[float] = None) -> float:
        """How long to wait before a call so that, after it runs `expected_s`, the share is <= duty: the busy time falls out of the
        window as time passes. 0 when there is room."""
        now = self.clock() if now is None else now
        cap = self.duty * self.window_s
        busy = self.busy_seconds(now) + expected_s
        if busy <= cap:
            return 0.0
        lo = now - self.window_s
        excess = busy - cap
        wait = 0.0
        with self._lock:
            for s, e in self._busy:               # oldest first: wait until enough of the old busy time leaves the window
                part = e - max(s, lo)
                if part <= 0:
                    continue
                if excess <= part:
                    wait = (max(s, lo) + excess) - lo
                    return min(wait, self.window_s)
                excess -= part
                wait = e - lo
        return min(max(wait, 0.0), self.window_s)

    # -- the door -------------------------------------------------------------------------------------------------------
    def _off(self) -> bool:
        return (not self.enabled) or os.environ.get("PFLAB_GPU_DUTY", "").lower() == "off"

    def before(self, purpose: str = "", expected_s: float = 0.0) -> float:
        """Sleep until the model may start another call (outside the queue's door, so a waiting call does not block it); returns the
        seconds slept. A person-facing call (priority 0) is held back at most MAX_FRONT_WAIT_S."""
        if self._off():
            return 0.0
        w = self.wait_needed(expected_s or self._ema)
        if w > 0:
            from pflab.llm.queue import PRIORITY
            if PRIORITY.get(purpose, 2) == 0:
                w = min(w, MAX_FRONT_WAIT_S)
            self.sleep(w)
        return w

    @contextmanager
    def busy(self):
        """Wrap the call itself: its running time is what counts toward the share."""
        if self._off():
            yield
            return
        t0 = self.clock()
        with self._lock:
            self._open = t0
        try:
            yield
        finally:
            t1 = self.clock()
            with self._lock:
                self._open = None
                self._busy.append((t0, t1))
                self._ema = (t1 - t0) if self._ema == 0.0 else 0.7 * self._ema + 0.3 * (t1 - t0)
                self._trim(t1)

    @contextmanager
    def slot(self, purpose: str = "", expected_s: float = 0.0):
        self.before(purpose, expected_s)
        with self.busy():
            yield


# Off until the lead calls set_mode (the workshop and the tests never throttle). PFLAB_GPU_DUTY=off always wins.
THROTTLE = DutyCycle(enabled=False)


def set_mode(mode: str) -> None:
    """The lead's hook: the market mode changed (pre_open, session, post_close, deep). The first call turns the throttle on."""
    THROTTLE.set_mode(mode)
    THROTTLE.enabled = True
