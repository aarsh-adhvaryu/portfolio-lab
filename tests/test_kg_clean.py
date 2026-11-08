"""S57 knowledge-graph cleanup: exact name matches merge (into the company when it is one), unsure ones are asked
once and his answer holds, syndicated copies point at the original, older analyst notes end, nothing is deleted."""
from datetime import datetime

import pandas as pd
import pytest

from pflab.agents import memory as mem
from pflab.agents import questions as qs
from pflab.kg import build as kb
from pflab.kg import clean
from pflab.kg import graph as g
from pflab.pm import store

NOW = datetime(2026, 10, 23, 23, 15)
CO = "company:INE000X01011"


@pytest.mark.parametrize("name,key", [
    ("Indian Oil Corp", "indian oil"), ("indian oil corporation ltd", "indian oil"), ("Nifty Private Bank", "nifty private bank"),
    ("company example industries", "example industries"), ("Foo Private Limited", "foo"),
    ("The Example Power Co. Ltd.", "example power"), ("Larsen & Toubro Limited", "larsen and toubro"), ("Co", "co")])
def test_name_key(name, key):
    assert clean.name_key(name) == key


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, symbol, name, source, built_at) VALUES "
              "('INE000X01011', 'isin', 'equity', 'equity', 'EXSOFT', 'Exsoft Systems Limited', 'test', ?)", [NOW])
    g.node(c, CO, "company", "Exsoft Systems", now=NOW)
    for i, (day, orgs) in enumerate((("2026-10-01", ["exsoft systems ltd", "indian oil corp", "nifty bank"]),
                                     ("2026-10-02", ["company exsoft systems", "indian oil corporation ltd", "nifty private bank",
                                                     "exsoft systems group"]),
                                     ("2026-10-03", ["indian oil corp", "indian oil corporation ltd"]))):
        d = g.doc(c, "article", f"a{i}", day, f"story number {i} about the market today", now=NOW)
        g.edge(c, d, "mentions", CO, day, "gdelt_gkg", now=NOW)
        for o in orgs:
            g.node(c, f"org:{o}", "org", o, now=NOW)
            g.edge(c, d, "names", f"org:{o}", day, "gdelt_gkg", now=NOW)
    return c


def nodes(con, kind):
    return sorted(r[0] for r in con.execute("SELECT node_id FROM kg_nodes WHERE kind=?", [kind]).fetchall())


def test_exact_names_merge_and_unsure_ones_are_asked(con):
    out = clean.run(con, NOW)
    assert out["names_merged"] == 4 and out["into_companies"] == 2 and out["asked"] == 1
    assert nodes(con, "org") == ["org:exsoft systems group", "org:indian oil", "org:nifty bank", "org:nifty private bank"]
    # the doc that named both spellings of Indian Oil now has one edge to it
    d2 = g.doc(con, "article", "a2", "2026-10-03")
    assert con.execute("SELECT count(*) FROM kg_edges WHERE src=? AND dst='org:indian oil'", [d2]).fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM kg_edges WHERE dst=? AND rel='names'", [CO]).fetchone()[0] == 2
    assert clean.canonical(con, "org:exsoft systems ltd") == CO and clean.canonical(con, "org:nifty bank") == "org:nifty bank"
    q = qs.open_questions(con)
    assert len(q) == 1 and '"exsoft systems group"' in q[0][2]
    assert clean.run(con, NOW)["asked"] == 0                            # asked once
    qs.answer(con, q[0][0], "no")
    clean.run(con, NOW)
    assert "org:exsoft systems group" in nodes(con, "org") and clean.canonical(con, "org:exsoft systems group") == "org:exsoft systems group"


def test_a_company_international_or_global_arm_is_kept_apart_without_asking(con):
    # 2026-11-08: he was asked whether "tata power international" was Tata Power; it is a separate (subsidiary) entity, so the system never asks
    d = g.doc(con, "article", "a9", "2026-10-04", "story number 9 about the market today", now=NOW)
    for o in ("exsoft systems international", "exsoft systems global"):
        g.node(con, f"org:{o}", "org", o, now=NOW)
        g.edge(con, d, "names", f"org:{o}", "2026-10-04", "gdelt_gkg", now=NOW)
    out = clean.run(con, NOW)
    assert out["asked"] == 1                                            # only "exsoft systems group", as before
    text = " ".join(r[2] for r in qs.open_questions(con))
    assert "international" not in text and "global" not in text
    assert "org:exsoft systems international" in nodes(con, "org") and "org:exsoft systems global" in nodes(con, "org")
    assert clean.canonical(con, "org:exsoft systems international") == "org:exsoft systems international"


def test_his_yes_merges(con):
    clean.run(con, NOW)
    qs.answer(con, qs.open_questions(con)[0][0], "yes")
    assert clean.run(con, NOW)["names_merged"] == 1
    assert "org:exsoft systems group" not in nodes(con, "org") and clean.canonical(con, "org:exsoft systems group") == CO


def test_a_merged_name_stays_merged_when_news_names_it_again(con):
    clean.run(con, NOW)
    gkg = pd.DataFrame([{"date": datetime(2026, 10, 4), "url": "https://x/4", "title": "Exsoft Systems wins a large deal",
                         "source": "x", "tone": 0.0, "isins": "", "themes": "", "orgs": "Exsoft Systems Ltd;Indian Oil Corp",
                         "persons": "", "india": True, "quotes": ""}])
    kb.articles(con, gkg, now=NOW)
    assert "org:exsoft systems ltd" not in nodes(con, "org") and "org:indian oil corp" not in nodes(con, "org")


def test_syndicated_copies_point_at_the_original(con):
    for k, day in (("x1", "2026-10-05 09:00"), ("x2", "2026-10-05 11:00"), ("x3", "2026-10-06 09:00")):
        g.doc(con, "article", k, day, "Exsoft Systems raises its revenue guidance for the year", now=NOW)
    assert clean.copies(con) == 1
    first = g.doc(con, "article", "x1", "2026-10-05 09:00")
    assert con.execute("SELECT dup_of FROM kg_docs WHERE doc_id=?", [g.doc(con, "article", "x2", "2026-10-05")]).fetchone()[0] == first
    assert con.execute("SELECT dup_of FROM kg_docs WHERE doc_id=?", [g.doc(con, "article", "x3", "2026-10-06")]).fetchone()[0] is None
    assert clean.copies(con) == 0


def test_older_analyst_notes_end_and_new_ones_replace(con):
    ids = [mem.remember(con, "note", f"Analyst note {i}", subject="EXSOFT", source=f"analyst call #{i}",
                        valid_from=datetime(2026, 10, 17 + i).date(), now=datetime(2026, 10, 17 + i)) for i in range(3)]
    mem.remember(con, "decision", "keep EXSOFT", subject="EXSOFT", now=NOW)
    assert clean.memory(con) == 2
    cur = [m.text for m in mem.recall(con, subject="EXSOFT", kinds=["note"], asof=NOW.date())]
    assert cur == ["Analyst note 2"] and len(mem.recall(con, subject="EXSOFT", kinds=["decision"], asof=NOW.date())) == 1
    assert con.execute("SELECT valid_to FROM memory WHERE mem_id=?", [ids[0]]).fetchone()[0] == datetime(2026, 10, 18).date()
