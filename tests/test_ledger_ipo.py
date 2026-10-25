"""S19: IPO ledger: blocked funds, allotment, release, listing into lots. Synthetic."""
from datetime import date

import pytest

from pflab.calc import valuation as val
from pflab.ledger import ipo
from pflab.ledger.book import Ledger
from pflab.ledger.cash import CashError
from pflab.ledger.events import Event, EventError, EventLog, load, save
from pflab.pm import store

BANK, DEMAT = "SBI", "ZERODHA"
NEW = "INE999Z01017"


def d(m, day=1):
    return date(2026, m, day)


def base(*extra, cash=100_000.0):
    return EventLog([Event("deposit", BANK, d(1), amount=cash), *extra])


def bid(ipo_id="ACME", qty=100, price=150.0, when=None):
    return ipo.block(ipo_id, BANK, when or d(2, 1), qty, price, category="retail", mandate_ref="UPI-123")


# --- blocked funds ---------------------------------------------------------------------------------------

def test_block_reduces_available_cash_not_the_balance():
    led = Ledger.replay(base(bid()))
    assert led.cash_balance(BANK) == 100_000.0 and led.cash_available(BANK) == 85_000.0
    assert led.ipo.blocked(BANK) == 15_000.0 and led.ipo.apps["ACME"].amount_blocked == 15_000.0
    assert led.ipo.apps["ACME"].mandate_ref == "UPI-123" and led.ipo.apps["ACME"].category == "retail"


def test_blocked_money_cannot_be_spent():
    log = base(bid(qty=500, price=150.0),                                       # blocks 75,000
               Event("buy", BANK, d(2, 5), isin="INE111A01011", qty=100, price=300.0))   # needs 30,000 > 25,000 free
    with pytest.raises(CashError, match="blocked for IPO"):
        Ledger.replay(log)
    ok = base(bid(qty=500, price=150.0), Event("buy", BANK, d(2, 5), isin="INE111A01011", qty=100, price=250.0))
    led = Ledger.replay(ok)                                                    # exactly the free 25,000
    assert led.cash_available(BANK) == pytest.approx(0.0, abs=1e-6)
    with pytest.raises(CashError):
        Ledger.replay(base(bid(qty=500, price=150.0), Event("withdrawal", BANK, d(2, 5), amount=25_000.01)))


def test_cannot_block_more_than_available_and_ids_are_unique():
    with pytest.raises(ipo.IpoError, match="only Rs 100,000.00 is available"):
        Ledger.replay(base(bid(qty=1000, price=150.0)))
    with pytest.raises(ipo.IpoError, match="only Rs 85,000.00 is available"):
        Ledger.replay(base(bid("A", 100, 150.0), bid("B", 600, 150.0, d(2, 2))))
    with pytest.raises(ipo.IpoError, match="already exists"):
        Ledger.replay(base(bid("A"), bid("A", when=d(2, 2))))


def test_two_open_bids_both_hold_funds():
    led = Ledger.replay(base(bid("A", 100, 150.0), bid("B", 200, 100.0, d(2, 2))))
    assert led.ipo.blocked(BANK) == 35_000.0 and led.cash_available(BANK) == 65_000.0
    assert led.ipo.blocked_by_account() == {BANK: 35_000.0}


# --- allotment ---------------------------------------------------------------------------------------------

def test_allotment_pays_only_the_allotted_amount_and_creates_a_lot_at_allotment_date():
    log = base(bid(qty=100, price=150.0),
               ipo.allot("ACME", BANK, d(2, 8), NEW, 40, 140.0, DEMAT, fees={"stamp": 5.0}, tax_class="EQUITY"))
    led = Ledger.replay(log)
    assert led.cash_balance(BANK) == pytest.approx(100_000 - (40 * 140 + 5)) and led.cash_available(BANK) == led.cash_balance(BANK)
    (lot,) = led.lots.lots(DEMAT, NEW)
    assert (lot.acq_date, lot.qty, lot.tax_class) == (d(2, 8), 40, "EQUITY")
    assert lot.cost_per_unit == pytest.approx((40 * 140 + 5) / 40)
    a = led.ipo.apps["ACME"]
    assert (a.status, a.allotted_qty, a.refund_on, a.demat_account) == ("allotted", 40, d(2, 8), DEMAT)
    assert led.ipo.blocked(BANK) == 0.0
    assert [f.kind for f in led.fees] == ["stamp"]


def test_listing_does_not_move_the_lot_but_records_the_date():
    log = base(bid(), ipo.allot("ACME", BANK, d(2, 8), NEW, 40, 140.0, DEMAT), ipo.listed("ACME", NEW, d(2, 12)),
               Event("sell", DEMAT, d(3, 1), isin=NEW, qty=40, price=190.0))
    led = Ledger.replay(log)
    a = led.ipo.apps["ACME"]
    assert a.listed_on == d(2, 12)
    (c,) = led.realised
    assert c.acq_date == d(2, 8) and c.gain == pytest.approx(40 * 50.0)          # held from allotment, not listing


