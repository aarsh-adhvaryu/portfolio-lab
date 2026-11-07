"""S79 phase 2: the building blocks of tools/drills_s79.py, fast and fake (no profile, no real process). The heavy drills (kill -9, off 10 days, the accelerated run) run from the tool."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from pflab.pm import store

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def D():
    spec = importlib.util.spec_from_file_location("drills_s79_under_test", REPO / "tools" / "drills_s79.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["drills_s79_under_test"] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def net(D):
    n = D.Net().install()
    yield n
    n.ollama_back()
    n.uninstall()


def test_clock_and_day_steps_reach_all_four_modes(D):
    from pflab import markets
    m = markets.get("IN")
    thu = date(2026, 10, 8)
    modes = {m.mode(t) for t in D.day_times(thu)}
    assert modes >= set(markets.MODES)
    sat = date(2026, 10, 10)
    assert all(t.date() == sat for t in D.day_times(sat)) and len(D.day_times(sat)) == 2        # a closed day: two steps, all "deep"
    clk = D.FakeClock(datetime(2026, 10, 8, 6))
    assert clk() == datetime(2026, 10, 8, 6) and clk.set(datetime(2026, 10, 9)) == datetime(2026, 10, 9) and clk() == datetime(2026, 10, 9)


def test_data_arrives_after_the_slot_not_at_the_close(D):
    assert D.available_through(datetime(2026, 10, 9, 16, 0)) == date(2026, 10, 8)        # Friday after the close, files not in yet
    assert D.available_through(datetime(2026, 10, 9, 20, 30)) == date(2026, 10, 9)
    assert D.available_through(datetime(2026, 10, 11, 9, 0)) == date(2026, 10, 9)        # Sunday: Friday's closes
    assert D.available_through(datetime(2026, 10, 12, 9, 0)) == date(2026, 10, 9)        # Monday morning: still Friday


def test_the_network_is_down_and_ollama_is_fake(D, net):
    import requests
    from pflab.llm import client
    with pytest.raises(requests.exceptions.ConnectionError):
        requests.get("https://example.com/x", timeout=1)
    assert net.blocked and "example.com" in net.blocked[0]
    r = client.chat("qwen3:8b-q8_0", [{"role": "user", "content": "hello"}])
    assert r.text and net.chat_calls == 1
    net.ollama_down()
    with pytest.raises(client.OllamaError, match="not reachable"):
        client.chat("qwen3:8b-q8_0", [{"role": "user", "content": "hello"}])
    net.ollama_back()
    assert client.chat("qwen3:8b-q8_0", [{"role": "user", "content": "hello"}]).text


def test_the_fake_model_satisfies_a_schema_and_the_debate_protocol(D, net, tmp_path):
    import json as _json
    from pflab.agents import debate as db
    from pflab.llm import client
    out = client.chat("qwen3:8b-q8_0", [{"role": "system", "content": "s"}, {"role": "user", "content": "Title line of a filing\nbody"}],
                      fmt={"type": "object", "properties": {"material": {"type": "string", "enum": ["yes", "no"]}, "quote": {"type": "string"}}, "required": ["material", "quote"]})
    obj = _json.loads(out.text)
    assert obj["material"] == "yes" and obj["quote"] == "Title line of a filing"
    con = duckdb.connect(str(tmp_path / "l.duckdb"))
    store.migrate(con)
    rt = SimpleNamespace(cursor=lambda: con.cursor(), data_root=tmp_path, con=con)
    ev = {"calc.ret_20d": ("return over the last 20 sessions, %", 8.4), "calc.rsi14": ("14-session RSI", 72.1), "calc.below_high": ("% below the 252-session high", -3.2)}
    res = db.debate(rt, "IN", "ABC", ev, datetime(2026, 10, 9, 17, 0))
    assert res["status"] == "done" and res["disagreements"], res


def test_a_question_sent_then_defaulted_on_the_fake_clock(D):
    from pflab.agents import questions, voice
    con = duckdb.connect(":memory:")
    store.migrate(con)
    clk = D.FakeClock(datetime(2026, 10, 8, 11))
    q = questions.ask(con, "paper", "drill:k", "Keep the gold ETF?", clk(), default="keep", deadline=datetime(2026, 10, 12, 10), options=["keep", "trim"])
    assert con.execute("SELECT count(*) FROM outbox WHERE kind='question'").fetchone()[0] == 1
    assert voice.effective(con, "drill:k") == ("keep", "pending-default")
    voice.sweep(con, clk.set(datetime(2026, 10, 12, 11)))
    assert voice.effective(con, "drill:k") == ("keep", "default")
    assert con.execute("SELECT status FROM questions WHERE q_id=?", [q]).fetchone()[0] == "defaulted"


def test_items_that_are_switched_off_are_listed_as_off(D, monkeypatch):
    monkeypatch.setattr(D, "switches", lambda: {"sentiment": {"on": False}, "waves": {"on": True}})
    assert D.item_state("sentiment", ["sentiment_now"], [])["state"] == "OFF"
    assert D.item_state("macro_attribution", [], [])["state"] in ("ABSENT", "PRESENT")
    assert D.item_state("sentiment", [], [])["tools"] == []


def test_check_records_findings_and_the_report_is_written(D, tmp_path):
    c = D.Check("demo")
    assert c.ok(True, "fine") and not c.ok(False, "broken thing", "pflab/x.py", "run it")
    r = c.result(0.0)
    assert r["status"] == "FAIL" and r["findings"][0]["where"] == "pflab/x.py"
    a = SimpleNamespace(out=str(tmp_path / "r.json"), findings=str(tmp_path / "f.md"))
    D.report([r], a)
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["results"][0]["name"] == "demo"
    assert "### D1. [demo] broken thing" in (tmp_path / "f.md").read_text(encoding="utf-8")


def test_every_registered_drill_has_a_budget_and_the_names_the_brief_asks_for(D):
    want = {"kill9", "off_fri_mon", "off_10_days", "net_down", "ollama_down", "docker_down", "kite_logged_out", "budget_exhausted", "accelerated"}
    assert want <= set(D.DRILLS)
    assert all(getattr(f, "minutes", 0) > 0 for f in D.DRILLS.values())
