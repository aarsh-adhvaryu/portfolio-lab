"""S10: bonds, SGB, physical gold, Estimate. All synthetic: the bonds are textbook cases
(no real bond's terms are asserted), SGB series are invented."""
from datetime import date

import pandas as pd
import pytest

from pflab.ledger.book import Ledger
from pflab.ledger.events import Event, EventLog
from pflab.pm import bonds as bd
from pflab.pm import estimate as est
from pflab.pm import gold, instruments as ins, prices, store


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


def bond(**kw):
    base = dict(isin="INE000000015", name="Synthetic 8% 2030", issue_date=date(2020, 1, 15),
                maturity_date=date(2030, 1, 15), coupon_rate=0.08, frequency=2)
    base.update(kw)
    return bd.Bond(**base)


# --- schedules ---------------------------------------------------------------------------

def test_semiannual_ten_year_schedule():
    fl = bd.schedule(bond())
    assert len(fl) == 20 and fl[0].date == date(2020, 7, 15) and fl[-1].date == date(2030, 1, 15)
    assert all(f.interest == pytest.approx(40.0) for f in fl)
    assert fl[-1].principal == 1000.0 and sum(f.principal for f in fl) == 1000.0


def test_month_end_maturity_keeps_its_day():
    b = bond(issue_date=date(2024, 8, 31), maturity_date=date(2027, 8, 31))
    assert [f.date for f in bd.schedule(b)] == [date(2025, 2, 28), date(2025, 8, 31), date(2026, 2, 28),
                                                date(2026, 8, 31), date(2027, 2, 28), date(2027, 8, 31)]


@pytest.mark.parametrize("freq,n", [(1, 5), (2, 10), (4, 20), (12, 60)])
def test_frequencies(freq, n):
    b = bond(issue_date=date(2025, 1, 1), maturity_date=date(2030, 1, 1), frequency=freq, coupon_rate=0.09)
    fl = bd.schedule(b)
    assert len(fl) == n and sum(f.interest for f in fl) == pytest.approx(0.09 * 1000 * 5)


def test_zero_coupon_single_flow():
    b = bond(coupon_rate=0.0, frequency=0, issue_date=date(2025, 1, 1), maturity_date=date(2028, 1, 1))
    assert bd.schedule(b) == [bd.Flow(date(2028, 1, 1), 0.0, 1000.0)]
    assert bd.accrued_interest(b, date(2026, 1, 1)) == 0.0
    # 3 years at 7%: price 1000 / 1.07^3 on issue
    assert bd.clean_price_from_yield(b, 0.07, date(2025, 1, 1)) == pytest.approx(100 / 1.07 ** (1095 / 365), rel=1e-9)


def test_first_period_stub_is_prorated_by_day_count():
    b = bond(issue_date=date(2026, 3, 1), maturity_date=date(2028, 1, 15), coupon_rate=0.08)
    first = bd.schedule(b)[0]
    assert first.date == date(2026, 7, 15)
    assert first.interest == pytest.approx(80.0 * 134 / 360)           # 30/360 from 1-Mar to 15-Jul
    assert bd.schedule(b)[1].interest == pytest.approx(40.0)


def test_validation():
    with pytest.raises(bd.BondError):
        bond(day_count="ACT/360")
    with pytest.raises(bd.BondError):
        bond(frequency=3)
    with pytest.raises(bd.BondError):
        bond(coupon_rate=0.0)
    with pytest.raises(bd.BondError):
        bond(maturity_date=date(2020, 1, 1))


# --- accrued interest conventions ---------------------------------------------------------------

def test_accrued_30_360():
    assert bd.accrued_interest(bond(), date(2026, 3, 15)) == pytest.approx(80.0 * 60 / 360)   # 13.33
    assert bd.accrued_interest(bond(), date(2026, 1, 15)) == 0.0                              # on a coupon date
    assert bd.accrued_interest(bond(), date(2026, 7, 14)) == pytest.approx(80.0 * 179 / 360)


