"""Company name -> security, for the name-only constituent records (E1b §3).

The rule under test throughout: a wrong match is silent and puts the wrong
company in the portfolio; an unresolved name lands in a list the investor reviews.
So every ambiguous case must come back unresolved, never guessed.
"""
from datetime import date

import pandas as pd
import pytest

from pflab.data import name_map as nm


def _table(rows):
    return pd.DataFrame(rows, columns=nm.COLUMNS)


def _row(norm, name, symbol, isin, source="corporate_actions",
         first=date(2005, 1, 1), last=date(2020, 1, 1)):
    return {"norm_name": norm, "name": name, "symbol": symbol, "isin": isin,
            "source": source, "first_seen": first, "last_seen": last}


# -- normalise ----------------------------------------------------------
def test_normalise_strips_corporate_form_and_punctuation():
    for v in ("Gadget Capital Ltd.", "Gadget Capital Limited",
              "GADGET CAPITAL LTD", "The Gadget Capital Ltd"):
        assert nm.normalise(v) == "gadget capital"


def test_normalise_maps_ampersand_to_and():
    assert nm.normalise("J.B. Chemicals & Pharmaceuticals Ltd.") == \
        nm.normalise("JB Chemicals and Pharmaceuticals Limited")


def test_normalise_keeps_words_that_distinguish_companies():
    """"India", "Industries" and "Corporation" are never stripped: dropping
    them would merge Tata Steel with Tata Steel Industries."""
    assert nm.normalise("Tata Steel Ltd") != nm.normalise("Tata Steel Industries Ltd")
    assert "india" in nm.normalise("JTEKT India Ltd.")
    assert "corporation" in nm.normalise("Container Corporation of India Ltd.")


def test_normalise_handles_junk():
    assert nm.normalise("") == ""
    assert nm.normalise(None) == ""
    assert nm.normalise("   Ltd.  ") == ""


# -- resolve ------------------------------------------------------------
def test_a_unique_name_resolves():
    t = _table([_row("cmc", "CMC Ltd.", "CMC", "INE314A01017")])
    r = nm.resolve("CMC Limited", t)
    assert r["isin"] == "INE314A01017" and r["symbol"] == "CMC"
    assert r["reason"] == "exact"


def test_an_unknown_name_is_unresolved_not_guessed():
    t = _table([_row("cmc", "CMC Ltd.", "CMC", "INE314A01017")])
    r = nm.resolve("Hotel Leela Venture Limited", t)
    assert r["isin"] is None and r["reason"] == "no match"


def test_two_companies_sharing_a_name_stay_unresolved():
    t = _table([_row("acme", "Acme Ltd", "ACMEA", "INE001A01011"),
                _row("acme", "Acme Ltd", "ACMEB", "INE002A01011")])
    r = nm.resolve("Acme Limited", t)
    assert r["isin"] is None and r["reason"] == "ambiguous symbol"
    assert len(r["candidates"]) == 2


def test_one_company_with_two_isins_is_settled_by_the_dated_map():
    """A split issues a new ISIN for the same company. This is 465 of the 579
    ambiguous names in the real map, and only the date-ranged symbol map can
    say which ISIN was live on the change date."""
    t = _table([_row("grasim industries", "Grasim Industries Limited", "GRASIM",
                     "INE047A01013"),
                _row("grasim industries", "Grasim Industries Limited", "GRASIM",
                     "INE047A01021", source="equity_master")])
    smap = pd.DataFrame([
        {"symbol": "GRASIM", "isin": "INE047A01021",
         "valid_from": date(1995, 1, 1), "valid_to": date(2004, 12, 31)},
        {"symbol": "GRASIM", "isin": "INE047A01013",
         "valid_from": date(2005, 1, 1), "valid_to": date(2999, 12, 31)}])

    early = nm.resolve("Grasim Industries Ltd.", t, on=date(2000, 6, 1),
                       symbol_isin=smap)
    late = nm.resolve("Grasim Industries Ltd.", t, on=date(2011, 6, 1),
                      symbol_isin=smap)
    assert early["isin"] == "INE047A01021"
    assert late["isin"] == "INE047A01013"
    assert early["reason"] == late["reason"] == "date-disambiguated"


def test_two_isins_and_no_date_stays_unresolved():
    t = _table([_row("acme", "Acme Ltd", "ACME", "INE001A01011"),
                _row("acme", "Acme Ltd", "ACME", "INE001A01029")])
    r = nm.resolve("Acme Ltd", t)
    assert r["isin"] is None and r["reason"] == "ambiguous isin"
    assert r["symbol"] == "ACME"      # the symbol is still known


def test_an_unparseable_name_is_reported_as_such():
    t = _table([_row("cmc", "CMC Ltd.", "CMC", "INE314A01017")])
    assert nm.resolve("Ltd.", t)["reason"] == "unparseable name"


# -- build --------------------------------------------------------------
def test_build_prefers_the_corporate_actions_feed():
    """The equity master is present-tense: a company delisted in 2011 is
    simply absent from it, which is the survivorship hole principle 6 warns
    about. It must never override a dated source."""
    ca = pd.DataFrame([{"comp": "Acme Ltd", "symbol": "ACME",
                        "isin": "INE001A01011", "ex_date": date(2008, 5, 1)}])
    t = nm.build(raw_ca=ca)
    assert len(t) >= 1
    row = t[t["norm_name"] == "acme"].iloc[0]
    assert row["source"] == "corporate_actions"
    assert row["symbol"] == "ACME"


def test_build_drops_rows_without_a_usable_key():
    ca = pd.DataFrame([{"comp": "Acme Ltd", "symbol": "ACME", "isin": None,
                        "ex_date": date(2008, 5, 1)},
                       {"comp": "", "symbol": "X", "isin": "INE002A01011",
                        "ex_date": date(2008, 5, 1)}])
    t = nm.build(raw_ca=ca)
    assert "acme" not in set(t["norm_name"])
    assert "" not in set(t["norm_name"])
