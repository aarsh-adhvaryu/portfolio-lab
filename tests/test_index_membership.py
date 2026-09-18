"""Point-in-time index membership and the E1b universe (charter E1b §3, §4).

All synthetic: nothing here touches NSE or PFLAB_DATA_DIR. The point of every
test below is the same one — a name must be eligible only inside its own
membership window, because using today's constituent list over history would
make E1b a backtest of the survivors (principle 6).
"""
from datetime import date

import pandas as pd
import pytest

from pflab.backtest import engine
from pflab.data import index_membership as im
from pflab.data import universe as uni
from pflab.eval.periods import Period, truncate_membership

from conftest import flat_index, make_panel, random_walk_panel


def _current(rows):
    return pd.DataFrame(rows, columns=["symbol", "isin", "company"])


# -- the window ---------------------------------------------------------
def test_members_at_is_half_open():
    t = pd.DataFrame([
        {"index": "NIFTY200", "isin": "INE001A01011", "symbol": "A",
         "from_date": date(2010, 3, 1), "to_date": date(2015, 9, 30)},
        {"index": "NIFTY200", "isin": "INE002A01011", "symbol": "B",
         "from_date": date(2010, 3, 1), "to_date": None},
    ], columns=im.COLUMNS)

    assert im.members_at(t, "NIFTY200", date(2010, 2, 28)) == set()
    assert im.members_at(t, "NIFTY200", date(2010, 3, 1)) == {"INE001A01011", "INE002A01011"}
    # inclusive at from_date, exclusive at to_date: on the exclusion date the
    # name is already out, which is what NSE's "with effect from" means
    assert im.members_at(t, "NIFTY200", date(2015, 9, 29)) == {"INE001A01011", "INE002A01011"}
    assert im.members_at(t, "NIFTY200", date(2015, 9, 30)) == {"INE002A01011"}
    assert im.members_at(t, "NIFTY200", date(2026, 1, 1)) == {"INE002A01011"}


def test_members_at_is_per_index():
    t = pd.DataFrame([
        {"index": "NIFTY200", "isin": "INE001A01011", "symbol": "A",
         "from_date": date(2010, 1, 1), "to_date": None},
        {"index": "NIFTY500", "isin": "INE002A01011", "symbol": "B",
         "from_date": date(2010, 1, 1), "to_date": None},
    ], columns=im.COLUMNS)
    assert im.members_at(t, "NIFTY200", date(2012, 1, 1)) == {"INE001A01011"}
    assert im.members_at(t, "NIFTY500", date(2012, 1, 1)) == {"INE002A01011"}


def test_assert_no_membership_leak_names_the_offender():
    t = pd.DataFrame([
        {"index": "NIFTY200", "isin": "INE001A01011", "symbol": "A",
         "from_date": date(2010, 1, 1), "to_date": date(2012, 1, 1)},
    ], columns=im.COLUMNS)
    im.assert_no_membership_leak(t, "NIFTY200", {date(2011, 6, 30): ["INE001A01011"]})
    with pytest.raises(AssertionError) as e:
        im.assert_no_membership_leak(t, "NIFTY200", {date(2013, 6, 28): ["INE001A01011"]})
    assert "INE001A01011" in str(e.value)


# -- building backwards -------------------------------------------------
def test_build_walks_changes_backwards():
    current = _current([("A", "INE001A01011", "A Ltd"),
                        ("B", "INE002A01011", "B Ltd")])
    changes = [
        # B joined in 2015, so it was NOT a member before that
        {"index": "NIFTY200", "action": "included", "symbol": "B",
         "company": "B Ltd", "effective": date(2015, 4, 1)},
        # C left in 2015, so it WAS a member until then
        {"index": "NIFTY200", "action": "excluded", "symbol": "C",
         "company": "C Ltd", "effective": date(2015, 4, 1)},
    ]
    sym_isin = pd.DataFrame([
        {"symbol": s, "isin": i, "valid_from": date(2000, 1, 1),
         "valid_to": date(2030, 1, 1)}
        for s, i in (("A", "INE001A01011"), ("B", "INE002A01011"),
                     ("C", "INE003A01011"))])
    table, manifest, unresolved = im.build(
        "NIFTY200", changes, current, start=date(2014, 6, 1),
        asof=date(2026, 9, 17), symbol_isin=sym_isin)
    assert unresolved == []

    before = im.members_at(table, "NIFTY200", date(2014, 12, 31))
    after = im.members_at(table, "NIFTY200", date(2016, 1, 31))
    assert before == {"INE001A01011", "INE003A01011"}   # A and C
    assert after == {"INE001A01011", "INE002A01011"}    # A and B
    assert manifest["history_starts"] == "2015-04-01"
    assert manifest["changes_applied"] == 2


