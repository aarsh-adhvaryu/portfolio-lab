"""PURPOSE parsing for the NSE corporate-actions feed (charter §15, 2026-09-16).

Every subject string below is copied verbatim from the live feed, including
NSE's own typos ("Face Valus Split") and spacing variants.
"""
from datetime import date

import pandas as pd
import pytest

from pflab.data import nse_corporate_actions as nca

BONUS_1_1 = "Bonus 1:1"
SPLIT_10_2 = "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"


def _f(subject):
    return nca.parse_purpose(subject)


# -- bonuses ------------------------------------------------------------
@pytest.mark.parametrize("subject", [
    "Bonus 1:1", "Bonus 1 : 1", "Bonus 1: 1", "Bonus - 1:1", "Bonus Issue 1:1",
])
def test_bonus_one_for_one_spacing_variants(subject):
    """a new shares for every b held: 1:1 doubles the count, so price halves."""
    assert _f(subject) == [("bonus", 0.5)]


def test_bonus_ratios():
    assert _f("Bonus 1:2") == [("bonus", pytest.approx(2 / 3))]
    assert _f("Bonus 2:1") == [("bonus", pytest.approx(1 / 3))]
    assert _f("Bonus 1:6") == [("bonus", pytest.approx(6 / 7))]
    assert _f("Bonus 10:1") == [("bonus", pytest.approx(1 / 11))]


@pytest.mark.parametrize("subject,want", [
    ("Bon-1:1", 0.5),
    ("Bon 1:1", 0.5),
    ("Bon-2:1", 1 / 3),
    ("Bon-12:1", 1 / 13),
    ("Bon-3:2", 0.4),
])
def test_pre_2010_bon_abbreviation(subject, want):
    """NSE abbreviated Bonus to "Bon" before ~2010. Missing it left the split
    half of a compound action applied on its own, which is worse than missing
    both: the price was adjusted by the wrong amount."""
    assert dict(_f(subject))["bonus"] == pytest.approx(want)


@pytest.mark.parametrize("subject,bonus,split", [
    ("Bonus 1 : 1 / Face Value Split From Rs 10/- Each To Rs 2/- Each", 0.5, 0.2),
    ("Spl-Rs10 To Rs2/Bonus-1:2", 2 / 3, 0.2),
    ("Bonus 1:1 / Face Value Split From 10/- To Face Value 2/-", 0.5, 0.2),
    ("Bonus-1:1 Spl-Rs 5/ To 2/", 0.5, 0.4),
    ("Fv Spl-Rs10tors2/Bon-1:1", 0.5, 0.2),
    ("Fv Spl-Rs2 To Re1/Bon-2:1", 1 / 3, 0.5),
    ("Fv Spl-Rs10tore1/Bon-3:2", 0.4, 0.1),
    ("Bon 1:1/Fv Spl Rs.5tors.2", 0.5, 0.4),
])
def test_compound_action_phrasings_from_the_live_feed(subject, bonus, split):
    """Each of these was mis-parsed at some point, yielding one leg instead of
    two. Verified against the actual price jump on the ex-date."""
    got = dict(_f(subject))
    assert got["bonus"] == pytest.approx(bonus)
    assert got["split"] == pytest.approx(split)


def test_bonus_debenture_is_not_a_share_bonus():
    """Bonus debentures issue debt; the share count is unchanged."""
    assert _f("Scheme Of Arrangement - Bonus Debentures 1:1") == []


def test_bonus_inside_a_longer_subject():
    """Real: WIDGETCO 2015-06-15."""
    s = "Annual General Meeting/ Dividend - Rs 29.50/- Per Share And Bonus 1:1"
    assert _f(s) == [("bonus", 0.5)]


# -- splits -------------------------------------------------------------
def test_face_value_split_10_to_2():
    assert _f(SPLIT_10_2) == [("split", pytest.approx(0.2))]


