"""S80 phase 4: what Today shows of the v2 core (spend by use, champion against the plain baseline, open storylines): the data from `core/screens.py` and the page in a real
browser. Synthetic data only."""
from __future__ import annotations

import os
from datetime import date, datetime

import pytest

from pflab.core import screens
from pflab.story import store
from tests import _edge
from tests.test_s68_ui import NOW, server  # noqa: F401  (the fixture)

NOWT = datetime(2026, 11, 9, 16, 0)


def _story(con):
    r = store.open_storyline(con, NOWT, "Foreign money is rotating out of AI-heavy Asia into India, which should lift the Nifty", 1, date(2026, 11, 5), ["fii_buying_strong"])
    assert r["ok"]
    return r["storyline_id"]


def test_the_view_has_spend_policies_and_storylines_and_names_a_part_it_cannot_read(server):
    rt, _port = server
    con = rt.cursor()
    sid = _story(con)
    v = screens.view(con, NOWT)
    assert v["left_out"] == [] or all("(" in x for x in v["left_out"])
    assert v["spend"]["month"]["total"] == 0 and v["spend"]["lab_runs"] == 0
    assert v["policies"]["champion"] in (None, "baseline_v1") and v["policies"]["challengers"] == []
    s = v["storylines"][0]
    assert s["id"] == sid and s["direction"] == "up" and 0 < s["probability"] < 1 and s["pending"] == 0 and s["scored"] == 0


@pytest.mark.ui
@pytest.mark.skipif(not os.path.exists(_edge.EDGE), reason="Microsoft Edge is not installed here")
def test_today_shows_the_policy_the_storyline_and_the_spend_without_scrolling(server, tmp_path):
    rt, port = server
    con = rt.cursor()
    con.execute("INSERT INTO paper_cash VALUES (1, ?, 500000, 'seed', 'fake starting cash', now())", [date(2026, 10, 30)])
    con.execute("INSERT INTO paper_days VALUES (?, 500000, 500000, 0, 0, '{}')", [date(2026, 10, 30)])
    con.execute("INSERT INTO paper_days VALUES (?, 506000, 500000, 0, 0, '{}')", [date(2026, 10, 31)])
    _story(con)
    steps = [("document.getElementById('screen').innerText", 2.0), ("document.documentElement.scrollHeight <= window.innerHeight + 4", 0.1)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/today", str(tmp_path / "core.png"), 1500, 1000, 5, steps)
    assert errors == [], errors
    t = res[0].lower()
    assert "the policy that trades" in t and "what is driving the market" in t and "what the strategist costs" in t and "foreign money is rotating" in t
    assert res[1] is True or res[1] == "true"