def test_build_refuses_a_decade_long_carry_back():
    """§4 permits a declared gap. Nineteen years is not a gap, it is
    survivorship: with no change history the universe would be 'names in the
    index today' for the whole backtest."""
    current = _current([("A", "INE001A01011", "A Ltd")])
    with pytest.raises(im.CarryBackTooLong) as e:
        im.build("NIFTY200", changes=[], current=current,
                 start=date(2005, 1, 1), asof=date(2026, 9, 17))
    assert "survivorship" in str(e.value)

    table, manifest, _ = im.build("NIFTY200", changes=[], current=current,
                                  start=date(2005, 1, 1), asof=date(2026, 9, 17),
                                  allow_long_carry_back=True)
    assert manifest["carry_back_years"] > 19          # always recorded
    assert len(table) == 1


def test_unresolved_names_halt_the_build():
    """E1b §3 as amended 2026-09-17: more than 2% of a year's changes
    unresolved halts. A quiet partial answer would put roughly the right
    names in the universe and nobody would notice the difference."""
    current = _current([("A", "INE001A01011", "A Ltd")])
    changes = [{"index": "NIFTY200", "action": "excluded", "symbol": None,
                "company": "Some Company Nobody Can Key", "effective": date(2015, 4, 1)},
               {"index": "NIFTY200", "action": "included", "symbol": "A",
                "company": "A Ltd", "effective": date(2015, 4, 1)}]
    sym = pd.DataFrame([{"symbol": "A", "isin": "INE001A01011",
                         "valid_from": date(2000, 1, 1), "valid_to": date(2030, 1, 1)}])
    with pytest.raises(im.UnresolvedNamesTooMany) as e:
        im.build("NIFTY200", changes, current, start=date(2015, 1, 1),
                 asof=date(2026, 9, 17), symbol_isin=sym)
    assert "2015" in str(e.value)


def test_a_tolerable_share_of_unresolved_names_does_not_halt():
    current = _current([("A", "INE001A01011", "A Ltd")])
    sym = pd.DataFrame([{"symbol": f"S{i}", "isin": f"INE{i:03d}A01011",
                         "valid_from": date(2000, 1, 1), "valid_to": date(2030, 1, 1)}
                        for i in range(60)]
                       + [{"symbol": "A", "isin": "INE001A01011",
                           "valid_from": date(2000, 1, 1), "valid_to": date(2030, 1, 1)}])
    changes = [{"index": "NIFTY200", "action": "included", "symbol": f"S{i}",
                "company": f"S{i} Ltd", "effective": date(2015, 4, 1)}
               for i in range(60)]
    changes.append({"index": "NIFTY200", "action": "included", "symbol": None,
                    "company": "Unkeyable Ltd", "effective": date(2015, 4, 1)})
    table, manifest, unresolved = im.build(
        "NIFTY200", changes, current, start=date(2015, 1, 1),
        asof=date(2026, 9, 17), symbol_isin=sym)
    assert len(unresolved) == 1
    assert manifest["unresolved_by_year"][2015]["share"] < 0.02


