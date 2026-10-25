"""Panel assembly and charter section 9 plausibility (Phase 1 task 1.3)."""
from datetime import date, timedelta

import pandas as pd
import pytest

from pflab.data import panel, symbol_isin
from pflab.data.calendar import TradingCalendar

DAYS = [date(2024, 1, d) for d in (2, 3, 4, 5, 8, 9, 10, 11, 12)]
CAL = TradingCalendar(DAYS)


def _rows(isin, symbol, closes, days=None, volume=1000):
    days = days or DAYS[:len(closes)]
    prev = [closes[0]] + list(closes[:-1])
    return pd.DataFrame({
        "date": days, "isin": [isin] * len(closes), "symbol": [symbol] * len(closes),
        "open": closes, "high": closes, "low": closes, "close": closes,
        "prev_close": prev, "volume": [volume] * len(closes),
        "turnover": [c * volume for c in closes],
        "adj_factor": [1.0] * len(closes), "adj_close": closes,
        "adj_open": closes, "dividend": [0.0] * len(closes)})


# -- adjustment factors -------------------------------------------------
def test_adj_factor_applies_only_before_ex_date():
    p = _rows("INE1", "AAA", [100.0, 100.0, 50.0, 50.0])
    f = pd.DataFrame({"isin": ["INE1"], "ex_date": [DAYS[2]], "factor": [0.5]})
    a = panel.adj_factor_series(p, f)
    assert list(a) == [0.5, 0.5, 1.0, 1.0]        # today's basis is 1.0


def test_adj_factor_compounds_multiple_events_backwards():
    p = _rows("INE1", "AAA", [100.0] * 5)
    f = pd.DataFrame({"isin": ["INE1", "INE1"],
                      "ex_date": [DAYS[2], DAYS[4]], "factor": [0.5, 0.2]})
    a = panel.adj_factor_series(p, f)
    assert a.iloc[0] == pytest.approx(0.1)        # before both
    assert a.iloc[3] == pytest.approx(0.2)        # after the first only
    assert a.iloc[4] == pytest.approx(1.0)


def test_adj_factor_is_one_without_factors():
    p = _rows("INE1", "AAA", [10.0, 11.0])
    assert list(panel.adj_factor_series(p, None)) == [1.0, 1.0]
    assert list(panel.adj_factor_series(p, pd.DataFrame())) == [1.0, 1.0]


def test_adj_factor_leaves_other_securities_alone():
    p = pd.concat([_rows("INE1", "AAA", [100.0, 100.0]),
                   _rows("INE2", "BBB", [50.0, 50.0])], ignore_index=True)
    f = pd.DataFrame({"isin": ["INE1"], "ex_date": [DAYS[1]], "factor": [0.5]})
    a = panel.adj_factor_series(p, f)
    assert list(a) == [0.5, 1.0, 1.0, 1.0]


# -- plausibility -------------------------------------------------------
def test_big_move_halts_when_unexplained():
    p = _rows("INE1", "AAA", [100.0, 50.0, 50.0])
    halts, _ = panel.plausibility(p)
    assert [h["kind"] for h in halts] == ["move"]
    assert halts[0]["return"] == pytest.approx(-0.5)


def test_big_move_is_silent_when_a_corporate_action_explains_it():
    p = _rows("INE1", "AAA", [100.0, 50.0, 50.0])
    f = pd.DataFrame({"isin": ["INE1"], "ex_date": [DAYS[1]], "factor": [0.5]})
    halts, _ = panel.plausibility(p, factors=f)
    assert halts == []


def test_move_just_inside_the_threshold_does_not_halt():
    p = _rows("INE1", "AAA", [100.0, 61.0])       # -39%
    halts, _ = panel.plausibility(p)
    assert halts == []


def test_zero_price_halts():
    p = _rows("INE1", "AAA", [100.0, 100.0])
    p.loc[1, "open"] = 0.0
    halts, _ = panel.plausibility(p)
    assert any(h["kind"] == "zero_price" and h["field"] == "open" for h in halts)


def test_identical_closes_are_a_finding_at_ten():
    p = _rows("INE1", "AAA", [7.0] * 9, days=DAYS)
    _, f9 = panel.plausibility(p)
    assert not [x for x in f9 if x["kind"] == "identical_closes"]
    more = DAYS + [date(2024, 1, 15)]
    p10 = _rows("INE1", "AAA", [7.0] * 10, days=more)
    _, f10 = panel.plausibility(p10)
    hit = [x for x in f10 if x["kind"] == "identical_closes"]
    assert len(hit) == 1 and hit[0]["sessions"] == 10


def test_gaps_need_a_calendar_and_are_findings_not_halts():
    """Charter section 9 halts on a gap for a HELD name, which only the engine
    knows; the panel reports every gap instead."""
    days = [DAYS[0], DAYS[1], DAYS[8]]            # skips 6 sessions, so > 5
    p = _rows("INE1", "AAA", [10.0, 10.5, 11.0], days=days)
    halts, findings = panel.plausibility(p, calendar=CAL)
    assert not [h for h in halts if "gap" in h["kind"]]
    g = [x for x in findings if x["kind"] == "gap"]
    assert len(g) == 1 and g[0]["missing_sessions"] == 6


def test_gap_of_exactly_five_is_not_yet_the_long_finding():
    """The contract says gaps *longer than* 5 sessions; 5 is the boundary."""
    p = _rows("INE1", "AAA", [10.0, 11.0], days=[DAYS[0], DAYS[6]])
    _, findings = panel.plausibility(p, calendar=CAL)
    assert [x["kind"] for x in findings] == ["short_gap"]
    assert findings[0]["missing_sessions"] == 5