def test_full_allotment_and_validation():
    led = Ledger.replay(base(bid(qty=100, price=150.0), ipo.allot("ACME", BANK, d(2, 8), NEW, 100, 148.0, DEMAT)))
    assert led.cash_balance(BANK) == pytest.approx(100_000 - 14_800) and led.holdings(NEW, DEMAT) == 100
    with pytest.raises(ipo.IpoError, match="more than the Rs 15,000.00 blocked"):
        Ledger.replay(base(bid(), ipo.allot("ACME", BANK, d(2, 8), NEW, 100, 151.0, DEMAT)))
    with pytest.raises(ipo.IpoError, match="but bid for 100"):
        Ledger.replay(base(bid(qty=100, price=150.0), ipo.allot("ACME", BANK, d(2, 8), NEW, 101, 1.0, DEMAT)))
    with pytest.raises(ipo.IpoError, match="funded from"):
        Ledger.replay(base(bid(), ipo.allot("ACME", "OTHER", d(2, 8), NEW, 10, 100.0, DEMAT)))


def test_allotment_without_a_block_or_twice_fails():
    with pytest.raises(ipo.IpoError, match="unknown IPO"):
        Ledger.replay(base(ipo.allot("NOPE", BANK, d(2, 8), NEW, 10, 100.0, DEMAT)))
    with pytest.raises(ipo.IpoError, match="already allotted"):
        Ledger.replay(base(bid(), ipo.allot("ACME", BANK, d(2, 8), NEW, 10, 100.0, DEMAT),
                           ipo.allot("ACME", BANK, d(2, 9), NEW, 10, 100.0, DEMAT)))


# --- release (non-allotment) --------------------------------------------------------------------------------------

def test_refund_releases_the_block_with_no_cash_movement():
    log = base(bid(), ipo.release("ACME", BANK, d(2, 8)))
    led = Ledger.replay(log)
    assert led.cash_balance(BANK) == 100_000.0 and led.cash_available(BANK) == 100_000.0
    a = led.ipo.apps["ACME"]
    assert (a.status, a.refund_on) == ("released", d(2, 8)) and led.positions() == {}
    with pytest.raises(ipo.IpoError, match="already released"):
        Ledger.replay(base(bid(), ipo.release("ACME", BANK, d(2, 8)), ipo.release("ACME", BANK, d(2, 9))))


def test_released_funds_can_be_spent_again():
    log = base(bid(qty=500, price=150.0), ipo.release("ACME", BANK, d(2, 8)),
               Event("buy", BANK, d(2, 9), isin="INE111A01011", qty=100, price=900.0))
    assert Ledger.replay(log).cash_balance(BANK) == pytest.approx(10_000.0)


# --- order, valuation, store ---------------------------------------------------------------------------------------------

def test_same_day_order_deposit_then_block_then_allot():
    log = EventLog([ipo.allot("ACME", BANK, d(2, 1), NEW, 10, 100.0, DEMAT), bid(when=d(2, 1)),
                    Event("deposit", BANK, d(2, 1), amount=50_000.0)])
    led = Ledger.replay(log)
    assert led.holdings(NEW, DEMAT) == 10 and led.cash_balance(BANK) == pytest.approx(49_000.0)


def test_valuation_available_cash_excludes_blocked_funds():
    led = Ledger.replay(base(bid(qty=100, price=150.0)))
    v = val.value_ledger(led, lambda i, a: None, d(2, 2), blocked=led.ipo.blocked_by_account())
    assert v.cash_total == 100_000.0 and v.cash_available == 85_000.0 and v.total == 100_000.0


def test_event_validation():
    with pytest.raises(EventError):
        Event("ipo_block", BANK, d(1), amount=10.0, params={"bid_qty": 1, "bid_price": 10.0})    # no ipo id
    with pytest.raises(EventError):
        Event("ipo_block", BANK, d(1), ref="X", amount=0.0, params={"bid_qty": 1, "bid_price": 10.0})
    with pytest.raises(EventError):
        Event("ipo_block", BANK, d(1), ref="X", amount=10.0, params={})
    with pytest.raises(EventError):
        Event("ipo_allot", BANK, d(1), ref="X", isin=NEW, qty=1, price=1.0, params={})            # no demat


def test_a_past_application_replays_through_the_store(tmp_path):
    """Block, partial allotment, listing, sale, plus a second bid not allotted: saved, loaded, replayed
    to the same lots, cash and application rows."""
    log = base(bid("ACME", 100, 150.0), ipo.allot("ACME", BANK, d(2, 8), NEW, 40, 140.0, DEMAT, fees={"stamp": 5.0}),
               ipo.listed("ACME", NEW, d(2, 12)),
               bid("OTHER", 50, 200.0, d(3, 1)), ipo.release("OTHER", BANK, d(3, 6)),
               Event("sell", DEMAT, d(4, 1), isin=NEW, qty=40, price=170.0))
    led = Ledger.replay(log)
    con = store.connect(tmp_path / "l.duckdb")
    save(con, log)
    led2 = Ledger.replay(load(con))
    assert led2.cash_balance(BANK) == led.cash_balance(BANK) and led2.positions() == led.positions()
    assert {k: (a.status, a.allotted_qty, a.listed_on, a.refund_on) for k, a in led2.ipo.apps.items()} == \
        {k: (a.status, a.allotted_qty, a.listed_on, a.refund_on) for k, a in led.ipo.apps.items()}
    led2.write_derived(con)
    rows = {r[0]: r for r in con.execute("SELECT ipo_id, status, allotted_qty, amount_blocked, listed_on FROM ipo_applications").fetchall()}
    assert rows["ACME"][1:] == ("allotted", 40.0, 15_000.0, d(2, 12)) and rows["OTHER"][1] == "released"