# -- truncation ---------------------------------------------------------
def test_truncate_membership_hides_the_future_on_both_ends():
    t = pd.DataFrame([
        {"index": "NIFTY200", "isin": "INE001A01011", "symbol": "A",
         "from_date": date(2010, 1, 1), "to_date": date(2024, 1, 1)},
        {"index": "NIFTY200", "isin": "INE002A01011", "symbol": "B",
         "from_date": date(2020, 1, 1), "to_date": None},
    ], columns=im.COLUMNS)
    p = Period("dev", date(2007, 1, 1), date(2016, 12, 31))
    tt = truncate_membership(t, p)

    # B joins after the period end: gone entirely
    assert set(tt["isin"]) == {"INE001A01011"}
    # A leaves after the period end: inside this period it never leaves
    assert tt["to_date"].iloc[0] is None
    assert im.members_at(tt, "NIFTY200", date(2016, 12, 30)) == {"INE001A01011"}


# -- the E1b universe filter -------------------------------------------
def _two_name_panel():
    sessions = list(pd.bdate_range("2014-01-01", "2016-12-31").date)
    names = ["INE001A01011", "INE002A01011"]
    prices = {n: pd.Series([100.0] * len(sessions)).values for n in names}
    # INE002 is by far the more heavily traded name
    a = make_panel(sessions, [names[0]], {names[0]: prices[names[0]]}, turnover=1e8)
    b = make_panel(sessions, [names[1]], {names[1]: prices[names[1]]}, turnover=1e12)
    return sessions, names, pd.concat([a, b], ignore_index=True)


def test_e1b_universe_is_membership_not_turnover():
    """§3: 'No turnover ranking.' A thin member is in; a heavily traded
    non-member is out. That is the whole experiment."""
    sessions, names, panel = _two_name_panel()
    thin, heavy = names
    table = pd.DataFrame([
        {"index": "NIFTY200", "isin": thin, "symbol": "S0",
         "from_date": date(2014, 1, 1), "to_date": None},
    ], columns=im.COLUMNS)

    elig = uni.eligible_index_members(panel, table, "NIFTY200", date(2016, 12, 30))
    assert list(elig) == [thin]
    # E1's §2 filter on the same panel would have ranked the heavy name first
    assert heavy in list(uni.eligible(panel, top_n=500))


def test_e1b_universe_respects_the_window():
    sessions, names, panel = _two_name_panel()
    a, b = names
    table = pd.DataFrame([
        {"index": "NIFTY200", "isin": a, "symbol": "S0",
         "from_date": date(2014, 1, 1), "to_date": date(2015, 7, 1)},
        {"index": "NIFTY200", "isin": b, "symbol": "S1",
         "from_date": date(2015, 7, 1), "to_date": None},
    ], columns=im.COLUMNS)
    assert list(uni.eligible_index_members(panel, table, "NIFTY200", date(2015, 6, 30))) == [a]
    assert list(uni.eligible_index_members(panel, table, "NIFTY200", date(2015, 12, 31))) == [b]


def test_e1b_universe_keeps_the_250_session_and_price_floors():
    """§3 changes the universe, not the rest of §2."""
    sessions, names, panel = _two_name_panel()
    a = names[0]
    table = pd.DataFrame([
        {"index": "NIFTY200", "isin": a, "symbol": "S0",
         "from_date": date(2014, 1, 1), "to_date": None},
    ], columns=im.COLUMNS)
    early = panel[panel["date"] <= date(2014, 3, 31)]
    assert list(uni.eligible_index_members(early, table, "NIFTY200", date(2014, 3, 31))) == []
    assert list(uni.eligible_index_members(panel, table, "NIFTY200", date(2016, 12, 30),
                                           min_price=1e6)) == []


# -- through the engine -------------------------------------------------
def test_engine_index_mode_matches_the_filter_at_every_month_end(base_config, cost_model,
                                                                 tax_policy):
    sessions, names, panel = random_walk_panel(seed=3, n_names=12,
                                               start="2014-01-01", end="2016-12-31")
    half = names[:6]
    table = pd.DataFrame(
        [{"index": "NIFTY200", "isin": n, "symbol": f"S{i}",
          "from_date": date(2014, 1, 1), "to_date": None}
         for i, n in enumerate(half)], columns=im.COLUMNS)

    cfg = {**base_config, "universe": {**base_config["universe"],
                                       "mode": "index_members", "index": "NIFTY200"}}
    period = Period("t", date(2015, 1, 1), date(2016, 12, 31))
    res = engine.run(cfg, period, panel, flat_index(sessions), cost_model,
                     tax_policy, membership=table)

    held_by_date = {d["month_end"]: d.get("held") or [] for d in res.decisions}
    im.assert_no_membership_leak(table, "NIFTY200", held_by_date)
    for d in res.decisions:
        assert set(d.get("eligible", [])) <= set(half) or d["n_eligible"] <= 6


