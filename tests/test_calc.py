"""S14: valuation, returns, growth identity, what-if. Synthetic ledgers and prices."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pflab.calc import growth as gr
from pflab.calc import returns as rt
from pflab.calc import valuation as val
from pflab.ledger import corporate_actions as ca
from pflab.ledger.book import Ledger
from pflab.ledger.events import Event, EventLog
from pflab.pm import bonds as bd
from pflab.pm import gold, prices, store

A, B = "ACC1", "DORMANT"
X, Y, Z = "INE000000011", "INE000000029", "INE000000037"


def d(m, day=1, y=2026):
    return date(y, m, day)


def pricer(table, stale=()):
    """table: {isin: price} or {isin: {date: price}}; latest on/before asof."""
    def fn(isin, asof):
        t = table.get(isin)
        if t is None:
            return None
        if isinstance(t, dict):
            ds = [k for k in t if k <= asof]
            if not ds:
                return None
            k = max(ds)
            return val.PriceInfo(t[k], k, "close", isin in stale)
        return val.PriceInfo(t, asof, "close", isin in stale)
    return fn


# --- valuation -------------------------------------------------------------------------------

def _basic_log():
    return EventLog([
        Event("deposit", A, d(1), amount=100_000.0),
        Event("deposit", B, d(1), amount=5_000.0),
        Event("buy", A, d(2), isin=X, qty=100, price=100.0, fees={"b": 20.0}),     # cost 10,020
        Event("buy", A, d(2), isin=Y, qty=10.5, price=200.0),                      # cost 2,100
        Event("buy", B, d(2), isin=Z, qty=5, price=300.0),                         # dormant account
    ])


def test_valuation_totals_and_labels():
    led = Ledger.replay(_basic_log())
    v = val.value_ledger(led, pricer({X: 110.0, Y: 190.0, Z: 310.0}), d(3),
                         accounts={B: {"dormant": True, "read_only": True}}, blocked={A: 1_000.0})
    assert v.invested == pytest.approx(100 * 110 + 10.5 * 190 + 5 * 310)
    assert v.cash_total == pytest.approx(100_000 - 10_020 - 2_100 + 5_000 - 1_500)
    assert v.cash_available == pytest.approx(v.cash_total - 1_000.0)
    assert v.total == pytest.approx(v.invested + v.cash_total)
    p = v.positions.set_index("isin")
    assert p.loc[X, "unrealised"] == pytest.approx(11_000 - 10_020)
    assert bool(p.loc[Z, "dormant"]) is True and bool(p.loc[X, "dormant"]) is False
    assert v.unpriced == [] and v.stale == []
    assert val.by_isin(v).set_index("isin").loc[Y, "value"] == pytest.approx(10.5 * 190)


def test_unpriced_is_listed_never_valued_at_cost():
    led = Ledger.replay(_basic_log())
    v = val.value_ledger(led, pricer({X: 110.0}), d(3))
    assert {u[1] for u in v.unpriced} == {Y, Z}
    assert v.invested == pytest.approx(11_000.0)                  # only X counts
    assert v.positions.set_index("isin").loc[Y, "value"] != v.positions.set_index("isin").loc[Y, "value"]  # NaN


def test_stale_price_is_used_and_flagged():
    led = Ledger.replay(_basic_log())
    v = val.value_ledger(led, pricer({X: 110.0, Y: 190.0, Z: 310.0}, stale={X}), d(3))
    assert v.stale == [X] and v.invested == pytest.approx(100 * 110 + 10.5 * 190 + 5 * 310)


# --- realised, income ---------------------------------------------------------------------------

def _year_log():
    return EventLog([
        Event("deposit", A, date(2025, 4, 1), amount=200_000.0),
        Event("buy", A, date(2025, 4, 2), isin=X, qty=100, price=100.0, fees={"b": 10.0}),
        Event("dividend", A, date(2025, 8, 1), isin=X, amount=500.0, fees={"tds": 50.0}),
        Event("sell", A, date(2025, 12, 1), isin=X, qty=40, price=130.0, fees={"b": 8.0}),
        Event("deposit", A, date(2026, 1, 10), amount=50_000.0),
        Event("buy", A, date(2026, 1, 11), isin=Y, qty=20, price=500.0),
        Event("interest", A, date(2026, 3, 31), amount=300.0),
        Event("charge", A, date(2026, 3, 31), amount=118.0, ref="AMC"),
        Event("withdrawal", A, date(2026, 3, 31), amount=10_000.0),
        Event("sell", A, date(2026, 5, 1), isin=Y, qty=20, price=520.0),
        Event("dividend", A, date(2026, 6, 1), isin=X, amount=400.0, fees={"tds": 0.0}),
    ])


def test_realised_and_income_by_fy():
    led = Ledger.replay(_year_log())
    fy = rt.realised_by_fy(led)
    assert fy[2026] == pytest.approx(40 * 130 - 8 - 40 * 100.1)         # cost incl. fees: 10 over 100 units
    assert fy[2027] == pytest.approx(20 * 20)
    assert rt.realised_pnl(led, date(2026, 4, 1), date(2026, 12, 31)) == pytest.approx(400.0)
    inc = rt.income_by_fy(led)
    assert inc[2026] == {"gross": 800.0, "tds": 50.0, "net": 750.0}      # dividend 500 + interest 300
    assert inc[2027]["net"] == 400.0
    assert rt.income_total(led, kind="dividend") == pytest.approx(850.0)
    assert rt.income_total(led, kind="dividend", net=False) == pytest.approx(900.0)


def test_unrealised_pnl():
    led = Ledger.replay(_year_log())
    assert rt.unrealised_pnl(led, pricer({X: 120.0, Y: 520.0}), d(7, 1, 2026)) == pytest.approx(60 * 120 - 60 * 100.1)


# --- XIRR ---------------------------------------------------------------------------------------------

def test_xirr_known_cases():
    led = Ledger.replay(EventLog([Event("deposit", A, date(2025, 1, 1), amount=1000.0)]))
    assert rt.xirr(led, 1100.0, date(2026, 1, 1)) == pytest.approx(0.10, abs=1e-6)       # 365 days
    assert rt.xirr(led, 1210.0, date(2027, 1, 1)) == pytest.approx(0.10, abs=2e-3)       # 730 days, 21%
    assert rt.xirr(led, 900.0, date(2026, 1, 1)) == pytest.approx(-0.10, abs=1e-6)


def test_xirr_npv_is_zero_with_multiple_flows():
    log = EventLog([Event("deposit", A, date(2025, 1, 1), amount=1000.0),
                    Event("deposit", A, date(2025, 7, 1), amount=500.0),
                    Event("withdrawal", A, date(2025, 10, 1), amount=200.0)])
    led = Ledger.replay(log)
    r = rt.xirr(led, 1500.0, date(2026, 1, 1))
    flows = [(date(2025, 1, 1), -1000.0), (date(2025, 7, 1), -500.0), (date(2025, 10, 1), 200.0),
             (date(2026, 1, 1), 1500.0)]
    npv = sum(a / (1 + r) ** ((dt - date(2025, 1, 1)).days / 365.0) for dt, a in flows)
    assert abs(npv) < 1e-6 and r > 0


def test_xirr_with_start_value():
    log = EventLog([Event("deposit", A, date(2025, 1, 1), amount=1000.0)])
    led = Ledger.replay(log)
    # portfolio worth 1050 on 2025-07-01, 1100 on 2026-01-01 (no flows after the start)
    r = rt.xirr(led, 1100.0, date(2026, 1, 1), start=date(2025, 7, 1), start_value=1050.0)
    assert (1 + r) ** (184 / 365) == pytest.approx(1100 / 1050, rel=1e-6)


# --- TWR ----------------------------------------------------------------------------------------------------

def test_twr_ignores_flow_timing():
    log = EventLog([Event("deposit", A, d(1), amount=1_000.0),
                    Event("buy", A, d(1), isin=X, qty=10, price=100.0),
                    Event("deposit", A, d(3), amount=1_000.0),
                    Event("buy", A, d(3), isin=X, qty=5, price=200.0)])
    table = {X: {d(1): 100.0, d(2): 200.0, d(3): 200.0, d(4): 200.0}}
    dates = [d(1), d(2), d(3), d(4)]
    values, flows = rt.value_series(log, pricer(table), dates)
    assert list(values) == [1_000.0, 2_000.0, 3_000.0, 3_000.0] and list(flows) == [0.0, 0.0, 1_000.0, 0.0]
    nav = rt.twr(values, flows)
    assert nav.iloc[-1] == pytest.approx(200.0)       # +100% on the first 1,000; the second 1,000 bought at 200 stays flat


# --- growth identity -------------------------------------------------------------------------------------------

def test_growth_identity_on_a_synthetic_year():
    log = _year_log()
    table = {X: {date(2025, 4, 2): 100.0, date(2025, 12, 1): 130.0, date(2026, 3, 31): 125.0, date(2026, 6, 30): 140.0},
             Y: {date(2026, 1, 11): 500.0, date(2026, 3, 31): 510.0, date(2026, 5, 1): 520.0}}
    for start, end in [(date(2025, 4, 1), date(2026, 3, 31)), (date(2026, 3, 31), date(2026, 6, 30)),
                       (date(2025, 4, 1), date(2026, 6, 30))]:
        g = gr.growth(log, pricer(table), start, end)
        assert g.start_value + g.contributions + g.gains + g.income - g.charges + g.other == pytest.approx(g.end_value)
        assert g.other == pytest.approx(0.0, abs=1e-6)
    g = gr.growth(log, pricer(table), date(2025, 4, 1), date(2026, 3, 31))
    assert g.contributions == pytest.approx(40_000.0) and g.start_value == pytest.approx(200_000.0)
    assert g.income == pytest.approx(450.0 + 300.0) and g.charges == pytest.approx(118.0)
    assert g.realised == pytest.approx(40 * 130 - 8 - 40 * 100.1)
    assert g.gains == pytest.approx(g.realised + (60 * 125 - 60 * 100.1) + (20 * 510 - 20 * 500))
    assert g.total_change == pytest.approx(g.end_value - g.start_value)


def test_growth_other_is_cash_credit_minus_cost_removed():
    log = EventLog([Event("deposit", A, d(1), amount=20_000.0),
                    Event("buy", A, d(1), isin=X, qty=100, price=100.0),
                    ca.cash_credit(X, d(3), 0.9, 8.0)])
    table = {X: {d(1): 100.0, d(3): 92.0}}
    g = gr.growth(log, pricer(table), d(1), d(3))
    assert g.other == pytest.approx(800.0 - 1_000.0)          # cash 800 in, cost 1,000 out
    assert g.start_value + g.contributions + g.gains + g.income - g.charges + g.other == pytest.approx(g.end_value)


def test_growth_identity_with_split_bonus_and_transfer():
    log = EventLog([Event("deposit", A, d(1), amount=50_000.0),
                    Event("buy", A, d(1), isin=X, qty=50, price=100.0, fees={"b": 12.0}),
                    ca.split(X, d(2), 0.5), ca.bonus(X, d(3), 1, 1),
                    Event("transfer", A, d(4), isin=X, qty=100, counter_account=B),
                    Event("sell", B, d(5), isin=X, qty=60, price=40.0, fees={"b": 5.0}),
                    Event("dividend", B, d(6), isin=X, amount=90.0, fees={"tds": 9.0})])
    # B has no cash: sale proceeds fund nothing it needs; dividend nets in
    table = {X: {d(1): 100.0, d(2): 50.0, d(5): 40.0, d(6): 42.0}}
    g = gr.growth(log, pricer(table), d(1), d(6))
    assert g.start_value + g.contributions + g.gains + g.income - g.charges + g.other == pytest.approx(g.end_value)
    assert g.other == pytest.approx(0.0, abs=1e-6)


# --- what-if ----------------------------------------------------------------------------------------------------------







# --- store price function ------------------------------------------------------------------------------------------------

def test_store_price_fn_bond_gold_and_equity(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    b = bd.Bond("INE000000015", "Synthetic 8% 2030", date(2020, 1, 15), date(2030, 1, 15), 0.08, 2)
    bd.load_bonds(con, [b], "synthetic")
    prices.load_bhavcopy(con, pd.DataFrame([(date(2026, 3, 13), b.isin, "N1", 102.0),
                                            (date(2026, 3, 13), X, "EQ", 55.0)],
                                           columns=["date", "isin", "series", "close"]))
    prices.load_gold(con, pd.DataFrame([(date(2026, 3, 13), "PM", "gold999", 149_000.0, "per_10g")],
                                       columns=["date", "session", "metal", "rate", "unit"]))
    fn = val.store_price_fn(con)
    asof = date(2026, 3, 15)
    assert fn(b.isin, asof).value == pytest.approx(1000 * 1.02 + 1000 * 0.08 * 60 / 360)   # dirty, per bond
    assert fn(X, asof).value == 55.0
    assert fn("PHYS:GOLD999", asof).value == pytest.approx(14_900.0)                      # per gram
    assert fn("INE_NOPRICE", asof) is None
