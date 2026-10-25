"""S11: corporate actions on ledger lots. Synthetic histories; the KOTAKBANK case uses
the real 2026-01-14 ISIN change and 5-for-1 split (INE237A01028 -> INE237A01036)."""
import random
from datetime import date

import pytest

from pflab.ledger import corporate_actions as ca
from pflab.ledger.book import Ledger
from pflab.ledger.events import Event, EventLog, load, save
from pflab.ledger.lots import LotBook
from pflab.pm import store
from pflab.tax.india_lots import LotBook as EngineBook, TaxPolicy

A, B = "ACC1", "ACC2"
X, Y = "INE000000011", "INE000000029"


def d(m, day=1, y=2026):
    return date(y, m, day)


def funded(*events, amount=1e9):
    return EventLog([Event("deposit", A, date(2020, 1, 1), amount=amount),
                     Event("deposit", B, date(2020, 1, 1), amount=amount), *events])


def buy(acc, isin, dt, qty, price, **kw):
    return Event("buy", acc, dt, isin=isin, qty=qty, price=price, **kw)


# --- parity with the engine's whole-share algorithms ---------------------------------

@pytest.mark.parametrize("seed", range(30))
def test_split_and_bonus_parity_with_engine(seed):
    rng = random.Random(seed)
    eng, log = EngineBook(TaxPolicy()), funded()
    for k in range(rng.randint(1, 6)):
        dt, q, p = date(2023, 1, 1 + 3 * k), rng.randint(1, 40), round(rng.uniform(10, 500), 2)
        eng.buy(X, dt, q, p, 5.0)
        log.append(buy(A, X, dt, q, p, fees={"c": 5.0}))
    factor = rng.choice([0.5, 0.2, 0.1, 0.25, 4.0, 3.0, 1 / 3])
    eng.adjust_shares(X, factor)
    log.append(ca.split(X, d(3), factor))
    a, b = rng.choice([(1, 1), (1, 2), (2, 1), (3, 5)])
    eng.bonus(X, b / (a + b), d(6))
    log.append(ca.bonus(X, d(6), a, b))
    led = Ledger.replay(log)
    mine = led.lots.lots(A, X)
    theirs = eng.lots(X)
    assert [(l.acq_date, l.qty) for l in mine] == [(l.buy_date, l.qty) for l in theirs]
    for l, t in zip(mine, theirs):
        assert l.cost_per_unit == pytest.approx(t.cost_per_share)
    assert [(f.units, f.basis, f.acq_date) for f in led.lots.fractions] == \
        [(pytest.approx(f.units), pytest.approx(f.basis), f.buy_date) for f in eng.fractions]


def test_lots_1_1_3_consolidated_4_to_1_give_one_share_and_a_fraction():
    log = funded(buy(A, X, d(1), 1, 100.0), buy(A, X, d(2), 1, 100.0), buy(A, X, d(3), 3, 100.0),
                 ca.split(X, d(6), 4.0))
    led = Ledger.replay(log)
    assert led.holdings(X) == 1
    (f,) = led.lots.fractions
    assert f.units == pytest.approx(0.25) and f.basis == pytest.approx(100.0)
    assert led.lots.lots(A, X)[0].cost == pytest.approx(400.0)        # 500 total: 400 to the share, 100 to the fraction


def test_fractional_split_keeps_fractions_for_funds():
    log = funded(buy(A, Y, d(1), 10.5, 20.0), ca.split(Y, d(2), 0.5, whole=False))
    led = Ledger.replay(log)
    assert led.holdings(Y) == pytest.approx(21.0) and led.lots.fractions == []
    assert led.lots.lots(A, Y)[0].cost == pytest.approx(210.0)


# --- split / ISIN change: KOTAKBANK 2026-01-14 -------------------------------------------

def test_kotakbank_isin_change_with_split_keeps_date_and_cost():
    old, new = "INE237A01028", "INE237A01036"
    log = funded(buy(A, old, date(2025, 3, 10), 100, 2000.0),
                 ca.split(old, date(2026, 1, 14), 0.2),
                 ca.isin_change(old, date(2026, 1, 14), new))
    led = Ledger.replay(log)
    assert led.holdings(old) == 0 and led.holdings(new) == 500
    (lot,) = led.lots.lots(A, new)
    assert lot.acq_date == date(2025, 3, 10) and lot.cost == pytest.approx(200_000.0)
    assert led.lots.fractions == []
    # sold later: long-term by the ORIGINAL purchase date, cost per new share 400
    led2 = Ledger.replay(EventLog(log.raw() + [Event("sell", A, date(2026, 6, 1), isin=new, qty=500, price=450.0)]))
    (c,) = led2.realised
    assert c.acq_date == date(2025, 3, 10) and c.gain == pytest.approx(25_000.0)


