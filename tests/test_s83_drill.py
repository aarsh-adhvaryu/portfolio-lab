"""S83 drill findings (docs/s83_drill_notes.md): one regression test for each real bug the accelerated_picks drill found in S83's code."""
from __future__ import annotations

import pytest

from pflab.core import picks_card, stress


# --- stress: a scenario with no figure for any holding is not a fall of 0% ---------------------------------------------------------------------------------

ITEMS = [{"symbol": "AAA", "market": "IN", "value_inr": 60000.0}, {"symbol": "BBB", "market": "IN", "value_inr": 20000.0}]


def test_a_scenario_no_holding_has_a_figure_for_is_not_a_fall_of_zero_and_says_how_much_of_the_book_it_covers():
    nodata = lambda h: {"fall_pct": None, "basis": "no data", "detail": {"note": "no own history and no series"}}
    r = stress._scenario_result("2008", ITEMS, 100000.0, nodata)
    assert r["book_fall_pct"] is None and r["worst_holding"] is None and r["coverage_pct"] == 20.0 and r["value_without_figure_inr"] == 80000.0   # cash (20,000) does not fall: 20% is known
    assert r["loss_inr"] == 0.0


def test_a_scenario_with_a_figure_for_part_of_the_book_keeps_its_number_and_names_the_part_it_could_not_measure():
    part = lambda h: ({"fall_pct": -40.0, "basis": "own history"} if h["symbol"] == "AAA" else {"fall_pct": None, "basis": "no data"})
    r = stress._scenario_result("2008", ITEMS, 100000.0, part)
    assert r["book_fall_pct"] == pytest.approx(-24.0) and r["coverage_pct"] == 80.0 and r["value_without_figure_inr"] == 20000.0
    full = lambda h: {"fall_pct": -10.0, "basis": "estimate"}
    assert stress._scenario_result("2008", ITEMS, 100000.0, full)["coverage_pct"] == 100.0
    assert stress._scenario_result("2008", [], 100000.0, full)["book_fall_pct"] == 0.0                            # nothing held: the cash does not fall


def test_the_stored_row_and_the_reader_carry_the_none_and_the_coverage(tmp_path, monkeypatch):
    from datetime import date
    from pflab.pm import store
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    con = store.connect(tmp_path / "l.duckdb")
    nodata = lambda h: {"fall_pct": None, "basis": "no data"}
    r = stress._scenario_result("2008", ITEMS, 100000.0, nodata)
    res = {"scopes": {"IN": {"scenarios": [{**r, "window": None}]}}, "whole_book_source": "test"}
    stress.store(con, date(2026, 11, 12), res)
    assert con.execute("SELECT fall_pct FROM stress_s83").fetchone()[0] is None
    out = stress.latest(con)["scopes"]["IN"]["scenarios"][0]
    assert out["book_fall_pct"] is None and out["coverage_pct"] == 20.0 and out["value_without_figure_inr"] == 80000.0


# --- the PICKS text: a line ends like a sentence; the share it shows is what the sleeve holds ------------------------------------------------------------

def _block(**kw):
    p = {"symbol": "KKK", "source": "kite", "state": "held", "days_held": 5, "weight": 0.2, "thesis": "held from his Kite portfolio", "break_condition": "not written yet", "vs_index": None}
    b = {"market": "IN", "on": True, "share": 0.35, "share_why": "judged", "holds": 0.367, "room": 0.0, "no_new_picks": True, "picks": [p]}
    b.update(kw)
    return b


def test_the_thesis_line_ends_with_a_full_stop_before_what_would_break_it():
    t = picks_card._market_text(_block())
    assert "Thesis: held from his Kite portfolio. Breaks if: not written yet" in t
    done = picks_card._market_text(_block(picks=[{**_block()["picks"][0], "thesis": "a thesis that is cut…"}]))
    assert "Thesis: a thesis that is cut… Breaks if:" in done and "…." not in done                                   # a thesis that already ends in a mark is left as it is
    assert picks_card._sentence("") == "" and picks_card._sentence("ends.") == "ends."


def test_the_card_says_what_the_sleeve_really_holds_when_that_is_over_its_share():
    t = picks_card._market_text(_block())
    assert "the picks hold 36.7%" in t and "they hold more than the share: nothing is sold to reach it" in t
    ok = picks_card._market_text(_block(holds=0.30, room=0.05, no_new_picks=False))
    assert "the picks hold 30.0%, room left under the share 5%" in ok and "more than the share" not in ok


