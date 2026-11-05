"""S79 item 5, never idle: the agenda (picker, yield, runner, snapshot, the `agenda` tool, the World panel). Synthetic; the local model is replaced by a function."""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import types
from datetime import datetime, timedelta

import pytest

from pflab.agenda import items, kinds, picker, runner
from pflab.pm import store

NOW = datetime(2026, 11, 5, 21, 0)


def _connect(path):
    """The store with the base schema (up to 60) and this item's migration (65) only, so another item's migration in flight cannot break these tests."""
    import duckdb
    con = duckdb.connect(str(path))
    store.migrate(con, [m for m in store.MIGRATIONS if m[0] <= 60 or m[0] == 65])
    return con


@pytest.fixture
def rt(tmp_path):
    from pflab.app import runtime
    (tmp_path / "pm").mkdir()
    con = _connect(tmp_path / "l.duckdb")
    yield runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


@pytest.fixture(autouse=True)
def _clean_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path / "nodata"))           # fill_data_gap must never see the workshop's real data folder
    saved, last = dict(kinds.REGISTRY), dict(runner._LAST_REFILL)
    kinds.REGISTRY.clear()
    runner._LAST_REFILL.clear()
    yield
    kinds.REGISTRY.clear()
    kinds.REGISTRY.update(saved)
    runner._LAST_REFILL.clear()
    runner._LAST_REFILL.update(last)


def _ok(rt, item, now):
    return {"useful": True, "effect": "belief: something changed", "outcome": "done"}


def _nothing(rt, item, now):
    return {"useful": False, "effect": "", "outcome": "nothing new"}


def _add(con, kind, subject, ev=1.0, rup=0.0, sec=10.0, market="IN", when=NOW):
    return items.add(con, market, kind, subject, f"why {subject}", ev, rup, sec, when)


def _acts(con, kind, n, useful, market="IN"):
    """n finished acts of a kind, `useful` or not (a synthetic history)."""
    for i in range(n):
        iid = _add(con, kind, f"h{kind}{useful}{i}{n}", when=NOW - timedelta(days=5))
        items.start(con, iid, NOW)
        items.finish(con, iid, NOW + timedelta(seconds=i), "o", useful, "belief: x" if useful else "")
    items.refresh_stats(con, market, kind, NOW)


# --- the picker -----------------------------------------------------------------------------------------------------------------------

def test_picker_orders_by_value_over_cost(rt):
    con = rt.cursor()
    a = _add(con, "k", "cheap_small", ev=2.0, sec=5)          # 2 / (0.05+...)
    b = _add(con, "k", "dear_big", ev=3.0, sec=300)           # 3 / 3.0
    c = _add(con, "k", "cheap_big", ev=6.0, sec=10)           # 6 / 0.1
    ok, _ = picker.candidates(con, "IN", "deep", NOW)
    assert [i["item_id"] for i in ok] == [c, a, b]
    assert picker.next_item(con, "IN", "deep", NOW)["item_id"] == c


def test_a_low_yield_kind_loses_priority_but_keeps_a_floor(rt):
    con = rt.cursor()
    _acts(con, "dull", 40, False)
    _acts(con, "keen", 40, True)
    assert items.multiplier(con, "IN", "dull") == items.FLOOR > 0
    assert items.multiplier(con, "IN", "keen") == items.CEIL
    _add(con, "dull", "d", ev=4.0)
    _add(con, "keen", "k", ev=4.0)
    assert picker.next_item(con, "IN", "deep", NOW)["kind"] == "keen"
    # the floor keeps it in play: a much more valuable dull item still wins
    _add(con, "dull", "big", ev=80.0)
    assert picker.next_item(con, "IN", "deep", NOW)["subject"] == "big"


def test_under_ten_acts_the_multiplier_is_neutral(rt):
    con = rt.cursor()
    _acts(con, "few", 9, False)
    assert items.multiplier(con, "IN", "few") == 1.0
    _acts(con, "few", 1, False)
    assert items.multiplier(con, "IN", "few") == items.FLOOR


