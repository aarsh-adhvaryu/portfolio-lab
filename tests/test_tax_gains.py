"""S12: realised gains by FY from ledger consumptions. Synthetic; parity with india_lots."""
import random
from datetime import date, timedelta

import pandas as pd
import pytest

from pflab.ledger.book import Ledger
from pflab.ledger.events import Event, EventLog
from pflab.ledger.lots import Consumption
from pflab.tax import gains as g
from pflab.tax.gains import CarriedLoss
from pflab.tax.india_lots import LotBook as EngineBook, TaxPolicy, fy_of

A = "ACC"
X = "INE000000011"


def cons(isin, acq, sell, qty, proceeds, cost, tax_class="EQUITY"):
    return Consumption(1, A, isin, acq, sell, qty, proceeds, cost, tax_class, 1)


def rows_of(*cs, **kw):
    return g.detail(cs, lambda i, _: None, **kw)


# --- classification ----------------------------------------------------------------------------

@pytest.mark.parametrize("tc,acq,sell,bucket,holding,rate", [
    ("EQUITY", date(2025, 1, 1), date(2025, 6, 1), "ST_111A", "ST", 0.20),
    ("EQUITY", date(2025, 1, 1), date(2026, 2, 1), "LT_112A", "LT", 0.125),
    ("EQUITY", date(2025, 6, 1), date(2026, 6, 1), "ST_111A", "ST", 0.20),        # exactly 12 months: short
    ("EQUITY", date(2025, 6, 1), date(2026, 6, 2), "LT_112A", "LT", 0.125),
    ("LISTED_NONEQUITY", date(2025, 1, 1), date(2026, 6, 1), "LT_112", "LT", 0.125),   # gold ETF
    ("LISTED_NONEQUITY", date(2026, 1, 1), date(2026, 6, 1), "ST_SLAB", "ST", "slab"),
    ("DEBT_MF", date(2023, 5, 1), date(2026, 6, 1), "ST_SLAB", "ST", "slab"),          # specified MF, always ST
    ("DEBT_MF", date(2023, 1, 1), date(2026, 6, 1), "LT_112", "LT", 0.125),            # pre-2023 listed? default listed
    ("BUSINESS_TRUST", date(2025, 1, 1), date(2026, 6, 1), "LT_112A", "LT", 0.125),
    ("SGB", date(2025, 1, 1), date(2026, 6, 1), "LT_112", "LT", 0.125),
    ("PHYSICAL_GOLD", date(2024, 9, 1), date(2026, 9, 2), "LT_112", "LT", 0.125),
    ("PHYSICAL_GOLD", date(2024, 9, 1), date(2026, 9, 1), "ST_SLAB", "ST", "slab"),    # 24 months exactly
])
def test_classification(tc, acq, sell, bucket, holding, rate):
    c = cons(X, acq, sell, 1, 120.0, 100.0, tc)
    r = g.classify(c, tc)
    assert (r["bucket"], r["holding"], r["rate"]) == (bucket, holding, rate) and r["gain"] == 20.0


def test_review_class_and_missing_class_raise():
    with pytest.raises(g.GainsError, match="unresolved"):
        rows_of(cons(X, date(2025, 1, 1), date(2026, 1, 1), 1, 1.0, 1.0, tax_class="REVIEW"))
    with pytest.raises(g.GainsError):
        rows_of(cons(X, date(2025, 1, 1), date(2026, 1, 1), 1, 1.0, 1.0, tax_class=None))


def test_sale_before_rule_coverage_raises():
    from pflab.tax.rules import RuleGap
    with pytest.raises(RuleGap):
        g.classify(cons(X, date(2024, 1, 1), date(2024, 7, 22), 1, 1.0, 1.0), "EQUITY")


def test_grandfathering_needs_fmv_and_uses_the_higher_cost():
    c = cons(X, date(2017, 5, 1), date(2026, 6, 1), 10, 5000.0, 2000.0)
    with pytest.raises(g.GainsError, match="FMV"):
        g.classify(c, "EQUITY")
    r = g.classify(c, "EQUITY", fmv_2018=lambda i: 300.0)          # FMV 3,000 < proceeds 5,000
    assert r["cost_used"] == 3000.0 and r["gain"] == 2000.0 and r["grandfathered"]
    r = g.classify(c, "EQUITY", fmv_2018=lambda i: 800.0)          # FMV 8,000 > proceeds: capped at proceeds
    assert r["cost_used"] == 5000.0 and r["gain"] == 0.0
    r = g.classify(c, "EQUITY", fmv_2018=lambda i: 100.0)          # FMV below actual cost: cost stays
    assert r["cost_used"] == 2000.0
    new = cons(X, date(2018, 2, 1), date(2026, 6, 1), 10, 5000.0, 2000.0)
    assert g.classify(new, "EQUITY")["grandfathered"] is False


