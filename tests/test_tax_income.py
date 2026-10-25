"""S13: income tax under both regimes, advance tax, dividend TDS, proposed sales. Hand-worked
numbers; rates come from the dated tables (primary sources in configs/tax/income.toml)."""
from datetime import date

import pytest

from pflab.ledger.events import Event, EventLog
from pflab.ledger.lots import LotError
from pflab.tax import gains as gn
from pflab.tax import income as inc
from pflab.tax import proposed as pr
from pflab.tax import rules
from pflab.tax.income import YearInputs

A, X = "ACC", "INE000000011"
FY = 2027


def y(**kw):
    return YearInputs(FY, **kw)


# --- slab tables from the Acts -----------------------------------------------------------------

def test_slab_tables_match_the_gazette_texts():
    on = date(2026, 10, 1)
    new = rules.slab_rates("new", on)
    assert new == [(400000, 0.0), (800000, 0.05), (1200000, 0.10), (1600000, 0.15),
                   (2000000, 0.20), (2400000, 0.25), (None, 0.30)]
    assert rules.tax_on_slabs(2_400_000, new) == pytest.approx(4_000_000 * 0 + 20_000 + 40_000 + 60_000 + 80_000 + 100_000)
    assert rules.tax_on_slabs(3_000_000, new) == pytest.approx(300_000 + 180_000)
    assert rules.slab_rates("old", on, "under60") == [(250000, 0.0), (500000, 0.05), (1000000, 0.20), (None, 0.30)]
    assert rules.tax_on_slabs(1_000_000, rules.slab_rates("old", on)) == 112_500.0          # Act: 1,12,500 at 10 lakh
    assert rules.slab_rates("old", on, "80+")[0] == (500000, 0.0)
    assert rules.slab_rates("old", on, "60-79")[0] == (300000, 0.0)
    with pytest.raises(rules.RuleGap):
        rules.slab_rates("new", date(2026, 3, 31))                 # tax year 2025-26 new-regime slabs not read


def test_slab_helper_edge_cases():
    r = rules.slab_rates("new", date(2026, 10, 1))
    assert rules.tax_on_slabs(0, r) == 0 and rules.tax_on_slabs(400_000, r) == 0
    assert rules.tax_on_slabs(400_001, r) == pytest.approx(0.05)


# --- new regime hand cases --------------------------------------------------------------------------

def test_new_regime_ten_lakh_is_nil_after_rebate():
    r = inc.compute(y(other_income=1_000_000.0), "new")
    assert r.slab_tax == pytest.approx(40_000.0) and r.rebate == pytest.approx(40_000.0)
    assert r.total_tax == 0.0 and r.balance == 0.0


def test_new_regime_marginal_rebate_just_above_twelve_lakh():
    r = inc.compute(y(other_income=1_250_000.0), "new")
    assert r.slab_tax == pytest.approx(20_000 + 40_000 + 7_500)
    assert r.rebate == pytest.approx(67_500 - 50_000)               # tax over the excess income, per s.156(2)(b)
    assert r.cess == pytest.approx(50_000 * 0.04) and r.total_tax == pytest.approx(52_000.0)


def test_new_regime_thirteen_lakh_no_rebate():
    r = inc.compute(y(other_income=1_300_000.0), "new")
    assert r.slab_tax == pytest.approx(20_000 + 40_000 + 15_000) and r.rebate == 0.0
    assert r.total_tax == pytest.approx(75_000 * 1.04)


def test_unused_basic_exemption_absorbs_equity_ltcg():
    # A typical year: small slab income, LTCG 3 lakh: the 4 lakh basic exemption absorbs all of it
    g = _gains({"LT_112A": 300_000.0})
    r = inc.compute(y(dividends_gross=20_000.0, interest_gross=30_000.0, gains=g), "new")
    assert r.slab_income == 50_000.0 and r.absorbed["LT_112A"] == pytest.approx(300_000.0)
    assert r.special_tax == 0.0 and r.total_tax == 0.0
    assert any("unused basic exemption" in n for n in r.notes)