def test_short_gap_is_labelled_separately():
    days = [DAYS[0], DAYS[2]]                     # one missing session
    p = _rows("INE1", "AAA", [10.0, 10.1], days=days)
    _, findings = panel.plausibility(p, calendar=CAL)
    assert [x["kind"] for x in findings] == ["short_gap"]
    assert findings[0]["missing_sessions"] == 1


def test_gaps_helper_gives_the_engine_the_table_it_halts_on():
    days = [DAYS[0], DAYS[3]]
    p = _rows("INE1", "AAA", [10.0, 10.1], days=days)
    g = panel.gaps(p, CAL)
    assert len(g) == 1 and g[0]["isin"] == "INE1" and g[0]["missing_sessions"] == 2


# -- symbol -> ISIN map -------------------------------------------------
def _known():
    """A panel spanning the ISIN era: AAA is stable, BBB is reused."""
    return pd.DataFrame({
        "symbol": ["AAA", "AAA", "BBB", "BBB"],
        "isin": ["INE_A", "INE_A", "INE_B1", "INE_B2"],
        "date": [date(2012, 1, 2), date(2015, 1, 2),
                 date(2012, 1, 2), date(2018, 1, 2)]})


NO_CHANGES = pd.DataFrame({"company": [], "old": [], "new": [], "date": []})


def test_map_opens_the_earliest_isin_backwards():
    m = symbol_isin.build(_known(), changes=NO_CHANGES)
    aaa = m[m["symbol"] == "AAA"].iloc[0]
    assert aaa["isin"] == "INE_A" and aaa["valid_from"] == symbol_isin.FAR_PAST


def test_reused_symbol_gets_disjoint_date_ranges():
    """535 real symbols point at more than one ISIN; a bare symbol join is wrong."""
    m = symbol_isin.build(_known(), changes=NO_CHANGES)
    bbb = m[m["symbol"] == "BBB"].sort_values("valid_from")
    assert list(bbb["isin"]) == ["INE_B1", "INE_B2"]
    assert bbb.iloc[0]["valid_to"] < bbb.iloc[1]["valid_from"]


def test_apply_map_respects_the_date_range():
    m = symbol_isin.build(_known(), changes=NO_CHANGES)
    raw = pd.DataFrame({"symbol": ["BBB", "BBB"], "isin": [None, None],
                        "date": [date(2005, 6, 1), date(2019, 6, 1)]})
    out = symbol_isin.apply_map(raw, m)
    assert list(out["isin"]) == ["INE_B1", "INE_B2"]


def test_rename_chain_resolves_an_old_symbol():
    changes = pd.DataFrame({"company": ["x"], "old": ["OLDN"], "new": ["AAA"],
                            "date": [date(2013, 1, 1)]})
    m = symbol_isin.build(_known(), changes=changes)
    raw = pd.DataFrame({"symbol": ["OLDN"], "isin": [None], "date": [date(2006, 1, 2)]})
    assert symbol_isin.apply_map(raw, m).loc[0, "isin"] == "INE_A"


def test_unmapped_report_flags_years_over_tolerance():
    p = pd.DataFrame({"symbol": ["Z"] * 100 + ["AAA"] * 100,
                      "isin": [None] * 100 + ["INE_A"] * 100,
                      "date": [date(2005, 1, 3)] * 100 + [date(2015, 1, 2)] * 100})
    r = symbol_isin.unmapped_report(p)
    assert r["by_year"][2005]["share"] == 1.0
    assert 2005 in r["breaches"] and 2015 not in r["breaches"]
    assert r["symbols"] == ["Z"]


def test_synthetic_key_only_touches_unmapped_rows():
    p = pd.DataFrame({"symbol": ["Z", "AAA"], "isin": [None, "INE_A"],
                      "date": [date(2005, 1, 3)] * 2})
    syn = symbol_isin.synthetic_key(p)
    assert syn.iloc[0] == symbol_isin.SYNTHETIC_PREFIX + "Z"
    assert pd.isna(syn.iloc[1])
    assert list(symbol_isin.is_synthetic(pd.Series([syn.iloc[0], "INE_A"]))) == [True, False]


# -- wide ---------------------------------------------------------------
def test_wide_is_sessions_by_isin_and_windows():
    p = pd.concat([_rows("INE1", "AAA", [10.0, 11.0, 12.0]),
                   _rows("INE2", "BBB", [20.0, 21.0, 22.0])], ignore_index=True)
    w = panel.wide(p, "adj_close")
    assert list(w.columns) == ["INE1", "INE2"] and len(w) == 3
    assert w.loc[DAYS[1], "INE2"] == 21.0
    assert len(panel.wide(p, "adj_close", start=DAYS[1], end=DAYS[2])) == 2


def test_verified_stitch_list_holds_only_renames():
    """§9 / §15, 2026-09-16. Mergers are not renames and follow the delisting
    rule; the prefix heuristic that proposed TECHNOELEC->TECHNOFAB is exactly
    why this list is hand-verified."""
    assert symbol_isin.VERIFIED_STITCHES == {
        "GESHIPPING": "GESHIP", "ESSARSHIP": "ESSARPORTS"}
    for rejected in ("JINDALIRON", "TV-18", "TECHNOELEC"):
        assert rejected not in symbol_isin.VERIFIED_STITCHES


def test_stitched_symbol_resolves_to_its_successor_isin():
    known = pd.DataFrame({
        "symbol": ["GESHIP"], "isin": ["INE017A01032"], "date": [date(2012, 1, 2)]})
    m = symbol_isin.build(known, changes=NO_CHANGES)
    raw = pd.DataFrame({"symbol": ["GESHIPPING"], "isin": [None],
                        "date": [date(2005, 6, 1)]})
    assert symbol_isin.apply_map(raw, m).loc[0, "isin"] == "INE017A01032"