def test_isin_change_moves_pending_fractions_too():
    log = funded(buy(A, X, d(1), 5, 100.0), ca.split(X, d(2), 4.0), ca.isin_change(X, d(3), Y))
    led = Ledger.replay(log)
    assert [f.isin for f in led.lots.fractions] == [Y] and led.holdings(Y) == 1


# --- bonus ---------------------------------------------------------------------------------

def test_bonus_new_lot_dated_at_allotment_nil_cost():
    log = funded(buy(A, X, d(1), 100, 50.0), ca.bonus(X, d(5), 1, 1))
    led = Ledger.replay(log)
    old, new = led.lots.lots(A, X)
    assert (old.qty, old.acq_date, old.cost_per_unit) == (100, d(1), 50.0)
    assert (new.qty, new.acq_date, new.cost_per_unit) == (100, d(5), 0.0)
    log.append(Event("sell", A, d(8), isin=X, qty=150, price=40.0))
    led = Ledger.replay(log)
    assert led.positions() == {(A, X): 50.0}
    assert sum(c.gain for c in led.realised) == pytest.approx(100 * 40 - 100 * 50 + 50 * 40)


def test_bonus_fraction_then_cash_in_lieu_is_a_disposal():
    log = funded(buy(A, X, d(1), 3, 100.0), ca.bonus(X, d(2), 1, 2))     # 1 new per 2 held: 1.5 -> 1 + 0.5
    led = Ledger.replay(log)
    assert led.holdings(X) == 4 and led.lots.fractions[0].units == pytest.approx(0.5)
    log.append(ca.cash_in_lieu(A, X, d(10), 60.0))
    led = Ledger.replay(log)
    assert led.lots.fractions == []
    (c,) = led.realised
    assert (c.qty, c.proceeds, c.cost, c.acq_date) == (pytest.approx(0.5), 60.0, 0.0, d(2))
    assert led.cash_balance(A) == pytest.approx(1e9 - 300 + 60)


# --- merger / demerger -------------------------------------------------------------------------

def test_merger_carries_cost_and_acquisition_date():
    log = funded(buy(A, X, date(2024, 1, 5), 100, 80.0), buy(A, X, date(2025, 2, 5), 40, 100.0),
                 ca.merger(X, d(4), Y, 1.5))
    led = Ledger.replay(log)
    assert led.holdings(X) == 0 and led.holdings(Y) == 210
    lots = led.lots.lots(A, Y)
    assert [(l.acq_date, l.qty) for l in lots] == [(date(2024, 1, 5), 150), (date(2025, 2, 5), 60)]
    assert sum(l.cost for l in lots) == pytest.approx(100 * 80 + 40 * 100)


def test_demerger_splits_cost_by_announced_fraction_keeps_dates():
    log = funded(buy(A, X, date(2023, 6, 1), 100, 200.0),     # cost 20,000
                 ca.demerger(X, d(3), Y, 0.5, 0.25))          # 1 new per 2 old, 25% of cost moves
    led = Ledger.replay(log)
    (old,) = led.lots.lots(A, X)
    (new,) = led.lots.lots(A, Y)
    assert (old.qty, old.cost) == (100, pytest.approx(15_000.0))
    assert (new.qty, new.cost, new.acq_date) == (50, pytest.approx(5_000.0), date(2023, 6, 1))
    assert old.acq_date == new.acq_date


def test_demerger_bad_fraction_rejected():
    with pytest.raises(ca.ActionError):
        Ledger.replay(funded(buy(A, X, d(1), 10, 10.0), ca.demerger(X, d(2), Y, 1, 1.0)))


def test_cash_credit_scales_cost_and_pays_cash():
    log = funded(buy(A, X, d(1), 100, 100.0), ca.cash_credit(X, d(2), 0.9, 10.0))
    led = Ledger.replay(log)
    assert led.lots.lots(A, X)[0].cost_per_unit == pytest.approx(90.0)
    assert led.cash_balance(A) == pytest.approx(1e9 - 10_000 + 1_000) and led.realised == []


# --- buy-back (2026 rule) and rights ---------------------------------------------------------------

