"""Internet Archive captures and the capture-anchored walk (E1b §4).

A capture pins the exact membership of an index on one date. That makes two
things possible that the change notices alone cannot do: anchoring the walk
back every couple of years instead of once at the present, and checking the
result against a known answer rather than against a count.

All synthetic; nothing here touches the network.
"""
from datetime import date

import pandas as pd
import pytest

from pflab.data import index_captures as cap
from pflab.data import index_membership as im

OLD_STYLE = (b"Constituents list of CNX 100,,,,\r\n\r\n"
             b"Company Name,Industry,Symbol,Series,ISIN Code\r\n\r\n"
             b"Hindalco Industries Ltd.,ALUMINIUM,HINDALCO,EQ,INE038A01020\r\n"
             b"Bajaj Auto Ltd.,AUTOMOBILES,BAJAJAUTO,EQ,INE118A01012\r\n")

NEW_STYLE = (b"Company Name,Industry,Symbol,Series,ISIN Code\r\n"
             b"ABB India Ltd.,INDUSTRIAL MANUFACTURING,ABB,EQ,INE117A01022\r\n"
             b"ACC Ltd.,CEMENT,ACC,EQ,INE012A01025\r\n")


# -- parsing ------------------------------------------------------------
def test_parses_the_old_capture_format_with_its_title_line():
    """The 2006-2015 files carry a title above the header, so the header row
    has to be found rather than assumed."""
    df = cap.parse_capture(OLD_STYLE)
    assert list(df["symbol"]) == ["HINDALCO", "BAJAJAUTO"]
    assert list(df["isin"]) == ["INE038A01020", "INE118A01012"]


def test_parses_the_modern_capture_format():
    df = cap.parse_capture(NEW_STYLE)
    assert list(df["symbol"]) == ["ABB", "ACC"]


def test_every_capture_carries_isin():
    """Even the 2006 ones do, which is what makes them usable as anchors
    without a symbol join."""
    for blob in (OLD_STYLE, NEW_STYLE):
        assert cap.parse_capture(blob)["isin"].str.match(r"^INE").all()


def test_a_capture_that_is_not_a_list_is_refused():
    with pytest.raises(cap.CaptureUnreadable):
        cap.parse_capture(b"<html>404 not found</html>")
    with pytest.raises(cap.CaptureUnreadable):
        cap.parse_capture(b"Company Name,Industry\r\nFoo Ltd.,BANKS\r\n")


# -- the exact-list check ----------------------------------------------
def _table(rows):
    return pd.DataFrame(rows, columns=im.COLUMNS)


def _caps(index, by_date):
    return {index: {d: pd.DataFrame({"symbol": [f"S{i}" for i in range(len(v))],
                                     "isin": list(v)})
                    for d, v in by_date.items()}}


def test_exact_list_check_passes_on_an_exact_match():
    t = _table([{"index": "NIFTY100", "isin": "INE001A01011", "symbol": "A",
                 "from_date": date(2010, 1, 1), "to_date": None},
                {"index": "NIFTY100", "isin": "INE002A01011", "symbol": "B",
                 "from_date": date(2010, 1, 1), "to_date": None}])
    c = _caps("NIFTY100", {date(2012, 6, 30): {"INE001A01011", "INE002A01011"}})
    r = cap.exact_list_check(t, "NIFTY100", c)
    assert r["exact"] == 1 and r["worst"] == 0
    assert r["per_date"]["2012-06-30"]["exact"] is True


def test_exact_list_check_separates_a_missing_name_from_an_invented_one():
    """Counting cannot tell these apart: both tables hold two names. Only
    comparing the sets says which way the reconstruction is wrong."""
    t = _table([{"index": "NIFTY100", "isin": "INE001A01011", "symbol": "A",
                 "from_date": date(2010, 1, 1), "to_date": None},
                {"index": "NIFTY100", "isin": "INE003A01011", "symbol": "C",
                 "from_date": date(2010, 1, 1), "to_date": None}])
    c = _caps("NIFTY100", {date(2012, 6, 30): {"INE001A01011", "INE002A01011"}})
    r = cap.exact_list_check(t, "NIFTY100", c)
    per = r["per_date"]["2012-06-30"]
    assert per["exact"] is False
    assert per["n_missing"] == 1 and per["missing"] == ["INE002A01011"]
    assert per["n_extra"] == 1 and per["extra"] == ["INE003A01011"]
    assert r["worst"] == 2

    # the count check is blind to this: both are size 2
    assert im.count_check(t, "NIFTY100", [date(2012, 6, 30)],
                          expected=2)["off"] == {}


