"""S3: event log, fractional FIFO lots, cash ledger, replay. All synthetic."""
import random
from datetime import date, timedelta

import pytest

from pflab.ledger.book import Ledger
from pflab.ledger.cash import CashError, CashLedger
from pflab.ledger.events import Event, EventError, EventLog, load, save
from pflab.ledger.lots import EPS, LotBook, LotError
from pflab.pm import store
from pflab.tax.india_lots import LotBook as EngineBook, TaxPolicy, is_long_term

A, B = "ACC1", "ACC2"
X, Y = "INE000000011", "INF000000022"


def d(m, day=1, y=2026):
    return date(y, m, day)


# --- FIFO, fractions, oversell ---------------------------------------------

def test_fifo_per_account_and_isin():
    b = LotBook()
    b.buy(A, X, d(1), 10, 100.0)
    b.buy(A, X, d(2), 10, 120.0)
    b.buy(B, X, d(1), 5, 50.0)        # other account: untouched by A's sale
    cons = b.sell(A, X, d(6), 15, 130.0)
    assert [(c.acq_date, c.qty) for c in cons] == [(d(1), 10), (d(2), 5)]
    assert b.holdings(A, X) == 5 and b.holdings(B, X) == 5
    assert b.lots(A, X)[0].cost_per_unit == 120.0


def test_fractional_units_and_dust():
    b = LotBook()
    b.buy(A, Y, d(1), 10.123, 25.5)
    cons = b.sell(A, Y, d(2), 4.0005, 30.0)
    assert cons[0].qty == pytest.approx(4.0005)
    assert b.holdings(A, Y) == pytest.approx(10.123 - 4.0005)
    b.sell(A, Y, d(3), 10.123 - 4.0005, 30.0)
    assert b.lots(A, Y) == [] and b.positions() == {}


def test_oversell_raises_and_changes_nothing():
    b = LotBook()
    b.buy(A, X, d(1), 5, 10.0)
    with pytest.raises(LotError, match="cannot sell"):
        b.sell(A, X, d(2), 5.01, 10.0)
    with pytest.raises(LotError):
        b.sell(B, X, d(2), 1, 10.0)     # nothing held in that account
    assert b.holdings(A, X) == 5 and b.consumed == []


def test_costs_in_basis_and_proceeds():
    b = LotBook()
    b.buy(A, X, d(1), 10, 100.0, fees=20.0)           # cost 1020
    (c,) = b.sell(A, X, d(2), 10, 110.0, fees=30.0)   # proceeds 1070
    assert (c.cost, c.proceeds, c.gain) == (1020.0, 1070.0, 50.0)


def test_transfer_keeps_date_and_cost():
    b = LotBook()
    b.buy(A, X, d(1), 10, 100.0, tax_class="EQUITY")
    b.buy(A, X, d(2), 10, 200.0)
    moved = b.transfer(A, B, X, d(5), 15)
    assert [(m.acq_date, m.qty, m.cost_per_unit) for m in moved] == [(d(1), 10, 100.0), (d(2), 5, 200.0)]
    assert moved[0].tax_class == "EQUITY" and b.holdings(A, X) == 5 and b.holdings(B, X) == 15
    with pytest.raises(LotError):
        b.transfer(A, B, X, d(6), 6)
    with pytest.raises(LotError):
        b.transfer(A, A, X, d(6), 1)


def test_scale_units_conserves_cost():
    b = LotBook()
    b.buy(A, X, d(1), 10, 100.0)
    b.scale_units(A, X, 2.0)
    (l,) = b.lots(A, X)
    assert (l.qty, l.cost_per_unit, l.cost) == (20.0, 50.0, 1000.0)


def test_rekey_moves_lots_to_successor_isin():
    b = LotBook()
    b.buy(A, X, d(1), 10, 100.0)
    b.rekey(A, X, "INE999999999")
    assert b.holdings(A, X) == 0 and b.holdings(A, "INE999999999") == 10
    assert b.lots(A, "INE999999999")[0].acq_date == d(1)


# --- cash -------------------------------------------------------------------