def test_buyback_from_2026_04_01_is_a_disposal():
    log = funded(buy(A, X, date(2025, 1, 1), 100, 100.0),
                 ca.buyback(A, X, date(2026, 5, 1), 40, 150.0, fees={"stt": 6.0}))
    led = Ledger.replay(log)
    (c,) = led.realised
    assert c.qty == 40 and c.gain == pytest.approx(40 * 150 - 40 * 100)        # STT paid, not deductible (s.48)
    assert led.holdings(X) == 60


def test_buyback_before_2026_04_01_refused():
    log = funded(buy(A, X, date(2025, 1, 1), 100, 100.0), ca.buyback(A, X, date(2026, 3, 31), 40, 150.0))
    with pytest.raises(ca.ActionError, match="deemed-dividend"):
        Ledger.replay(log)


def test_rights_taken_up_is_a_buy_dated_at_allotment():
    log = funded(buy(A, X, date(2024, 1, 1), 100, 100.0), ca.rights_issue(A, X, d(5), 20, 80.0))
    led = Ledger.replay(log)
    assert [(l.acq_date, l.qty, l.cost_per_unit) for l in led.lots.lots(A, X)] == \
        [(date(2024, 1, 1), 100, 100.0), (d(5), 20, 80.0)]


# --- accounts, validation, persistence ---------------------------------------------------------------

def test_star_applies_to_every_holding_account_only():
    log = funded(buy(A, X, d(1), 10, 10.0), buy(B, X, d(1), 20, 10.0), buy(B, Y, d(1), 7, 10.0),
                 ca.split(X, d(2), 0.5))
    led = Ledger.replay(log)
    assert (led.holdings(X, A), led.holdings(X, B), led.holdings(Y, B)) == (20, 40, 7)


def test_single_account_action_leaves_others_alone():
    log = funded(buy(A, X, d(1), 10, 10.0), buy(B, X, d(1), 20, 10.0), ca.split(X, d(2), 0.5, account=B))
    led = Ledger.replay(log)
    assert (led.holdings(X, A), led.holdings(X, B)) == (10, 40)


def test_action_on_unheld_isin_is_harmless():
    led = Ledger.replay(funded(ca.split(X, d(2), 0.5)))
    assert led.positions() == {} and led.actions_applied[0][2] == "split"


def test_unknown_action_and_bad_event_rejected():
    from pflab.ledger.events import EventError
    with pytest.raises(EventError):
        Event("corp_action", "*", d(1), params={"action": "split"})        # no isin
    with pytest.raises(ca.ActionError):
        Ledger.replay(funded(Event("corp_action", "*", d(1), isin=X, params={"action": "teleport"})))


def test_actions_round_trip_through_the_store(tmp_path):
    log = funded(buy(A, X, d(1), 10, 10.0), ca.split(X, d(2), 0.5), ca.bonus(X, d(3), 1, 2),
                 ca.demerger(X, d(4), Y, 0.5, 0.2), ca.isin_change(Y, d(5), "INE000000037"))
    led = Ledger.replay(log)
    con = store.connect(tmp_path / "l.duckdb")
    save(con, log)
    led2 = Ledger.replay(load(con))
    assert led2.positions() == led.positions()
    assert [(l.acq_date, l.qty, l.cost_per_unit) for l in led2.lots.all_lots()] == \
        [(l.acq_date, l.qty, l.cost_per_unit) for l in led.lots.all_lots()]
    led2.write_derived(con)
    assert con.execute("SELECT count(*) FROM corporate_actions_applied").fetchone()[0] == 4


def test_from_nse_feed_builds_split_and_bonus_for_held_isins_only():
    import pandas as pd
    raw = pd.DataFrame([
        dict(isin=X, ex_date=d(3), subject="Bonus 1:2"),
        dict(isin=X, ex_date=d(4), subject="Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"),
        dict(isin=Y, ex_date=d(3), subject="Bonus 1:1"),
        dict(isin=X, ex_date=d(5), subject="Dividend - Rs 6 Per Share"),
        dict(isin=X, ex_date=date(2025, 1, 1), subject="Bonus 1:1"),
    ])
    ev = ca.from_nse_feed(raw, [X], since=date(2026, 1, 1))
    assert [(e.params["action"], e.date) for e in ev] == [("bonus", d(3)), ("split", d(4))]
    assert (ev[0].params["a"], ev[0].params["b"]) == (1, 2)
    assert ev[1].params["factor"] == pytest.approx(0.2)
    log = funded(buy(A, X, d(1), 10, 100.0), *ev)
    assert Ledger.replay(log).holdings(X) == (10 + 5) * 5