def test_exact_list_check_with_no_captures_is_vacuous_not_passing():
    t = _table([{"index": "NIFTY100", "isin": "INE001A01011", "symbol": "A",
                 "from_date": date(2010, 1, 1), "to_date": None}])
    r = cap.exact_list_check(t, "NIFTY100", {})
    assert r["dates"] == 0 and r["exact"] == 0 and r["worst"] == 0


# -- the Nifty 100 cross-check -----------------------------------------
def test_nifty100_is_nifty50_plus_next50():
    d = date(2019, 3, 29)
    c = {}
    c.update(_caps("NIFTY50", {d: {"INE001A01011", "INE002A01011"}}))
    c.update(_caps("NIFTY_NEXT50", {d: {"INE003A01011"}}))
    c.update(_caps("NIFTY100", {d: {"INE001A01011", "INE002A01011",
                                    "INE003A01011"}}))
    r = cap.cross_check_nifty100(c)
    assert r["comparisons"] == 1 and r["exact"] == 1


def test_the_cross_check_notices_a_disagreement():
    d = date(2019, 3, 29)
    c = {}
    c.update(_caps("NIFTY50", {d: {"INE001A01011"}}))
    c.update(_caps("NIFTY_NEXT50", {d: {"INE003A01011"}}))
    c.update(_caps("NIFTY100", {d: {"INE001A01011", "INE002A01011"}}))
    r = cap.cross_check_nifty100(c)
    assert r["exact"] == 0
    assert r["detail"][0]["only_in_100"] == 1
    assert r["detail"][0]["only_in_union"] == 1


def test_the_cross_check_skips_captures_that_are_weeks_apart():
    c = {}
    c.update(_caps("NIFTY50", {date(2019, 1, 1): {"INE001A01011"}}))
    c.update(_caps("NIFTY_NEXT50", {date(2019, 1, 1): {"INE003A01011"}}))
    c.update(_caps("NIFTY100", {date(2019, 6, 30): {"INE001A01011"}}))
    assert cap.cross_check_nifty100(c)["comparisons"] == 0


# -- the segmented walk -------------------------------------------------
def _sym(pairs):
    return pd.DataFrame([{"symbol": s, "isin": i,
                          "valid_from": date(2000, 1, 1),
                          "valid_to": date(2030, 1, 1)} for s, i in pairs])


def _list(pairs):
    return pd.DataFrame([{"symbol": s, "isin": i} for s, i in pairs])


def test_a_capture_anchors_its_own_segment():
    """A missed change before the capture must not leak past it. With a single
    anchor at the present, one missed change in 2013 is wrong for every date
    before 2013; anchored, it is wrong only inside its own segment."""
    sym = _sym([("A", "INE001A01011"), ("B", "INE002A01011"),
                ("C", "INE003A01011")])
    anchors = [
        (date(2012, 6, 30), _list([("A", "INE001A01011"), ("B", "INE002A01011")])),
        (date(2020, 6, 30), _list([("A", "INE001A01011"), ("C", "INE003A01011")])),
    ]
    # the only change we know about: C joined in 2016. B's exit was never seen.
    changes = [{"index": "NIFTY100", "action": "included", "symbol": "C",
                "company": "C Ltd", "effective": date(2016, 4, 1)}]
    table, manifest, _ = im.build_segmented(
        "NIFTY100", changes, anchors, start=date(2012, 1, 1),
        asof=date(2020, 6, 30), symbol_isin=sym)

    assert manifest["anchors"] == 2
    # the 2012 capture is reproduced exactly, despite the missing change
    assert im.members_at(table, "NIFTY100", date(2012, 6, 30)) == {
        "INE001A01011", "INE002A01011"}
    # and so is the 2020 one
    assert im.members_at(table, "NIFTY100", date(2020, 6, 30)) == {
        "INE001A01011", "INE003A01011"}


def test_segments_do_not_speak_outside_their_own_span():
    sym = _sym([("A", "INE001A01011"), ("B", "INE002A01011")])
    anchors = [
        (date(2012, 6, 30), _list([("A", "INE001A01011")])),
        (date(2020, 6, 30), _list([("B", "INE002A01011")])),
    ]
    table, _, _ = im.build_segmented(
        "NIFTY100", [], anchors, start=date(2012, 1, 1),
        asof=date(2020, 6, 30), symbol_isin=sym)
    assert im.members_at(table, "NIFTY100", date(2012, 6, 30)) == {"INE001A01011"}
    assert im.members_at(table, "NIFTY100", date(2020, 6, 30)) == {"INE002A01011"}


