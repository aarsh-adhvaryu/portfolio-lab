"""E3-R §11 (b): the sell-down ranks names by the tax a FIFO sale would cost."""
from datetime import date

import pytest

from pflab.portfolio import selldown as sd
from pflab.tax.india_lots import Lot, LotBook, TaxPolicy

P = TaxPolicy()
M = date(2020, 3, 31)


def _lots(isin, *specs):
    return [Lot(isin, d, q, c) for d, q, c in specs]


def test_categories_order_loss_then_long_term_then_short_term():
    lots = {
        "ST": _lots("ST", (date(2020, 1, 2), 10, 100.0)),            # +20 short
        "LT": _lots("LT", (date(2017, 1, 2), 10, 100.0)),            # +50 long
        "LOSS": _lots("LOSS", (date(2019, 11, 1), 10, 100.0)),       # -30
    }
    r = sd.rank(lots, {"ST": 102.0, "LT": 105.0, "LOSS": 97.0}, {}, M, P)
    assert [c.isin for c in r] == ["LOSS", "LT", "ST"]
    assert [c.category for c in r] == [sd.NET_LOSS, sd.NET_LONG_TERM, sd.SHORT_TERM]


def test_mixed_position_with_a_short_term_gain_is_short_term():
    lots = {"X": _lots("X", (date(2017, 1, 2), 10, 50.0), (date(2020, 1, 2), 10, 90.0))}
    c = sd.rank(lots, {"X": 100.0}, {}, M, P)[0]
    assert c.category == sd.SHORT_TERM
    assert c.st_gain == pytest.approx(100.0) and c.lt_gain == pytest.approx(500.0)
    assert c.tax_per_rupee == pytest.approx((0.20 * 100 + 0.125 * 500) / 2000)


def test_within_a_category_lowest_tax_per_rupee_then_weakest_score():
    lots = {"A": _lots("A", (date(2017, 1, 2), 10, 90.0)),     # 10% gain
            "B": _lots("B", (date(2017, 1, 2), 10, 50.0)),     # 50% gain
            "C": _lots("C", (date(2017, 1, 2), 10, 90.0))}     # same as A
    r = sd.rank(lots, {"A": 100.0, "B": 100.0, "C": 100.0},
                {"A": 0.9, "C": 0.1, "B": 0.5}, M, P)
    assert [c.isin for c in r] == ["C", "A", "B"]


def test_whole_names_then_the_last_partially_in_whole_shares():
    lots = {"A": _lots("A", (date(2019, 11, 1), 10, 110.0)),   # loss, 1000
            "B": _lots("B", (date(2017, 1, 2), 20, 50.0))}     # LT, 2000
    r = sd.rank(lots, {"A": 100.0, "B": 100.0}, {}, M, P)
    assert sd.plan(r, 1450.0) == [("A", 10), ("B", 5)]         # 1000 + ceil(450/100)
    assert sd.plan(r, 1000.0) == [("A", 10)]
    assert sd.plan(r, 0.0) == []
    assert sd.plan(r, 10_000.0) == [("A", 10), ("B", 20)]


def test_the_lot_book_still_sells_fifo_within_the_chosen_name():
    book = LotBook(P)
    book.buy("A", date(2017, 1, 2), 10, 50.0)
    book.buy("A", date(2020, 1, 2), 10, 120.0)
    realised = book.sell("A", M, 5, 100.0)
    assert [r.buy_date for r in realised] == [date(2017, 1, 2)]
    assert all(r.long_term for r in realised)
