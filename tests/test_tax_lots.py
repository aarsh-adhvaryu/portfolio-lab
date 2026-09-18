from datetime import date

import pytest

from pflab.tax.india_lots import LotBook, TaxPolicy, fy_of, is_long_term

P = TaxPolicy()


def test_fy_label():
    assert fy_of(date(2024, 3, 31)) == 2024
    assert fy_of(date(2024, 4, 1)) == 2025


def test_long_term_boundary():
    b = date(2024, 1, 15)
    assert not is_long_term(b, date(2025, 1, 15))   # exactly 12 months: short
    assert is_long_term(b, date(2025, 1, 16))       # one day more: long


def test_fifo_and_split_of_lots():
    bk = LotBook(P)
    bk.buy("X", date(2024, 1, 10), 10, 100.0)
    bk.buy("X", date(2024, 6, 10), 10, 200.0)
    r = bk.sell("X", date(2024, 9, 10), 15, 300.0)
    assert [x.qty for x in r] == [10, 5]
    assert r[0].buy_date == date(2024, 1, 10)
    assert bk.holdings("X") == 5
    assert bk.lots("X")[0].cost_per_share == 200.0


def test_costs_change_cost_basis_and_proceeds():
    bk = LotBook(P)
    bk.buy("X", date(2024, 1, 10), 10, 100.0, costs=10.0)   # 101 per share
    r = bk.sell("X", date(2024, 2, 10), 10, 110.0, costs=20.0)
    assert r[0].cost == pytest.approx(1010.0)
    assert r[0].proceeds == pytest.approx(1080.0)
    assert r[0].gain == pytest.approx(70.0)


def test_stcg_ltcg_rates_exemption_and_cess():
    bk = LotBook(P)
    bk.buy("A", date(2023, 5, 1), 100, 1000.0)   # will be long-term
    bk.buy("B", date(2024, 5, 1), 100, 1000.0)   # short-term
    bk.sell("A", date(2024, 12, 1), 100, 3000.0)  # LTCG 200,000
    bk.sell("B", date(2024, 12, 1), 100, 1500.0)  # STCG 50,000
    t = bk.settle_fy(2025)
    assert t.ltcg_taxable == pytest.approx(200_000)
    assert t.stcg_taxable == pytest.approx(50_000)
    expected = (50_000 * 0.20 + (200_000 - 125_000) * 0.125) * 1.04
    assert t.total == pytest.approx(expected)


def test_stcl_offsets_ltcg_but_ltcl_does_not_offset_stcg():
    bk = LotBook(P)
    bk.buy("A", date(2023, 1, 1), 10, 100.0)
    bk.buy("B", date(2024, 6, 1), 10, 100.0)
    bk.sell("A", date(2024, 12, 1), 10, 200.0)   # LTCG +1000
    bk.sell("B", date(2024, 12, 1), 10, 50.0)    # STCL -500
    t = bk.settle_fy(2025)
    assert t.ltcg_taxable == pytest.approx(500)
    assert t.stcg_taxable == 0
    bk2 = LotBook(P)
    bk2.buy("A", date(2023, 1, 1), 10, 100.0)
    bk2.buy("B", date(2024, 6, 1), 10, 100.0)
    bk2.sell("A", date(2024, 12, 1), 10, 50.0)    # LTCL -500
    bk2.sell("B", date(2024, 12, 1), 10, 200.0)   # STCG +1000
    t2 = bk2.settle_fy(2025)
    assert t2.stcg_taxable == pytest.approx(1000)
    assert len(t2.carried_forward) == 1 and t2.carried_forward[0].long_term


def test_carry_forward_used_next_year_and_expires():
    bk = LotBook(P)
    bk.buy("A", date(2024, 4, 5), 10, 100.0)
    bk.sell("A", date(2024, 5, 5), 10, 40.0)     # STCL -600 in FY2025
    t1 = bk.settle_fy(2025)
    assert t1.carried_forward[0].amount == pytest.approx(600)
    bk.buy("B", date(2025, 4, 5), 10, 100.0)
    bk.sell("B", date(2025, 5, 5), 10, 150.0)    # STCG +500 in FY2026
    t2 = bk.settle_fy(2026)
    assert t2.stcg_taxable == 0
    assert t2.carried_forward[0].amount == pytest.approx(100)
    for fy in range(2027, 2027 + 9):
        bk.settle_fy(fy)
    assert bk.settled[2027 + 8].carried_forward == []   # expired after 8 years


def test_dividends_taxed_at_slab():
    bk = LotBook(P)
    bk.dividend(date(2024, 8, 1), 10_000.0)
    t = bk.settle_fy(2025)
    assert t.total == pytest.approx(10_000 * 0.30 * 1.04)


def test_liquidation_simulation_does_not_mutate():
    bk = LotBook(P)
    bk.buy("A", date(2023, 1, 1), 10, 100.0)
    t = bk.simulate_liquidation(date(2024, 12, 31), {"A": 200.0}, lambda n: 0.0)
    assert t.ltcg_realised == pytest.approx(1000)
    assert bk.holdings("A") == 10 and bk.settled == {}


def test_settle_twice_raises_and_oversell_raises():
    bk = LotBook(P)
    bk.settle_fy(2025)
    with pytest.raises(ValueError):
        bk.settle_fy(2025)
    with pytest.raises(ValueError):
        bk.sell("Z", date(2025, 1, 1), 1, 1.0)