# --- set-off, carry-forward ---------------------------------------------------------------------------

def net(realised, carried=(), fy=2027, **kw):
    ac, tx, out, exp = g.net_year(realised, list(carried), fy, **kw)
    return ac, tx, out, exp


def test_cbdt_style_basic_tax():
    # LT equity gain 300,000 in FY2026-27: exemption 125,000, taxable 175,000 at 12.5% = 21,875
    r = rows_of(cons(X, date(2025, 1, 1), date(2026, 8, 1), 100, 400_000.0, 100_000.0))
    res = g.settle_year(2027, r, [])
    assert res.exemption_used == 125_000.0 and res.taxable["LT_112A"] == 175_000.0
    assert res.tax_special == pytest.approx(21_875.0)
    st = g.settle_year(2027, rows_of(cons(X, date(2026, 5, 1), date(2026, 8, 1), 10, 15_000.0, 10_000.0)), [])
    assert st.tax_special == pytest.approx(1_000.0) and st.exemption_used == 0.0


def test_stcl_sets_off_stcg_then_ltcg_but_ltcl_only_ltcg():
    _, tx, out, _ = net({"ST_111A": -50_000, "ST_SLAB": 20_000, "LT_112A": 100_000})
    assert tx["ST_SLAB"] == 0 and tx["LT_112A"] == 70_000 and out == []        # 20k vs slab, 30k vs LT
    _, tx, out, _ = net({"ST_111A": 10_000, "LT_112A": -40_000})
    assert tx["ST_111A"] == 10_000 and [(c.long_term, c.amount) for c in out] == [(True, 40_000.0)]
    _, tx, out, _ = net({"LT_112": -30_000, "LT_112A": 50_000})
    assert tx["LT_112A"] == 20_000


def test_default_order_hits_111a_before_slab_and_112_before_112a():
    _, tx, _, _ = net({"ST_111A": 30_000, "ST_SLAB": 30_000, "LT_112A": -1, "LT_112": 0})   # no st loss: nothing moves
    assert tx["ST_111A"] == 30_000
    ac, tx, _, _ = net({"LT_112A": -20_000, "ST_111A": 5_000, "ST_SLAB": 0, "LT_112": 0})
    assert tx["ST_111A"] == 5_000                                                               # LT loss never touches ST
    ac, tx, out, _ = net({"ST_111A": 10_000, "ST_SLAB": -4_000, "LT_112": 8_000, "LT_112A": 8_000})
    assert tx["ST_111A"] == 6_000 and tx["ST_SLAB"] == 0                                        # loss in one ST bucket vs another
    ac, tx, _, _ = net({"ST_111A": -9_000, "LT_112": 8_000, "LT_112A": 8_000})
    assert (tx["LT_112"], tx["LT_112A"]) == (0.0, 7_000.0)                                      # 112 absorbed first


def test_brought_forward_oldest_first_and_by_character():
    carried = [CarriedLoss(2026, True, 30_000.0), CarriedLoss(2025, False, 10_000.0)]
    _, tx, out, _ = net({"ST_111A": 4_000, "LT_112A": 50_000}, carried)
    # oldest (FY2025 short-term 10k): 4k vs ST then 6k vs LT; then FY2026 long-term 30k vs LT
    assert tx["ST_111A"] == 0 and tx["LT_112A"] == 50_000 - 6_000 - 30_000 and out == []
    # a long-term b/f loss cannot absorb short-term gains
    _, tx, out, _ = net({"ST_111A": 9_000}, [CarriedLoss(2026, True, 5_000.0)])
    assert tx["ST_111A"] == 9_000 and [(c.long_term, c.amount) for c in out] == [(True, 5_000.0)]