def test_partial_absorption_then_exemption_then_rate():
    g = _gains({"LT_112A": 300_000.0})
    r = inc.compute(y(other_income=300_000.0, gains=g), "new")          # shortfall 1,00,000
    assert r.absorbed["LT_112A"] == pytest.approx(100_000.0)
    assert r.special_gains["LT_112A"] == pytest.approx(75_000.0)        # 3,00,000 - 1,00,000 - 1,25,000
    assert r.special_tax == pytest.approx(9_375.0) and r.rebate == 0.0
    assert r.total_tax == pytest.approx(9_375.0 * 1.04)


def test_absorption_order_is_111a_then_112_then_112a():
    g = _gains({"ST_111A": 50_000.0, "LT_112": 40_000.0, "LT_112A": 200_000.0})
    r = inc.compute(y(other_income=300_000.0, gains=g), "new")          # shortfall 1,00,000
    assert r.absorbed == {"ST_111A": 50_000.0, "LT_112": 40_000.0, "LT_112A": 10_000.0}


def test_rebate_never_reduces_special_rate_tax():
    g = _gains({"ST_111A": 400_000.0})
    r = inc.compute(y(other_income=500_000.0, gains=g), "new")          # total 9 lakh, under the 12 lakh limit
    assert r.slab_tax == pytest.approx(5_000.0) and r.special_tax == pytest.approx(80_000.0)
    assert r.rebate == pytest.approx(5_000.0)                           # capped at the slab-rate tax: s.156(3)
    assert r.total_tax == pytest.approx(80_000.0 * 1.04)


def test_slab_taxed_gains_are_income_at_slab():
    g = _gains({"ST_SLAB": 100_000.0})
    r = inc.compute(y(other_income=500_000.0, gains=g), "new")
    assert r.slab_income == 600_000.0 and r.slab_tax == pytest.approx(10_000.0)


# --- old regime --------------------------------------------------------------------------------------------

def test_old_regime_hand_cases():
    r = inc.compute(y(other_income=800_000.0), "old")
    assert r.slab_tax == pytest.approx(12_500 + 60_000) and r.rebate == 0.0 and r.total_tax == pytest.approx(75_400.0)
    r = inc.compute(y(other_income=500_000.0), "old")                  # exactly 5 lakh: rebate wipes the tax
    assert r.slab_tax == 12_500.0 and r.rebate == 12_500.0 and r.total_tax == 0.0
    r = inc.compute(y(other_income=800_000.0, old_regime_deductions=150_000.0), "old")
    assert r.slab_income == 650_000.0 and r.slab_tax == pytest.approx(12_500 + 30_000)
    assert inc.compute(y(other_income=300_000.0, age="60-79"), "old").total_tax == 0.0
    assert inc.compute(y(other_income=300_000.0, age="under60"), "old").slab_tax == pytest.approx(2_500.0)


def test_old_regime_without_deductions_is_flagged_as_a_lower_bound():
    r = inc.compute(y(other_income=800_000.0), "old")
    assert any("NO deductions" in a for a in r.assumptions)
    assert not any("NO deductions" in a for a in inc.compute(y(other_income=800_000.0, old_regime_deductions=1.0), "old").assumptions)
    assert not any("NO deductions" in a for a in inc.compute(y(other_income=800_000.0), "new").assumptions)


def test_old_regime_deductions_ignored_in_new_regime():
    a = inc.compute(y(other_income=1_500_000.0, old_regime_deductions=150_000.0), "new")
    b = inc.compute(y(other_income=1_500_000.0), "new")
    assert a.total_tax == b.total_tax


# --- credits, compare, limits --------------------------------------------------------------------------------

