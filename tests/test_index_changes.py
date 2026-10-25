"""Reading NSE Indices press releases (charter E1b §3, §4).

Every fixture here is a handwritten copy of a real release's shape. Nothing
touches the network. The tests are mostly about SILENT failure: a press
release that parses cleanly into the wrong answer is the only failure mode
that could actually reach the portfolio.
"""
from datetime import date

import pandas as pd
import pytest

from pflab.data import index_changes as ic

TWO_INDICES = """\
IISL
PRESS RELEASE
The Index Maintenance Sub-Committee has decided to make the following changes
in various indices which will become effective from December 7, 2011:
1) CNX 200 Index
The following company is being excluded:
Sr. Company Name Symbol
No.
1 Indiabulls Real Estate Limited IBREALEST
The following company is being included:
Sr. Company Name Symbol
No.
1 Redington (India) Limited REDINGTON
2) S&P CNX 500 Index
The following company is being excluded:
Sr. Company Name Symbol
No.
1 Indiabulls Real Estate Limited IBREALEST
The following company is being included:
Sr. Company Name Symbol
No.
1 Jai Balaji Industries Limited JAIBALAJI
3) CNX Realty Index
The following company is being excluded:
Sr. Company Name Symbol
No.
1 Phoenix Mills Limited PHOENIXLTD
Place: Mumbai
Date: December 1, 2011
"""


def test_parses_each_index_section_separately():
    got = ic.parse(TWO_INDICES, default_effective=date(2011, 12, 1))
    n200 = [c for c in got if c["index"] == "NIFTY200"]
    n500 = [c for c in got if c["index"] == "NIFTY500"]
    assert len(n200) == 2 and len(n500) == 2
    assert {(c["action"], c["symbol"]) for c in n200} == {
        ("excluded", "IBREALEST"), ("included", "REDINGTON")}
    assert {(c["action"], c["symbol"]) for c in n500} == {
        ("excluded", "IBREALEST"), ("included", "JAIBALAJI")}


def test_an_unrecognised_heading_still_closes_the_section():
    """CNX Realty is not one of ours. If it does not end the Nifty 500
    section, Phoenix Mills is silently read as a Nifty 500 exclusion."""
    got = ic.parse(TWO_INDICES, default_effective=date(2011, 12, 1))
    assert "PHOENIXLTD" not in {c["symbol"] for c in got}


def test_effective_date_beats_the_announcement_date():
    got = ic.parse(TWO_INDICES, default_effective=date(2011, 12, 1))
    assert {c["effective"] for c in got} == {date(2011, 12, 7)}


def test_effective_date_is_found_across_a_line_break():
    """Real releases wrap mid-sentence. A per-line search finds nothing and
    falls back to the announcement date, which is a week early."""
    wrapped = TWO_INDICES.replace(
        "which will become effective from December 7, 2011:",
        "which will become effective from December 7\n, 2011:")
    got = ic.parse(wrapped, default_effective=date(2011, 12, 1))
    assert {c["effective"] for c in got} == {date(2011, 12, 7)}


def test_a_per_group_effective_date_wins_over_a_distant_one():
    text = """\
1) NIFTY 500
The following company is being excluded:
Sr. No. Company Name Symbol
1 Asahi India Glass Ltd. ASAHIINDIA
The changes shall become effective from September 14, 2020.
2) NIFTY 100
The following company is being included:
Sr. No. Company Name Symbol
1 NOCIL Ltd. NOCIL
The changes shall become effective from September 25, 2020 (close of September 24, 2020).
"""
    got = ic.parse(text, default_effective=date(2020, 9, 7))
    by = {c["index"]: c["effective"] for c in got}
    assert by["NIFTY500"] == date(2020, 9, 14)
    assert by["NIFTY100"] == date(2020, 9, 25)