def test_cash_never_negative_without_overdraft():
    c = CashLedger()
    c.post(A, d(1), 1000.0, "deposit")
    with pytest.raises(CashError, match="balance would be"):
        c.post(A, d(2), -1000.01, "buy")
    assert c.balance(A) == 1000.0
    c.set_overdraft_limit(A, 500.0)
    c.post(A, d(2), -1200.0, "buy")
    assert c.balance(A) == pytest.approx(-200.0)
    with pytest.raises(CashError):
        c.post(A, d(3), -400.0, "buy")


def test_cash_balance_as_of():
    c = CashLedger()
    c.post(A, d(1), 100.0, "deposit")
    c.post(A, d(3), -40.0, "buy")
    assert c.balance(A, d(2)) == 100.0 and c.balance(A) == 60.0


# --- events -----------------------------------------------------------------

def test_event_validation():
    with pytest.raises(EventError):
        Event("buy", A, d(1), isin=X, qty=0, price=1)
    with pytest.raises(EventError):
        Event("buy", A, d(1), qty=1, price=1)
    with pytest.raises(EventError):
        Event("deposit", A, d(1), amount=-5)
    with pytest.raises(EventError):
        Event("transfer", A, d(1), isin=X, qty=1)
    with pytest.raises(EventError):
        Event("nope", A, d(1))
    with pytest.raises(EventError):
        Event("buy", A, d(1), isin=X, qty=1, price=1, fees={"stt": -1.0})


def test_same_day_order_deposit_buy_sell():
    log = EventLog()
    log.append(Event("sell", A, d(2), isin=X, qty=5, price=11.0))
    log.append(Event("buy", A, d(2), isin=X, qty=5, price=10.0))
    log.append(Event("deposit", A, d(2), amount=100.0))   # appended last, replayed first
    led = Ledger.replay(log)
    assert led.cash_balance(A) == pytest.approx(105.0) and led.positions() == {}


def test_sell_before_buy_by_date_fails_loudly():
    log = EventLog([Event("deposit", A, d(1), amount=100.0),
                    Event("sell", A, d(2), isin=X, qty=1, price=10.0),
                    Event("buy", A, d(3), isin=X, qty=1, price=10.0)])
    with pytest.raises(LotError):
        Ledger.replay(log)


def test_buy_without_funds_fails_loudly():
    log = EventLog([Event("buy", A, d(1), isin=X, qty=1, price=10.0)])
    with pytest.raises(CashError):
        Ledger.replay(log)


# --- a synthetic year round-trips ---------------------------------------------

def _year_log():
    ev = [
        Event("deposit", A, d(4, 1, 2025), amount=500_000.0, ref="seed"),
        Event("buy", A, d(4, 2, 2025), isin=X, qty=100, price=1000.0, fees={"brokerage": 20.0, "stt": 100.0}),
        Event("buy", A, d(5, 2, 2025), isin=Y, qty=250.5, price=40.25, tax_class="OTHER_MF"),
        Event("dividend", A, d(8, 1, 2025), isin=X, amount=2_000.0, fees={"tds": 200.0}),
        Event("buy", A, d(9, 1, 2025), isin=X, qty=50, price=1100.0),
        Event("sell", A, d(2, 1, 2026), isin=X, qty=120, price=1300.0, fees={"stt": 156.0}),
        Event("transfer", A, d(2, 5, 2026), isin=Y, qty=100.25, counter_account=B),
        Event("interest", A, d(3, 31, 2026), amount=1_500.0, ref="sweep"),
        Event("charge", A, d(3, 31, 2026), amount=354.0, ref="AMC"),
        Event("withdrawal", A, d(3, 31, 2026), amount=50_000.0),
    ]
    return EventLog(ev)


