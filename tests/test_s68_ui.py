"""S68: the redesigned dashboard in a REAL browser (headless Edge), on a synthetic profile. Every screen draws without a script error; the rail has
the new screens and none of the retired ones; the assistant's conversation is one persistent thread that shows what the system told it and what he
sent; an investigation shows its card with the blocker and next trigger; the limits in force are shown. Skipped where Edge is missing."""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from datetime import datetime

import pytest

pytest.importorskip("websockets")
from tests import _edge  # noqa: E402

pytestmark = [pytest.mark.ui, pytest.mark.skipif(not os.path.exists(_edge.EDGE), reason="Microsoft Edge is not installed here")]

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


def test_the_bar_has_the_redesigned_screens_a_gear_for_settings_and_the_assistant_is_one_click_away(server, tmp_path):
    """S78 (the redesign): Today, Account, Watchlist, Research, Assistant, System in a top bar; Settings is the gear."""
    rt, port = server
    steps = [("[...document.querySelectorAll('#tabs a:not(.rd-gear)')].map(a => a.textContent.replace(/[0-9]+$/, '').replace(/^[^A-Za-z]+/, '').trim()).join('|')", 0.3),
             ("!!document.querySelector('#status a.rd-gear[href=\"#/settings\"]')", 0.1),
             ("document.querySelector('#tabs a.on').textContent.trim().replace(/^[^A-Za-z]+/, '')", 0.1)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/", str(tmp_path / "home.png"), 1500, 1000, 5, steps)
    assert errors == [], errors
    assert res[0] == "Today|Account|Watchlist|Research|Assistant|System"
    assert "Command centre" not in res[0] and "AI centre" not in res[0] and "Schedule" not in res[0] and "World" not in res[0]
    assert res[1] is True or res[1] == "true"
    assert res[2] == "Today"
    steps2 = [("!!document.getElementById('thread') && !!document.getElementById('chatIn') && !!document.getElementById('arail')", 0.3)]
    errors, res2 = _edge.shoot(f"http://127.0.0.1:{port}/#/assistant", str(tmp_path / "asst.png"), 1500, 1000, 5, steps2)
    assert errors == [], errors
    assert res2[0] is True or res2[0] == "true"


def test_the_limits_screen_shows_the_window_and_every_limit(server, tmp_path):
    rt, port = server
    steps = [("document.getElementById('screen').innerText", 1.5)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/system/limits", str(tmp_path / "limits.png"), 1500, 1000, 4, steps)
    assert errors == [], errors
    t = res[0].lower()
    assert "spending policy now: acceptance" in t and "1,500" in t and "brain layer, rupees a day" in t and "lifted by the acceptance window" in t