def test_credits_make_balance_payable_or_refund():
    r = inc.compute(y(other_income=1_300_000.0, tds_credit=10_000.0, advance_tax_paid=20_000.0), "new")
    assert r.credits == 30_000.0 and r.balance == pytest.approx(75_000 * 1.04 - 30_000)
    r = inc.compute(y(dividends_gross=100_000.0, tds_credit=10_000.0), "new")
    assert r.total_tax == 0.0 and r.balance == pytest.approx(-10_000.0)        # refund of TDS


def test_compare_names_cheaper_but_leaves_the_choice():
    c = inc.compare(y(other_income=1_300_000.0))
    assert c["cheaper"] in ("new", "old") and c["saving"] == pytest.approx(abs(c["new"].total_tax - c["old"].total_tax))
    assert "The investor chooses" in c["decision"]
    assert c["new"].total_tax < c["old"].total_tax                  # 13 lakh, no deductions


def test_total_income_above_fifty_lakh_refuses():
    with pytest.raises(NotImplementedError, match="marginal relief"):
        inc.compute(y(other_income=5_000_001.0), "new")
    inc.compute(y(other_income=5_000_000.0), "new")


# --- advance tax, TDS ----------------------------------------------------------------------------------------------

def test_advance_tax_schedule():
    s = inc.advance_tax_schedule(100_000.0, 2027)
    assert s == [(date(2026, 6, 15), 15_000.0), (date(2026, 9, 15), 45_000.0),
                 (date(2026, 12, 15), 75_000.0), (date(2027, 3, 15), 100_000.0)]
    assert inc.advance_tax_schedule(9_999.0, 2027) == []                   # under Rs 10,000: not liable
    assert inc.advance_tax_schedule(10_000.0, 2027) != []
    assert inc.advance_tax_schedule(100_000.0, 2027, age=61) == []         # senior, no business: s.403(3)
    assert inc.advance_tax_schedule(100_000.0, 2027, age=61, has_business=True) != []


def test_dividend_tds_rule():
    assert inc.dividend_tds(8_000.0, paid_in_cash=False, on=date(2026, 8, 1)) == 0.0
    assert inc.dividend_tds(10_000.0, paid_in_cash=False, on=date(2026, 8, 1)) == 0.0
    assert inc.dividend_tds(10_001.0, paid_in_cash=False, on=date(2026, 8, 1)) == pytest.approx(1_000.1)
    assert inc.dividend_tds(2_000.0, paid_in_cash=True, on=date(2026, 8, 1)) == pytest.approx(200.0)


# --- proposed sale ----------------------------------------------------------------------------------------------------

def _tc(isin, _):
    return "EQUITY"


def _log(*extra):
    return EventLog([Event("deposit", A, date(2025, 1, 1), amount=1_000_000.0),
                     Event("buy", A, date(2025, 1, 10), isin=X, qty=100, price=100.0),
                     Event("buy", A, date(2026, 6, 1), isin=X, qty=100, price=120.0),
                     *extra])


def test_proposed_sale_by_lot_and_incremental_tax():
    kw = dict(other_income=900_000.0)                                  # uses up the basic exemption
    p = pr.proposed_sale(_log(), A, X, 150, 160.0, date(2026, 9, 10), _tc, **kw)
    lots = p["lots"].sort_values("acq_date")
    assert list(lots["qty"]) == [100, 50] and list(lots["holding"]) == ["LT", "ST"]     # FIFO per account
    assert list(lots["gain"]) == pytest.approx([6_000.0, 2_000.0])
    assert list(lots["rule"]) == ["equity_stt_paid", "equity_stt_paid"]
    # new regime: 20% of 2,000 = 400 special tax; slab tax 30,000 fully rebated; cess 4%
    assert p["new"]["tax_before"] == 0.0 and p["new"]["extra_tax"] == pytest.approx(400 * 1.04)
    assert p["proceeds"] == 150 * 160.0


