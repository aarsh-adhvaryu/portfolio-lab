"""Dividend parsing and the yfinance basis correction (charter §8, sprint step 5).

Subjects are copied verbatim from the NSE corporate-actions feed.
"""
from datetime import date

import pandas as pd
import pytest

from pflab.data import dividends as dv


def _p(subject, fv=None):
    return dv.parse_dividend(subject, fv)


# -- absolute amounts ---------------------------------------------------
def test_simple_amount():
    assert _p("Dividend - Rs 5/- Per Share") == 5.0
    assert _p("Interim Dividend - Rs 1.50/- Per Share") == 1.5
    assert _p("Dividend - Re 1 Per Share") == 1.0


def test_amount_inside_a_longer_subject():
    """Real: INFY 2015-06-15, the row that also carries the 1:1 bonus."""
    s = "Annual General Meeting/ Dividend - Rs 29.50/- Per Share And Bonus 1:1"
    assert _p(s) == 29.5


def test_split_clause_is_not_read_as_a_dividend():
    """A sub-division reads 'From Rs 10/- Per Share To Rs 2/- Per Share',
    which would otherwise look like two dividends of 10 and 2."""
    s = ("Interim Dividend - Rs 1.50/- Per Share / Face Value Split - "
         "From Rs 10/- Per Share To Rs 2/- Per Share")
    assert _p(s) == 1.5


def test_split_only_row_yields_no_dividend():
    s = "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"
    assert _p(s) is None


def test_two_dividends_on_one_ex_date_are_summed():
    s = "Interim Dividend - Rs 2/- Per Share / Special Dividend - Rs 5/- Per Share"
    assert _p(s) == 7.0


# -- percentage of face value (mostly pre-2010) -------------------------
def test_percentage_of_face_value():
    assert _p("Dividend-10% / Agm", 10) == pytest.approx(1.0)
    assert _p("Agm/Dividend-40%", 2) == pytest.approx(0.8)
    assert _p("Agm/Dividend-120%", 10) == pytest.approx(12.0)


def test_percentage_without_face_value_is_unusable():
    assert _p("Dividend-25%", None) is None
    assert _p("Dividend-25%", 0) is None


def test_absolute_amount_wins_over_percentage():
    assert _p("Dividend-10% / Dividend - Rs 7/- Per Share", 10) == 7.0


# -- non-dividends ------------------------------------------------------
@pytest.mark.parametrize("subject", [
    "Annual General Meeting", "Bonus 1:1", "Rights 1:5 @ Premium Rs 100", "", None])
def test_non_dividend_subjects(subject):
    assert _p(subject) is None


# -- assembly -----------------------------------------------------------
def _raw(rows):
    return pd.DataFrame(rows)


def test_from_feed_filters_series_and_missing_isin():
    raw = _raw([
        {"isin": "INE1", "series": "EQ", "ex_date": date(2015, 1, 5),
         "subject": "Dividend - Rs 5/- Per Share", "faceVal": 10},
        {"isin": "IN00", "series": "GS", "ex_date": date(2015, 1, 5),
         "subject": "Dividend - Rs 5/- Per Share", "faceVal": 100},
        {"isin": "-", "series": "EQ", "ex_date": date(2015, 1, 5),
         "subject": "Dividend - Rs 5/- Per Share", "faceVal": 10}])
    out = dv.from_feed(raw=raw)
    assert list(out["isin"]) == ["INE1"]
    assert list(out.columns) == dv.COLUMNS


def test_revised_duplicate_takes_the_larger_not_the_sum():
    """NSE republishes a row when a purpose is revised; paying twice is wrong."""
    raw = _raw([
        {"isin": "INE1", "series": "EQ", "ex_date": date(2015, 1, 5),
         "subject": "Dividend - Rs 5/- Per Share", "faceVal": 10},
        {"isin": "INE1", "series": "EQ", "ex_date": date(2015, 1, 5),
         "subject": "Dividend - Rs 6/- Per Share  Purpose Revised", "faceVal": 10}])
    out = dv.from_feed(raw=raw)
    assert len(out) == 1 and out.loc[0, "dividend_per_share"] == 6.0


# -- the yfinance basis problem ----------------------------------------
def test_unadjust_uses_an_inclusive_ex_date_bound():
    """Infosys paid Rs 29.50 on 2015-06-15 and yfinance reports 7.375, having
    divided by the 1:1 that went ex the SAME day and the 1:1 in 2018. An
    exclusive bound would recover only 14.75."""
    div = pd.DataFrame({"isin": ["INE009A01021"], "ex_date": [date(2015, 6, 15)],
                        "dividend_per_share": [7.375]})
    factors = pd.DataFrame({
        "isin": ["INE009A01021", "INE009A01021"],
        "ex_date": [date(2015, 6, 15), date(2018, 9, 4)],
        "factor": [0.5, 0.5]})
    out = dv.unadjust(div, factors)
    assert out.loc[0, "dividend_per_share"] == pytest.approx(29.5)


def test_unadjust_ignores_factors_before_the_dividend():
    div = pd.DataFrame({"isin": ["INE1"], "ex_date": [date(2020, 1, 1)],
                        "dividend_per_share": [10.0]})
    factors = pd.DataFrame({"isin": ["INE1"], "ex_date": [date(2019, 1, 1)],
                            "factor": [0.5]})
    assert dv.unadjust(div, factors).loc[0, "dividend_per_share"] == 10.0


def test_unadjust_without_factors_is_a_no_op():
    div = pd.DataFrame({"isin": ["INE1"], "ex_date": [date(2020, 1, 1)],
                        "dividend_per_share": [10.0]})
    assert dv.unadjust(div, None).equals(div)
    assert dv.unadjust(div, pd.DataFrame()).equals(div)


def test_drop_collisions_removes_rows_a_factor_already_covers():
    """§9, 2026-09-16: where a PREVCLOSE factor wins, the dividend cash is
    already inside the price adjustment and must not be credited again."""
    d = pd.DataFrame({"isin": ["I1", "I1", "I2"],
                      "ex_date": [date(2020, 1, 2), date(2021, 5, 5), date(2020, 1, 2)],
                      "dividend_per_share": [1.0, 2.0, 3.0]})
    out = dv.drop_collisions(d, [("I1", "2020-01-02")])
    assert len(out) == 2
    assert (out["isin"] + out["ex_date"].astype(str)).tolist() == \
        ["I12021-05-05", "I22020-01-02"]


def test_drop_collisions_is_a_no_op_without_collisions():
    d = pd.DataFrame({"isin": ["I1"], "ex_date": [date(2020, 1, 2)],
                      "dividend_per_share": [1.0]})
    assert len(dv.drop_collisions(d, [])) == 1
