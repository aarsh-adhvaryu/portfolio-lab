from datetime import date

import pandas as pd
import pytest

from pflab.data.bhavcopy import normalize, urls_for, FORMAT_SWITCH

OLD = b"""SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,
WIDGETCO,EQ,1500,1520.5,1490,1510,1511,1495,1000000,1510000000.5,02-JAN-2020,54321,INE999W01011,
ABC,BE,10,11,9,10,10,10,100,1000,02-JAN-2020,5,INE000000001,
"""
OLD_NO_ISIN = b"""SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,
WIDGETCO,EQ,1500,1520.5,1490,1510,1511,1495,1000000,1510000000.5,02-JAN-2008,54321,
"""
# A debt row (NCD / tax-free bond). NSE leaves SERIES empty on these; observed
# in the live 2024-07-05 file, 9 rows of 2775.
OLD_BLANK_SERIES = b"""SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,
WIDGETCO,EQ,1500,1520.5,1490,1510,1511,1495,1000000,1510000000.5,05-JUL-2024,54321,INE999W01011,
76NHAI31,,1125.6,1127.25,1125.6,1127.1,1126.3,1126.52,1460,1644888.75,05-JUL-2024,6,INE906B07EJ8,
"""
# Before ~Oct 2011 the old format carried neither TOTALTRADES nor ISIN, and the
# day in TIMESTAMP was not zero-padded. Observed in the live 2004-01-02 file.
OLD_PRE2011 = b"""SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,
AARTIDRUGS,EQ,101,105.75,100.7,105.6,105.7,100.7,79273,8247959.95,2-JAN-2004,
"""
# NSE published 2020-07-13 with a two-digit, mixed-case year in TIMESTAMP.
# Every neighbouring session uses "13-JUL-2020".
OLD_TWO_DIGIT_YEAR = b"""SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN
20MICRONS,EQ,32.85,33.85,31.85,33.45,33.85,32.3,187303,6187285.7,13-Jul-20,1382,INE144J01027
"""
_NEW_HEADER = (b"TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
               b"FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,"
               b"LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,"
               b"TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n")
# Sgmt is "CM" in the live UDiFF files, not "CASH". A fixture that said "CASH"
# is what hid the segment-filter bug through Phase 0.
NEW = _NEW_HEADER + (
    b"2024-07-08,2024-07-08,CM,NSE,STK,1594,INE999W01011,WIDGETCO,EQ,,,,,WIDGET CO LIMITED,"
    b"1600,1610,1590,1605,1605,1598,,,,,2000000,3210000000,80000,F1,1,,,,,\n"
)
NEW_WITH_FO = NEW + (
    b"2024-07-08,2024-07-08,FO,NSE,IDF,35000,,NIFTY,,2024-07-25,2024-07-25,,,NIFTY 25JUL24,"
    b"24300,24400,24250,24350,24350,24280,,24350,150000,2500,90000,2190000000,45000,F1,50,,,,,\n"
)


def test_old_format():
    df = normalize(OLD, date(2020, 1, 2))
    assert list(df.columns) == ["date", "symbol", "series", "isin", "open", "high", "low", "close",
                                "prev_close", "volume", "turnover", "trades"]
    assert df.loc[0, "isin"] == "INE999W01011" and df.loc[0, "close"] == 1510.0
    assert int(df.loc[0, "volume"]) == 1_000_000 and df.loc[1, "series"] == "BE"


def test_old_format_without_isin_column():
    df = normalize(OLD_NO_ISIN, date(2008, 1, 2))
    assert pd.isna(df.loc[0, "isin"]) and df.loc[0, "symbol"] == "WIDGETCO"


def test_old_format_blank_series_becomes_empty_string():
    """Debt rows keep their row but sort/compare as "", never NaN."""
    df = normalize(OLD_BLANK_SERIES, date(2024, 7, 5))
    assert df["series"].notna().all()
    assert df.loc[1, "series"] == "" and df.loc[1, "symbol"] == "76NHAI31"
    assert list(df[df["series"] == "EQ"]["symbol"]) == ["WIDGETCO"]


def test_old_format_pre_2011_has_no_trades_or_isin_column():
    """Files before ~Oct 2011 lack TOTALTRADES and ISIN and use an unpadded day."""
    df = normalize(OLD_PRE2011, date(2004, 1, 2))
    assert df.loc[0, "date"] == date(2004, 1, 2)
    assert df.loc[0, "symbol"] == "AARTIDRUGS" and df.loc[0, "close"] == 105.6
    assert pd.isna(df.loc[0, "isin"])
    assert df["trades"].isna().all()
    assert df.loc[0, "turnover"] == 8_247_959.95


def test_old_format_two_digit_year_timestamp():
    """Regression: 2020-07-13 shipped as "13-Jul-20" and failed to parse."""
    df = normalize(OLD_TWO_DIGIT_YEAR, date(2020, 7, 13))
    assert df.loc[0, "date"] == date(2020, 7, 13)
    assert df.loc[0, "symbol"] == "20MICRONS" and df.loc[0, "close"] == 33.45


def test_unparseable_timestamp_raises():
    bad = OLD_TWO_DIGIT_YEAR.replace(b"13-Jul-20,", b"2020/07/13,")
    with pytest.raises(ValueError, match="unrecognised TIMESTAMP"):
        normalize(bad, date(2020, 7, 13))


def test_turnover_is_rupees_in_both_formats():
    """Turnover ~ volume * close, so the universe's traded-value rank in
    charter section 2 is comparable across the 2024 format change."""
    for raw, d in ((OLD, date(2020, 1, 2)), (NEW, date(2024, 7, 8)),
                   (OLD_PRE2011, date(2004, 1, 2))):
        row = normalize(raw, d).iloc[0]
        assert 0.9 < row["turnover"] / (float(row["volume"]) * row["close"]) < 1.1


def test_new_udiff_format():
    df = normalize(NEW, date(2024, 7, 8))
    assert df.loc[0, "symbol"] == "WIDGETCO" and df.loc[0, "close"] == 1605.0
    assert df.loc[0, "turnover"] == 3_210_000_000.0 and int(df.loc[0, "trades"]) == 80000


def test_new_udiff_keeps_cm_segment():
    """Regression: the live cash-market label is "CM"; filtering on "CASH"
    silently emptied every session after 2024-07-05."""
    df = normalize(NEW, date(2024, 7, 8))
    assert len(df) == 1


def test_new_udiff_drops_derivatives_segment():
    df = normalize(NEW_WITH_FO, date(2024, 7, 8))
    assert list(df["symbol"]) == ["WIDGETCO"]


def test_empty_parse_raises_rather_than_writing_nothing():
    """A parse that drops every row must halt, not produce an empty session."""
    with pytest.raises(ValueError, match="zero rows"):
        normalize(_NEW_HEADER, date(2024, 7, 8))


def test_wrong_session_date_raises():
    with pytest.raises(ValueError, match="!="):
        normalize(NEW, date(2024, 7, 9))


def test_url_order_switches():
    assert "BhavCopy_NSE_CM" in urls_for(FORMAT_SWITCH)[0]
    assert "historical/EQUITIES" in urls_for(date(2020, 1, 2))[0]


def test_format_switch_boundary_is_the_verified_one():
    """Verified against the live archive 2026-09-16: 2024-07-05 is the last
    session in the old format, 2024-07-08 the first published only as UDiFF."""
    assert FORMAT_SWITCH == date(2024, 7, 8)
    assert "historical/EQUITIES" in urls_for(date(2024, 7, 5))[0]
    assert "BhavCopy_NSE_CM" in urls_for(date(2024, 7, 8))[0]
