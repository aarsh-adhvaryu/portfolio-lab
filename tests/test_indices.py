"""Index series normalisation (charter section 6 trend filter, section 10 benchmarks).

Fixtures mirror the exact JSON the niftyindices BackPage endpoints return,
captured 2026-09-16.
"""
from datetime import date

import pandas as pd
import pytest

from pflab.data import indices

PRICE_ROWS = [
    {"RequestNumber": "His639", "Index Name": "", "INDEX_NAME": "Nifty 50",
     "HistoricalDate": "31 Jan 2024", "OPEN": "21487.25", "HIGH": "21741.35",
     "LOW": "21448.85", "CLOSE": "21725.70"},
    {"RequestNumber": "His639", "Index Name": "", "INDEX_NAME": "Nifty 50",
     "HistoricalDate": "30 Jan 2024", "OPEN": "21400.00", "HIGH": "21500.00",
     "LOW": "21350.00", "CLOSE": "21522.10"},
]
TRI_ROWS = [
    {"RequestNumber": "TRI639", "Index Name": "Nifty 50", "Date": "31 Jan 2024",
     "TotalReturnsIndex": "31939.59", "NTR_Value": "28933.54"},
    {"RequestNumber": "TRI639", "Index Name": "Nifty 50", "Date": "30 Jan 2024",
     "TotalReturnsIndex": "31640.24", "NTR_Value": "28662.37"},
]


def test_price_normalise_sorts_oldest_first():
    df = indices.normalize(PRICE_ROWS, "price")
    assert list(df.columns) == ["date", "open", "high", "low", "close"]
    assert df.loc[0, "date"] == date(2024, 1, 30) and df.loc[1, "date"] == date(2024, 1, 31)
    assert df.loc[1, "close"] == 21725.70


def test_tri_normalise_uses_total_returns_index():
    df = indices.normalize(TRI_ROWS, "tri")
    assert list(df.columns) == ["date", "close"]
    assert df.loc[1, "close"] == 31939.59


def test_normalise_strips_thousands_separators():
    rows = [dict(TRI_ROWS[0], TotalReturnsIndex="31,939.59")]
    assert indices.normalize(rows, "tri").loc[0, "close"] == 31939.59


def test_normalise_drops_duplicate_dates():
    df = indices.normalize(TRI_ROWS + [TRI_ROWS[0]], "tri")
    assert len(df) == 2


def test_empty_response_is_empty_frame_not_an_error():
    assert indices.normalize([], "tri").empty


def test_non_positive_close_halts():
    """A zero index level is a data error, never a real session."""
    with pytest.raises(ValueError, match="non-positive"):
        indices.normalize([dict(TRI_ROWS[0], TotalReturnsIndex="0")], "tri")


def test_series_registry_covers_the_charter():
    """Section 6 needs the price index; B1-B3 need the three TRIs."""
    assert indices.SERIES["NIFTY50_PRICE"] == ("NIFTY 50", "price")
    assert {k for k, (_n, kind) in indices.SERIES.items() if kind == "tri"} == {
        "NIFTY50_TRI", "NIFTY500_TRI", "NIFTY200_MOMENTUM30_TRI"}
    # The site returns [] for any other spelling of the momentum index.
    assert indices.SERIES["NIFTY200_MOMENTUM30_TRI"][0] == "NIFTY200 MOMENTUM 30"


VALUATION_ROWS = [
    {"RequestNumber": "pepb639", "Index Name": "Nifty 50", "pe": "23.15",
     "pb": "3.82", "divYield": "1.28", "DATE": "05 Jan 2024"},
    {"RequestNumber": "pepb639", "Index Name": "Nifty 50", "pe": "22.90",
     "pb": "3.80", "divYield": "1.30", "DATE": "04 Jan 2024"},
]


def test_valuation_normalise():
    df = indices.normalize(VALUATION_ROWS, "valuation")
    assert list(df.columns) == ["date", "pe", "pb", "div_yield"]
    assert df.loc[0, "date"] == date(2024, 1, 4)
    assert df.loc[1, "pe"] == 23.15 and df.loc[1, "div_yield"] == 1.28


def test_valuation_series_are_not_e1_inputs():
    """Guard rail: valuation data is collected but must not leak into SERIES,
    which is what the engine reads. Charter section 3 is pure price momentum."""
    assert not set(indices.SERIES) & set(indices.VALUATION_SERIES)
    assert "NIFTY200_MOMENTUM30_TRI" not in indices.VALUATION_SERIES
