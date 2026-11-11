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
    for want in ("allocation_proposed_and_adopted", "core_etfs_bought", "exit_plan_fires", "harvest_sale_and_buyback", "view_entry_exit_closed", "thesis_break_sale", "us_subbook_close", "session_replay"):
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