def test_engine_index_mode_refuses_to_run_without_a_table(base_config, cost_model,
                                                          tax_policy):
    """Silently falling back to E1's top-500 would look like a working E1b run
    and answer a different question."""
    sessions, names, panel = random_walk_panel(seed=1, n_names=6,
                                               start="2014-01-01", end="2015-12-31")
    cfg = {**base_config, "universe": {**base_config["universe"],
                                       "mode": "index_members", "index": "NIFTY200"}}
    with pytest.raises(ValueError) as e:
        engine.run(cfg, Period("t", date(2015, 1, 1), date(2015, 12, 31)), panel,
                   flat_index(sessions), cost_model, tax_policy)
    assert "membership" in str(e.value)


def test_unknown_universe_mode_is_an_error(base_config, cost_model, tax_policy):
    sessions, names, panel = random_walk_panel(seed=1, n_names=6,
                                               start="2014-01-01", end="2015-12-31")
    cfg = {**base_config, "universe": {**base_config["universe"], "mode": "typo"}}
    with pytest.raises(ValueError):
        engine.run(cfg, Period("t", date(2015, 1, 1), date(2015, 12, 31)), panel,
                   flat_index(sessions), cost_model, tax_policy)


def test_e1_path_is_untouched(base_config, cost_model, tax_policy):
    """No universe.mode key means E1 exactly as it ran for its verdict."""
    sessions, names, panel = random_walk_panel(seed=7, n_names=10,
                                               start="2014-01-01", end="2016-12-31")
    period = Period("t", date(2015, 1, 1), date(2016, 12, 31))
    a = engine.run(base_config, period, panel, flat_index(sessions), cost_model, tax_policy)
    cfg = {**base_config, "universe": {**base_config["universe"],
                                       "mode": "turnover_top_n"}}
    b = engine.run(cfg, period, panel, flat_index(sessions), cost_model, tax_policy)
    pd.testing.assert_frame_equal(a.equity, b.equity)
    pd.testing.assert_frame_equal(a.trades, b.trades)


# -- the Nifty 200 union (E1b §4) --------------------------------------
def test_union_of_merges_touching_windows():
    """NSE's methodology: "Nifty 200 -- Constituents forming part of Nifty 100
    and Nifty Midcap 100". A name that moves from Nifty 100 into Nifty Midcap
    100 never leaves Nifty 200, so the two windows must merge into one."""
    n100 = pd.DataFrame([
        {"index": "NIFTY100", "isin": "INE001A01011", "symbol": "A",
         "from_date": date(2006, 1, 1), "to_date": date(2010, 4, 1)}],
        columns=im.COLUMNS)
    mid = pd.DataFrame([
        {"index": "NIFTY_MIDCAP100", "isin": "INE001A01011", "symbol": "A",
         "from_date": date(2010, 4, 1), "to_date": None}], columns=im.COLUMNS)

    u = im.union_of([n100, mid], "NIFTY200", ["NIFTY100", "NIFTY_MIDCAP100"])
    assert len(u) == 1
    assert u["from_date"].iloc[0] == date(2006, 1, 1)
    assert u["to_date"].iloc[0] is None
    assert im.members_at(u, "NIFTY200", date(2010, 4, 1)) == {"INE001A01011"}


def test_union_of_keeps_a_genuine_gap_as_two_windows():
    n100 = pd.DataFrame([
        {"index": "NIFTY100", "isin": "INE001A01011", "symbol": "A",
         "from_date": date(2006, 1, 1), "to_date": date(2008, 1, 1)}],
        columns=im.COLUMNS)
    mid = pd.DataFrame([
        {"index": "NIFTY_MIDCAP100", "isin": "INE001A01011", "symbol": "A",
         "from_date": date(2012, 1, 1), "to_date": None}], columns=im.COLUMNS)
    u = im.union_of([n100, mid], "NIFTY200", ["NIFTY100", "NIFTY_MIDCAP100"])
    assert len(u) == 2
    assert im.members_at(u, "NIFTY200", date(2010, 1, 1)) == set()


