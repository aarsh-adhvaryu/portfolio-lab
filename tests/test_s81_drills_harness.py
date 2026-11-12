"""S81: the building blocks of tools/drills_s81.py, fast and fake (no profile, no child process). The drills themselves run from the tool: `python tools/drills_s81.py run`."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def D():
    spec = importlib.util.spec_from_file_location("drills_s81_under_test", REPO / "tools" / "drills_s81.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["drills_s81_under_test"] = m
    spec.loader.exec_module(m)
    return m


def test_the_day_steps_reach_all_four_modes_and_the_default_start_is_a_thursday(D):
    from pflab import markets
    m = markets.get("IN")
    assert D.DEFAULT_START.weekday() == 3 and m.is_session(D.DEFAULT_START)
    assert {m.mode(t) for t in D.day_times(D.DEFAULT_START)} >= set(markets.MODES)
    sat = D.DEFAULT_START + timedelta(days=2)
    assert len(D.day_times(sat)) == 2 and all(t.date() == sat for t in D.day_times(sat))
    ten = D.DEFAULT_START
    for _ in range(9):
        ten = m.next_session(ten)
    assert ten == date(2026, 10, 29)                                         # ten sessions: a weekend and the Tuesday 20 Oct holiday inside


def test_data_arrives_after_the_slot_not_at_the_close(D):
    assert D.available_through(datetime(2026, 10, 16, 16, 0)) == date(2026, 10, 15)
    assert D.available_through(datetime(2026, 10, 16, 20, 30)) == date(2026, 10, 16)
    assert D.available_through(datetime(2026, 10, 18, 9, 0)) == date(2026, 10, 16)        # Sunday: Friday's closes


def test_a_check_is_pass_fail_or_off_with_the_reason_and_findings_carry_where_and_how(D):
    c = D.Check("x")
    c.ok(True, "fine")
    assert c.result(time.time())["status"] == "PASS"
    c.ok(False, "broken", "core/loop.py")
    r = c.result(time.time())
    assert r["status"] == "FAIL" and r["findings"][0]["where"] == "core/loop.py" and "run --only x" in r["findings"][0]["how"]
    o = D.Check("y")
    o.off("waiting for module pflab.core.exits")
    r = o.result(time.time())
    assert r["status"] == "OFF" and r["evidence"] == ["OFF: waiting for module pflab.core.exits"]


def test_a_step_that_waits_for_a_module_says_exactly_which(D):
    ok, why = D.needs("pflab.core.rails")()
    assert ok and why == ""
    ok, why = D.needs("pflab.core.rails", "pflab.no_such_module", why="B9 something")()
    assert not ok and "pflab.no_such_module" in why and "B9 something" in why
    names = [n for n, _fn, _ap in D.ACCELERATED_STEPS]
    assert names[0] == "standing" and len(names) == len(set(names))
    for want in ("allocation_proposed_and_adopted", "core_etfs_bought", "exit_plan_fires", "harvest_sale_and_buyback", "view_entry_exit_closed", "thesis_break_sale", "us_subbook_close", "session_replay",
                 "picks_learning_book", "thinking_loop"):
        assert want in names
    for _n, _fn, ap in D.ACCELERATED_STEPS:
        ok, why = ap(None)
        assert ok or why.startswith("waiting for")


def test_the_synthetic_prices_are_deterministic_and_the_data_files_hold_nothing_from_the_future(D, tmp_path, monkeypatch):
    import pandas as pd
    from pflab.pm import store
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    a_b, a_a = D.synth_prices(D.DEFAULT_START)
    b_b, b_a = D.synth_prices(D.DEFAULT_START)
    assert a_b == b_b and a_a == b_a and all(r[1] < D.DEFAULT_START for r in a_b) and all(r[1] >= D.DEFAULT_START for r in a_a)
    con = store.connect(tmp_path / "l.duckdb")
    for s in D.STOCKS:
        con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, ?, ?, ?, 's', now())", [s[1], s[0], s[0], s[2]])
    for e in D.ETFS:
        con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'etf', ?, TRUE, ?, ?, 's', now())", [e[1], e[5], e[0], e[2]])
    for i, d, px, series, src in a_b:
        con.execute("INSERT INTO prices VALUES (?,?,?,?,?, now())", [i, d, px, series, src])
    data = tmp_path / "data"
    D.sync_data_files(con, data)
    last = a_b[-1][1]
    for f in ("indices/NIFTY50_PRICE", "indices/NIFTY500_TRI", "global/US_SP500", "panel/prices"):
        df = pd.read_parquet(data / f"{f}.parquet")
        assert pd.to_datetime(df["date"]).max().date() <= last
    panel = pd.read_parquet(data / "panel" / "prices.parquet")
    assert set(panel["instrument_type"]) == {"STK", "ETF"} and {"NIFTYBEES", "GOLDBEES", "JUNIORBEES"} <= set(panel["symbol"])
    # S84 (drillfix): the real panel carries the day's open/high/low and the lab's replay reads them (`build_panel(extras=True)`); the drills' panel lacked them, so every drill's strategist
    # job logged `allocation: BinderException: Referenced column "open" not found`
    assert {"open", "high", "low"} <= set(panel.columns) and bool((panel["low"] < panel["close"]).all() and (panel["high"] > panel["close"]).all())
    from pflab.lab import runner
    monkeypatch.setattr(runner, "_sector", lambda k: None)                      # the sector map and the results map are real data files the drills do not carry
    monkeypatch.setattr(runner, "build_results", lambda *a, **k: {})
    built = runner.build_panel(data, n_names=20, start=date(2000, 1, 1), end=date(2100, 1, 1), extras=True)
    assert set(built["ohlc"]) == {"open", "high", "low"} and not built["ohlc"]["open"].dropna(how="all").empty


def test_the_fake_local_model_answers_the_storyline_readers_schema_validly(D):
    from pflab.story import reader, store
    sch = reader.schema()
    stories = "OPEN STORIES:\n- #7 (down): foreign selling\n\nSIGNAL MENU (for a new story):\n" + "\n".join(f"- {k}: x" for k in sorted(store.TEMPLATES)) + "\n\nNEW FACT"
    out = json.loads(D.fake_chat_text({"format": sch, "messages": [{"role": "user", "content": stories}]}))
    assert out["action"] == "attach" and out["storyline_id"] == 7 and out["strength"] in store.STRENGTH
    none = stories.replace("- #7 (down): foreign selling", "(none open)")
    out = json.loads(D.fake_chat_text({"format": sch, "messages": [{"role": "user", "content": none}]}))
    assert out["action"] == "new" and out["templates"] and out["direction"] in (-1, 1)


def test_the_counting_client_counts_a_paid_request_and_the_network_is_down(D):
    import requests
    cl = D.CountingClient()
    with pytest.raises(RuntimeError):
        cl.beta.messages.create(model="x")
    assert cl.created == 1
    net = D.Net().install()
    try:
        with pytest.raises(requests.exceptions.ConnectionError):
            requests.get("https://example.com/x", timeout=1)
        assert net.blocked and "example.com" in net.blocked[0]
    finally:
        net.uninstall()


# --- S83: the picks step (20 sessions, a scripted strategist) ------------------------------------------------------------------------------------------------

def test_the_picks_step_needs_twenty_sessions_and_is_off_in_a_shorter_run_and_the_accelerated_alias_runs_both_drills(D):
    from types import SimpleNamespace
    assert D.step_picks.sessions == D.PICKS_SESSIONS == 20 and D.step_picks.ticks
    assert D.ALIASES["accelerated"] == ["accelerated", "accelerated_picks"] and "accelerated_picks" in D.DRILLS and "accelerated_long" not in D.ALIASES["accelerated"]
    assert len(D._picks_days(SimpleNamespace(start=D.DEFAULT_START))) == 20


def test_the_scripted_model_answers_turn_by_turn_then_done_and_a_failing_one_raises_and_is_not_counted(D):
    counter = {}
    m = D.ScriptedModel([[("write_note", {"text": "x"})]], counter)
    one = m.beta.messages.create(messages=[{"content": [{"text": "hello"}]}])
    assert one.stop_reason == "tool_use" and one.content[0].name == "write_note" and m.first == "hello"
    two = m.beta.messages.create(messages=[{"content": [{"text": "hello"}]}])
    assert two.stop_reason == "end_turn" and two.content[0].text == "Done." and counter["answers"] == 2
    bad = D.ScriptedModel([], counter, fail="the API is down")
    with pytest.raises(RuntimeError):
        bad.beta.messages.create(messages=[{"content": [{"text": "hello"}]}])
    assert counter["answers"] == 2 and m.messages.count_tokens().input_tokens > 0


def test_the_pick_names_are_in_the_profile_and_the_benchmark_does_not_move_for_them(D, tmp_path, monkeypatch):
    import pandas as pd
    from pflab.pm import store
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    b_rows, _a = D.synth_prices(D.DEFAULT_START)
    assert {s[1] for s in D.PICK_STOCKS} <= {r[0] for r in b_rows} and len({s[1] for s in D.PICK_STOCKS} & {s[1] for s in D.STOCKS}) == 0 and all(len(s[1]) == 12 for s in D.PICK_STOCKS)
    con = store.connect(tmp_path / "l.duckdb")
    for s in D.STOCKS + D.PICK_STOCKS:
        con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, ?, ?, ?, 's', now())", [s[1], s[0], s[0], s[2]])
    for e in D.ETFS:
        con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'etf', ?, TRUE, ?, ?, 's', now())", [e[1], e[5], e[0], e[2]])
    for i, d, px, series, src in b_rows:
        con.execute("INSERT INTO prices VALUES (?,?,?,?,?, now())", [i, d, px, series, src])
    D.sync_data_files(con, tmp_path / "data")
    full = pd.read_parquet(tmp_path / "data" / "indices" / "NIFTY500_TRI.parquet")
    con.execute("DELETE FROM prices WHERE isin IN (%s)" % ",".join("?" for _ in D.PICK_STOCKS), [s[1] for s in D.PICK_STOCKS])
    D.sync_data_files(con, tmp_path / "data2")
    plain = pd.read_parquet(tmp_path / "data2" / "indices" / "NIFTY500_TRI.parquet")
    assert full["close"].round(9).tolist() == plain["close"].round(9).tolist()                    # the pick names do not move the benchmark: the other drills' numbers are as they were
    panel = pd.read_parquet(tmp_path / "data" / "panel" / "prices.parquet")
    thin = panel[panel["isin"] == D.PICK_STOCKS[2][1]]["turnover"].unique().tolist()
    assert thin == [1.0e7] and set(panel[panel["isin"] == D.PICK_STOCKS[0][1]]["turnover"]) == {8e7}
    us = pd.read_parquet(tmp_path / "data" / "us" / "raw" / f"{D.US_PICKS[0][0]}.parquet")
    assert (us["close"] > 5).all() and (us["close"] * us["volume"]).median() > 2e6