def test_proposed_sale_equals_the_realised_result_after_the_sale():
    kw = dict(other_income=900_000.0)
    p = pr.proposed_sale(_log(), A, X, 150, 160.0, date(2026, 9, 10), _tc, fees={"stt": 24.0}, **kw)
    real = _log(Event("sell", A, date(2026, 9, 10), isin=X, qty=150, price=160.0, fees={"stt": 24.0}))
    after = pr.year_tax(real, 2027, _tc, **kw)
    for reg in ("new", "old"):
        assert p[reg]["tax_after"] == pytest.approx(after["regimes"][reg].total_tax)
    assert p["after"]["gains"].taxable == after["gains"].taxable
    assert sum(after["rows"]["gain"]) == pytest.approx(sum(p["lots"]["gain"]))


def test_proposed_sale_with_nothing_else_is_absorbed_by_the_basic_exemption():
    p = pr.proposed_sale(_log(), A, X, 150, 160.0, date(2026, 9, 10), _tc)      # no other income
    assert p["new"]["extra_tax"] == 0.0 and p["extra_tax_cheaper_regime"] == 0.0
    assert any("unused basic exemption" in n for n in p["after"]["regimes"]["new"].notes)


def test_proposed_sale_uses_carried_losses():
    kw = dict(other_income=900_000.0, opening_losses=[gn.CarriedLoss(2026, False, 2_000.0)])   # ST loss b/f
    p = pr.proposed_sale(_log(), A, X, 150, 160.0, date(2026, 9, 10), _tc, **kw)
    assert p["after"]["gains"].taxable["ST_111A"] == 0.0            # the 2,000 short-term gain is wiped
    assert p["new"]["extra_tax"] == 0.0


def test_proposed_oversell_raises_and_changes_nothing():
    log = _log()
    with pytest.raises(LotError):
        pr.proposed_sale(log, A, X, 201, 160.0, date(2026, 9, 10), _tc)
    assert len(log) == 3                                           # the real log is untouched


def test_year_tax_picks_up_dividends_interest_and_tds():
    log = _log(Event("dividend", A, date(2026, 8, 1), isin=X, amount=20_000.0, fees={"tds": 2_000.0}),
               Event("interest", A, date(2026, 9, 30), amount=30_000.0))
    t = pr.year_tax(log, 2027, _tc)
    yi = t["inputs"]
    assert (yi.dividends_gross, yi.interest_gross, yi.tds_credit) == (20_000.0, 30_000.0, 2_000.0)
    assert t["regimes"]["new"].balance == pytest.approx(-2_000.0)  # nothing owed; TDS comes back


# --- helpers ------------------------------------------------------------------------------------------------------------

def _gains(taxable_pre_exemption):
    """FYGains with the given pre-exemption amounts (LT_112A exemption applied as S12 does)."""
    t = {k: 0.0 for k in gn.ST_BUCKETS + gn.LT_BUCKETS}
    t.update(taxable_pre_exemption)
    ex_avail = rules.exemption(FY)
    used = min(t["LT_112A"], ex_avail)
    final = dict(t)
    final["LT_112A"] = t["LT_112A"] - used
    return gn.FYGains(FY, dict(t), dict(t), final, used, ex_avail, 0.0, final["ST_SLAB"], [], [])


def test_cli_pm_tax_prints_both_regimes(tmp_path, monkeypatch, capsys):
    from pflab import cli
    from pflab.ledger.events import save
    from pflab.pm import store
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    con = store.connect()
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, source, built_at)
                   VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, 'synthetic', now())""", [X])
    save(con, _log(Event("sell", A, date(2026, 9, 10), isin=X, qty=150, price=160.0)))
    con.close()
    assert cli.main(["pm", "tax", "--fy", "2027", "--other-income", "900000"]) == 0
    out = capsys.readouterr().out
    assert "-- new regime --" in out and "-- old regime --" in out and "TOTAL TAX" in out
    assert "the investor's" in out and "NO deductions" in out and "special-rate tax" in out
