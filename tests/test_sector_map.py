"""Point-in-time sector map (E2-B §3 as instructed 2026-09-26)."""
from datetime import date

import pandas as pd
import pytest

from pflab.data import sector_map as sm


def _table():
    rows = [
        # (capture_date, index, isin, industry)
        (date(2010, 1, 2), "NIFTY500", "INE000A01011", "COMPUTERS - SOFTWARE"),
        (date(2010, 1, 2), "NIFTY500", "INE000B01011", "BANKS"),
        (date(2010, 1, 2), "NIFTY500", "INE000C01011", "FINANCE - HOUSING"),
        (date(2014, 1, 22), "NIFTY500", "INE000A01011", "IT"),
        (date(2014, 1, 22), "NIFTY500", "INE000B01011", "FINANCIAL SERVICES"),
        (date(2014, 1, 22), "NIFTY500", "INE000C01011", "FINANCIAL SERVICES"),
        # D first appears in 2014; E only under a new serial after a split
        (date(2014, 1, 22), "NIFTY500", "INE000D01011", "PHARMA"),
        (date(2014, 1, 22), "NIFTY500", "INE000E01029", "METALS"),
    ]
    t = pd.DataFrame(rows, columns=["capture_date", "index", "isin", "industry"])
    t["taxonomy"] = t.groupby("capture_date")["industry"].transform(
        lambda s: sm.taxonomy_of(s))
    t["issuer"] = t["isin"].map(sm.issuer)
    return t[sm.COLUMNS]


def test_taxonomy_detection():
    assert sm.taxonomy_of(["IT", "FINANCIAL SERVICES"]) == "B"
    assert sm.taxonomy_of(["COMPUTERS - SOFTWARE", "IT"]) == "A"
    assert sm.taxonomy_of(["Financial Services", "IT"]) == "C"


def test_latest_capture_on_or_before_m_wins():
    s = sm.sector_at(_table(), ["INE000A01011"], date(2013, 6, 30),
                     allow_later=False).iloc[0]
    assert (s.industry, s.taxonomy, s.as_of) == ("COMPUTERS - SOFTWARE", "A", date(2010, 1, 2))
    s = sm.sector_at(_table(), ["INE000A01011"], date(2014, 1, 31),
                     allow_later=False).iloc[0]
    assert (s.industry, s.taxonomy) == ("IT", "B")


def test_capture_on_m_is_usable_but_not_the_day_after():
    t = _table()
    s = sm.sector_at(t, ["INE000D01011"], date(2014, 1, 22), allow_later=False).iloc[0]
    assert s.industry == "PHARMA"
    s = sm.sector_at(t, ["INE000D01011"], date(2014, 1, 21), allow_later=False).iloc[0]
    assert s.industry is None and s.matched_by is None


def test_later_capture_only_when_allowed_and_flagged():
    s = sm.sector_at(_table(), ["INE000D01011"], date(2012, 3, 31),
                     allow_later=True).iloc[0]
    assert s.industry == "PHARMA" and bool(s.approximate)


def test_allow_later_has_no_default():
    with pytest.raises(TypeError):
        sm.sector_at(_table(), ["INE000A01011"], date(2014, 1, 31))


def test_issuer_match_covers_a_split_isin_and_says_so():
    # held under the pre-split serial 01011; the capture lists 01029
    s = sm.sector_at(_table(), ["INE000E01011"], date(2015, 1, 31),
                     allow_later=False).iloc[0]
    assert s.industry == "METALS" and s.matched_by == "issuer"
    s = sm.sector_at(_table(), ["INE000E01011"], date(2015, 1, 31),
                     allow_later=False, match_issuer=False).iloc[0]
    assert s.industry is None


def test_exact_isin_beats_issuer():
    t = pd.concat([_table(), pd.DataFrame([{
        "capture_date": date(2014, 1, 22), "index": "NIFTY500",
        "isin": "INE000A01029", "industry": "SERVICES", "taxonomy": "B",
        "issuer": "INE000A01"}])], ignore_index=True)
    s = sm.sector_at(t, ["INE000A01011"], date(2014, 2, 28), allow_later=False).iloc[0]
    assert s.industry == "IT" and s.matched_by == "isin"


def test_future_capture_cannot_change_an_earlier_answer():
    t = _table()
    before = sm.sector_at(t, ["INE000A01011", "INE000B01011"], date(2012, 12, 31),
                          allow_later=False)
    later = pd.concat([t, pd.DataFrame([{
        "capture_date": date(2013, 1, 1), "index": "NIFTY500",
        "isin": "INE000A01011", "industry": "TRADING", "taxonomy": "A",
        "issuer": "INE000A01"}])], ignore_index=True)
    after = sm.sector_at(later, ["INE000A01011", "INE000B01011"], date(2012, 12, 31),
                         allow_later=False)
    pd.testing.assert_frame_equal(before, after)


def test_crosswalk_reports_purity():
    cw = sm.crosswalk(_table(), date(2010, 1, 2), date(2014, 1, 22)).set_index("from")
    assert cw.loc["BANKS", "to"] == "FINANCIAL SERVICES"
    assert cw.loc["FINANCE - HOUSING", "to"] == "FINANCIAL SERVICES"
    assert cw.loc["COMPUTERS - SOFTWARE", "purity"] == 1.0


def test_parse_industry_handles_title_line_and_blank_rows():
    raw = (b"Constituents list of S&P CNX 500,,,,\n\n"
           b"Company Name,Industry,Symbol,Series,ISIN Code\n\n"
           b"3M India Ltd.,TRADING,3MINDIA,EQ,INE470A01017\n")
    df = sm.parse_industry(raw)
    assert df.to_dict("records") == [{"isin": "INE470A01017", "industry": "TRADING"}]


def test_build_drops_an_isin_carrying_two_labels_in_one_capture(tmp_path):
    raw = tmp_path / "index_membership" / "raw" / "captures"
    raw.mkdir(parents=True)
    (raw / "20061108030001_ind_cnx500list.csv").write_bytes(
        b"Company Name,Industry,Symbol,Series,ISIN Code\n"
        b"Ramco Industries Ltd.,CEMENT AND CEMENT PRODUCTS,RAMCOIND,EQ,INE614A01010\n"
        b"Ramco Systems Ltd.,COMPUTERS - SOFTWARE,RAMCOSYS,BE,INE614A01010\n"
        b"ACC Ltd.,CEMENT AND CEMENT PRODUCTS,ACC,EQ,INE012A01025\n")
    t = sm.build(tmp_path)
    assert list(t["isin"]) == ["INE012A01025"]
    assert {c["industry"] for c in t.attrs["conflicts"]} == {
        "CEMENT AND CEMENT PRODUCTS", "COMPUTERS - SOFTWARE"}
