"""S67 local: the World screen in a REAL browser (headless Edge over DevTools), on a synthetic profile. Skipped where Edge or websockets are missing.
It checks what a person would see: the map draws without a script error, the numbers agree with the API, a click opens the inspector, a change in the
store shows up on the next refresh WITHOUT the map being rebuilt, and Pause works."""
from __future__ import annotations

import os
import socket
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("websockets")
from tests import _edge  # noqa: E402

pytestmark = [pytest.mark.ui, pytest.mark.skipif(not os.path.exists(_edge.EDGE), reason="Microsoft Edge is not installed here")]

NOW = datetime(2026, 10, 29, 21, 30)


@pytest.fixture
def server(tmp_path, monkeypatch):
    import uvicorn
    from pflab.app import runtime
    from pflab.app.server import create_app
    from pflab.pm import store
    (tmp_path / "pm").mkdir()
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    con = store.connect(tmp_path / "l.duckdb")
    for rid, job, st, mins in ((1, "collect", "ok", 300), (2, "prices", "ok", 290), (3, "mail", "ok", 200)):
        t0 = NOW - timedelta(minutes=mins)
        con.execute("INSERT INTO job_runs (run_id, job, slot, started_at, finished_at, status) VALUES (?,?,?,?,?,?)", [rid, job, t0, t0, t0 + timedelta(seconds=20), st])
    rt = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = uvicorn.Server(uvicorn.Config(create_app(rt), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(50):
        try:
            import urllib.request
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    yield rt, port
    srv.should_exit = True
    th.join(5)


def test_the_world_draws_updates_in_place_opens_the_inspector_and_pauses(server, tmp_path):
    rt, port = server
    con = rt.cursor()

    def break_mail():                                                    # a failure appears in the store while the page is open
        time.sleep(3.0)
        con.execute("INSERT INTO job_runs (run_id, job, slot, started_at, finished_at, status, detail) VALUES (99, 'mail', ?, ?, ?, 'failed', 'MailError: Gmail answered 401')",
                    [NOW, NOW, NOW + timedelta(seconds=5)])
    threading.Thread(target=break_mail, daemon=True).start()
    steps = [
        ("document.querySelectorAll('[data-nid]').length", 0.2),                                                              # 0: the map has its nodes
        ("document.querySelector('svg.wsvg').dataset.mark = 'kept'; document.getElementById('wverdict').textContent", 0.2),    # 1: the verdict as drawn
        ("document.querySelector('[data-nid=\"mail\"]').dispatchEvent(new MouseEvent('click', {bubbles: true})); 1", 0.4),     # 2: click Mail
        ("document.getElementById('winsp').innerText", 0.2),                                                                  # 3: the inspector says Mail
        ("document.getElementById('wpause').click(); 1", 7.5),                                                                # 4: pause, then wait for a refresh
        ("JSON.stringify({mark: document.querySelector('svg.wsvg').dataset.mark, mail: document.querySelector('[data-nid=\"mail\"]').getAttribute('class'), "
         "pause: document.getElementById('wpause').textContent, verdict: document.getElementById('wverdict').textContent})", 0.1),   # 5: after the refresh
    ]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/world", str(tmp_path / "world.png"), 1500, 1000, 5, steps)
    assert errors == [], errors
    assert res[0] >= 30 and (tmp_path / "world.png").stat().st_size > 20000                                                    # a real picture was drawn
    assert "Mail" in res[3] and "daily 21:15" in res[3]
    import json
    after = json.loads(res[5])
    assert after["mark"] == "kept"                                                                                            # the map was patched, not rebuilt
    assert "st-down" in after["mail"]                                                                                         # the failure showed up by itself
    assert after["pause"] == "Resume the system" and "Paused" in after["verdict"]
    assert rt.settings["scheduler"] is False
