"""S81 B6: the exit manager acts inside the close loop before the rebalance, on the S80 core fixture. Synthetic."""
from __future__ import annotations

from datetime import datetime

from pflab.core import exits, loop, policy
from pflab.paper import book
from tests.test_s80_core import AAA, BBB, DAYS, NOW, calm_index, con  # noqa: F401  (the fixture and helpers)


def test_a_stop_hit_is_an_exit_order_with_its_reason_and_the_rebalance_does_not_trade_the_same_name(con):
    day = DAYS[-1]
    exits.backfill_plans(con, day, "IN", NOW)
    px = book.close_on(con, AAA, day)[1]
    con.execute("UPDATE exit_plans_s81 SET stop=? WHERE isin=? AND status='open'", [px * 1.5, AAA])         # the close is far below the stop: it fires
    r = loop.run(con, NOW, None, calm_index())
    assert r.get("status") == "traded", r
    sells = [o for o in r["orders"] if o["symbol"] == "AAA" and o["side"] == "sell"]
    assert len(sells) == 1                                                                                    # one order for AAA, not two
    d = con.execute("SELECT reason FROM paper_decisions WHERE symbol='AAA' ORDER BY decision_id DESC LIMIT 1").fetchone()[0]
    assert d.startswith("exit manager (stop)") and "stop" in d
    assert con.execute("SELECT count(*) FROM exit_events_s81 WHERE kind='stop' AND isin=?", [AAA]).fetchone()[0] == 1


def test_a_failing_exit_manager_leaves_the_policys_orders_standing(con, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("exit manager broke")
    monkeypatch.setattr(exits, "check_close", boom)
    r = loop.run(con, NOW, None, calm_index())
    assert r.get("status") in ("traded", "held")
    assert con.execute("SELECT count(*) FROM paper_acts WHERE loop='core_loop' AND useful=FALSE").fetchone()[0] >= 1