def test_stt_moves_cash_but_stays_out_of_cost_and_proceeds():
    log = EventLog([Event("deposit", A, d(4, 1, 2026), amount=10_000.0),
                    Event("buy", A, d(4, 2, 2026), isin=X, qty=10, price=100.0, fees={"brokerage": 2.0, "stt": 1.0}),
                    Event("sell", A, d(4, 3, 2026), isin=X, qty=10, price=110.0, fees={"brokerage": 3.0, "stt": 1.1})])
    led = Ledger.replay(log)
    (c,) = led.realised
    assert c.cost == pytest.approx(1002.0) and c.proceeds == pytest.approx(1097.0)
    assert led.cash_balance(A) == pytest.approx(10_000 - 1003 + 1100 - 4.1)
    assert sorted(f.kind for f in led.fees) == ["brokerage", "brokerage", "stt", "stt"]


def test_synthetic_year_round_trips_through_the_store(tmp_path):
    log = _year_log()
    led = Ledger.replay(log)
    assert led.holdings(X) == 30 and led.holdings(Y, B) == pytest.approx(100.25)
    assert led.holdings(Y, A) == pytest.approx(150.25)
    # identity: cash = deposits - withdrawals - buys + sells + net income - charges
    spent = 100 * 1000 + 120 + 250.5 * 40.25 + 50 * 1100
    expect = 500_000 - spent + (120 * 1300 - 156) + 1_800 + 1_500 - 354 - 50_000
    assert led.cash_balance(A) == pytest.approx(expect)
    # gains: brokerage enters cost; STT (100 on the buy, 156 on the sell) is paid but not deductible (s.48)
    assert sum(c.gain for c in led.realised) == pytest.approx(
        100 * 1300 - (100 * 1000 + 20) + 20 * 1300 - 20 * 1100)

    con = store.connect(tmp_path / "l.duckdb")
    assert save(con, log) == len(log) and save(con, log) == 0       # idempotent
    led2 = Ledger.replay(load(con))
    assert led2.positions() == led.positions()
    assert led2.cash_balance(A) == led.cash_balance(A)
    assert [(c.lot_id, c.gain) for c in led2.realised] == [(c.lot_id, c.gain) for c in led.realised]
    led2.write_derived(con)
    assert con.execute("SELECT count(*) FROM lots").fetchone()[0] == len(led.lots.all_lots())
    assert con.execute("SELECT sum(amount) FROM cash_ledger WHERE account_id='ACC1'").fetchone()[0] \
        == pytest.approx(led.cash_balance(A))
    assert con.execute("SELECT count(*) FROM income").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM fees").fetchone()[0] == 4  # brokerage, stt, stt, AMC


# --- parity with india_lots on equity-only random histories --------------------

@pytest.mark.parametrize("seed", range(40))
def test_parity_with_india_lots(seed):
    rng = random.Random(seed)
    isins = ["INE00000000%d" % i for i in range(3)]
    eng, led_log = EngineBook(TaxPolicy()), EventLog()
    led_log.append(Event("deposit", A, date(2022, 1, 1), amount=1e12))
    held = {i: 0 for i in isins}
    day = date(2022, 1, 3)
    for _ in range(60):
        day += timedelta(days=rng.randint(1, 40))
        i = rng.choice(isins)
        price = round(rng.uniform(50, 2000), 2)
        costs = round(rng.uniform(0, 80), 2)
        if held[i] == 0 or rng.random() < 0.6:
            q = rng.randint(1, 200)
            eng.buy(i, day, q, price, costs)
            led_log.append(Event("buy", A, day, isin=i, qty=q, price=price, fees={"all": costs}))
            held[i] += q
        else:
            q = rng.randint(1, held[i])
            eng.sell(i, day, q, price, costs)
            led_log.append(Event("sell", A, day, isin=i, qty=q, price=price, fees={"all": costs}))
            held[i] -= q
    led = Ledger.replay(led_log)
    assert len(led.realised) == len(eng.realised)
    for c, r in zip(led.realised, eng.realised):
        assert (c.isin, c.acq_date, c.sell_date) == (r.isin, r.buy_date, r.sell_date)
        assert c.qty == pytest.approx(r.qty)
        assert c.proceeds == pytest.approx(r.proceeds) and c.cost == pytest.approx(r.cost)
        assert is_long_term(c.acq_date, c.sell_date) == r.long_term
    assert {k[1]: v for k, v in led.positions().items()} == {i: q for i, q in eng.positions().items()}