@pytest.mark.parametrize("subject,want", [
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share", 0.1),
    ("Face Value Split (Sub-Division): From Rs 10/- Per Share To Re 1/- Per Share", 0.1),
    ("Face Value Split From Rs 10 To Rs 1", 0.1),
    ("Face Value Split Rs 10 To Rs 1", 0.1),
    ("Face Value Split (Sub-Division) - From Rs 5/- Per Share To Re 1/- Per Share", 0.2),
    ("Face Value Split (Sub-Division) - From Rs 2/- Per Share To Re 1/- Per Share", 0.5),
])
def test_split_phrasing_variants(subject, want):
    assert _f(subject) == [("split", pytest.approx(want))]


def test_nse_typo_face_valus_split_is_still_parsed():
    s = "Face Valus Split (Sub-Division) - From Rs 10/- Per To Rs 2/- Per Share"
    assert _f(s) == [("split", pytest.approx(0.2))]


def test_record_date_revised_suffix_is_ignored():
    s = "Face Value Split From Rs 10 To Re 1 (Record Date Revised)"
    assert _f(s) == [("split", pytest.approx(0.1))]


def test_consolidation_is_not_treated_as_a_split():
    """A reverse split raises the face value; it is not a sub-division and is
    deliberately not parsed, so it surfaces as a plausibility halt instead."""
    assert _f("Face Value Consolidation From Re 1/- Per Share To Rs 10/- Per Share") == []


def test_dividend_alone_yields_nothing():
    assert _f("Interim Dividend - Rs 1.50/- Per Share") == []
    assert _f("Annual General Meeting") == []
    assert _f("") == []


# -- combined -----------------------------------------------------------
def test_bonus_and_split_on_one_ex_date_are_both_returned():
    s = ("Bonus 1:1 / Face Value Split From Rs 10/- Per Share "
         "To Rs 2/- Per Share")
    got = dict(_f(s))
    assert got["bonus"] == pytest.approx(0.5)
    assert got["split"] == pytest.approx(0.2)


def test_factors_multiply_same_day_actions():
    raw = pd.DataFrame({
        "isin": ["INE1"], "series": ["EQ"], "ex_date": [date(2015, 1, 5)],
        "subject": ["Bonus 1:1 / Face Value Split From Rs 10/- Per Share To Rs 2/- Per Share"]})
    out = nca.factors(raw=raw)
    assert len(out) == 1
    assert out.loc[0, "factor"] == pytest.approx(0.5 * 0.2)


def test_factors_filters_series_and_missing_isin():
    raw = pd.DataFrame({
        "isin": ["INE1", "IN0020100031", "-"],
        "series": ["EQ", "GS", "EQ"],
        "ex_date": [date(2015, 1, 5)] * 3,
        "subject": [BONUS_1_1, BONUS_1_1, BONUS_1_1]})
    out = nca.factors(raw=raw)
    assert list(out["isin"]) == ["INE1"]


def test_identical_duplicate_rows_do_not_compound():
    """NSE sometimes repeats a row; the factor must not be squared."""
    raw = pd.DataFrame({
        "isin": ["INE1", "INE1"], "series": ["EQ", "EQ"],
        "ex_date": [date(2015, 1, 5)] * 2, "subject": [BONUS_1_1, BONUS_1_1]})
    assert nca.factors(raw=raw).loc[0, "factor"] == pytest.approx(0.5)


def test_empty_feed_gives_the_right_columns():
    raw = pd.DataFrame({"isin": [], "series": [], "ex_date": [], "subject": []})
    out = nca.factors(raw=raw)
    assert list(out.columns) == ["isin", "ex_date", "factor", "bonus_factor"]


# -- PREVCLOSE-derived factors (charter §9 / §15, 2026-09-16) -----------
def _panel(rows):
    return pd.DataFrame(rows)


SUVEN = [  # the real shape: suspended for a demerger, resumes adjusted
    {"isin": "INE495B01038", "date": date(2020, 1, 20), "close": 304.20,
     "prev_close": 310.60},
    {"isin": "INE495B01038", "date": date(2020, 2, 3), "close": 26.95,
     "prev_close": 24.50},
]