def test_loss_expires_after_eight_years():
    ok = net({"LT_112A": 10_000}, [CarriedLoss(2026, True, 6_000.0)], fy=2034)       # 8 years after: usable
    assert ok[1]["LT_112A"] == 4_000 and ok[3] == []
    late = net({"LT_112A": 10_000}, [CarriedLoss(2026, True, 6_000.0)], fy=2035)     # 9: gone
    assert late[1]["LT_112A"] == 10_000 and [(c.origin_fy, c.amount) for c in late[3]] == [(2026, 6_000.0)]


def test_current_year_loss_carries_by_character_and_ages_through_empty_years():
    r = rows_of(cons(X, date(2026, 5, 1), date(2026, 8, 1), 10, 8_000.0, 10_000.0),          # ST loss 2,000
                cons(X, date(2024, 9, 1), date(2026, 9, 1), 10, 7_000.0, 10_000.0))          # LT loss 3,000
    res = g.settle_all(r, first_fy=2027, last_fy=2029)
    assert [(c.origin_fy, c.long_term, c.amount) for c in res[0].carried_out] == [(2027, False, 2_000.0), (2027, True, 3_000.0)]
    assert len(res) == 3 and res[2].carried_out == res[0].carried_out                        # untouched, still alive
    assert g.carry_forward_rows(res[0]) == [(2027, "ST", 2_000.0, 2035), (2027, "LT", 3_000.0, 2035)]


def test_opening_losses_from_prior_returns_are_used():
    r = rows_of(cons(X, date(2025, 1, 1), date(2026, 8, 1), 100, 150_000.0, 100_000.0))     # LT gain 50k
    res = g.settle_all(r, opening_losses=[CarriedLoss(2026, True, 20_000.0)])
    assert res[0].fy == 2027 and res[0].exemption_used == 30_000.0 and res[0].taxable["LT_112A"] == 0.0 and res[0].tax_special == 0.0


def test_exemption_applies_to_112a_only():
    r = rows_of(cons("INF1", date(2025, 1, 1), date(2026, 8, 1), 1, 200_000.0, 0.0, "LISTED_NONEQUITY"))
    res = g.settle_year(2027, r, [])
    assert res.exemption_used == 0.0 and res.tax_special == pytest.approx(25_000.0)


def test_slab_amounts_reported_for_s13():
    r = rows_of(cons("INF2", date(2025, 1, 1), date(2025, 9, 1), 1, 60_000.0, 50_000.0, "DEBT_MF"))
    res = g.settle_year(2026, r, [])
    assert res.slab_income == 10_000.0 and res.tax_special == 0.0


# --- parity with india_lots on random equity histories ----------------------------------------------------------

@pytest.mark.parametrize("seed", range(25))
def test_parity_with_engine_over_several_fys(seed):
    rng = random.Random(seed)
    isins = ["INE00000000%d" % i for i in range(3)]
    eng, ev = EngineBook(TaxPolicy()), [Event("deposit", A, date(2024, 1, 1), amount=1e12)]
    held = {i: 0 for i in isins}
    day = date(2024, 8, 1)
    for _ in range(90):
        day += timedelta(days=rng.randint(1, 25))
        i = rng.choice(isins)
        price = round(rng.uniform(40, 400), 2)
        costs = round(rng.uniform(0, 30), 2)
        if held[i] == 0 or rng.random() < 0.55:
            q = rng.randint(1, 150)
            eng.buy(i, day, q, price, costs)
            ev.append(Event("buy", A, day, isin=i, qty=q, price=price, fees={"x": costs}))
            held[i] += q
        else:
            q = rng.randint(1, held[i])
            eng.sell(i, day, q, price, costs)
            ev.append(Event("sell", A, day, isin=i, qty=q, price=price, fees={"x": costs}))
            held[i] -= q
    led = Ledger.replay(EventLog(ev))
    rows = g.detail(led.realised, lambda i, _: "EQUITY")
    last = fy_of(day)
    mine = g.settle_all(rows, first_fy=2025, last_fy=last)
    for res in mine:
        e = eng.settle_fy(res.fy)
        assert res.stcg_taxable == pytest.approx(e.stcg_taxable, abs=1e-6)
        assert res.ltcg_taxable_before_exemption + res.exemption_used == pytest.approx(e.ltcg_taxable, abs=1e-6)
        assert res.tax_special * 1.04 == pytest.approx(e.tax_capital, abs=1e-6)
        assert sorted((c.origin_fy, c.long_term, round(c.amount, 6)) for c in res.carried_out) == \
            sorted((c.origin_fy, c.long_term, round(c.amount, 6)) for c in e.carried_forward)
