"""S64 Phase 6 item 1: the foreign-tax rows are sourced and dated; an unconfirmed row is refused."""
from datetime import date

import pytest

from pflab.tax import foreign as fx


def test_every_row_has_a_source_a_date_and_a_known_verification():
    for fid, r in fx.rows().items():
        assert r["source_url"].startswith("https://") and r["source_title"] and r["verified_on"] == date(2026, 10, 27), fid
        assert r["verification"] in ("primary", "secondary", "unverified") and r["source_kind"], fid
    assert {"lrs_limit_usd", "tcs_lrs_threshold_inr", "tcs_lrs_rate_investment", "cg_foreign_long_term_months", "fx_conversion_rule",
            "dtaa_dividend_withholding", "us_estate_tax_nra_threshold_usd", "schedule_fa_period"} <= set(fx.rows())


def test_an_unverified_row_is_never_used(tmp_path):
    p = tmp_path / "f.toml"
    p.write_text('[[fact]]\nid = "x"\nvalue = 1\nsource_url = "https://a"\nsource_title = "t"\nverification = "unverified"\nverified_on = 2026-10-27\n')
    with pytest.raises(fx.Unconfirmed):
        fx.fact("x", p)
    with pytest.raises(KeyError):
        fx.fact("nope")


def test_tcs_is_20_percent_of_what_goes_above_10_lakh_in_the_year():
    assert fx.tcs(0, 800_000)["tcs_rs"] == 0
    t = fx.tcs(800_000, 400_000)                                 # 12 lakh in all: 2 lakh above the threshold
    assert t["tcs_rs"] == 40_000 and t["taxable_rs"] == 200_000 and "estimate" in t["label"]
    assert fx.tcs(1_500_000, 100_000)["tcs_rs"] == 20_000        # already above: the whole new amount
    assert fx.lrs_room(40_000) == 210_000


def test_holding_class_is_more_than_24_months_and_gain_tax_follows_it():
    assert fx.holding_class(date(2024, 8, 10), date(2026, 8, 10)) == "short"        # exactly 24 months: not MORE than
    assert fx.holding_class(date(2024, 8, 10), date(2026, 8, 11)) == "long"
    assert fx.holding_class(date(2024, 2, 29), date(2026, 3, 1)) == "long"          # leap-day purchase
    lt = fx.gain_tax(100_000, date(2023, 1, 5), date(2026, 2, 1), slab=0.30)
    assert lt["class"] == "long" and lt["tax_rs"] == 12_500 and "cess" in lt["excludes"]
    st = fx.gain_tax(100_000, date(2025, 6, 1), date(2026, 2, 1), slab=0.30)
    assert st["class"] == "short" and st["tax_rs"] == 30_000
    assert fx.gain_tax(-5_000, date(2025, 6, 1), date(2026, 2, 1), slab=0.30)["tax_rs"] == 0
    with pytest.raises(fx.Unconfirmed):
        fx.gain_tax(1, date(2020, 1, 1), date(2024, 7, 1), slab=0.3)


def test_dividend_withholding_and_the_conversion_date_and_estate_note():
    assert fx.dividend_withholding(100.0)["withheld_usd"] == 25.0 and fx.dividend_withholding(100.0, w8ben=False)["rate"] == 0.30
    assert fx.fx_date(date(2026, 3, 15)) == date(2026, 2, 28) and fx.fx_date(date(2026, 1, 2)) == date(2025, 12, 31)
    assert fx.estate_exposure(50_000) is None
    assert "no estate-tax treaty" in fx.estate_exposure(80_000)