def test_prevclose_factor_recovers_an_unparseable_demerger():
    """The feed row says only "Demerger" -- no ratio to parse."""
    out = nca.prevclose_factors(_panel(SUVEN))
    assert len(out) == 1
    assert out.loc[0, "factor"] == pytest.approx(24.50 / 304.20)
    assert out.loc[0, "source"] == "prevclose"


def test_prevclose_ignores_a_row_where_nse_adjusted_nothing():
    rows = [{"isin": "I1", "date": date(2020, 1, 1), "close": 100.0, "prev_close": 99.0},
            {"isin": "I1", "date": date(2020, 1, 2), "close": 60.0, "prev_close": 100.0}]
    assert nca.prevclose_factors(_panel(rows)).empty


def test_prevclose_skips_pairs_already_parsed_so_nothing_adjusts_twice():
    parsed = pd.DataFrame({"isin": ["INE495B01038"], "ex_date": [date(2020, 2, 3)],
                           "factor": [0.5]})
    assert nca.prevclose_factors(_panel(SUVEN), parsed).empty


def test_cash_credit_is_the_price_the_holder_lost():
    """§9: 100 shares at 304.20 becoming 26.95 is not a 91% loss; the holder
    receives (304.20 - 24.50) x 100 in cash, with no tax event."""
    row = nca.prevclose_factors(_panel(SUVEN)).iloc[0].to_dict()
    assert nca.cash_credit_per_share(row) == pytest.approx(304.20 - 24.50)
    assert nca.cash_credit_per_share(row) * 100 == pytest.approx(27970.0)


def test_purpose_factors_get_no_cash_credit():
    """A bonus changes the share count, not the cash balance."""
    assert nca.cash_credit_per_share({"source": "purpose", "prior_close": 100.0,
                                      "adj_prev_close": 50.0}) == 0.0


# -- dividend collision (§9, 2026-09-16) --------------------------------
def _extra(factor, prior, adj, isin="I1", d=date(2020, 1, 2)):
    return pd.DataFrame([{"isin": isin, "ex_date": d, "factor": factor,
                          "source": "prevclose", "prior_close": prior,
                          "adj_prev_close": adj}])


def test_dividend_wins_when_it_explains_the_drop():
    """CARERATING 2018-09-18: a 2.8% implied drop against a Rs 37 special
    dividend. Keeping both would credit the cash twice."""
    extra = _extra(0.9716, 1300.0, 1263.0)
    div = pd.DataFrame({"isin": ["I1"], "ex_date": [date(2020, 1, 2)],
                        "dividend_per_share": [37.0]})
    kept, rep = nca.resolve_dividend_collisions(extra, div)
    assert kept.empty
    assert (rep["coinciding"], rep["dividend_wins"], rep["factor_wins"]) == (1, 1, 0)
    assert rep["dividends_dropped"] == []      # the dividend is the one kept


def test_factor_wins_when_the_drop_dwarfs_the_dividend():
    """ZUARIIND 2021-04-27: a 31% drop with a Rs 1 dividend is a demerger that
    happens to share an ex-date."""
    extra = _extra(0.6921, 100.0, 69.21)
    div = pd.DataFrame({"isin": ["I1"], "ex_date": [date(2020, 1, 2)],
                        "dividend_per_share": [1.0]})
    kept, rep = nca.resolve_dividend_collisions(extra, div)
    assert len(kept) == 1 and rep["factor_wins"] == 1
    # the dividend must be removed, or its cash is counted twice
    assert rep["dividends_dropped"] == [("I1", "2020-01-02")]


def test_no_dividend_on_the_date_leaves_the_factor_alone():
    kept, rep = nca.resolve_dividend_collisions(_extra(0.5, 100.0, 50.0), pd.DataFrame(
        {"isin": ["I1"], "ex_date": [date(2021, 6, 6)], "dividend_per_share": [2.0]}))
    assert len(kept) == 1 and rep["coinciding"] == 0
