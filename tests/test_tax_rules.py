"""S2: dated tax rule tables. Synthetic checks against the sourced rows."""
from datetime import date, timedelta

import pytest

from pflab import _toml
from pflab.pm import instruments as ins
from pflab.tax import rules
from pflab.tax.rules import AmbiguousRule, RuleBook, RuleGap, lookup

TODAY = date(2026, 10, 6)  # fixed: the tables were verified this day
CLASSES = [c for c in ins.TAX_CLASSES if c != ins.REVIEW]
LISTED_ONLY = {ins.EQUITY, ins.BUSINESS_TRUST, ins.LISTED_NONEQUITY}


# --- sources -----------------------------------------------------------------

def test_every_row_has_source_and_verified_on():
    book = rules.load()
    n = 0
    for table, r in book.rows():
        n += 1
        where = f"{table}:{r.get('id')}"
        assert r.get("source_title"), where
        assert r.get("verification") in rules.VERIFICATIONS, where
        assert isinstance(r.get("verified_on"), date), where
        if r["verification"] != "unverified":
            assert str(r.get("source_url", "")).startswith("https://"), where
        else:
            assert r.get("note"), f"{where}: unverified rows must say what is open"
    assert n >= 25


def test_verified_on_not_stale():
    # PLAN §10: a row verified more than 13 months ago fails. Compared with the
    # real clock on purpose: it is the April re-verification reminder.
    for table, r in rules.load().rows():
        assert (date.today() - r["verified_on"]).days <= 396, f"{table}:{r['id']} is stale"


def test_rule_ids_unique():
    ids = [r["id"] for _, r in rules.load().rows()]
    assert len(ids) == len(set(ids))


# --- coverage and gaps -------------------------------------------------------

ACQ = [date(2015, 1, 1), date(2018, 1, 31), date(2018, 2, 1), date(2023, 3, 31),
       date(2023, 4, 1), date(2024, 7, 22), date(2026, 1, 1)]


def _transfer_dates():
    d = rules.COVERAGE_START
    while d <= TODAY:
        yield d
        d += timedelta(days=7)
    yield TODAY


@pytest.mark.parametrize("tax_class", CLASSES)
def test_lookup_covers_every_class_from_start_to_today(tax_class):
    listed_opts = [True] if tax_class in LISTED_ONLY else [True, False]
    for t in _transfer_dates():
        for a in ACQ:
            if a > t:
                continue
            for listed in listed_opts:
                r = lookup(tax_class, t, a, stt_paid=True, listed=listed)  # must not raise
                assert r.tax_class == tax_class


def test_equity_without_stt_covered():
    r = lookup(ins.EQUITY, TODAY, date(2025, 1, 1), stt_paid=False)
    assert r.stcg_rate == rules.SLAB and r.ltcg_rate == 0.125


def test_tables_never_overlap_on_the_whole_grid():
    for c in CLASSES:
        for t in (rules.COVERAGE_START, date(2025, 4, 1), TODAY):
            for a in ACQ:
                for stt in (True, False):
                    for listed in (True, False):
                        try:
                            lookup(c, t, a, stt_paid=stt, listed=listed)
                        except RuleGap:
                            pass  # a gap is fine here; AmbiguousRule would propagate


def test_gap_before_coverage_raises():
    with pytest.raises(RuleGap, match="before rule coverage"):
        lookup(ins.EQUITY, date(2024, 7, 22), date(2020, 1, 1))
    assert lookup(ins.EQUITY, date(2024, 7, 23), date(2020, 1, 1)).id == "equity_stt_paid"


def test_review_class_raises():
    with pytest.raises(RuleGap, match="REVIEW"):
        lookup(ins.REVIEW, TODAY, date(2025, 1, 1))


def test_uncovered_combination_raises():
    with pytest.raises(RuleGap):
        lookup(ins.BUSINESS_TRUST, TODAY, date(2025, 1, 1), stt_paid=False)


def test_overlapping_rows_raise():
    row = dict(id="a", tax_class="EQUITY", effective_from=date(2024, 7, 23), stcg_rate=0.2,
               source_url="u", source_title="t", verification="primary", verified_on=TODAY)
    book = RuleBook({"rule": [row, dict(row, id="b")]})
    with pytest.raises(AmbiguousRule):
        lookup("EQUITY", TODAY, date(2025, 1, 1), book=book)


# --- known cases (CBDT FAQ, PIB 2036604) -------------------------------------
# The FAQ has no numeric worked examples; these pin its stated rules.

def test_faq_q6_q7_equity_rates_and_exemption():
    r = lookup(ins.EQUITY, date(2025, 3, 3), date(2024, 1, 1))
    assert (r.stcg_rate, r.ltcg_rate, r.lt_months) == (0.20, 0.125, 12)
    assert rules.exemption(2025) == 125000.0 and rules.exemption(2027) == 125000.0
    with pytest.raises(RuleGap):
        rules.exemption(2024)


