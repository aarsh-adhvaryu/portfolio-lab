"""S65 Phase 7 item 7: "I'm investing 50k this month" goes to the brain, which calls prepare_plan(amount): the whole path on a synthetic
store (the advisor is a fake; the plan store, the trigger and the tool's report are real)."""
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from pflab.app import research
from pflab.hq import egress, governor as gv, tools as tl
from pflab.hq.desk import Desk
from pflab.plan import ready
from pflab.pm import store

NOW = datetime(2026, 10, 26, 10, 0)
AAA = "INE000A01011"


def fake_advisor(con, asof, amount, with_plan=True):
    buy = SimpleNamespace(isin=AAA, symbol="AAA", qty=int(amount * 0.6 // 100), price=100.0, cost=float(int(amount * 0.6 // 100) * 100),
                          held_value=1000.0, target_value=5000.0)
    adv = SimpleNamespace(buys=[buy], notes=["note from the advisor"], unspent=0.0, skipped=[])
    plan = SimpleNamespace(buys=[SimpleNamespace(isin=AAA, bucket="equity", units=buy.qty, cost=buy.cost)], notes=[])
    return "bucket text", adv, {"AAA": ["BUY 300 AAA at or below 100 (you place it)"]}, plan, {"equity": amount * 0.6, "gold": amount * 0.4}


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path / "pm"))
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                   VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, 'AAA', 'AAA Limited', 'synthetic', now())""", [AAA])
    s = {"brain": "economy", "preset": "full", "telegram_send": False, "drop_watch": True}
    rt = Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None, s, clock=lambda: NOW)
    real_build = ready.build
    monkeypatch.setattr(ready, "build", lambda con, asof, trig, zones, root, fall_fn=None, run=None: real_build(con, asof, trig, zones, root, fall_fn, run=fake_advisor))
    monkeypatch.setattr(ready, "ring", lambda *a, **k: {"shown": False, "why": "stub"})                  # the outer ring needs price history
    monkeypatch.setattr(ready, "sleeve_fall", lambda root, *a, **k: None)
    return tl.Ctx(rt, 1, gv.OPUS, False, {"AAA": AAA}, egress.Gate(), NOW, source="AAA")


def test_the_amount_becomes_a_ready_plan_and_the_tool_says_so(ctx):
    text, err = tl.run(ctx, "prepare_plan", {"amount": 50_000, "why": "he said he is investing 50k this month"})
    assert not err and "carried_out" in text and "plan(s) refreshed, one for Rs 50,000" in json.loads(text)["result"]
    row = ctx.con.execute("SELECT trigger_key, kind, amount, plan_json, status FROM ready_plans WHERE kind='custom'").fetchone()
    assert row[0] == f"custom:{NOW.date()}:50000" and row[2] == 50_000.0 and row[4] == "current"
    plan = json.loads(row[3])
    assert plan["amount"] == 50_000.0 and plan["stocks"][0]["symbol"] == "AAA" and plan["stocks"][0]["tickets"] == ["BUY 300 AAA at or below 100 (you place it)"]
    assert sum(b["rupees"] for b in plan["buckets"]) == pytest.approx(50_000.0)
    assert ctx.decisions[-1]["action"] == "prepare_plan" and ctx.decisions[-1]["subject"] == "Rs 50,000"


def test_asking_again_for_the_same_amount_does_not_pile_up_plans(ctx):
    for _ in range(2):
        tl.run(ctx, "prepare_plan", {"amount": 50_000, "why": "again"})
    assert ctx.con.execute("SELECT count(*) FROM ready_plans WHERE kind='custom'").fetchone()[0] == 1
    tl.run(ctx, "prepare_plan", {"amount": 80_000, "why": "a different amount"})
    cur = ctx.con.execute("SELECT amount FROM ready_plans WHERE kind='custom' AND status='current'").fetchall()
    assert cur == [(80_000.0,)]                                                                          # one re-plan at a time


def test_missing_index_history_leaves_out_the_fall_estimate_but_keeps_the_plan(ctx, monkeypatch):
    monkeypatch.setattr(ready, "sleeve_fall", lambda root, *a, **k: (_ for _ in ()).throw(OSError("no NIFTY500_TRI.parquet")))
    text, err = tl.run(ctx, "prepare_plan", {"amount": 50_000, "why": "he said 50k"})
    assert "plan(s) refreshed" in json.loads(text)["result"] and "FAILED" not in text
    assert ctx.con.execute("SELECT count(*) FROM ready_plans WHERE kind='custom'").fetchone()[0] == 1


def test_a_failure_is_reported_as_one_and_never_as_zero_plans(ctx, monkeypatch):
    monkeypatch.setattr(ready, "build", lambda *a, **k: (_ for _ in ()).throw(OSError("no price history")))
    text, err = tl.run(ctx, "prepare_plan", {"amount": 50_000, "why": "he said 50k"})
    assert "plan refresh FAILED: OSError: no price history" in json.loads(text)["result"]
    assert any("prepare_plan failed" in p for p in ctx.problems)


def test_an_amount_below_the_tools_floor_is_refused_before_anything_runs(ctx):
    text, err = tl.run(ctx, "prepare_plan", {"amount": 50, "why": "too small"})
    assert err and ctx.con.execute("SELECT count(*) FROM ready_plans").fetchone()[0] == 0
