"""S58b tax planning from the tax engine, checked against hand-worked figures. SYNTHETIC ledger: 20 lakh of interest
(slab income above the basic exemption and the rebate, below any surcharge), so a sale's extra tax is its special-rate
tax plus 4% cess: short-term 20%, long-term 12.5% above the 1.25 lakh 112A exemption."""
from datetime import date

import pytest

from pflab.ledger.events import Event, EventLog, save
from pflab.pm import store
from pflab.tax import plan

AAA, BBB, CCC = "INE000A01011", "INE000B01011", "INE000C01011"
ASOF = date(2026, 10, 24)
PRICE = {AAA: 200.0, BBB: 150.0}


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    c.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha (synthetic)'), "
              "('SBI', 'bank', 'SBI (synthetic)')")
    for isin, sym in ((AAA, "AAA"), (BBB, "BBB"), (CCC, "CCC")):
        c.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                     VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, ?, ?, 'synthetic', now())""", [isin, sym, sym])
    for isin, px in PRICE.items():
        c.execute("INSERT INTO prices VALUES (?, DATE '2026-10-23', ?, 'EQ', 'synthetic', now())", [isin, px])
    save(c, EventLog([
        Event("deposit", "ZER", date(2025, 1, 1), amount=2_000_000.0),
        Event("buy", "ZER", date(2025, 1, 10), isin=AAA, qty=2000, price=100.0, ref="A1"),    # long-term by now
        Event("buy", "ZER", date(2026, 6, 1), isin=AAA, qty=50, price=150.0, ref="A2"),       # short-term
        Event("buy", "ZER", date(2026, 3, 1), isin=BBB, qty=100, price=200.0, ref="B1"),      # short-term, at a loss
        Event("buy", "ZER", date(2026, 4, 10), isin=CCC, qty=100, price=100.0, ref="C1"),
        Event("sell", "ZER", date(2026, 7, 1), isin=CCC, qty=100, price=200.0, ref="C2"),     # 10,000 STCG this FY
        Event("interest", "SBI", date(2026, 9, 30), amount=2_000_000.0)]))
    return c


def test_each_step_of_the_ladder_is_the_engines_tax_by_hand(con):
    eng = plan.Engine(con)
    steps = plan.ladder(eng, ASOF, "ZER", AAA, 200.0)
    a, b = steps
    assert (a["term"], a["long_term_from"]) == ("LT", date(2026, 1, 11))          # held MORE than 12 months
    assert a["extra_tax"] == pytest.approx((200_000 - 125_000) * 0.125 * 1.04)    # 9,750: above the exemption
    assert (b["term"], b["long_term_from"], b["through_qty"]) == ("ST", date(2027, 6, 2), 2050)
    assert b["extra_tax"] - a["extra_tax"] == pytest.approx(2_500 * 0.20 * 1.04)  # the short-term lot adds 520
    # sold on 2 Jun 2027 instead (FY2027-28, no other income, a fresh exemption): no tax at all
    assert b["extra_if_waited"] == pytest.approx(0.0) and b["waiting_saves"] == pytest.approx(b["extra_tax"])


def test_the_anniversary_itself_is_still_short_term():
    rule = plan.rule_of("EQUITY", date(2025, 1, 10), date(2026, 1, 10))
    assert plan.long_term_from(rule, date(2025, 1, 10)) == date(2026, 1, 11)


def test_harvest_fills_the_exemption_exactly_and_the_replay_confirms_no_tax(con):
    o = plan.overview(con, ASOF)
    h = o["harvest"]
    assert h["left"] == pytest.approx(125_000.0) and h["sales"] == [
        {"account": "ZER", "isin": AAA, "symbol": "AAA", "qty": 1250.0, "price": 200.0}]       # 1,250 x 100 gain
    assert h["gain_booked"] == pytest.approx(125_000.0) and abs(h["extra_tax_checked"]) < plan.NIL
    eng = plan.Engine(con)                                      # one share more is taxed: the fill is the limit
    assert eng.extra([("ZER", AAA, 1251, 200.0, ASOF)], 2027)["cheaper"] == pytest.approx(100 * 0.125 * 1.04)


def test_a_loss_that_offsets_this_years_gains_is_found(con):
    o = plan.overview(con, ASOF)
    assert o["losses"] == [{"account": "ZER", "isin": BBB, "symbol": "BBB", "sell_qty": 100, "tax_saved": pytest.approx(
        5_000 * 0.20 * 1.04), "step": 1}]                      # the 5,000 short-term loss offsets the 10,000 gain


def test_a_tax_question_is_answered_by_the_engine_not_by_written_code(con, tmp_path, monkeypatch):
    from datetime import datetime

    from pflab.agents import analyst as an
    from pflab.agents import workshop as wk
    monkeypatch.setattr(an, "config", lambda: {"adopted": False})
    writes = []
    out = wk.ask(con, "How much tax if I sell all my AAA today?", tmp_path / "pm", tmp_path / "data", ASOF,
                 local=lambda p: '{"measure": "tax_plan", "series": null}' if p.startswith("Pick the one")
                 else writes.append(p) or "{}", now=datetime(2026, 10, 24, 15, 0))
    assert out.measure == "tax_plan" and writes == []
    r = out.run.result
    assert r["taxplan.AAA.extra_tax_if_all_sold_today"] == round((200_000 - 125_000) * 0.125 * 1.04 + 2_500 * 0.2 * 1.04)
    assert "taxplan.BBB.extra_tax_if_all_sold_today" not in r                       # only the holding asked about
    assert r["taxplan.exemption_left"] == 125_000


def test_the_overview_reads_in_lines_with_rupees_marked(con):
    lines = plan.render(plan.overview(con, ASOF))
    assert lines[0] == "FY2026-27: 112A exemption ₹125,000, used ₹0, left ₹125,000."
    assert any(l.startswith("Selling 100 BBB lowers this year's tax by ₹1,040") for l in lines)


def test_lots_turning_long_term_soon_are_listed_with_what_waiting_saves(con):
    # AAA's second lot turns long-term on 2 Jun 2027, in the next FY (no other income there: the sale is untaxed)
    o = plan.overview(con, date(2027, 3, 20), wait_days=90)
    soon = o["turning_long_term"]
    assert [(s["symbol"], s["long_term_from"], s["days"]) for s in soon] == [("AAA", date(2027, 6, 2), 74)]
    now = plan.Engine(con).extra([("ZER", AAA, 2050, 200.0, date(2027, 3, 20))], 2027)["cheaper"]
    assert soon[0]["waiting_saves"] == pytest.approx(now)
    assert plan.overview(con, date(2027, 4, 20), wait_days=60)["turning_long_term"] == []   # same FY then: nothing saved
