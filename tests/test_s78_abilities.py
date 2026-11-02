"""S78: what the AI may see and use is a real switch, enforced where each thing is used (tools, live quotes, the chat front), not a label. Synthetic data only."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from pflab.app import front, settings as st
from pflab.hq import egress, tools as tl
from pflab.hq.desk import Desk
from pflab.paper import book
from pflab.pm import store

NOW = datetime(2026, 11, 2, 11, 0)


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "a.duckdb")
    c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES ('INE000A01011', 'isin', 'equity', 'EQUITY', TRUE, 'AAA', 'AAA Ltd', 's', now())")
    return c


def test_only_known_abilities_and_only_true_or_false_are_saved(tmp_path):
    out = st.save(tmp_path, {"abilities": {"charts": False, "web": "no", "nonsense": True, "kite_live": True}})
    assert out["abilities"] == {"charts": False, "kite_live": True}
    again = st.save(tmp_path, {"abilities": {"web": False}}, out)
    assert again["abilities"] == {"charts": False, "kite_live": True, "web": False}                          # merged, not replaced
    assert st.ability("charts", current=again) is False and st.ability("calculations", current=again) is True        # missing = on
    assert json.loads(st.path(tmp_path).read_text(encoding="utf-8"))["abilities"]["web"] is False


def test_a_tool_whose_ability_is_off_is_refused_for_every_agent_and_works_when_on(con, tmp_path):
    (tmp_path / "pm" / "app").mkdir(parents=True)
    rt = Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None, {"abilities": {"charts": False, "web": False}}, clock=lambda: NOW)
    ctx = tl.Ctx(rt, None, "m", False, {}, egress.Gate(), NOW, role="research", allowed=frozenset(tl.TOOLS))
    text, err = tl.run(ctx, "chart_view", {"symbol": "AAA"})
    assert err and "switched off in Settings" in text and "charts" in text
    t2, e2 = tl.run(ctx, "web_search", {"question": "What did the company announce today?"})
    assert e2 and "switched off in Settings" in t2
    rt.settings["abilities"]["charts"] = True
    t3, e3 = tl.run(ctx, "chart_view", {"symbol": "AAA"})
    assert "switched off" not in t3                                                                           # now it runs (and may say there are no candles: that is its own answer)


def test_with_kite_live_off_no_fill_and_no_watch_uses_a_live_quote(con, tmp_path, monkeypatch):
    con.execute("INSERT INTO live_quotes VALUES ('INE000A01011', ?, 100.0, 'kite')", [datetime(2026, 11, 2, 10, 58)])
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    assert book.live_prices(con, NOW, ["INE000A01011"]) == {"INE000A01011": 100.0}
    st.save(tmp_path, {"abilities": {"kite_live": False}})
    assert book.live_prices(con, NOW, ["INE000A01011"]) == {}


def test_local_first_off_sends_the_chat_to_the_cloud_agent(monkeypatch, tmp_path):
    import importlib
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    real = importlib.reload(front)                                                        # (the suite's fixture replaces front.enabled; this is the real function)
    assert real.enabled() is True
    st.save(tmp_path, {"abilities": {"local_first": False}})
    assert real.enabled() is False
