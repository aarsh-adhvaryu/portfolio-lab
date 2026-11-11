"""S79b item 17: idle cores for deep work (replay by year, Monte Carlo, event studies), only in `deep` mode.

    pool = DeepPool()                         # workers = cores - 2 (never fewer than 1)
    out = pool.run(fn, items)                 # fn must be picklable (a module-level function); items are its single arguments
    out == {"results": [...in order, None where not done], "done": n, "total": N, "cancelled": bool, "mode": "deep", "workers": k, "reason": ""}

Rules:
  * It parallelises only when the primary market's mode (`pflab.markets.primary`) is `deep` and configs/s79b.toml [seats] deep_pool is on. In any other mode, or with
    the switch off, the items run serially in the caller (same results, no extra cores) and `reason` says why; `serial_fallback=False` skips them instead.
  * Cooperative cancel: between completions the mode is read again (and `cancel()` is honoured); when it is no longer deep the not-yet-started items are cancelled, the
    ones already running finish (a process is never killed mid-write), and the partial results come back with cancelled=True. A caller that needs all of it
    runs again at the next deep window.
  * The core budget leaves two cores for the app, DuckDB and the model server. An exception in one item is returned in `errors` and does not lose the others.
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import FIRST_COMPLETED, Executor, ProcessPoolExecutor, wait
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence


def core_budget(cores: Optional[int] = None) -> int:
    return max(1, int(cores if cores is not None else (os.cpu_count() or 4)) - 2)


def _switch_on() -> bool:
    try:
        from pflab.llm import seats
        sw = seats.switch()
        return bool(sw.get("on", True)) and bool(sw.get("deep_pool", True))
    except Exception:
        return True


def current_mode(now: Optional[datetime] = None) -> str:
    from pflab import markets
    return markets.primary(now or datetime.now())[1]


class DeepPool:
    def __init__(self, workers: Optional[int] = None, *, mode_fn: Optional[Callable[[], str]] = None, executor_factory: Optional[Callable[[int], Executor]] = None,
                 poll_s: float = 1.0, serial_fallback: bool = True, switch_fn: Optional[Callable[[], bool]] = None) -> None:
        self.workers = core_budget() if workers is None else max(1, int(workers))
        self.mode_fn = mode_fn or current_mode
        self.factory = executor_factory or (lambda n: ProcessPoolExecutor(max_workers=n))
        self.poll_s = poll_s
        self.serial_fallback = serial_fallback
        self.switch_fn = switch_fn or _switch_on
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def allowed(self) -> tuple:
        if not self.switch_fn():
            return False, "off ([seats] deep_pool = false)"
        try:
            m = self.mode_fn()
        except Exception as e:
            return False, f"mode unknown ({type(e).__name__})"
        return (m == "deep"), m

    def _stop(self) -> Optional[str]:
        if self._cancel.is_set():
            return "cancelled by the caller"
        try:
            m = self.mode_fn()
        except Exception:
            return None
        return None if m == "deep" else f"mode is now {m}"

    def run(self, fn: Callable[[Any], Any], items: Sequence[Any]) -> Dict[str, Any]:
        items = list(items)
        n = len(items)
        ok, why = self.allowed()
        res: List[Any] = [None] * n
        errors: Dict[int, str] = {}
        done = 0
        if not ok:
            if not self.serial_fallback:
                return {"results": res, "done": 0, "total": n, "cancelled": False, "mode": why, "workers": 0, "errors": errors, "reason": f"not parallel: {why}"}
            for i, it in enumerate(items):                      # serial, in the caller: the same answers without taking cores
                try:
                    res[i] = fn(it)
                except Exception as e:
                    errors[i] = f"{type(e).__name__}: {str(e)[:160]}"
                done += 1
            return {"results": res, "done": done, "total": n, "cancelled": False, "mode": why, "workers": 1, "errors": errors, "reason": f"ran serially: {why}"}
        self._cancel.clear()
        k = min(self.workers, max(1, n))
        reason = ""
        cancelled = False
        ex = self.factory(k)
        try:
            pending = {ex.submit(fn, it): i for i, it in enumerate(items)}
            while pending:
                finished, _ = wait(list(pending), timeout=self.poll_s, return_when=FIRST_COMPLETED)
                for f in finished:
                    i = pending.pop(f)
                    try:
                        res[i] = f.result()
                    except Exception as e:
                        errors[i] = f"{type(e).__name__}: {str(e)[:160]}"
                    done += 1
                if not cancelled:
                    stop = self._stop()
                    if stop:
                        cancelled, reason = True, stop
                        for f in list(pending):
                            if f.cancel():                      # only a not-yet-started item can be cancelled; the running ones finish and are collected by the loop
                                pending.pop(f)
        finally:
            ex.shutdown(wait=True, cancel_futures=True)
        return {"results": res, "done": done, "total": n, "cancelled": cancelled, "mode": "deep", "workers": k, "errors": errors, "reason": reason}

