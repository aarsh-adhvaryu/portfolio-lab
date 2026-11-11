"""S55 ready plans: the next money (always the next FD tranche; the monthly amount asked once), a plan per trigger with
price ranges and reasons, versions kept only when the plan changes (with what changed), a held message when the money is
a week away, one re-plan at a time, and the outer ring as an idea with its numbers."""
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from pflab.agents import questions as qs
from pflab.calc import networth
from pflab.plan import advisor, deploy, guards, ready
from pflab.plan import rebalance
from pflab.pm import store

ASOF = date(2026, 10, 23)
NOW = datetime(2026, 10, 23, 21, 30)
LIST = [{"symbol": "AAA", "isin": "INE000A01001"}, {"symbol": "BBB", "isin": "INE000B01001"},
        {"symbol": "CCC", "isin": "INE000C01001"}]


@pytest.fixture
def con(tmp_path, monkeypatch):
    c = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(ready, "_meta", lambda: {"deploy_months": 10})
    monkeypatch.setattr(guards, "stock_list", lambda: LIST)
    pos = pd.DataFrame({"isin": ["INE000A01001"], "bucket": ["equity"], "value": [50_000.0]})
    monkeypatch.setattr(networth, "build", lambda con, asof: {"positions": pos})
    monkeypatch.setattr(ready, "_zone", lambda con, root, isin, asof: {})
    return c


def tranches(*months):
    return [deploy.Tranche(m, 100_000.0, date(2027, 1, 30), n) for n, m in enumerate(months, start=1)]


def fake_run(qty_a=10, qty_b=20):
    def run(con, asof, amount, with_plan=False):
        buys = [advisor.StockBuy("AAA", "INE000A01001", 30_000, 1000.0, qty_a, qty_a * 1000.0, 50_000, 80_000),
                advisor.StockBuy("BBB", "INE000B01001", 20_000, 1000.0, qty_b, qty_b * 1000.0, 0, 80_000)]
        adv = advisor.Advice(asof, amount, buys, unspent=500.0, skipped=["CCC (fail)"])
        plan = SimpleNamespace(buys=[rebalance.BuyLine("gold", "INF000G01001", 10_000, 100.0, 10_000.0, 0.0, False)],
                               notes=["an FD note"])
        return "bucket plan text", adv, {"AAA": ["limit 1,000"], "BBB": ["limit 1,000"]}, plan, \
            {"equity": 50_000.0, "gold": 10_000.0, "debt": 0.0}
    return run


def test_the_next_tranche_is_always_planned_and_the_monthly_amount_asked_once(con, monkeypatch):
    monkeypatch.setattr(deploy, "schedule", lambda fds, months, asof: tranches(date(2027, 2, 1), date(2027, 3, 1)))
    t = ready.triggers(con, ASOF, now=NOW)
    assert [x.due for x in t] == [date(2027, 2, 1)]                     # far off, still planned; the second waits
    assert "tranche 1 of 10" in t[0].source and t[0].estimate
    assert qs.open_questions(con)[0][2].startswith("How much will you add each month")
    ready.triggers(con, ASOF, now=NOW)
    assert len(qs.open_questions(con)) == 1                              # asked once
    monkeypatch.setattr(deploy, "schedule", lambda fds, months, asof: tranches(date(2026, 11, 1), date(2026, 12, 1)))
    assert len(ready.triggers(con, ASOF, now=NOW)) == 2                  # both within reach
    qid = qs.open_questions(con)[0][0]
    qs.answer(con, qid, "25,000 a month from January")
    t = ready.triggers(con, ASOF, now=NOW)
    m = [x for x in t if x.kind == "monthly"]
    assert len(m) == 1 and m[0].amount == 25_000 and m[0].due == date(2027, 1, 1)   # from January
    monkeypatch.setattr(ready, "_meta", lambda: {"deploy_months": 10, "monthly_amount": 0})
    assert all(x.kind == "fd_tranche" for x in ready.triggers(con, ASOF, now=NOW))


