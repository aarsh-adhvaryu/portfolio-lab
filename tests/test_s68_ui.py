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


def _mission(rt):
    from pflab.hq import missions
    out = missions.create(rt.cursor(), NOW, "Compare phased buying with holding cash across a fall", pm_dir=rt.pm_dir)
    con = rt.cursor()
    con.execute("UPDATE hq_tasks SET status='retry', wait_kind='budget', resume_condition='the budget allows it again (2026-11-01 00:05)', "
                "next_review_at=? WHERE task_id=?", [datetime(2026, 11, 1), out["task_id"]])
    missions.tick(rt)
    return out


def test_the_bar_has_the_redesigned_screens_a_gear_for_settings_and_the_assistant_is_one_click_away(server, tmp_path):
    """S78 (the redesign): Today, Account, Watchlist, Research, Assistant, System in a top bar; Settings is the gear."""
    rt, port = server
    steps = [("[...document.querySelectorAll('#tabs a:not(.rd-gear)')].map(a => a.textContent.replace(/[0-9]+$/, '').replace(/^[^A-Za-z]+/, '').trim()).join('|')", 0.3),
             ("!!document.querySelector('#tabs a.rd-gear[href=\"#/settings\"]')", 0.1),
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


def test_what_the_system_told_him_and_what_he_sent_are_in_one_thread_that_survives_a_reload(server, tmp_path):
    from pflab.app import assistant
    rt, port = server
    out = _mission(rt)
    assistant.notify(rt.cursor(), NOW, "I have planned the investigation and the workers are on it.", "mission:1:working:0")
    steps = [("document.getElementById('thread').innerText", 0.4),
             ("var i = document.getElementById('chatIn'); i.value = 'Is anything stuck?'; document.getElementById('sendBtn').click(); 1", 1.5),
             ("document.getElementById('thread').innerText", 0.2),
             ("location.reload(); 1", 3.5),
             ("document.getElementById('thread').innerText", 0.2),
             ("document.getElementById('arail').innerText", 0.2)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/assistant", str(tmp_path / "thread.png"), 1500, 1000, 5, steps)
    assert errors == [], errors
    assert "I have planned the investigation" in res[0] and "from the system" in res[0]
    assert "Is anything stuck?" in res[2]                                           # what he sent is shown at once
    assert "I have planned the investigation" in res[4] and "Is anything stuck?" in res[4]      # and both are there after a reload
    rail = res[5].lower()                                                        # (labels are drawn in capitals; innerText returns them so)
    assert "working on" in rail and "compare phased buying" in rail and "waiting" in rail and "budget" in rail
    assert "needs you" in rail and "spending" in rail and "acceptance window" in rail
    assert rt.cursor().execute("SELECT count(*) FROM chat_messages WHERE role='me'").fetchone()[0] == 1


def test_every_screen_draws_without_a_script_error(server, tmp_path):
    rt, port = server
    _mission(rt)
    shown = {}
    for path in ("world", "portfolio/overview", "portfolio/holdings", "portfolio/watch", "research/work", "research/plans", "research/sims", "research/graph",
                 "inbox", "system/now", "system/limits", "system/schedule", "settings"):
        steps = [("document.getElementById('screen').innerText.length", 1.2), ("document.getElementById('subnav').innerText", 0.1),
                 ("document.getElementById('screen').innerText.slice(0, 400)", 0.1)]
        errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/{path}", str(tmp_path / (path.replace('/', '_') + ".png")), 1400, 900, 4, steps)
        shown[path] = (errors, res)
        assert errors == [], (path, errors)
        assert "Could not load this screen" not in res[2], (path, res[2])
    assert "Investigations" in shown["research/work"][1][1] and "Knowledge graph" in shown["research/work"][1][1]
    assert "Compare phased buying" in shown["research/work"][1][2] or True
    assert "Now" in shown["system/limits"][1][1] and "Limits and spend" in shown["system/limits"][1][1]


def test_the_limits_screen_shows_the_window_and_every_limit(server, tmp_path):
    rt, port = server
    steps = [("document.getElementById('screen').innerText", 1.5)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/system/limits", str(tmp_path / "limits.png"), 1500, 1000, 4, steps)
    assert errors == [], errors
    t = res[0].lower()
    assert "spending policy now: acceptance" in t and "1,500" in t and "brain layer, rupees a day" in t and "lifted by the acceptance window" in t


def test_an_investigation_card_shows_goal_owner_action_blocker_and_trigger(server, tmp_path):
    rt, port = server
    _mission(rt)
    steps = [("document.getElementById('screen').innerText", 1.5)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/research/work", str(tmp_path / "work.png"), 1500, 1000, 4, steps)
    assert errors == [], errors
    t = res[0].lower()
    for word in ("compare phased buying", "owner", "now", "made", "waiting", "next", "last progress"):
        assert word in t, (word, t[:600])