def test_only_the_four_broad_indices_are_returned():
    text = """\
NIFTY BANK
The following company is being excluded:
Sr. No. Company Name Symbol
1 Bandhan Bank Ltd. BANDHANBNK
NIFTY 200
The following company is being included:
Sr. No. Company Name Symbol
1 Lupin Ltd. LUPIN
"""
    got = ic.parse(text, default_effective=date(2024, 1, 1))
    assert [(c["index"], c["symbol"]) for c in got] == [("NIFTY200", "LUPIN")]


def test_old_house_styles_are_recognised():
    """The index names changed twice: S&P CNX -> CNX -> Nifty."""
    for heading in ("S&P CNX 500 Index", "CNX 500", "NIFTY 500", "Nifty 500 Index",
                    "2) S&P CNX 500"):
        assert ic._index_of_heading(heading) == "NIFTY500"
    for heading in ("CNX Midcap Index", "NIFTY Midcap 100", "CNX Midcap 100"):
        assert ic._index_of_heading(heading) == "NIFTY_MIDCAP100"


def test_a_name_only_release_still_parses():
    """2005-2009 releases print no Symbol column."""
    text = """\
S&P CNX 500
The following companies are being excluded :
Sr. No. Company Name
1 Flextronics Software Systems Ltd.
2 CMC Ltd.
The following companies are being included :
Sr. No. Company Name
1 Container Corporation of India Ltd.
"""
    got = ic.parse(text, default_effective=date(2006, 3, 2))
    assert len(got) == 3
    assert all(c["symbol"] is None for c in got)
    assert got[0]["company"] == "Flextronics Software Systems Ltd."


# -- faux-bold doubling -------------------------------------------------
def test_dedouble_collapses_a_bold_line():
    line = "TThhee ffoolllloowwiinngg ccoommppaannyy iiss bbeeiinngg eexxcclluuddeedd:"
    assert ic._dedouble_line(line) == "The following company is being excluded:"


def test_dedouble_fixes_the_date_that_word_level_handling_broke():
    """"77," is odd-length once the comma is attached, so a per-word rule
    leaves it doubled and "December 77, 2011" never parses as a date."""
    line = "wwhhiicchh wwiillll bbeeccoommee eeffffeeccttiivvee ffrroomm DDeecceemmbbeerr 77, 2011:"
    out = ic._dedouble_line(line)
    assert "December 7, 2011" in out


def test_dedouble_leaves_an_ordinary_line_alone():
    """A genuine "77" on a line that was never bold must survive."""
    line = "1 Some Company Limited SYM77"
    assert ic._dedouble_line(line) == line
    assert ic._dedouble_line("Page 77 of 100") == "Page 77 of 100"


def test_dedouble_collapses_doubled_punctuation_only_when_bold():
    bold = "11 RReeddiinnggttoonn ((IInnddiiaa)) LLiimmiitteedd REDINGTON"
    assert ic._dedouble_line(bold) == "1 Redington (India) Limited REDINGTON"


# -- validation ---------------------------------------------------------
def test_validate_catches_a_duplicated_row():
    """pypdf returns some releases out of reading order, which shows up as the
    same company appearing twice under one index."""
    changes = [{"index": "NIFTY200", "action": "excluded", "company": "X Ltd"},
               {"index": "NIFTY200", "action": "excluded", "company": "X Ltd"}]
    assert any("duplicate" in p for p in ic.validate(changes, TWO_INDICES))


def test_validate_catches_a_row_before_the_first_heading():
    scrambled = ("The following company is being excluded:\n"
                 "1 Indiabulls Real Estate Limited IBREALEST\n"
                 "1) CNX 200 Index\n")
    assert any("precedes the first heading" in p
               for p in ic.validate([], scrambled))


def test_validate_passes_a_clean_release():
    assert ic.validate(ic.parse(TWO_INDICES, date(2011, 12, 1)), TWO_INDICES) == []


def test_a_served_error_page_is_not_silently_empty():
    with pytest.raises(ic.PressReleaseMissing):
        ic.text_of(b" <!DOCTYPE html><html>404</html>")


def test_date_of_filename():
    assert ic._date_of("ind_prs07092020.pdf") == date(2020, 9, 7)
    assert ic._date_of("ind_prs01092022_1.pdf") == date(2022, 9, 1)
    assert ic._date_of("nonsense.pdf") is None


