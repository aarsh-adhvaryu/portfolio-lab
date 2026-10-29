"""A headless worker (S67): the dashboard's whole runtime and server with no window, for the verifier and the tests of independent operation.

    python -m pflab.app.worker            # PFLAB_PM_DIR / PFLAB_DATA_DIR as for the app; the port from settings.json

It is the same `launcher._serve` the app runs, except that it does not stop when no window is open: it runs until `/api/shutdown` (or a
signal), then shuts down the way the app does (a running job gets its grace, the store is closed). A test client may come and go; the worker
does not depend on one.
"""
from __future__ import annotations

import logging
import signal
import sys
from pathlib import Path


def main() -> int:
    from pflab.app import launcher, settings as st
    from pflab.pm import store
    pm = store.pm_dir()
    (pm / "app").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=pm / "app" / "worker.log", level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("pflab.worker")
    port = st.load(pm)["port"]

    def term(*_):                                         # SIGTERM / Ctrl+C: stop the way a requested shutdown does
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, term)
    try:
        return launcher._serve(pm, log, f"http://127.0.0.1:{port}/", port, None, headless=True)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