def test_holding_boundary_is_more_than_twelve_months():
    r = lookup(ins.EQUITY, date(2026, 6, 1), date(2025, 6, 1))
    assert r.holding(date(2025, 6, 1), date(2026, 6, 1)) == "ST"   # anniversary
    assert r.holding(date(2025, 6, 1), date(2026, 6, 2)) == "LT"
    assert r.rate(date(2025, 6, 1), date(2026, 6, 1)) == 0.20
    assert r.rate(date(2025, 6, 1), date(2026, 6, 2)) == 0.125


def test_faq_q3_q4_unlisted_and_gold_are_24_months():
    g = lookup(ins.PHYSICAL_GOLD, TODAY, date(2024, 1, 1))
    assert g.lt_months == 24 and g.holding(date(2024, 10, 1), date(2026, 10, 1)) == "ST"
    assert g.holding(date(2024, 10, 1), date(2026, 10, 2)) == "LT"
    m = lookup(ins.OTHER_MF, TODAY, date(2024, 1, 1), listed=False)
    assert m.lt_months == 24 and m.ltcg_rate == 0.125
    assert lookup(ins.LISTED_NONEQUITY, TODAY, date(2024, 1, 1)).lt_months == 12


def test_specified_mf_always_short_term_from_2023_04_01():
    r = lookup(ins.DEBT_MF, TODAY, date(2023, 4, 1))
    assert r.id == "debt_mf_specified" and r.lt_months is None
    assert r.holding(date(2023, 4, 1), TODAY) == "ST" and r.rate(date(2023, 4, 1), TODAY) == "slab"
    old = lookup(ins.DEBT_MF, TODAY, date(2023, 3, 31), listed=False)
    assert old.holding(date(2023, 3, 31), TODAY) == "LT" and old.ltcg_rate == 0.125
    assert lookup(ins.DEBT_MF, TODAY, date(2023, 3, 31), listed=True).lt_months == 12


def test_unlisted_debt_and_business_trust():
    u = lookup(ins.UNLISTED_DEBT, TODAY, date(2020, 1, 1), listed=False)
    assert u.holding(date(2020, 1, 1), TODAY) == "ST" and u.rate(date(2020, 1, 1), TODAY) == "slab"
    b = lookup(ins.BUSINESS_TRUST, TODAY, date(2025, 1, 1))
    assert (b.stcg_rate, b.ltcg_rate) == (0.20, 0.125)


def test_equity_rates_match_engine_policy():
    pol = _toml.load(rules.config_dir().parent / "tax_policy_in.toml")["tax"]
    r = lookup(ins.EQUITY, TODAY, date(2025, 1, 1))
    assert (r.stcg_rate, r.ltcg_rate, pol["long_term_months"]) == (pol["stcg_rate"], pol["ltcg_rate"], r.lt_months)
    assert rules.exemption(2027) == pol["ltcg_exemption"]
    assert rules.cess_rate(TODAY) == pol["cess"]


# --- SGB (Finance Act 2026 s.43) ---------------------------------------------

def test_sgb_redemption_rule_by_date_and_holder():
    before, after = date(2026, 3, 31), date(2026, 4, 1)
    assert rules.sgb_redemption_exempt(before, False) is True           # any holder, old law
    assert rules.sgb_redemption_exempt(before, True) is True
    assert rules.sgb_redemption_exempt(after, True) is True             # original, to maturity
    assert rules.sgb_redemption_exempt(after, False) is False           # secondary buyer
    assert rules.sgb_redemption_exempt(after, True, premature=True) is False


def test_sgb_rows_cite_finance_act_2026_section_43():
    row = next(r for r in rules.load().t["sgb_redemption"] if r["id"] == "sgb_redemption_fa2026")
    assert "s.43" in row["source_title"] and "30-Mar-2026" in row["source_title"]
    assert row["verification"] == "primary" and "till maturity" in row["text"]


def test_sgb_sale_on_exchange_is_ordinary_listed_gain():
    r = lookup(ins.SGB, TODAY, date(2025, 1, 1))
    assert (r.lt_months, r.ltcg_rate, r.stcg_rate) == (12, 0.125, "slab")


# --- general table -----------------------------------------------------------

def test_surcharge_cap_cess_basic_exemption():
    assert rules.surcharge_cap(date(2025, 6, 1)) == 0.15 and rules.surcharge_cap(TODAY) == 0.15
    assert rules.cess_rate(date(2025, 4, 1)) == 0.04
    assert rules.basic_exemption("new", TODAY) == 400000.0
    assert rules.basic_exemption("old", TODAY) == 250000.0
    with pytest.raises(RuleGap):
        rules.cess_rate(date(2025, 3, 31))


def test_buyback_promoter_rates_from_finance_act_2026():
    row = next(r for r in rules.load().t["buyback"] if r["id"] == "buyback_promoter_additional_tax")
    assert (row["stcg_additional_domestic_company"], row["stcg_additional_other"]) == (0.02, 0.10)
    assert (row["ltcg_additional_domestic_company"], row["ltcg_additional_other"]) == (0.095, 0.175)
