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
    for rid, job, st, mins in ((1, "collect", "ok", 300), (2, "prices", "ok", 290), (3, "tradecheck", "ok", 200)):
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
        con.execute("INSERT INTO job_runs (run_id, job, slot, started_at, finished_at, status, detail) VALUES (99, 'tradecheck', ?, ?, ?, 'failed', 'TokenException: the Kite login expired')",
                    [NOW, NOW, NOW + timedelta(seconds=5)])
    threading.Thread(target=break_mail, daemon=True).start()
    steps = [
        ("document.querySelectorAll('[data-nid]').length", 0.2),                                                              # 0: the map has its nodes
        ("document.querySelector('svg.wsvg').dataset.mark = 'kept'; document.getElementById('wverdict').textContent", 0.2),    # 1: the verdict as drawn
        ("document.querySelector('[data-nid=\"broker\"]').dispatchEvent(new MouseEvent('click', {bubbles: true})); 1", 0.4),   # 2: click Kite
        ("document.getElementById('winsp').innerText", 0.2),                                                                  # 3: the inspector says Kite
        ("document.getElementById('wpause').click(); 1", 7.5),                                                                # 4: pause, then wait for a refresh
        ("JSON.stringify({mark: document.querySelector('svg.wsvg').dataset.mark, mail: document.querySelector('[data-nid=\"broker\"]').getAttribute('class'), "
         "pause: document.getElementById('wpause').textContent, verdict: document.getElementById('wverdict').textContent})", 0.1),   # 5: after the refresh
    ]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/world", str(tmp_path / "world.png"), 1500, 1000, 5, steps)
    assert errors == [], errors
    assert res[0] >= 30 and (tmp_path / "world.png").stat().st_size > 20000                                                    # a real picture was drawn
    assert "Kite" in res[3] and "every 15 min" in res[3]
    import json
    after = json.loads(res[5])
    assert after["mark"] == "kept"                                                                                            # the map was patched, not rebuilt
    assert "st-down" in after["mail"]                                                                                         # the failure showed up by itself
    assert after["pause"] == "Resume the system" and "Paused" in after["verdict"]
    assert rt.settings["scheduler"] is False


def test_an_order_given_from_an_agents_panel_reaches_the_board_and_the_old_tab_is_gone(server, tmp_path):
    """What Agent HQ used to do, from the World: click an agent, give it an order, and it is on the board (and shown there)."""
    rt, port = server
    steps = [
        ("document.querySelector('[data-nid=\"a:quant\"]').dispatchEvent(new MouseEvent('click', {bubbles: true})); 1", 0.6),            # 0: open Quant (its orders go to the calculation runner)
        ("var t = document.getElementById('wio-t'); t.value = 'Drawdown of the Nifty 50 since 2020'; document.getElementById('wio-go').click(); 1", 1.5),   # 1: order it
        ("document.getElementById('wbench').innerText", 0.2),                                                                          # 2: the board shows it
        ("[...document.querySelectorAll('#tabs a')].map(a => a.textContent).join('|')", 0.1),                                          # 3: the tab bar
    ]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/world", str(tmp_path / "order.png"), 1500, 1000, 5, steps)
    assert errors == [], errors
    row = rt.cursor().execute("SELECT to_agent, text, from_agent FROM hq_tasks").fetchall()
    assert row == [("calc", "Drawdown of the Nifty 50 since 2020", "investor")], row
    assert "Drawdown of the Nifty 50" in res[2]
    assert "Agent HQ" not in res[3] and "Assistant" in res[3] and "World" in res[3] and "Command centre" not in res[3] and "AI centre" not in res[3]


def test_a_reply_being_typed_is_not_redrawn_away_and_the_screen_catches_up_after(server, tmp_path):
    """Found on the first real launch: with 30 questions arriving, the screen refreshed under the cursor and an answer could not be finished."""
    from pflab.agents import questions
    rt, port = server
    con = rt.cursor()
    q1 = questions.ask(con, "mail", "k1", "First question: is this yours?", NOW)

    def later():                                                            # a new question arrives while he is typing the first answer
        time.sleep(8.0)
        questions.ask(con, "mail", "k2", "Second question arrived later", NOW)
        rt.bump("inbox")
        rt.bump("command")
    threading.Thread(target=later, daemon=True).start()
    steps = [
        (f"var i = document.getElementById('qa{q1}'); i.dataset.mark = 'kept'; i.focus(); i.value = 'yes, it is mine and I'; 1", 0.2),     # 0: typing
        ("load(true); 1", 4.0),                                                                                                           # 1: a refresh while he types (the arriving question is already in the store)
        ("load(true); 1", 5.0),                                                                                                                       # 1: refreshes come and go
        (f"var j = document.getElementById('qa{q1}'); JSON.stringify({{mark: j.dataset.mark, value: j.value, focused: document.activeElement === j, "
         "second: document.getElementById('screen').innerText.includes('Second question arrived later')})", 0.1),                        # 2: still being typed
        ("document.activeElement.blur(); 1", 3.0),                                                                                        # 3: he leaves the box
        (f"JSON.stringify({{second: document.getElementById('screen').innerText.includes('Second question arrived later'), "
         f"first: (document.getElementById('qa{q1}') || {{}}).value || ''}})", 0.1),                                                      # 4: the screen has caught up, his text is kept
    ]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/assistant", str(tmp_path / "type.png"), 1500, 1000, 5, steps)
    import json
    assert errors == [], errors
    mid = json.loads(res[3])
    assert mid["mark"] == "kept" and mid["value"] == "yes, it is mine and I" and mid["focused"] and mid["second"] is False
    end = json.loads(res[5])
    assert end["second"] is True and end["first"] == "yes, it is mine and I"