def test_session_mode_holds_back_costly_items_deep_mode_does_not(rt):
    con = rt.cursor()
    cheap = _add(con, "k", "cheap", ev=1.0, sec=5)
    mid = _add(con, "k", "mid", ev=50.0, sec=60)
    slow = _add(con, "k", "slow", ev=50.0, sec=300)

    def ids(mode, which=0):
        return {i["item_id"] for i in picker.candidates(con, "IN", mode, NOW, mark=False)[which]}
    assert ids("session") == {cheap} and ids("session", 1) == {mid, slow}      # while the market trades: only short free items
    assert ids("post_close") == {cheap, mid} and ids("pre_open") == {cheap, mid}   # evening: up to two minutes
    assert ids("deep") == {cheap, mid, slow}


def test_an_item_over_budget_is_skipped_with_its_reason_and_a_stale_one_is_dropped(rt):
    con = rt.cursor()
    dear = _add(con, "k", "dear", ev=9.0, rup=1e7)
    old = _add(con, "k", "old", ev=9.0, when=NOW - timedelta(days=5))
    free = _add(con, "k", "free", ev=1.0)
    assert picker.next_item(con, "IN", "deep", NOW)["item_id"] == free
    assert items.get(con, dear)["state"] == "skipped" and items.get(con, dear)["skip_reason"]
    assert "stale" in items.get(con, old)["skip_reason"]


def test_urgent_work_preempts_the_agenda(rt):
    con = rt.cursor()
    kinds.register("k", lambda c, m, n: [], _ok)
    _add(con, "k", "a", ev=5.0)
    assert picker.urgent_pending(con) is False
    con.execute("INSERT INTO hq_tasks (task_id, created_at, from_agent, to_agent, text, status, hops) VALUES (1, ?, 'investor', 'calc', 'do it', 'queued', 0)", [NOW])
    assert picker.urgent_pending(con) is True
    r = runner.work_one(rt, NOW, "deep")
    assert r["state"] == "urgent" and items.counts(con).get("queued") == 1
    con.execute("UPDATE hq_tasks SET status='done'")
    assert runner.work_one(rt, NOW, "deep")["state"] == "done"


# --- the runner -----------------------------------------------------------------------------------------------------------------------

def test_an_exception_is_recorded_as_failed_and_never_raised(rt):
    con = rt.cursor()

    def boom(rt, item, now):
        raise RuntimeError("the source is down")
    kinds.register("boom", lambda c, m, n: [], boom)
    iid = _add(con, "boom", "x", ev=5.0)
    r = runner.work_one(rt, NOW, "deep")
    assert r["state"] == "failed" and "the source is down" in r["error"]
    row = items.get(con, iid)
    assert row["state"] == "failed" and "the source is down" in row["outcome"] and row["useful"] is False


def test_an_unregistered_kind_fails_without_stopping_the_loop(rt):
    con = rt.cursor()
    iid = _add(con, "ghost", "x")
    assert runner.work_one(rt, NOW, "deep")["state"] == "failed"
    assert items.get(con, iid)["state"] == "failed"


def test_useful_acts_feed_the_kind_stats_and_the_cadence(rt):
    con = rt.cursor()
    kinds.register("good", lambda c, m, n: [], _ok)
    kinds.register("dud", lambda c, m, n: [], _nothing)
    _add(con, "good", "g", ev=9.0)
    _add(con, "dud", "d", ev=1.0)
    r1, r2 = runner.work_one(rt, NOW, "deep"), runner.work_one(rt, NOW, "deep")
    assert (r1["kind"], r1["useful"]) == ("good", True) and (r2["kind"], r2["useful"]) == ("dud", False)
    st = {k["kind"]: k for k in items.kind_stats(con)}
    assert st["good"]["n_done"] == 1 and st["good"]["n_useful"] == 1 and st["dud"]["n_useful"] == 0
    acts = con.execute("SELECT what, useful FROM paper_acts WHERE loop='agenda' ORDER BY act_id").fetchall()
    assert len(acts) == 2 and acts[0][1] is True and acts[1][1] is False


def test_useful_must_name_what_changed(rt):
    con = rt.cursor()
    kinds.register("vague", lambda c, m, n: [], lambda rt, it, now: {"useful": True, "effect": "it felt good", "outcome": "ok"})
    iid = _add(con, "vague", "v")
    r = runner.work_one(rt, NOW, "deep")
    assert r["useful"] is False and items.get(con, iid)["useful"] is False