def test_segmented_needs_at_least_one_anchor():
    with pytest.raises(ValueError):
        im.build_segmented("NIFTY100", [], [], start=date(2012, 1, 1),
                           asof=date(2020, 1, 1))


def test_anchors_for_puts_the_current_list_last():
    caps = _caps("NIFTY200", {date(2018, 6, 29): {"INE001A01011"}})
    cur = _list([("A", "INE001A01011"), ("B", "INE002A01011")])
    a = im.anchors_for("NIFTY200", caps, date(2026, 9, 17), current=cur)
    assert [x[0] for x in a] == [date(2018, 6, 29), date(2026, 9, 17)]
    assert set(a[-1][1]["isin"]) == {"INE001A01011", "INE002A01011"}


def test_anchors_after_the_asof_date_are_dropped():
    """A capture from after the period end is data the run may not see."""
    caps = _caps("NIFTY200", {date(2018, 6, 29): {"INE001A01011"},
                              date(2024, 6, 28): {"INE002A01011"}})
    cur = _list([("A", "INE001A01011")])
    a = im.anchors_for("NIFTY200", caps, date(2020, 12, 31), current=cur)
    assert [x[0] for x in a] == [date(2018, 6, 29), date(2020, 12, 31)]


# -- the bracket (E1b §6, S12) -----------------------------------------
def test_a_guessed_start_is_bounded_by_the_capture_that_first_shows_it():
    """The name is absent from the capture at T1 and present at T2, so it
    joined in (T1, T2]. The base row says T1+1, S12 says T2; neither is more
    true, and running both is what turns a doubt into a bracket."""
    sym = pd.DataFrame([{"symbol": s, "isin": i, "valid_from": date(2000, 1, 1),
                         "valid_to": date(2030, 1, 1)}
                        for s, i in (("A", "INE001A01011"),
                                     ("B", "INE002A01011"))])
    anchors = [
        (date(2012, 6, 30), pd.DataFrame([{"symbol": "A", "isin": "INE001A01011"}])),
        (date(2016, 6, 30), pd.DataFrame([{"symbol": "A", "isin": "INE001A01011"},
                                          {"symbol": "B", "isin": "INE002A01011"}])),
    ]
    table, _, _ = im.build_segmented("NIFTY200", [], anchors,
                                     start=date(2012, 1, 1),
                                     asof=date(2016, 6, 30), symbol_isin=sym)
    b = table[table["isin"] == "INE002A01011"].iloc[0]
    assert b["from_source"] == "inferred_start"
    assert b["from_date"] == date(2012, 7, 1)        # earliest it could have
    assert b["from_date_latest"] == date(2016, 6, 30)  # latest it could have

    mid = date(2014, 6, 30)
    assert im.members_at(table, "NIFTY200", mid) == {"INE001A01011",
                                                     "INE002A01011"}
    late = im.with_bound(table, "latest")
    assert im.members_at(late, "NIFTY200", mid) == {"INE001A01011"}


def test_both_bounds_still_reproduce_every_capture():
    """Whichever end of the bracket is used, the captures must still come out
    right -- otherwise the bracket is hiding an error rather than bounding
    one."""
    sym = pd.DataFrame([{"symbol": s, "isin": i, "valid_from": date(2000, 1, 1),
                         "valid_to": date(2030, 1, 1)}
                        for s, i in (("A", "INE001A01011"),
                                     ("B", "INE002A01011"))])
    caps = {date(2012, 6, 30): pd.DataFrame([{"symbol": "A", "isin": "INE001A01011"}]),
            date(2016, 6, 30): pd.DataFrame([{"symbol": "A", "isin": "INE001A01011"},
                                             {"symbol": "B", "isin": "INE002A01011"}])}
    anchors = sorted(caps.items())
    table, _, _ = im.build_segmented("NIFTY200", [], anchors,
                                     start=date(2012, 1, 1),
                                     asof=date(2016, 6, 30), symbol_isin=sym)
    for bound in ("earliest", "latest"):
        r = cap.exact_list_check(im.with_bound(table, bound), "NIFTY200",
                                 {"NIFTY200": caps})
        assert r["exact"] == r["dates"] == 2, (bound, r)