def test_union_of_takes_the_union_not_the_intersection():
    n100 = pd.DataFrame([
        {"index": "NIFTY100", "isin": "INE001A01011", "symbol": "A",
         "from_date": date(2006, 1, 1), "to_date": None}], columns=im.COLUMNS)
    mid = pd.DataFrame([
        {"index": "NIFTY_MIDCAP100", "isin": "INE002A01011", "symbol": "B",
         "from_date": date(2006, 1, 1), "to_date": None}], columns=im.COLUMNS)
    u = im.union_of([n100, mid], "NIFTY200", ["NIFTY100", "NIFTY_MIDCAP100"])
    assert im.members_at(u, "NIFTY200", date(2009, 1, 1)) == {"INE001A01011",
                                                              "INE002A01011"}


# -- the self-check ----------------------------------------------------
def test_count_check_finds_a_dropped_change():
    """These indices hold exactly N names by construction, so a reconstruction
    that drifts to N-1 has missed a change. This is the real test of the
    parse, and it needs no external answer key."""
    rows = [{"index": "NIFTY100", "isin": f"INE{i:03d}A01011", "symbol": f"S{i}",
             "from_date": date(2010, 1, 1), "to_date": None} for i in range(100)]
    good = pd.DataFrame(rows, columns=im.COLUMNS)
    dates = [date(2012, 6, 29), date(2013, 6, 28)]
    ok = im.count_check(good, "NIFTY100", dates)
    assert ok["expected"] == 100 and ok["off"] == {} and ok["exact"] == 2

    bad = pd.DataFrame(rows[:99], columns=im.COLUMNS)
    miss = im.count_check(bad, "NIFTY100", dates)
    assert miss["worst"] == 1
    assert set(miss["off"]) == {"2012-06-29", "2013-06-28"}


# -- splicing the two eras (E1b §4) ------------------------------------
def test_splice_lets_neither_era_speak_for_the_other():
    """Before the cutover membership is derived from Nifty 100 + Midcap 100;
    from the cutover it is what NSE published. A name present only in the
    reconstruction must not survive past the cutover, and vice versa."""
    recon = pd.DataFrame([
        {"index": "NIFTY200", "isin": "INE001A01011", "symbol": "A",
         "from_date": date(2006, 1, 1), "to_date": None},
        {"index": "NIFTY200", "isin": "INE002A01011", "symbol": "B",
         "from_date": date(2006, 1, 1), "to_date": None},
    ], columns=im.COLUMNS)
    pub = pd.DataFrame([
        {"index": "NIFTY200", "isin": "INE001A01011", "symbol": "A",
         "from_date": date(2005, 1, 1), "to_date": None},
        {"index": "NIFTY200", "isin": "INE003A01011", "symbol": "C",
         "from_date": date(2005, 1, 1), "to_date": None},
    ], columns=im.COLUMNS)
    cut = date(2011, 4, 1)
    t = im.splice(recon, pub, "NIFTY200", cut)

    before = im.members_at(t, "NIFTY200", date(2009, 6, 30))
    after = im.members_at(t, "NIFTY200", date(2013, 6, 28))
    assert before == {"INE001A01011", "INE002A01011"}   # reconstruction only
    assert after == {"INE001A01011", "INE003A01011"}    # publication only


def test_splice_keeps_one_window_for_a_name_that_spans_the_cutover():
    """A joins before the cutover and is still a member after. It must not
    look as though it left and rejoined on the cutover date."""
    recon = pd.DataFrame([
        {"index": "NIFTY200", "isin": "INE001A01011", "symbol": "A",
         "from_date": date(2006, 1, 1), "to_date": None}], columns=im.COLUMNS)
    pub = pd.DataFrame([
        {"index": "NIFTY200", "isin": "INE001A01011", "symbol": "A",
         "from_date": date(2005, 1, 1), "to_date": None}], columns=im.COLUMNS)
    t = im.splice(recon, pub, "NIFTY200", date(2011, 4, 1))
    assert len(t) == 1
    assert t["from_date"].iloc[0] == date(2006, 1, 1)
    assert t["to_date"].iloc[0] is None
    assert im.members_at(t, "NIFTY200", date(2011, 4, 1)) == {"INE001A01011"}