def test_a_worker_can_skip_with_a_reason(rt):
    con = rt.cursor()
    kinds.register("sk", lambda c, m, n: [], lambda rt, it, now: {"skip": "nothing to read"})
    iid = _add(con, "sk", "s")
    assert runner.work_one(rt, NOW, "deep")["state"] == "skipped"
    assert items.get(con, iid)["skip_reason"] == "nothing to read"


def test_refill_dedupes_by_kind_subject_and_day(rt):
    con = rt.cursor()
    kinds.register("c", lambda c, m, n: [{"subject": "same", "reason": "r", "expected_value": 1.0}, {"subject": "same", "reason": "r", "expected_value": 1.0}], _ok)
    assert runner.refill(con, "IN", NOW) == {"c": 1}
    assert runner.refill(con, "IN", NOW) == {"c": 0}                        # queued already
    runner.work_one(rt, NOW, "deep")
    assert runner.refill(con, "IN", NOW + timedelta(hours=1)) == {"c": 0}   # done today
    assert runner.refill(con, "IN", NOW + timedelta(days=1)) == {"c": 1}    # a new day
    assert items.add(con, "US", "c", "same", "r", 1.0, 0, 1, NOW)           # another market is its own


def test_a_producer_that_raises_adds_nothing_and_does_not_stop_the_rest(rt):
    con = rt.cursor()
    kinds.register("bad", lambda c, m, n: 1 / 0, _ok)
    kinds.register("fine", lambda c, m, n: [{"subject": "s", "expected_value": 1.0}], _ok)
    assert runner.refill(con, "IN", NOW) == {"bad": 0, "fine": 1}


def test_tick_refills_then_works_one_item(rt):
    con = rt.cursor()
    kinds.register("c", lambda c, m, n: [{"subject": "t", "reason": "r", "expected_value": 2.0}] if m == "IN" else [], _ok)
    r = runner.tick(rt, NOW, mode="deep")
    assert r["state"] == "done" and r["kind"] == "c" and r["refilled"]["IN"] == 1
    assert runner.tick(rt, NOW, mode="deep")["state"] == "idle"             # nothing new; the producer asked again only after REFILL_EVERY


def test_an_interrupted_running_item_is_failed_on_the_next_look(rt):
    con = rt.cursor()
    iid = _add(con, "k", "x")
    items.start(con, iid, NOW - timedelta(hours=2))
    kinds.register("k", lambda c, m, n: [], _ok)
    runner.work_one(rt, NOW, "deep")
    assert items.get(con, iid)["state"] == "failed" and "interrupted" in items.get(con, iid)["outcome"]


# --- the kinds that exist -------------------------------------------------------------------------------------------------------------

def test_recheck_thesis_notices_new_evidence(rt):
    from pflab.agents import thesis
    con = rt.cursor()
    kinds._install()
    tid = thesis.add(con, "AI capex is a bubble", ["bubble"], [], now=NOW - timedelta(days=3))
    r = runner.tick(rt, NOW, mode="deep")
    assert r["kind"] == "recheck_thesis" and r["state"] == "done" and r["useful"] is False        # no matching document yet: nothing new
    con.execute("INSERT INTO kg_docs (doc_id, kind, url, title, source, published_at, ingested_at) VALUES ('d1','article','u','Is the AI bubble bursting?','wire',?,?)", [NOW - timedelta(hours=3), NOW])
    later = NOW + timedelta(days=1)
    r = runner.tick(rt, later, mode="deep")
    assert r["state"] == "done" and r["useful"] is True and r["effect"].startswith("belief") and f"#{tid}" in r["effect"]


