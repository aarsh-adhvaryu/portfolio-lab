"""S68: shares Kite shows and the statements do not yet get a provisional tax figure labelled 'estimate, from Kite' instead of a failure. Synthetic ledger, fake Kite."""
from __future__ import annotations

import pytest

from pflab.pm import today
from pflab.tax import kite_estimate as ke
from tests.test_s58b_today import AAA, BBB, FakeKite, NOW, ledger


@pytest.fixture
def con(tmp_path):
    return ledger(tmp_path)


def test_a_new_allotment_kite_shows_gets_a_labelled_provisional_figure(con):
    today.record(con, FakeKite(), "ZER", NOW)                       # BBB: 20 in Kite, 0 in the ledger, average 45, price 50
    est = {e["isin"]: e for e in ke.estimates(con, NOW.date(), rate=0.20)}
    assert set(est) == {BBB}                                         # AAA is fewer in Kite than the ledger: a sale, not a new holding
    e = est[BBB]
    assert e["label"] == "estimate, from Kite" and e["quantity"] == 20 and e["average_price"] == pytest.approx(45.0)
    assert e["unrealised_gain"] == pytest.approx(100.0) and e["tax_if_sold_now"] == pytest.approx(20.0)
    assert e["not_a_lot"] is True and "short-term" in e["assumes"][0] and "statement" in e["replaced_by"]
    assert "ESTIMATE" in ke.lines([e])[0] and "estimate, from Kite" in ke.lines([e])[0]
    assert con.execute("SELECT count(*) FROM events WHERE isin=?", [BBB]).fetchone()[0] == 0     # never written to the record


def test_a_loss_gives_no_tax_and_no_kite_view_gives_no_estimate(con):
    assert ke.estimates(con, NOW.date()) == []                       # no Kite snapshot: nothing to estimate
    today.record(con, FakeKite(), "ZER", NOW)
    con.execute("UPDATE prices SET close=40.0 WHERE isin=?", [BBB])
    e = ke.estimates(con, NOW.date(), rate=0.20)[0]
    assert e["unrealised_gain"] == pytest.approx(-100.0) and e["tax_if_sold_now"] == 0.0


def test_statements_newer_than_kites_view_replace_the_estimate(con):
    from datetime import datetime
    today.record(con, FakeKite(), "ZER", datetime(2026, 9, 30, 15, 0))        # Kite's view is older than the statements (they run to 1 Oct)
    assert ke.estimates(con, NOW.date(), rate=0.20) == []                     # the ledger speaks: no estimate


def test_the_tax_plan_tool_carries_the_estimate(con, tmp_path):
    from pflab.hq import egress, tools as tl
    from pflab.hq.desk import Desk
    today.record(con, FakeKite(), "ZER", NOW)
    d = Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None, {}, clock=lambda: NOW)
    ctx = tl.Ctx(d, 1, "m", False, {}, egress.Gate(), NOW)
    out = tl.tax_plan(ctx, {})
    assert out["kite_estimates"][0]["symbol"] == "BBB" and "ESTIMATE, from Kite" in out["kite_estimate_note"]