# -- the walk back never invents a member ------------------------------
def test_an_inclusion_with_no_matching_record_is_not_left_open():
    """We are told a name joined, but walking back from today we never saw it
    leave and it is not a member now -- so its exclusion is missing from what
    we parsed. Emitting the window anyway gives it `to_date=None`, a name that
    joins and never leaves, which inflates every later date by one and is
    invisible. It must be recorded instead."""
    current = _current([("A", "INE001A01011", "A Ltd")])
    sym = pd.DataFrame([
        {"symbol": s, "isin": i, "valid_from": date(2000, 1, 1),
         "valid_to": date(2030, 1, 1)}
        for s, i in (("A", "INE001A01011"), ("B", "INE002A01011"))])
    changes = [{"index": "NIFTY200", "action": "included", "symbol": "B",
                "company": "B Ltd", "effective": date(2012, 4, 1)}]
    table, manifest, _ = im.build(
        "NIFTY200", changes, current, start=date(2012, 1, 1),
        asof=date(2026, 9, 17), symbol_isin=sym)

    assert manifest["unmatched_includes"] == 1
    assert im.members_at(table, "NIFTY200", date(2020, 6, 30)) == {"INE001A01011"}
    assert "INE002A01011" not in set(table["isin"])


def test_a_current_member_survives_an_unmatched_exclusion():
    """A is in the index today AND we parse an exclusion for it, so it rejoined
    and we missed that. Overwriting its open window drops a name that is in the
    index right now, which shows up as the anchor itself being wrong."""
    current = _current([("A", "INE001A01011", "A Ltd")])
    sym = pd.DataFrame([{"symbol": "A", "isin": "INE001A01011",
                         "valid_from": date(2000, 1, 1), "valid_to": date(2030, 1, 1)}])
    changes = [{"index": "NIFTY200", "action": "excluded", "symbol": "A",
                "company": "A Ltd", "effective": date(2015, 4, 1)}]
    table, manifest, _ = im.build(
        "NIFTY200", changes, current, start=date(2015, 1, 1),
        asof=date(2026, 9, 17), symbol_isin=sym)

    assert manifest["unmatched_excludes"] == 1
    # the anchor is ground truth: A is a member today
    assert im.members_at(table, "NIFTY200", date(2026, 8, 31)) == {"INE001A01011"}
    # and it was a member before the exclusion too
    assert im.members_at(table, "NIFTY200", date(2015, 2, 28)) == {"INE001A01011"}


# -- provenance and S12 (E1b §4, §6) -----------------------------------
def test_a_window_records_how_each_end_was_established():
    """A window both of whose ends came from a published change is observed.
    Anything else rests on an inference, and S12 needs to be able to tell
    them apart."""
    current = _current([("A", "INE001A01011", "A Ltd"),
                        ("B", "INE002A01011", "B Ltd")])
    sym = pd.DataFrame([
        {"symbol": s, "isin": i, "valid_from": date(2000, 1, 1),
         "valid_to": date(2030, 1, 1)}
        for s, i in (("A", "INE001A01011"), ("B", "INE002A01011"))])
    changes = [{"index": "NIFTY200", "action": "included", "symbol": "B",
                "company": "B Ltd", "effective": date(2015, 4, 1)}]
    table, _, _ = im.build("NIFTY200", changes, current, start=date(2015, 1, 1),
                           asof=date(2026, 9, 17), symbol_isin=sym)

    b = table[table["isin"] == "INE002A01011"].iloc[0]
    assert b["from_source"] == "change" and b["to_source"] == "open"
    a = table[table["isin"] == "INE001A01011"].iloc[0]
    assert a["from_source"] == "carry_back"      # no inclusion was ever seen