def test_read_flagged_filing_needs_a_quote_from_the_filing(rt, tmp_path, monkeypatch):
    con = rt.cursor()
    kinds._install()
    p = tmp_path / "f.txt"
    p.write_text("The board approved the acquisition of a competitor for cash, subject to regulatory approval next quarter.", encoding="utf-8")
    con.execute("INSERT INTO kg_docs (doc_id, kind, url, title, source, published_at, attrs_json, text_path, text_status, ingested_at) VALUES ('doc1','filing','u','Acquisition','bse',?,'{}',?,'ok',?)", [NOW - timedelta(hours=5), str(p), NOW])
    con.execute("INSERT INTO research_flags VALUES (1,'INE001A01010','ABC','material_filing',?,?,'doc1','acquisition: Acquisition')", [NOW - timedelta(hours=5), NOW - timedelta(hours=4)])
    good = {"material": "yes", "what_changed": "It will buy a competitor.", "quote": "The board approved the acquisition of a competitor for cash"}
    monkeypatch.setattr(kinds, "local_json", lambda *a, **k: good)
    r = runner.tick(rt, NOW, mode="deep")
    assert r["kind"] == "read_flagged_filing" and r["useful"] is True and r["effect"].startswith("belief")
    assert con.execute("SELECT count(*) FROM memory WHERE source='agenda'").fetchone()[0] == 1
    # a made-up quote: the reading is thrown away, nothing is kept
    con.execute("INSERT INTO kg_docs (doc_id, kind, url, title, source, published_at, attrs_json, text_path, text_status, ingested_at) VALUES ('doc2','filing','u','Other','bse',?,'{}',?,'ok',?)", [NOW - timedelta(hours=5), str(p), NOW])
    con.execute("INSERT INTO research_flags VALUES (2,'INE001A01010','ABC','material_filing',?,?,'doc2','other')", [NOW - timedelta(hours=5), NOW - timedelta(hours=4)])
    monkeypatch.setattr(kinds, "local_json", lambda *a, **k: {**good, "quote": "the company will triple its profit next year for sure"})
    runner._LAST_REFILL.clear()
    r = runner.tick(rt, NOW + timedelta(minutes=20), mode="deep")
    assert r["useful"] is False and con.execute("SELECT count(*) FROM memory WHERE source='agenda'").fetchone()[0] == 1


def test_explain_move_is_a_plugin_that_may_be_absent(rt, monkeypatch):
    con = rt.cursor()
    kinds._install()
    with monkeypatch.context() as m:
        m.setitem(sys.modules, "pflab.hq.explain", None)                     # an import of it raises ImportError: the plugin is absent
        assert kinds._moves_to_explain(con, "IN", NOW) == []
    con.execute("INSERT INTO research_flags VALUES (7,'INE001A01010','ABC','fall',?,?,'r','fell 6% on the day')", [NOW - timedelta(hours=5), NOW - timedelta(hours=4)])
    mod = types.ModuleType("pflab.hq.explain")
    seen = {}

    def explain_move(rt, symbol, day, extra_ignored=None):
        seen.update(symbol=symbol, day=day)
        return {"explanation": "results missed"}
    mod.explain_move = explain_move
    monkeypatch.setitem(sys.modules, "pflab.hq.explain", mod)
    r = runner.tick(rt, NOW, mode="deep")
    assert r["kind"] == "explain_move" and r["useful"] is True and seen["symbol"] == "ABC"


def test_fill_data_gap_uses_the_backfill_step(rt, tmp_path, monkeypatch):
    kinds._install()
    (tmp_path / "data" / "bhavcopy").mkdir(parents=True)
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(kinds, "backfill", lambda root, now, budget: {"fetched": 3, "left": 10, "errors": 0})
    r = runner.tick(rt, NOW, mode="deep")
    assert r["kind"] == "fill_data_gap" and r["useful"] is True and "3 missing" in r["effect"]


def test_draft_learner_claim_reads_a_screened_source_locally(rt, monkeypatch):
    from pflab.learner import claims
    con = rt.cursor()
    kinds._install()
    con.execute("INSERT INTO learn_sources (src_id, found_at, origin, ref, title, status) VALUES (1, ?, 'drop', 'r1', 'A paper', 'screened')", [NOW])
    monkeypatch.setattr("pflab.learner.sources.fetch_text", lambda con, sid, d, **k: "text")
    monkeypatch.setattr(claims, "local_draft", lambda *a, **k: None)
    monkeypatch.setattr(claims, "read", lambda con, drafts, sid, text, now: [11, 12])
    r = runner.tick(rt, NOW, mode="deep")
    assert r["kind"] == "draft_learner_claim" and r["useful"] is True and "2 claim" in r["effect"]


# --- what the screen and the agents see ------------------------------------------------------------------------------------------------

