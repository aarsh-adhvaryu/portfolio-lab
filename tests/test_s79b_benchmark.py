"""S79b item 18B: the blended benchmark that follows the system's own allocation, and the monthly attribution of the book's result against it."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from pflab.ledger import events as ev
from pflab.ledger import system
from pflab.paper import allocation, benchmark, book, funds
from pflab.pm import store

AAA, BBB, GLD, SGB = "INE000A01011", "INE000B01012", "INF000G01015", "IN0020200427"
NOW = datetime(2026, 10, 28, 12, 0)
DAYS = [date(2026, 10, 26) + timedelta(days=k) for k in range(0, 45) if (date(2026, 10, 26) + timedelta(days=k)).weekday() < 5]


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    c = store.connect(tmp_path / "l.duckdb")
    for isin, cls, tc, sym, name in ((AAA, "equity", "EQUITY", "AAA", "AAA Ltd"), (BBB, "equity", "EQUITY", "BBB", "BBB Ltd"), (GLD, "etf", "LISTED_NONEQUITY", "GLDBEES", "Goldbees Gold ETF"),
                                     (SGB, "sgb", "SGB", "SGBX", "SGBX 2.5%")):
        c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', ?, ?, TRUE, ?, ?, 'synthetic', now())",
                  [isin, cls, tc, sym, name])
    c.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha')")
    log = ev.EventLog()
    log.append(ev.Event(kind="deposit", account_id="ZER", date=date(2024, 1, 1), amount=1_000_000.0))
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2024, 1, 10), isin=AAA, qty=500, price=80.0))
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2025, 3, 3), isin=BBB, qty=1000, price=40.0))
    ev.save(c, log, NOW)
    for k, d in enumerate(DAYS):
        for isin, px in ((AAA, 100.0 * 1.004 ** k), (BBB, 50.0 * 1.002 ** k), (GLD, 50.0 * 1.001 ** k), (SGB, 14000.0)):
            c.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [isin, d, px])
    system.switch(c, tmp_path, DAYS[2], NOW)
    return c


def levels(through=date(2026, 12, 31)):
    idx = pd.date_range("2026-10-01", "2026-12-31", freq="D")
    mk = lambda g: pd.Series([1000.0 * g ** n for n in range(len(idx))], index=idx)
    return {"equity": mk(1.003), "gold": mk(1.001), "international": mk(1.002), "cash_rate": lambda d: 0.07,
            "through": {"equity": through, "gold": through, "international": through}, "labels": benchmark.LABELS}


def approve(con, weights, at, reasons="x" * 60):
    t = allocation.propose_allocation(con, weights, reasons, at)
    allocation.review_target(con, t["target_id"], "approve", "ok", at)
    return t["target_id"]


def run_book(con, upto=DAYS[-1]):
    book.seed(con, DAYS[2], NOW)
    book.catch_up(con, upto, datetime.combine(upto, datetime.min.time()) + timedelta(hours=21))


def test_before_any_target_the_benchmark_is_the_kite_seed_weights_and_says_so(con):
    run_book(con, DAYS[6])
    out = benchmark.update(con, "IN", DAYS[6], NOW, levels())
    assert out["source"] == "kite_seed" and out["added"] == 5
    first = con.execute("SELECT level, weights_json FROM blended_benchmark_s79 ORDER BY as_of LIMIT 1").fetchone()
    w = json.loads(first[1])
    assert first[0] == 100.0 and w["source"] == "kite_seed" and sum(w["start"].values()) == pytest.approx(1.0)
    assert w["start"]["equity"] > 0.1 and w["start"]["cash"] > 0.7 and w["start"]["international"] == 0.0     # the seed lots are equities, the rest is the fake cash
    assert benchmark.update(con, "IN", DAYS[6], NOW, levels())["added"] == 0                                    # idempotent: nothing stored twice


def test_the_benchmark_takes_the_active_targets_weights_the_session_after_activation_and_reweights_on_change(con):
    run_book(con)
    t1 = approve(con, {"equity": 60, "gold": 20, "international": 10, "cash": 10}, datetime(2026, 11, 5, 15, 0))
    t2 = approve(con, {"equity": 40, "gold": 30, "international": 10, "cash": 20}, datetime(2026, 11, 19, 15, 0))
    benchmark.update(con, "IN", DAYS[-1], NOW, levels())
    rows = {r[0]: (json.loads(r[1]), r[2], r[3]) for r in con.execute("SELECT as_of, weights_json, level, target_id FROM blended_benchmark_s79 ORDER BY as_of").fetchall()}
    assert rows[date(2026, 11, 5)][0]["source"] == "kite_seed"                                    # the target was activated that afternoon: not yet in force
    w6 = rows[date(2026, 11, 6)][0]
    assert w6["source"] == f"target #{t1}" and w6["start"] == pytest.approx({"equity": 0.6, "gold": 0.2, "international": 0.1, "cash": 0.1})
    w9 = rows[date(2026, 11, 9)][0]
    assert w9["start"]["equity"] != pytest.approx(0.6) and w9["start"]["equity"] > 0.6 or w9["start"]["gold"] < 0.2    # it drifts with the markets between targets
    w20 = rows[date(2026, 11, 20)][0]
    assert w20["source"] == f"target #{t2}" and w20["start"] == pytest.approx({"equity": 0.4, "gold": 0.3, "international": 0.1, "cash": 0.2})
    # the level is the chain of the blended class returns (checked by hand for one day under target 1)
    lv = levels()
    rc = benchmark.class_returns(lv, date(2026, 11, 6), date(2026, 11, 9))
    expect = rows[date(2026, 11, 6)][1] * (1 + sum(w * rc[c] for c, w in rows[date(2026, 11, 9)][0]["start"].items()))
    assert rows[date(2026, 11, 9)][1] == pytest.approx(expect)


def _busy_book(con):
    book.seed(con, DAYS[2], NOW)
    approve(con, {"equity": 60, "gold": 20, "international": 10, "cash": 10}, datetime(2026, 11, 5, 15, 0))
    book.place(con, datetime(2026, 11, 3, 10, 0), None, GLD, "buy", amount=100_000.0)
    book.place(con, datetime(2026, 11, 17, 10, 0), None, GLD, "sell", qty=1000)
    funds.topup(con, 40_000, "the investor", date(2026, 11, 12), NOW)
    book.place(con, datetime(2026, 11, 13, 10, 0), None, BBB, "buy", amount=30_000.0)
    book.catch_up(con, DAYS[-1], datetime(2026, 12, 18, 21, 0))


def test_the_attribution_parts_add_up_to_the_excess_with_the_residual_shown(con):
    _busy_book(con)
    out = benchmark.refresh(con, "IN", DAYS[-1], NOW, levels())
    assert out["months"] >= 2
    rows = benchmark.attribute(con, "IN", NOW)["months"]
    assert [r["month"] for r in rows][:3] == ["2026-10-01", "2026-11-01", "2026-12-01"]
    for r in rows:
        parts = r["allocation"] + r["selection"] + r["timing"] + r["costs"] + r["tax"]
        assert parts + r["residual"] == pytest.approx(r["excess"], abs=1e-12)                       # exact: the residual is what is left, shown
        assert r["excess"] == pytest.approx(r["book_return"] - r["bench_return"], abs=1e-12)
        assert abs(r["residual"]) < 0.002                                                          # and small: the daily split is nearly the monthly one
    nov = rows[1]
    assert nov["costs"] < 0 and nov["tax"] <= 0                                                    # charges on four fills; the gold ETF sold inside a year is taxed at the slab (estimate)
    assert nov["partial"] is False and rows[-1]["partial"] is True
    tax_paid = con.execute("SELECT coalesce(sum(tax), 0) FROM paper_trades").fetchone()[0]
    assert tax_paid > 0 and nov["tax"] < 0


def test_a_top_up_is_outside_money_in_the_book_return_and_in_the_attribution(con):
    book.seed(con, DAYS[2], NOW)
    funds.topup(con, 40_000, "the investor", date(2026, 11, 12), NOW)
    book.catch_up(con, DAYS[-1], datetime(2026, 12, 18, 21, 0))
    benchmark.refresh(con, "IN", DAYS[-1], NOW, levels())
    rows = benchmark.attribute(con, "IN", NOW)["months"]
    twr = book.returns(con)["twr"]
    compounded = 1.0
    for r in rows:
        compounded *= 1 + r["book_return"]
    assert compounded - 1 == pytest.approx(twr, abs=1e-9)                                           # the same time-weighted result as the book's own: the Rs 40,000 is not a gain
    s = benchmark.status(con, "IN")
    assert s["book"]["return"] == pytest.approx(twr, abs=1e-9) and s["started"] is True and "labels" in s["benchmark"]


def test_cash_earns_nothing_in_the_book_so_a_cash_heavy_book_falls_behind_a_cash_benchmark_by_selection(con):
    book.seed(con, DAYS[2], NOW)
    book.catch_up(con, DAYS[-1], datetime(2026, 12, 18, 21, 0))
    benchmark.refresh(con, "IN", DAYS[-1], NOW, levels())
    rows = benchmark.attribute(con, "IN", NOW)["months"]
    by = rows[1]["detail"]["by_class"]["cash"]
    assert by["selection"] < 0 and by["avg_book_weight"] > 0.3                                       # the fake broker pays no interest; the cash benchmark does


def test_the_switch_off_makes_it_behave_as_not_there(con, monkeypatch):
    run_book(con, DAYS[6])
    monkeypatch.setattr(benchmark, "settings", lambda table="benchmark": {**benchmark.DEFAULTS, "on": False})
    assert benchmark.update(con, "IN", DAYS[6], NOW, levels()) == {"off": True}
    assert benchmark.attribute(con, "IN", NOW) == {"off": True} and benchmark.status(con, "IN") == {"off": True}
    assert con.execute("SELECT count(*) FROM blended_benchmark_s79").fetchone()[0] == 0


def test_stale_class_data_is_flagged_and_the_status_names_its_source_and_labels_tax_as_an_estimate(con):
    """(S82: the paper team's `dossier_text` had no caller and was deleted; what it read, `status`, is what is tested.)"""
    run_book(con)
    benchmark.refresh(con, "IN", DAYS[-1], NOW, levels(through=date(2026, 11, 2)))
    s = benchmark.status(con, "IN")
    assert set(s["stale_classes"]) == {"equity", "gold", "international"}
    assert "kite_seed" in s["benchmark"]["source"] and any("tax is an estimate" in n for n in s["notes"]) and s["latest_month"] is not None


def test_the_tool_the_job_and_the_world_panel_read_the_same_record(con, monkeypatch):
    from types import SimpleNamespace
    from pflab.app import world
    from pflab.hq import tools  # noqa: F401  (loads the tool registry first)
    from pflab.hq.tools_s79 import t_benchmark
    from pflab.service import jobs, tasks_s79_benchmark  # noqa: F401
    _busy_book(con)
    benchmark.refresh(con, "IN", DAYS[-1], NOW, levels())
    ctx = SimpleNamespace(con=con, now=datetime.combine(DAYS[-1], datetime.min.time()) + timedelta(hours=21))
    out = t_benchmark.benchmark(ctx, {})
    assert out["started"] and out["monthly"] and set(out["monthly"][-1]) >= {"month", "allocation", "selection", "timing", "costs", "tax", "residual", "excess"}
    assert "verification" in out and out["benchmark"]["labels"]["equity"].startswith("Nifty 500")
    panel = world._benchmark_panel(con, ctx.now)
    assert panel["available"] and panel["excess"] == pytest.approx(out["excess"]) and panel["month"]["month"] == out["latest_month"]["month"]
    job = jobs.REGISTRY["benchmark_attr"]
    assert job.redo_fn(SimpleNamespace(con=con)) is None                                         # the benchmark is up to date with the book
    con.execute("INSERT INTO paper_days VALUES (?, 1000000, 500000, 500000, 0, '{}')", [DAYS[-1] + timedelta(days=3)])
    assert "benchmark runs to" in job.redo_fn(SimpleNamespace(con=con))
    monkeypatch.setattr(benchmark, "settings", lambda table="benchmark": {**benchmark.DEFAULTS, "on": False})
    assert t_benchmark.benchmark(ctx, {}) == {"off": True} and job.enabled_fn(None)[0] is False