def test_a_plan_has_ranges_reasons_and_the_ring(con):
    zones = {"INE000A01001": {"bottom": 900.0, "top": 980.0, "price": 1000.0, "verdict": "ABOVE ZONE"},
             "INE000B01001": {"bottom": 950.0, "top": 1010.0, "price": 1000.0, "verdict": "IN ZONE"}}
    trig = ready.Trigger("fd:x:1", "fd_tranche", date(2027, 2, 1), 60_500.0, "tranche 1 of 10", True)
    p = ready.build(con, ASOF, trig, zones, None, fall_fn=lambda v: {"text": f"{len(v)} names"}, run=fake_run())
    a = p["stocks"][0]
    assert a["range"] == {"low": 900.0, "high": 980.0, "price": 1000.0} and a["verdict"] == "ABOVE ZONE"
    assert a["why"].startswith("holds 62% of its share") and a["tickets"] == ["limit 1,000"]
    assert p["how"][0]["range"] is None and p["buckets"][0] == {"bucket": "equity", "rupees": 50_000.0}
    r = p["ring"]                                                        # AAA held; BBB not; CCC failed the guards
    assert r["possible"] and [b["symbol"] for b in r["buys"]] == ["BBB"] and r["buys"][0]["qty"] == 30
    assert r["plan"]["names"] == 2 and r["ring"]["names"] == 2
    assert r["ring"]["largest"] == pytest.approx(50_000 / 80_000) and r["plan"]["largest"] == pytest.approx(60_000 / 80_000)
    assert r["plan"]["fall"] == {"text": "2 names"}


def test_versions_are_kept_only_when_the_plan_changes(con, monkeypatch):
    monkeypatch.setattr(deploy, "schedule", lambda fds, months, asof: tranches(date(2026, 10, 28)))
    p1 = ready.refresh(con, ASOF, None, NOW, {}, run=fake_run())
    assert p1[0]["changes"] == ["first version"]
    assert con.execute("SELECT count(*) FROM outbox WHERE kind='ready_plan'").fetchone()[0] == 1   # 5 days away: held
    ready.refresh(con, ASOF, None, NOW, {}, run=fake_run())
    assert con.execute("SELECT count(*) FROM ready_plans").fetchone()[0] == 1
    p3 = ready.refresh(con, ASOF, None, NOW, {}, run=fake_run(qty_b=25))
    assert p3[0]["changes"] == ["BBB: 20 -> 25 shares"]
    assert con.execute("SELECT status, count(*) FROM ready_plans GROUP BY 1 ORDER BY 1").fetchall() == \
        [("current", 1), ("superseded", 1)]
    assert con.execute("SELECT count(*) FROM outbox WHERE kind='ready_plan'").fetchone()[0] == 1   # not sent twice
    ready.refresh(con, ASOF, None, NOW, {}, ready.custom(40_000, ASOF), run=fake_run())
    ready.refresh(con, ASOF, None, NOW, {}, ready.custom(70_000, ASOF), run=fake_run())
    cur = ready.current(con)
    assert [p["kind"] for p in cur].count("custom") == 1 and any(p["amount"] == 70_000 for p in cur)
    monkeypatch.setattr(deploy, "schedule", lambda fds, months, asof: [])
    ready.refresh(con, ASOF, None, NOW, {}, run=fake_run())
    assert all(p["kind"] == "custom" for p in ready.current(con))       # the tranche went by: no longer current


def test_no_ring_without_names_to_start(con, monkeypatch):
    monkeypatch.setattr(guards, "stock_list", lambda: LIST[:1])
    adv = fake_run()(con, ASOF, 1.0, True)[1]
    r = ready.ring(con, ASOF, adv, {})
    assert r["shown"] and not r["possible"] and "new names on your list" in r["why"]


def test_the_zone_verdict_does_not_order_the_ring(con, monkeypatch):
    """A60 (the buy-zone test failed, S54c): a name 'IN ZONE' is not picked ahead of the others; picks go in the order of the list."""
    names = [("AAA", "A"), ("BBB", "B"), ("CCC", "C"), ("DDD", "D"), ("EEE", "E")]
    monkeypatch.setattr(guards, "stock_list", lambda: [{"symbol": s, "isin": f"INE000{k}01001"} for s, k in names])
    adv = fake_run()(con, ASOF, 1.0, True)[1]
    adv.skipped = []
    zones = {f"INE000{k}01001": {"bottom": 900.0, "top": 980.0, "price": 1000.0, "verdict": "IN ZONE" if s == "EEE" else "ABOVE ZONE"}
             for s, k in names}
    r = ready.ring(con, ASOF, adv, zones)
    assert [b["symbol"] for b in r["buys"]] == ["BBB", "CCC", "DDD"]
