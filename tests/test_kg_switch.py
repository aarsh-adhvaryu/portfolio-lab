"""2026-11-08: the knowledge graph deleted and OFF until its design is agreed (kg/switch.py, configs/kg.toml, tools/kg_delete.py)."""
from __future__ import annotations

import importlib.util
from datetime import datetime, date
from pathlib import Path

import pytest

from pflab.kg import clean, graph as g, hypotheses, switch
from pflab.pm import store

NOW = datetime(2026, 11, 8, 15, 0)
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "pm" / "ledger.duckdb")


def n(con, t):
    return con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]


def test_the_shipped_config_keeps_the_graph_off(monkeypatch):
    monkeypatch.delenv("PFLAB_KG", raising=False)
    assert switch.on() is False                                   # configs/kg.toml: on = false
    monkeypatch.setenv("PFLAB_KG", "on")
    assert switch.on() is True


def test_off_nothing_writes_the_graph_but_documents_are_kept(con, monkeypatch):
    monkeypatch.setenv("PFLAB_KG", "off")
    g.node(con, "org:exsoft", "org", "Exsoft", now=NOW)
    assert g.edge(con, "doc:x", "about", "company:INE000X01011", NOW, "test", now=NOW) is False
    assert g.close(con, "person:investor", "watches", "company:INE000X01011", NOW) == 0
    did = g.doc(con, "filing", "k1", NOW, "a filing", now=NOW)
    assert did.startswith("doc:filing:") and n(con, "kg_docs") == 1
    assert n(con, "kg_nodes") == 0 and n(con, "kg_edges") == 0
    assert "skipped" in clean.run(con, NOW)                       # no name merging and no name question
    assert n(con, "questions") == 0
    with pytest.raises(RuntimeError, match="switched off"):
        hypotheses.record(con, None, "AAA", "a cause", "an effect", [], date(2026, 11, 20), None, NOW)


def _tool():
    spec = importlib.util.spec_from_file_location("kg_delete", REPO / "tools" / "kg_delete.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_delete_tool_previews_then_empties_the_graph_keeps_documents_and_backs_up_first(tmp_path, monkeypatch, capsys):
    pm = tmp_path / "pm"
    c = store.connect(pm / "ledger.duckdb")
    g.node(c, "company:INE000X01011", "company", "Exsoft", now=NOW)
    d = g.doc(c, "article", "a1", NOW, "story", now=NOW)
    g.edge(c, d, "mentions", "company:INE000X01011", NOW, "gdelt_gkg", now=NOW)
    from pflab.agents import questions as qs
    qs.ask(c, "knowledge graph", "kg-same:org:x=>company:INE000X01011", "Is x the same as Exsoft?", NOW)
    c.close()
    tool = _tool()
    assert tool.main(["--pm", str(pm)]) == 0                      # preview changes nothing
    c = store.connect(pm / "ledger.duckdb")
    assert n(c, "kg_nodes") == 2 and n(c, "kg_edges") == 1
    c.close()
    assert tool.main(["--pm", str(pm), "--apply"]) == 0
    assert list((tmp_path / "backups").glob("ledger-*-before-kg-delete.duckdb"))
    c = store.connect(pm / "ledger.duckdb")
    assert n(c, "kg_nodes") == 0 and n(c, "kg_edges") == 0 and n(c, "kg_aliases") == 0 and n(c, "kg_hypotheses") == 0
    assert n(c, "kg_docs") == 1                                   # the documents are kept
    assert c.execute("SELECT count(*) FROM questions WHERE status='open' AND subject_key LIKE 'kg-same:%'").fetchone()[0] == 0
    assert "DELETED" in capsys.readouterr().out
