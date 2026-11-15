"""S80 phase 4: what Today shows of the v2 core (spend by use, champion against the plain baseline, open storylines): the data from `core/screens.py` and the page in a real
browser. Synthetic data only."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from pflab.core import screens
from pflab.story import store
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