def test_30_360_month_end_rule():
    # 31st is treated as the 30th: 30-Jan -> 31-Mar is 60 days, not 61
    b = bond(issue_date=date(2025, 1, 30), maturity_date=date(2030, 1, 30), coupon_rate=0.06, frequency=2)
    assert bd.accrued_interest(b, date(2026, 3, 31)) == pytest.approx(60.0 * 60 / 360)


def test_accrued_act_365():
    b = bond(day_count="ACT/365")
    assert bd.accrued_interest(b, date(2026, 3, 18)) == pytest.approx(80.0 * 62 / 365)


def test_accrued_act_act_uses_the_period_length():
    b = bond(day_count="ACT/ACT")
    # 15-Jan -> 15-Jul 2026 is 181 days; settle 15-Mar is 59 days in
    assert bd.accrued_interest(b, date(2026, 3, 15)) == pytest.approx(40.0 * 59 / 181)


def test_accrued_zero_outside_life():
    assert bd.accrued_interest(bond(), date(2019, 1, 1)) == 0.0
    assert bd.accrued_interest(bond(), date(2030, 1, 15)) == 0.0


def test_holding_value_clean_plus_accrued():
    v = bd.holding_value(bond(), 10, 101.5, date(2026, 3, 15))
    assert v["clean"] == pytest.approx(10 * 1000 * 1.015)
    assert v["accrued"] == pytest.approx(10 * 80 * 60 / 360)
    assert v["dirty"] == pytest.approx(v["clean"] + v["accrued"])


# --- coupon matching -----------------------------------------------------------------------------

def test_match_coupons_gross_net_and_unexplained():
    due = bd.coupons_due(bond(), 10, date(2026, 1, 15), date(2026, 12, 31))    # Jul-15, Jan-15 excluded
    assert due == [(date(2026, 7, 15), 400.0)]
    got = [(date(2026, 7, 16), 360.0), (date(2026, 8, 1), 55.0)]               # net of 10% TDS; a stray credit
    m = bd.match_coupons(due, got, tds_rate=0.10)
    assert m["matched"] == [(date(2026, 7, 15), 400.0, date(2026, 7, 16), 360.0)]
    assert m["unmatched_due"] == [] and m["unexplained_credits"] == [(date(2026, 8, 1), 55.0)]


def test_match_coupons_reports_missing_and_never_double_matches():
    due = [(date(2026, 1, 15), 400.0), (date(2026, 7, 15), 400.0)]
    m = bd.match_coupons(due, [(date(2026, 1, 15), 400.0)])
    assert len(m["matched"]) == 1 and m["unmatched_due"] == [(date(2026, 7, 15), 400.0)]
    late = bd.match_coupons([(date(2026, 1, 15), 400.0)], [(date(2026, 2, 20), 400.0)])
    assert late["matched"] == [] and len(late["unexplained_credits"]) == 1       # outside the window


# --- yield, model price, Estimate -----------------------------------------------------------------

def test_par_price_at_coupon_yield_and_monotonic():
    b = bond()
    assert bd.clean_price_from_yield(b, 0.08, date(2026, 1, 15)) == pytest.approx(100.0, abs=1e-9)
    p7, p8, p9 = (bd.clean_price_from_yield(b, y, date(2026, 3, 15)) for y in (0.07, 0.08, 0.09))
    assert p7 > p8 > p9


def test_yield_round_trip():
    b = bond()
    for y in (0.05, 0.0825, 0.12):
        p = bd.clean_price_from_yield(b, y, date(2026, 3, 15))
        assert bd.yield_from_clean_price(b, p, date(2026, 3, 15)) == pytest.approx(y, abs=1e-9)


def test_price_hand_check_one_period():
    # 1 coupon left: 40 + 1000 on 15-Jul-2030 style: settle on prior coupon date, y=8%/2 -> par
    b = bond(issue_date=date(2025, 1, 15), maturity_date=date(2026, 1, 15))
    assert bd.clean_price_from_yield(b, 0.10, date(2025, 7, 15)) == pytest.approx((1040 / 1.05) / 10)


