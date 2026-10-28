"""S65 Phase 6 item 3: his answer to the sleeve question carries a share and a start month; the system then shows how to spread
the money over financial years to keep TCS low. Nothing here changes a target."""
from datetime import date, datetime

import duckdb
import pytest

from pflab.agents import questions
from pflab.pm import store
from pflab.risk import sleeve, themes
from pflab.tax import foreign as tf

TODAY = date(2026, 10, 28)
NOW = datetime(2026, 10, 28, 21, 10)


@pytest.mark.parametrize("text,share,start", [
    ("yes 10", 0.10, None),
    ("Yes, 12.5% from February 2027", 0.125, date(2027, 2, 1)),
    ("10 from feb", 0.10, date(2027, 2, 1)),                      # no year: the next February
    ("yes 8 from november", 0.08, date(2026, 11, 1)),             # this month counts
    ("yes 10 2027-03", 0.10, date(2027, 3, 1)),
    ("15%", 0.15, None),
    ("yes", None, None),
    ("yes 80", None, None),                                       # above half the portfolio is read as a mistake
    ("", None, None),
])
def test_the_answer_is_read_as_a_share_and_a_start_month(text, share, start):
    got_share, got_start = sleeve.parse_answer(text, TODAY)
    assert got_share == (pytest.approx(share) if share is not None else None) and got_start == start


def test_the_funding_plan_fills_each_years_room_under_the_tcs_threshold():
    th = tf.tcs(0.0, 0.0)["threshold_rs"]
    plan = sleeve.funding_plan(1.5 * th, date(2026, 11, 1), remitted_before_inr=0.4 * th)
    assert plan["by_financial_year"] == [{"fy": "2026-2027", "amount_inr": round(0.6 * th)}, {"fy": "2027-2028", "amount_inr": round(0.9 * th)}]
    assert plan["unplaced_inr"] == 0 and plan["tcs_if_split_inr"] == 0.0
    assert plan["tcs_if_one_lump_inr"] == tf.tcs(0.4 * th, 1.5 * th)["tcs_rs"] > 0
    assert plan["label"].startswith("estimate")
    small = sleeve.funding_plan(0.2 * th, date(2027, 1, 1))
    assert small["by_financial_year"] == [{"fy": "2026-2027", "amount_inr": round(0.2 * th)}] and small["tcs_if_one_lump_inr"] == 0.0
    late = sleeve.funding_plan(0.5 * th, date(2027, 2, 1), remitted_before_inr=th)       # this year's room is already used
    assert late["by_financial_year"] == [{"fy": "2027-2028", "amount_inr": round(0.5 * th)}]


@pytest.fixture
def con(tmp_path):
    c = duckdb.connect(str(tmp_path / "pm.duckdb"))
    store.migrate(c)
    return c


def _ask(con):
    return themes.propose(con, "us_sleeve", "share", None, {"asof_history": "test"}, "study", NOW)


def _answer(con, text):
    qid = con.execute("SELECT q_id FROM limit_proposals WHERE kind='us_sleeve' ORDER BY prop_id DESC").fetchone()[0]
    questions.answer(con, qid, text, NOW)


def test_a_yes_with_a_share_is_applied_with_its_start_month_and_a_plan(con, monkeypatch):
    assert _ask(con)
    _answer(con, "yes 10 from January 2027")
    assert themes.resolve(con, NOW) == {"applied": 1, "declined": 0}
    assert themes.applied(con, "us_sleeve", "share") == pytest.approx(0.10)
    from pflab.plan import companion
    monkeypatch.setattr(companion, "positions", lambda c, d: {"investable": 20_000_000.0})
    plan = sleeve.plan_now(con, TODAY)
    assert plan["share"] == pytest.approx(0.10) and plan["start"] == "2027-01-01" and plan["amount_inr"] == 2_000_000
    assert [r["fy"] for r in plan["by_financial_year"]] == ["2026-2027", "2027-2028"]       # Rs 20 lakh needs two years of room
    assert sum(r["amount_inr"] for r in plan["by_financial_year"]) == 2_000_000


def test_a_yes_without_a_share_asks_once_more_and_the_number_alone_then_applies(con):
    assert _ask(con)
    _answer(con, "yes")
    assert themes.resolve(con, NOW) == {"applied": 0, "declined": 0}
    assert themes.applied(con, "us_sleeve", "share") is None
    assert [q[2] for q in questions.open_questions(con)] and "gave no share" in questions.open_questions(con)[0][2]
    assert themes.resolve(con, NOW) == {"applied": 0, "declined": 0} and len(questions.open_questions(con)) == 1     # asked once
    _answer(con, "12")
    assert themes.resolve(con, NOW)["applied"] == 1 and themes.applied(con, "us_sleeve", "share") == pytest.approx(0.12)


def test_deferred_us_items_open_on_their_date_or_event_and_once(con):
    from pflab.agents import needs
    from pflab.ledger import foreign as lf
    assert needs.deferred_items(con, datetime(2026, 10, 28)) == {}                       # nothing due yet
    lf.add_remittance(con, date(2026, 11, 3), 1000.0, 88_000.0, 0.0, "bank", source="t")
    got = needs.deferred_items(con, datetime(2026, 11, 4))
    assert list(got) == ["foreign_tax_check"] and got["foreign_tax_check"]               # the first remittance opens the tax check
    assert needs.deferred_items(con, datetime(2026, 11, 5)) == {"foreign_tax_check": False}   # asked once
    lf.register_instrument(con, "AAA", "US:AAA", "AAA")
    lf.add_trade(con, date(2026, 11, 6), "AAA", "US:AAA", "buy", 1, 100.0, 0.0, source="t")
    assert needs.deferred_items(con, datetime(2026, 11, 7))["sec_contact"]               # a US stock keyed by symbol opens the SEC ask
    con.execute("INSERT INTO inbox_items VALUES (1,'s.pdf','gift_city',NULL,NULL,'x','done',NULL,NULL,NULL,NULL,?,?,NULL)",
                [datetime(2026, 11, 8), datetime(2026, 11, 8)])
    assert needs.deferred_items(con, datetime(2026, 11, 9))["gift_city_parser"]
    texts = [t for _, _, t in questions.open_questions(con)]
    assert any("Quicko files your return" in t for t in texts) and any("real contact" in t for t in texts)


def test_the_dates_open_the_items_without_an_event(con):
    from pflab.agents import needs
    got = needs.deferred_items(con, datetime(2027, 1, 2))
    assert got["foreign_tax_check"] and got["sec_contact"] and "gift_city_parser" not in got


def test_a_no_declines_and_no_plan_shows(con):
    assert _ask(con)
    _answer(con, "no, not now")
    assert themes.resolve(con, NOW) == {"applied": 0, "declined": 1}
    assert sleeve.plan_now(con, TODAY) is None
