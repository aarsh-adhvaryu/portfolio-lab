"""S58b: The investor's answers are read as he writes them. "Same" is a yes for merging two names (2026-10-24: only an answer
starting with "y" counted); an answer that says neither yes nor no, or a monthly amount with no number, is asked again,
never lost."""
from datetime import date, datetime

import pytest

from pflab.agents import questions as qs
from pflab.kg import clean
from pflab.plan import ready
from pflab.pm import store

NOW = datetime(2026, 10, 24, 16, 0)
ISIN = "INE000R01011"
ORG, COMP = "org:aaa industries group", f"company:{ISIN}"


@pytest.mark.parametrize("answer,said", [("yes", True), ("Y", True), ("same", True), ("Yes, it's the same", True),
                                         ("haan same hai", True), ("no", False), ("not the same", False),
                                         ("different companies", False), ("they are separate", False),
                                         ("hmm", None), ("", None)])
def test_yes_or_no_from_ordinary_words(answer, said):
    assert clean.yes_no(answer) is said


def graph(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                   VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, 'AAA', 'Aaa Industries', 'synthetic', now())""", [ISIN])
    con.execute("INSERT INTO kg_nodes VALUES (?, 'company', 'Aaa Industries', NULL, ?), (?, 'org', 'Aaa Industries Group', "
                "NULL, ?), ('doc:1', 'doc', 'news', NULL, ?)", [COMP, NOW, ORG, NOW, NOW])
    con.execute("INSERT INTO kg_edges VALUES ('doc:1', 'mentions', ?, ?, NULL, 'gdelt_gkg', NULL, NULL, ?)", [ORG, NOW, NOW])
    return con


def test_same_merges_the_names(tmp_path):
    con = graph(tmp_path)
    key = f"kg-same:{ORG}=>{COMP}"
    q = qs.ask(con, "knowledge graph", key, "Is \"Aaa Industries Group\" the same as Aaa Industries (AAA)? Answer yes or no", NOW)
    qs.answer(con, q, "same", NOW)
    clean.names(con, NOW)
    assert con.execute("SELECT dst FROM kg_edges WHERE src='doc:1'").fetchall() == [(COMP,)]
    assert con.execute("SELECT how FROM kg_aliases WHERE alias=?", [ORG]).fetchone() == ("his yes",)


def test_an_unclear_answer_is_asked_again_and_the_new_answer_decides(tmp_path):
    con = graph(tmp_path)
    q = qs.ask(con, "knowledge graph", f"kg-same:{ORG}=>{COMP}", "Is \"Aaa Industries Group\" the same as Aaa Industries "
               "(AAA)? Answer yes or no", NOW)
    qs.answer(con, q, "hmm", NOW)
    clean.names(con, NOW)
    again = [r for r in qs.open_questions(con) if "could not tell" in r[2]]
    assert len(again) == 1 and con.execute("SELECT count(*) FROM kg_aliases").fetchone()[0] == 0
    qs.answer(con, again[0][0], "not the same", datetime(2026, 10, 24, 17, 0))
    clean.names(con, datetime(2026, 10, 24, 17, 5))
    assert con.execute("SELECT canonical, how FROM kg_aliases WHERE alias=?", [ORG]).fetchone() == (ORG, "his no")


def test_a_monthly_answer_with_no_amount_is_asked_again(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    asof = date(2026, 10, 24)
    ready.triggers(con, asof, meta={}, now=NOW)
    q = [r for r in qs.open_questions(con) if "each month" in r[2]][0][0]
    qs.answer(con, q, "whatever is left after expenses", NOW)
    ready.triggers(con, asof, meta={}, now=NOW)
    again = [r for r in qs.open_questions(con) if "could not read an amount" in r[2]]
    assert len(again) == 1
    qs.answer(con, again[0][0], "25,000 from December", datetime(2026, 10, 24, 17, 0))
    assert ready.monthly(con, asof, meta={}) == (25_000.0, date(2026, 12, 1))
    keys = [t.key for t in ready.triggers(con, asof, meta={}, now=NOW)]
    assert "monthly:2026-12" in keys