def test_the_block_built_from_the_store_carries_what_the_sleeve_holds(tmp_path, monkeypatch):
    from datetime import date
    from pflab.pm import store
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path / "data"))
    con = store.connect(tmp_path / "l.duckdb")
    b = picks_card.market_block(con, "IN", date(2026, 11, 2))
    assert b["holds"] == 0.0 and b["room"] == pytest.approx(0.40) and "the picks hold 0.0%, room left under the share 40%" in picks_card._market_text(b)


# --- the US sub-book: a withdrawn pick is sold whole, never left as dust ---------------------------------------------------------------------------------------

@pytest.fixture
def ucon(tmp_path, monkeypatch):
    from pflab.pm import store
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    return store.connect(tmp_path / "u.duckdb")


def _us_state(stk_qty, cash=1000.0, price=50.0):
    from datetime import date
    from pflab import core, us
    cfgs = us.settings({"on": True, "min_trade_usd": 25.0})
    spy_value = 8000.0
    total = spy_value + stk_qty * price + cash
    rows = [{"isin": "US:SPY", "symbol": "SPY", "sector": None, "asset_class": "etf", "qty": spy_value / 100.0, "price": 100.0, "value": spy_value, "weight": spy_value / total, "buyable": True, "klass": "us_equity"},
            {"isin": "US:STK", "symbol": "STK", "sector": None, "asset_class": "equity", "qty": stk_qty, "price": price, "value": stk_qty * price, "weight": stk_qty * price / total, "buyable": True, "klass": "us_equity"}]
    return {"day": date(2026, 11, 9), "market": "US", "value": total, "cash": cash, "bank": 0.0, "rows": rows, "breaker": {"on": False}, "gauge": {"fired": False}, "cfg": core.settings(),
            "settings": cfgs, "caps": {"US:SPY": 1.0, "US:STK": 0.10}}, total


def test_a_turnover_cap_that_would_leave_dust_of_a_withdrawn_pick_sells_it_whole(ucon):
    from pflab.us import policy
    st, total = _us_state(stk_qty=20.4)                                      # USD 1,020 of a withdrawn pick; the day's cap is 10% of the sub-book (about USD 1,000): 98%, leaving USD 20 of dust
    out = policy.check(ucon, st, {"weights": {"US:SPY": 0.80, "US:STK": 0.0}})
    sell = [o for o in out["orders"] if o["side"] == "sell" and o["symbol"] == "STK"]
    assert len(sell) == 1 and sell[0]["qty"] == pytest.approx(20.4) and sell[0]["value"] == pytest.approx(1020.0)       # whole: the dust under the minimum trade is not left behind
    assert "turnover cap" in sell[0]["note"]


def test_a_cap_that_leaves_more_than_the_minimum_trade_still_scales_the_sale_and_a_trim_is_still_not_a_dust_trade(ucon):
    from pflab.us import policy
    st, total = _us_state(stk_qty=40.0)                                      # USD 2,000: the cap sells about half, the rest waits for the next session
    out = policy.check(ucon, st, {"weights": {"US:SPY": 0.80, "US:STK": 0.0}})
    sell = [o for o in out["orders"] if o["side"] == "sell" and o["symbol"] == "STK"][0]
    assert 0.3 * 2000.0 < sell["value"] < 2000.0 and sell["qty"] < 40.0
    st2, _ = _us_state(stk_qty=10.0)                                         # a trim (target 8% of the book, not zero) under the minimum trade is skipped as before
    out2 = policy.check(ucon, st2, {"weights": {"US:SPY": 0.80, "US:STK": 0.045}})
    assert not [o for o in out2["orders"] if o["symbol"] == "STK"] and any(s_["symbol"] == "STK" for s_ in out2["skipped"])


def test_dust_of_a_withdrawn_pick_left_by_an_earlier_session_is_sold_whatever_the_minimum_trade_and_the_cost_filter_say(ucon):
    from pflab.us import policy
    st, total = _us_state(stk_qty=0.004, price=50.0)                         # USD 0.20 of a withdrawn pick: inside the band, under the USD 25 minimum, and its charges are a big share of it
    out = policy.check(ucon, st, {"weights": {"US:SPY": 0.80, "US:STK": 0.0}})
    sell = [o for o in out["orders"] if o["side"] == "sell" and o["symbol"] == "STK"]
    assert len(sell) == 1 and sell[0]["qty"] == pytest.approx(0.004) and sell[0]["charges_usd"] > 0.02 * sell[0]["value"]
