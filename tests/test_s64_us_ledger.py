"""S64 Phase 6 items 2 and 5: pseudo-ISINs, dollar trades, FIFO lots, gains in rupees with the sourced tax rules."""
from datetime import date, datetime

import duckdb
import pytest

from pflab.ledger import foreign as lf
from pflab.pm import store
from pflab.risk import exposure

NOW = datetime(2026, 10, 27)


@pytest.fixture
def con(tmp_path):
    c = duckdb.connect(str(tmp_path / "pm.duckdb"))
    store.migrate(c)
    return c


def test_pseudo_isin_round_trip_and_it_cannot_meet_a_real_isin():
    assert lf.pseudo_isin(320193) == "ZZ0000320193" and lf.pseudo_isin("0000320193") == "ZZ0000320193"
    assert len(lf.pseudo_isin(1)) == 12 and lf.is_pseudo("ZZ0000320193")
    assert not lf.is_pseudo("INE002A01018") and not lf.is_pseudo("US0378331005") and not lf.is_pseudo("ZZ00003201AB")
    for bad in (0, -5, 10 ** 10, "abc"):
        with pytest.raises(ValueError):
            lf.pseudo_isin(bad)


def test_an_alias_maps_the_pseudo_key_to_the_real_isin_from_a_date(con):
    key = lf.pseudo_isin(320193)
    lf.add_alias(con, key, "US0378331005", date(2026, 11, 1))
    assert lf.resolve(con, key, date(2026, 10, 1)) == key and lf.resolve(con, key, date(2026, 11, 2)) == "US0378331005"
    assert lf.resolve(con, "INE002A01018") == "INE002A01018"
    with pytest.raises(ValueError):
        lf.add_alias(con, "INE002A01018", "x", date(2026, 1, 1))


def test_a_us_instrument_goes_to_the_intl_equity_bucket(con):
    lf.register_instrument(con, "AAPL", lf.pseudo_isin(320193), "Apple Inc", now=NOW)
    r = con.execute("SELECT market, currency, key_kind, asset_class FROM instruments WHERE symbol='AAPL'").fetchone()
    assert r == ("US", "USD", "pseudo", "equity")
    assert exposure.bucket("equity", "FOREIGN", None, None, "US") == "intl_equity" and exposure.bucket("equity", "EQUITY", None, None, "NSE") == "equity"
    assert exposure.bucket("equity", "EQUITY", None, None, float("nan")) == "equity"            # an old row with no market stays Indian
    assert "intl_equity" in exposure.BUCKETS


def fx(con, rows):
    for d, r in rows:
        con.execute("INSERT INTO fx_rates VALUES (?, 'USDINR', ?, 'test')", [d, r])


def test_fifo_converts_cost_and_proceeds_at_the_month_before_rates_and_taxes_by_the_24_month_rule(con):
    key = lf.pseudo_isin(1)
    fx(con, [(date(2023, 12, 31), 83.0), (date(2024, 2, 29), 83.2), (date(2026, 1, 31), 90.0), (date(2026, 8, 31), 88.0)])
    lf.add_trade(con, date(2024, 1, 10), "AAA", key, "buy", 10, 100.0, 1.0)                    # rate of 2023-12-31: 83.0
    lf.add_trade(con, date(2024, 3, 12), "AAA", key, "buy", 10, 120.0, 1.0)                    # rate of 2024-02-29: 83.2
    lf.add_trade(con, date(2026, 2, 5), "AAA", key, "sell", 15, 150.0, 2.0)                    # rate of 2026-01-31: 90.0
    assert lf.holding(con, key, date(2026, 3, 1)) == 5
    g = lf.gains(con, 2025, slab=0.30)
    assert g["fy"] == "2025-2026" and len(g["rows"]) == 2
    first, second = g["rows"]
    # lot 1: 10 shares cost (100 + 1/10) * 10 = 1001 USD * 83.0; proceeds 10/15 of (15*150 - 2) = 1498.67... * 90
    assert first["class"] == "long" and first["rate"] == 0.125                                 # 2024-01-10 -> 2026-02-05 is over 24 months
    proceeds1 = (15 * 150 - 2) * (10 / 15) * 90.0
    assert first["gain_inr"] == pytest.approx(proceeds1 - 1001 * 83.0, abs=0.01)
    assert second["class"] == "short" and second["rate"] == 0.30 and second["qty"] == 5       # bought 2024-03-12: 23 months
    assert g["total"]["tax_inr"] == pytest.approx(first["tax_inr"] + second["tax_inr"]) and "estimate" in g["label"]
    assert g["total"]["long_gain_inr"] == pytest.approx(first["gain_inr"])


def test_a_sale_without_a_rate_is_listed_not_guessed_and_you_cannot_sell_what_you_do_not_hold(con):
    key = lf.pseudo_isin(2)
    lf.add_trade(con, date(2025, 5, 5), "BBB", key, "buy", 4, 50.0)
    lf.add_trade(con, date(2025, 8, 5), "BBB", key, "sell", 4, 60.0)
    g = lf.gains(con, 2025, slab=0.30)
    assert g["rows"] == [] and g["skipped"][0]["symbol"] == "BBB" and "no exchange rate" in g["skipped"][0]["why"]
    with pytest.raises(ValueError, match="nothing is guessed"):
        lf.add_trade(con, date(2025, 9, 1), "BBB", key, "sell", 1, 60.0)
    with pytest.raises(ValueError):
        lf.add_trade(con, date(2025, 9, 1), "BBB", key, "hold", 1, 60.0)


def test_remittances_per_financial_year_and_positions_in_two_currencies(con):
    lf.add_remittance(con, date(2026, 5, 2), 5000, 430_000, 0.0)
    lf.add_remittance(con, date(2026, 9, 1), 8000, 700_000, 40_000)
    lf.add_remittance(con, date(2026, 2, 1), 1000, 85_000, 0.0)                               # the year before
    r = lf.remitted_in_fy(con, date(2026, 10, 27))
    assert r["fy"] == "2026-2027" and r["usd"] == 13000 and r["tcs_inr"] == 40_000
    key = lf.pseudo_isin(3)
    fx(con, [(date(2026, 10, 26), 88.0)])
    lf.add_trade(con, date(2026, 6, 1), "CCC", key, "buy", 2.5, 200.0, 1.0)
    pos = lf.positions(con, date(2026, 10, 27), {key: 220.0})[0]
    assert pos["qty"] == 2.5 and pos["value_usd"] == 550.0 and pos["value_inr"] == 550 * 88.0 and pos["cost_usd"] == pytest.approx(501.0)


def test_load_fx_keeps_what_is_there(con, tmp_path, monkeypatch):
    import pandas as pd
    from pflab.data import macro
    monkeypatch.setattr(macro, "load", lambda key, root=None: pd.DataFrame({"date": pd.to_datetime(["2026-10-01", "2026-10-02"]), "value": [88.1, float("nan")]}))
    assert lf.load_fx(con, tmp_path) == 1 and lf.load_fx(con, tmp_path) == 0
    assert lf.fx_on(con, date(2026, 10, 5)) == (88.1, date(2026, 10, 1))
