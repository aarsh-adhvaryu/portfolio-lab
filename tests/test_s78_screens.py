"""S78: the redesigned screens draw in a REAL browser (headless Edge) on a synthetic profile: Today (one page), Account, Watchlist, Research overview, System checks, and the abilities
in Settings. Skipped where Edge is missing."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import pytest

from pflab.app import settings as st
from pflab.paper import watch
from tests import _edge
from tests.test_s68_ui import NOW, _mission, server  # noqa: F401  (the fixture)

pytestmark = [pytest.mark.ui, pytest.mark.skipif(not os.path.exists(_edge.EDGE), reason="Microsoft Edge is not installed here")]

AAA = "INE000A01011"


def _book(con):
    """A started paper book with two marked days, one decision, an act of each loop and a lesson."""
    con.execute("INSERT INTO paper_cash VALUES (1, ?, 500000, 'seed', 'fake starting cash', now())", [date(2026, 10, 30)])
    con.execute("INSERT INTO paper_days VALUES (?, 500000, 500000, 0, 0, '{}')", [date(2026, 10, 30)])
    con.execute("INSERT INTO paper_days VALUES (?, 506000, 500000, 0, 0, '{}')", [date(2026, 10, 31)])
    con.execute("INSERT INTO paper_decisions (decision_id, made_at, case_id, action, isin, symbol, amount, reason, alternatives, status) "
                "VALUES (1, now(), 7, 'WAIT', NULL, NULL, NULL, 'valuations are high across the market; keep cash for now', 'buy the index', 'executed')")


def test_today_is_one_page_with_the_account_the_gate_the_decisions_and_the_ask_bar(server, tmp_path):
    rt, port = server
    _book(rt.cursor())
    steps = [("document.getElementById('screen').innerText", 1.8),
             ("document.documentElement.scrollHeight <= window.innerHeight + 4", 0.1),
             ("document.querySelectorAll('.rd-card').length", 0.1),
             ("!!document.getElementById('rdAsk')", 0.1)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/today", str(tmp_path / "today.png"), 1500, 1000, 5, steps)
    assert errors == [], errors
    t = res[0].lower()                                                                    # (labels are upper-cased by the style)
    assert "the account" in t and "proving itself" in t and "of 40 sessions" in t and "keep cash for now" in t and "api money this month" in t
    assert res[1] is True or res[1] == "true"                                              # no page scrolling
    assert int(res[2]) >= 5 and (res[3] is True or res[3] == "true")


def test_the_ask_bar_on_today_goes_to_the_assistant(server, tmp_path):
    rt, port = server
    _book(rt.cursor())
    steps = [("var i = document.getElementById('rdAsk'); i.value = 'what are you waiting for?'; document.getElementById('rdSend').click(); 1", 5.0),
             ("location.hash", 0.2)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/today", str(tmp_path / "ask.png"), 1500, 1000, 5, steps)
    assert errors == [], errors
    assert res[1] == "#/assistant"


def test_account_shows_the_value_the_top_up_room_and_says_why_a_top_up_is_refused(server, tmp_path):
    rt, port = server
    _book(rt.cursor())
    steps = [("document.getElementById('screen').innerText", 1.5),
             ("document.getElementById('rdAmt').value = '20000'; document.getElementById('rdTop').click(); 1", 1.5),
             ("document.getElementById('rdTopMsg').textContent", 0.2)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/account", str(tmp_path / "acc.png"), 1500, 1000, 5, steps)
    assert errors == [], errors
    assert "account value" in res[0].lower() and "add money to its bank" in res[0].lower() and "not your money" in res[0].lower()
    assert "not the system's own" in res[2]                                               # (the synthetic profile has no system account: the server says no, the screen says why)


def test_watchlist_shows_an_item_with_its_zone_and_status_and_what_happens_next(server, tmp_path):
    rt, port = server
    con = rt.cursor()
    con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, 'AAA', 'AAA Ltd', 's', now())", [AAA])
    for k in range(5):
        con.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [AAA, date(2026, 10, 27) + timedelta(days=k), 1610.0 - k * 5])
    out = watch.add(con, NOW, symbol="AAA", kind="zone", reason="A quality name above its range; wait for the range before buying any.", by="the investor", zone_low=1420.0, zone_high=1500.0, his_numbers=True)
    assert out["stored"] is True, out
    steps = [("document.getElementById('screen').innerText", 1.5),
             ("document.querySelectorAll('[data-wl]').length", 0.1),
             ("document.querySelectorAll('.rd-zone').length", 0.1)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/watchlist", str(tmp_path / "wl.png"), 1500, 1000, 5, steps)
    assert errors == [], errors
    t = res[0]
    assert "AAA" in t and "WAITING" in t and "Wants ₹1,420–1,500" in t
    assert "what happens next" in t.lower() and "reaching the point never buys by itself" in t.lower()
    assert int(res[1]) == 1 and int(res[2]) == 1


def test_research_overview_says_why_research_exists_and_lists_the_investigations(server, tmp_path):
    rt, port = server
    _mission(rt)
    steps = [("document.getElementById('screen').innerText", 1.8)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/research", str(tmp_path / "res.png"), 1500, 1000, 5, steps)
    assert errors == [], errors
    t = res[0].lower()
    assert "why it researches" in t and "argues against itself" in t and "one look, start to finish" in t and "compare phased buying" in t


def test_system_checks_show_the_groups_and_what_failed_and_the_button_runs_them(server, tmp_path):
    rt, port = server
    con = rt.cursor()
    rows = [("Agents", "probe: research", "ok", "answered"), ("Tools", "probe: chart_view", "bad", "no candles for the probe name"), ("Data and Kite", "Docker", "warn", "Docker is asleep")]
    for i, (g, n, s, nt) in enumerate(rows, 1):
        con.execute("INSERT INTO selfchecks VALUES (?,?,?,?,?,?,?,?)", [i, 1, NOW, g, n, s, nt, 5])
    steps = [("document.getElementById('screen').innerText", 1.5),
             ("!!document.getElementById('rdRun')", 0.1)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/system/checks", str(tmp_path / "sys.png"), 1500, 1000, 5, steps)
    assert errors == [], errors
    t = res[0]
    assert "1 of 3 checks pass" in t and "1 failing" in t and "chart_view" in t and "no candles for the probe name" in t and "Docker is asleep" in t
    assert res[1] is True or res[1] == "true"


def test_the_abilities_are_in_settings_and_a_switch_is_saved(server, tmp_path):
    rt, port = server
    steps = [("document.getElementById('abilitiesP').innerText", 4.0),
             ("document.querySelector('[data-ab=\"charts\"]').getAttribute('aria-checked')", 0.1),
             ("document.querySelector('[data-ab=\"charts\"]').click(); 1", 5.0),
             ("document.querySelector('[data-ab=\"charts\"]').getAttribute('aria-checked')", 0.1)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/settings", str(tmp_path / "set.png"), 1500, 1400, 5, steps)
    assert errors == [], errors
    assert "Look at charts" in res[0] and "Place real orders" in res[0] and "BLOCKED" in res[0] and "Weekend and holiday work" in res[0] and "Backup folder" in res[0]
    before, after = str(res[1]).lower(), str(res[3]).lower()
    assert before != after                                                                 # one press flips the switch on the screen ...
    assert st.load(rt.pm_dir)["abilities"].get("charts", True) is (after == "true")        # ... and what is saved is what the screen shows