def test_snapshot_shape(rt):
    con = rt.cursor()
    kinds.register("ok", lambda c, m, n: [], _ok)
    kinds.register("sk", lambda c, m, n: [], lambda rt, it, now: {"skip": "not now"})
    _add(con, "ok", "a", ev=3.0)
    runner.work_one(rt, NOW, "deep")
    _add(con, "sk", "b", ev=9.0)
    runner.work_one(rt, NOW, "deep")
    _add(con, "ok", "c", ev=2.0)
    _add(con, "ok", "slow", ev=2.0, sec=500)
    run = _add(con, "ok", "now", ev=1.0)
    items.start(con, run, NOW)
    s = runner.snapshot(con, NOW)
    assert s["available"] is True and s["running"]["subject"] == "now"
    assert s["recent_done"][0]["effect"].startswith("belief") and s["recent_skipped"][0]["skip_reason"] == "not now"
    assert s["queue"][0]["subject"] == "c" and "reason" in s["queue"][0] and "expected_value" in s["queue"][0]
    assert {"kind_yields", "counts", "mode", "urgent", "held", "useful_today"} <= set(s)
    assert s["useful_today"] == 1


def test_snapshot_before_the_migration_does_not_raise():
    import duckdb
    assert runner.snapshot(duckdb.connect(":memory:"), NOW)["available"] is False


def test_the_agenda_tool_works_with_no_arguments(rt):
    from pflab.hq import tools
    from pflab.hq.tools import Ctx
    assert "agenda" in tools.TOOLS and tools.TOOLS["agenda"].kind == "read"
    t = tools.TOOLS["agenda"]
    assert tools.validate(t, {}) is None
    ctx = Ctx(rt=rt, pass_id=None, model="m", shadow=True, syms={}, gate=None, now=NOW)
    out = t.fn(ctx, {})
    assert out["available"] is True and "queue" in out and "recent_done" in out
    assert t.fn(ctx, {"market": "us"})["market_filter"] == "US"


def test_the_world_build_carries_the_agenda(rt):
    from pflab.app import world
    kinds.register("k", lambda c, m, n: [], _ok)
    _add(rt.cursor(), "k", "shown", ev=2.0)
    d = world.build(rt, NOW)
    assert d["agenda"]["available"] is True and d["agenda"]["queue"][0]["subject"] == "shown"
    assert "agenda" not in d["errors"]


# --- the World panel in a real browser ----------------------------------------------------------------------------------------------------

def test_the_world_panel_shows_what_it_is_doing_and_what_it_skipped(tmp_path, monkeypatch):
    pytest.importorskip("websockets")
    from tests import _edge
    if not os.path.exists(_edge.EDGE):
        pytest.skip("Microsoft Edge is not installed here")
    import urllib.request
    import uvicorn
    from pflab.app import runtime
    from pflab.app.server import create_app
    (tmp_path / "pm").mkdir()
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    con = _connect(tmp_path / "l.duckdb")
    t0 = NOW - timedelta(minutes=300)
    con.execute("INSERT INTO job_runs (run_id, job, slot, started_at, finished_at, status) VALUES (1,'collect',?,?,?,'ok')", [t0, t0, t0 + timedelta(seconds=20)])
    r = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)
    cur = r.cursor()
    done = _add(cur, "recheck_thesis", "thesis:3", ev=4.0)
    items.start(cur, done, NOW)
    items.finish(cur, done, NOW, "evidence moved", True, "belief: thesis #3 now has 4 matching document(s)")
    sk = _add(cur, "fill_data_gap", "bhavcopy:2026-11-03", ev=3.0)
    items.skip(cur, sk, NOW, "the workshop does not send outward")
    nxt = _add(cur, "read_flagged_filing", "flag:9", ev=5.0)
    run = _add(cur, "explain_move", "move:ABC", ev=6.0)
    items.start(cur, run, NOW)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = uvicorn.Server(uvicorn.Config(create_app(r), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    try:
        steps = [("document.getElementById('wagenda').innerText", 0.3)]
        errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/world", str(tmp_path / "w.png"), 1500, 1000, 4, steps)
    finally:
        srv.should_exit = True
        th.join(5)
    assert errors == [], errors
    txt = res[0]
    assert "explain move" in txt and "move:ABC" in txt                         # what it is doing now
    assert "thesis #3 now has 4 matching document(s)" in txt                    # a useful act, with what changed
    assert "the workshop does not send outward" in txt                          # what it skipped, and why
    assert "read flagged filing" in txt                                         # the next in line