def test_model_price_is_a_labelled_estimate():
    e = bd.model_price(bond(), 0.07, date(2026, 3, 15), "assumed")
    assert isinstance(e, est.Estimate) and "DCF at yield 7.0000%" in e.method and "assumed" in e.method
    assert "estimate" in e.render() and e.as_of == date(2026, 3, 15)
    assert 100 < e.value < 110


def test_estimate_refuses_to_be_a_bare_number():
    e = est.make(123.456, "test method", {"a": 1}, date(2026, 1, 1))
    with pytest.raises(TypeError):
        float(e)
    with pytest.raises(TypeError):
        f"{e:.2f}"
    with pytest.raises(TypeError):
        e + 1
    with pytest.raises(TypeError):
        1 * e
    with pytest.raises(TypeError):
        e > 100
    assert "test method" in f"{e}" and "123.46" in str(e) and e.value == 123.456
    assert est.inputs_hash({"a": 1}) == est.inputs_hash({"a": 1}) != est.inputs_hash({"a": 2})


# --- SGB ------------------------------------------------------------------------------------------------

SGB = gold.SGB("IN0020990001", "SYNTH-I", date(2020, 6, 15), date(2028, 6, 15), 5000.0)


def test_sgb_interest_schedule():
    s = gold.interest_schedule(SGB, 10)
    assert len(s) == 16 and s[0] == (date(2020, 12, 15), pytest.approx(625.0)) and s[-1][0] == date(2028, 6, 15)
    assert all(a == pytest.approx(625.0) for _, a in s)                    # 10 g x 5000 x 2.5% / 2
    assert [d for d, _ in gold.interest_schedule(SGB, 10, held_from=date(2027, 6, 15))] == \
        [date(2027, 12, 15), date(2028, 6, 15)]


def _gold_rates(con, rows):
    prices.load_gold(con, pd.DataFrame(rows, columns=["date", "session", "metal", "rate", "unit"]))


def test_sgb_redemption_price_is_three_day_average(con):
    # redeem Mon 2028-06-12: previous 3 business days are Fri 9, Thu 8, Wed 7
    _gold_rates(con, [(date(2028, 6, 9), "PM", "gold999", 100_000.0, "per_10g"),
                      (date(2028, 6, 8), "PM", "gold999", 100_300.0, "per_10g"),
                      (date(2028, 6, 7), "PM", "gold999", 100_600.0, "per_10g"),
                      (date(2028, 6, 6), "PM", "gold999", 1.0, "per_10g")])
    assert gold.redemption_price(con, date(2028, 6, 12)) == pytest.approx(10_030.0)
    with pytest.raises(gold.GoldError, match="missing"):
        gold.redemption_price(con, date(2028, 6, 13))


@pytest.mark.parametrize("red,original,premature,exempt", [
    (date(2028, 6, 15), True, None, True),       # original, to maturity, after 1-Apr-2026
    (date(2028, 6, 15), False, None, False),     # secondary buyer, after 1-Apr-2026
    (date(2026, 3, 31), False, False, True),     # before the Finance Act 2026 change: any holder
    (date(2026, 12, 15), True, None, False),     # premature (before 2028 maturity): taxable
])
def test_sgb_redemption_exemption_rule(red, original, premature, exempt):
    r = gold.redemption_outcome(SGB, 10, red, 9000.0, 5000.0, date(2020, 6, 15) if original else date(2025, 1, 1),
                                original_subscriber=original, premature=premature)
    assert r["exempt"] is exempt
    assert r["gain"] == pytest.approx(40_000.0)
    assert r["taxable_gain"] == (0.0 if exempt else pytest.approx(40_000.0))


def test_sgb_secondary_buyer_pays_long_term_rate_after_a_year():
    r = gold.redemption_outcome(SGB, 10, date(2028, 6, 15), 9000.0, 7000.0, date(2026, 5, 1),
                                original_subscriber=False)
    assert (r["exempt"], r["holding"], r["rate"], r["rule"]) == (False, "LT", 0.125, "sgb_listed")
    short = gold.redemption_outcome(SGB, 10, date(2027, 1, 1), 9000.0, 7000.0, date(2026, 5, 1),
                                    original_subscriber=False, premature=False)
    assert short["holding"] == "ST" and short["rate"] == "slab"