def test_index_size_is_the_published_size():
    assert ic.INDEX_SIZE == {"NIFTY200": 200, "NIFTY500": 500,
                             "NIFTY100": 100, "NIFTY_MIDCAP100": 100}


# -- the third column is not always the symbol --------------------------
INDUSTRY_STYLE = """\
PRESS RELEASE
Change in index w.e.f. October 06, 2005
(1) S&P CNX 500 Index
The following company will be excluded w.e.f. October 06, 2005:
Sr. No. Company Name Industry
1 Bank of Punjab Ltd. BANKS
The following company will be included w.e.f. October 06, 2005:
Sr. No. Company Name Industry
1 JSW Steel Ltd. STEEL AND STEEL PRODUCTS
"""


def test_an_industry_column_is_not_read_as_a_symbol():
    """Releases up to about 2009 print Company Name | Industry. Reading the
    third column as a symbol takes "BANKS" for Bank of Punjab and glues the
    industry to the company name, so the row resolves to nothing at all."""
    got = ic.parse(INDUSTRY_STYLE, default_effective=date(2005, 10, 5))
    assert len(got) == 2
    assert [c["company"] for c in got] == ["Bank of Punjab Ltd.", "JSW Steel Ltd."]
    assert all(c["symbol"] is None for c in got)
    assert {c["effective"] for c in got} == {date(2005, 10, 6)}


def test_will_be_excluded_is_recognised():
    """"is being excluded", "are being excluded" and "will be excluded" are
    all in use, sometimes in the same year."""
    assert len(ic.parse(INDUSTRY_STYLE, date(2005, 10, 5))) == 2


def test_a_section_with_an_action_but_no_rows_is_reported():
    """The release says a change happened and the table did not come back.
    Recording that as "no change" is the one failure that must never be
    silent, because the walk back would then keep a name that had left."""
    text = """\
S&P CNX 500 Index
The following company is being excluded w.e.f. March 29, 2007:
The following company is being included w.e.f. March 29, 2007:
Place: Mumbai
"""
    empty = []
    changes = ic.parse(text, date(2007, 3, 22), empty_out=empty)
    assert changes == [] and empty == ["NIFTY500"]
    problems = ic.validate(changes, text, empty_sections=empty)
    assert any("no rows" in p for p in problems)


def test_empty_section_state_does_not_leak_between_parses():
    """It used to be stashed on the function object, so a later clean release
    inherited the previous one's problems."""
    bad = []
    ic.parse("NIFTY 500\nThe following company is being excluded:\n", None,
             empty_out=bad)
    assert bad == ["NIFTY500"]
    good = []
    ic.parse(TWO_INDICES, date(2011, 12, 1), empty_out=good)
    assert good == []
    assert ic.validate([], TWO_INDICES) == []


def test_the_midcap_rename_is_followed_but_full_midcap_is_not():
    """NSE's 2016-02-22 restructure release: "rebranding of existing Nifty
    Midcap 100 and Nifty Smallcap 100 indices ... published under the new
    names Nifty Free Float Midcap 100 and Nifty Free Float Smallcap 100".

    Missing the alias cost 2016 and 2017 entirely -- two semi-annual review
    years parsed as zero changes, which showed up as the reconstruction
    holding ~222 names where the index holds 100. "Nifty FULL Midcap 100" is
    a different index launched in the same restructure.
    """
    for heading in ("CNX Midcap", "CNX Midcap Index", "Nifty Midcap 100",
                    "NIFTY Free Float Midcap 100",
                    "13) NIFTY Free float Midcap 100"):
        assert ic._index_of_heading(heading) == "NIFTY_MIDCAP100", heading
    for heading in ("NIFTY Full Midcap 100", "9) NIFTY Full Midcap 100",
                    "Nifty Midcap 150", "Nifty Midcap 50", "Nifty Midcap Select",
                    "Nifty Midcap Liquid 15 Index"):
        assert ic._index_of_heading(heading) != "NIFTY_MIDCAP100", heading
