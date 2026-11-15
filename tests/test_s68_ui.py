"""The app on a synthetic profile, served on a free port: the `server` fixture the endpoint tests use. (S90: the browser tests of the old screens that lived here
were removed with those screens; the screens of today are driven in tests/test_s89_screens.py and tests/test_s89b_screens.py.)"""
from __future__ import annotations

import socket
import threading
import time
from datetime import datetime

import pytest

NOW = datetime(2026, 10, 31, 15, 0)


@pytest.fixture
def server(tmp_path, monkeypatch):
    import uvicorn
    from pflab.app import runtime
    from pflab.app.server import create_app
    from pflab.pm import store
    (tmp_path / "pm").mkdir()
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    (tmp_path / "pm" / "api_budget.toml").write_text("[api]\nmonthly_cap_rupees = 2500\nask_above_rupees = 100\nusd_inr = 90.0\nadopted = true\n"
                                                      "[acceptance]\nsince = 2026-10-31T00:00:00\nuntil = 2026-11-07T23:59:00\ncap_rupees = 1500\n", encoding="utf-8")
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path / "pm"))
    con = store.connect(tmp_path / "l.duckdb")
    rt = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = uvicorn.Server(uvicorn.Config(create_app(rt), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    import urllib.request
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    yield rt, port
    srv.should_exit = True
    th.join(5)
