"""S75: the new screens draw in a REAL browser (headless Edge): Memory (does it change the work, and recall by subject) and Rules and money (house rules with Undo, a money rule waiting
for his yes with its buttons, the envelope, the scorecard). Synthetic profile; skipped where Edge is missing."""
from __future__ import annotations

import os
from datetime import datetime

import pytest

from pflab.hq import cases, rules
from tests import _edge
from tests.test_s68_ui import NOW, server  # noqa: F401  (the fixture)

pytestmark = [pytest.mark.ui, pytest.mark.skipif(not os.path.exists(_edge.EDGE), reason="Microsoft Edge is not installed here")]


def test_the_research_rail_offers_memory_and_rules(server, tmp_path):
    rt, port = server
    steps = [("document.getElementById('subnav').innerText", 1.0)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/research/memory", str(tmp_path / "m.png"), 1400, 900, 4, steps)
    assert errors == [], errors
    assert "Memory" in res[0] and "Rules and money" in res[0]


def test_memory_shows_whether_it_changes_the_work_and_answers_a_subject(server, tmp_path):
    rt, port = server
    con = rt.cursor()
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at)
                   VALUES ('INE000A01011', 'isin', 'equity', 'listed_equity', TRUE, 'AAA', 'AAA Limited', 'IT - Software', 'synthetic', now())""")
    cid, _ = cases.open_case(con, datetime(2026, 10, 10), "Is AAA exposed to a software sell-off?", origin="investor", isin="INE000A01011", key="k")
    cases.conclude(con, cid, datetime(2026, 10, 10), "watch", "exposure is modest", uncertainty="one quarter", next_review_at=datetime(2026, 12, 1))
    steps = [("document.getElementById('screen').innerText", 1.5),
             ("document.getElementById('memAbout').value = 'AAA'; document.getElementById('memGo').click(); 1", 1.8),
             ("document.getElementById('screen').innerText", 0.2)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/research/memory", str(tmp_path / "m2.png"), 1400, 1100, 5, steps)
    assert errors == [], errors
    first = res[0].lower()                                                                                  # (labels are drawn in capitals; innerText returns them so)
    assert "does memory change the work?" in first and "0 of 0" in first and "ask memory about a subject" in first
    t = res[2].lower()
    assert "what was concluded before, and why" in t and "exposure is modest" in t and "watch" in t and "current" in t


def test_rules_and_money_shows_rules_with_undo_a_money_rule_with_yes_and_no_and_the_envelope(server, tmp_path):
    rt, port = server
    con = rt.cursor()
    rules.propose(con, NOW, "method", "Always include a 0.5% charge in cost tests", name="costs")
    wait = rules.propose(con, NOW, "monthly_envelope", "I invest Rs 50,000 a month till January", {"amount_rupees": 50000, "until": "2027-01-31"})
    steps = [("document.getElementById('screen').innerText", 1.5),
             ("document.querySelectorAll('[data-undo]').length + '/' + document.querySelectorAll('[data-rdec]').length", 0.1),
             ("document.querySelector('[data-rdec=yes]').click(); 1", 1.8),
             ("document.getElementById('screen').innerText", 0.2)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/research/rules", str(tmp_path / "r.png"), 1500, 1100, 5, steps)
    assert errors == [], errors
    t = res[0].lower()
    assert "house rules" in t and "always include a 0.5% charge in cost tests" in t and "waiting for your yes" in t and "monthly envelope" in t
    assert "how the recommendations have turned out" in t and "nothing is scored yet" in t
    assert res[1] == "1/2"                                                                                  # one Undo, a Yes and a No
    assert con.execute("SELECT status FROM hq_rules WHERE rule_id = ?", [wait["rule_id"]]).fetchone()[0] == "active"      # the Yes button did it
    assert "rs 50,000 a month" in res[3].lower() or "₹50,000 a month" in res[3].lower()


def test_the_paper_portfolio_screen_shows_the_book_its_decisions(server, tmp_path):
    from datetime import date
    rt, port = server
    con = rt.cursor()
    con.execute("INSERT INTO paper_cash VALUES (1, ?, 50000, 'seed', 'his record without FDs', now())", [date(2026, 10, 30)])
    con.execute("INSERT INTO paper_days VALUES (?, 50000, 50000, 0, 0, '{}')", [date(2026, 10, 30)])
    con.execute("INSERT INTO paper_decisions (decision_id, made_at, case_id, action, isin, symbol, amount, reason, alternatives, status) "
                "VALUES (1, now(), 7, 'WAIT', NULL, NULL, NULL, 'valuations are high across the market; keep cash for now', 'buy the index', 'executed')")
    steps = [("document.getElementById('screen').innerText", 1.5)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/portfolio/paper", str(tmp_path / "p.png"), 1500, 1100, 5, steps)
    assert errors == [], errors
    t = res[0].lower()
    assert "paper portfolio" in t and "keep cash for now" in t and "gate to your real money" in t and "is its judgement holding up?" in t
    assert "ask it to look into something" not in t