def test_unbounded_names_are_exactly_the_inferred_ones():
    t = pd.DataFrame([
        {"index": "NIFTY200", "isin": "INE001A01011", "symbol": "A",
         "from_date": date(2010, 1, 1), "to_date": None,
         "from_source": "change", "to_source": "open"},
        {"index": "NIFTY200", "isin": "INE002A01011", "symbol": "B",
         "from_date": date(2010, 1, 1), "to_date": None,
         "from_source": "carry_back", "to_source": "open"},
        {"index": "NIFTY200", "isin": "INE003A01011", "symbol": "C",
         "from_date": date(2010, 1, 1), "to_date": date(2015, 1, 1),
         "from_source": "inferred_start", "to_source": "change"},
        # pinned by a capture on the far side: bounded by evidence, kept
        {"index": "NIFTY200", "isin": "INE004A01011", "symbol": "D",
         "from_date": date(2010, 1, 1), "to_date": date(2015, 1, 1),
         "from_source": "capture", "to_source": "capture"},
    ], columns=im.COLUMNS + im.PROVENANCE)
    assert im.unbounded_isins(t, "NIFTY200") == {"INE002A01011", "INE003A01011"}


def test_s12_brackets_a_guessed_start_rather_than_dropping_it():
    """E1b §6 as revised 2026-09-18. A guessed start is an INTERVAL, not a
    missing fact: the base row places it at the earliest date the name could
    have joined and S12 at the latest, so the two bracket the truth. Dropping
    the name instead would throw away the part of the universe the
    reconstruction is least sure about, which is not measuring it."""
    from pflab.data import universe as uni
    sessions = list(pd.bdate_range("2013-01-01", "2016-12-31").date)
    names = ["INE001A01011", "INE002A01011"]
    prices = {n: pd.Series([100.0] * len(sessions)).values for n in names}
    panel = make_panel(sessions, names, prices)
    t = pd.DataFrame([
        {"index": "NIFTY200", "isin": names[0], "symbol": "S0",
         "from_date": date(2013, 1, 1), "to_date": None,
         "from_source": "change", "to_source": "open",
         "from_date_latest": date(2013, 1, 1)},
        {"index": "NIFTY200", "isin": names[1], "symbol": "S1",
         "from_date": date(2013, 1, 1), "to_date": None,
         "from_source": "inferred_start", "to_source": "open",
         "from_date_latest": date(2016, 6, 30)},
    ], columns=im.COLUMNS + im.PROVENANCE + im.BOUNDS)

    early = date(2015, 6, 30)
    # the base row: the guessed name is already in
    assert set(uni.eligible_index_members(panel, t, "NIFTY200", early)) == set(names)
    # S12: it has not joined yet at that date
    assert set(uni.eligible_index_members(panel, t, "NIFTY200", early,
                                          bound="latest")) == {names[0]}
    # and by the latest bound both are in again
    late = date(2016, 12, 30)
    assert set(uni.eligible_index_members(panel, t, "NIFTY200", late,
                                          bound="latest")) == set(names)


def test_with_bound_rejects_an_unknown_bound():
    t = pd.DataFrame([
        {"index": "NIFTY200", "isin": "INE001A01011", "symbol": "A",
         "from_date": date(2013, 1, 1), "to_date": None,
         "from_source": "change", "to_source": "open",
         "from_date_latest": date(2013, 1, 1)},
    ], columns=im.COLUMNS + im.PROVENANCE + im.BOUNDS)
    with pytest.raises(ValueError):
        im.with_bound(t, "middle")
    assert im.with_bound(t, "earliest") is t


def test_era_labels_split_the_month_ends_at_the_cutover():
    """E1b §4: a proxy month and a published month are not the same
    experiment, so the manifest has to say how many of each it averaged."""
    me = [date(2011, 6, 30), date(2011, 12, 30), date(2012, 1, 31),
          date(2013, 6, 28)]
    lab = im.era_labels(me)
    assert lab["proxy"] == 2 and lab["published"] == 2
    assert lab["labels"]["2011-12-30"] == "proxy"
    assert lab["labels"]["2012-01-31"] == "published"
    assert im.era_at(date(2011, 12, 31)) == "proxy"
    assert im.era_at(date(2012, 1, 1)) == "published"