def test_sgb_store_round_trip(con):
    assert gold.load_sgb(con, [SGB], "synthetic") == 1 and gold.get_sgb(con, SGB.isin) == SGB
    assert gold.get_sgb(con, "nope") is None


def test_bond_store_round_trip(con):
    assert bd.load_bonds(con, [bond()], "synthetic") == 1 and bd.get_bond(con, bond().isin) == bond()


# --- physical gold ----------------------------------------------------------------------------------------

def test_physical_keys_and_classification():
    assert gold.physical_key("916") == "PHYS:GOLD916" and gold.purity_of("PHYS:GOLD916") == "916"
    with pytest.raises(gold.GoldError):
        gold.physical_key("800")
    with pytest.raises(gold.GoldError):
        gold.purity_of("INE000000011")
    assert ins.classify("PHYS:GOLD999")[:2] == ("gold_physical", ins.PHYSICAL_GOLD)


def test_value_physical_at_ibja(con):
    _gold_rates(con, [(date(2026, 10, 5), "PM", "gold916", 135_749.0, "per_10g")])
    v = gold.value_physical(con, "PHYS:GOLD916", 25.0, date(2026, 10, 6))
    assert v["value"] == pytest.approx(2.5 * 135_749.0) and v["stale"] is False
    assert "excludes GST" in v["basis"]
    with pytest.raises(LookupError):
        gold.value_physical(con, "PHYS:GOLD999", 5.0, date(2026, 10, 6))


# --- a synthetic portfolio values correctly ------------------------------------------------------------------

def test_synthetic_portfolio_values_correctly(con):
    d0, asof = date(2026, 1, 5), date(2026, 3, 15)
    A = "ACC"
    log = EventLog([
        Event("deposit", A, d0, amount=5_000_000.0),
        Event("buy", A, d0, isin="PHYS:GOLD999", qty=20.0, price=14_000.0, fees={"making": 5_000.0}),
        Event("buy", A, d0, isin=SGB.isin, qty=8.0, price=14_500.0),
        Event("buy", A, d0, isin=bond().isin, qty=10.0, price=1_010.0),
    ])
    led = Ledger.replay(log)
    prices.load_gold(con, pd.DataFrame([(date(2026, 3, 13), "PM", "gold999", 149_000.0, "per_10g")],
                                       columns=["date", "session", "metal", "rate", "unit"]))
    prices.load_bhavcopy(con, pd.DataFrame([(date(2026, 3, 13), SGB.isin, "GB", 15_000.0),
                                            (date(2026, 3, 13), bond().isin, "N1", 102.0)],
                                           columns=["date", "isin", "series", "close"]))
    pos = {i: q for (a, i), q in led.positions().items()}
    gold_v = gold.value_physical(con, "PHYS:GOLD999", pos["PHYS:GOLD999"], asof)["value"]
    sgb_v = pos[SGB.isin] * prices.latest_price(con, SGB.isin, asof).value
    bond_v = bd.holding_value(bond(), pos[bond().isin], prices.latest_price(con, bond().isin, asof).value, asof)
    assert gold_v == pytest.approx(2.0 * 149_000.0)
    assert sgb_v == pytest.approx(8 * 15_000.0)
    assert bond_v["dirty"] == pytest.approx(10 * 1000 * 1.02 + 10 * 80 * 60 / 360)
    total = gold_v + sgb_v + bond_v["dirty"] + led.cash_balance(A)
    cost = 20 * 14_000 + 5_000 + 8 * 14_500 + 10 * 1_010
    assert led.cash_balance(A) == pytest.approx(5_000_000 - cost)
    assert total == pytest.approx(298_000 + 120_000 + 10_200 + 10 * 80 * 60 / 360 + 5_000_000 - cost)
