"""S64: the IPO planner: arithmetic by code, base rates from history, nothing predicted."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pflab.plan import ipo

ASOF = date(2026, 10, 27)


def test_allotment_arithmetic_and_listing_scenarios():
    s = ipo.scenarios(22, 1191.0)
    by = {x["listing_price_vs_issue_pct"]: x for x in s}
    assert by[0]["value_rs"] == 26202 and by[0]["profit_rs"] == 0
    assert by[25]["price"] == 1488.75 and by[25]["profit_rs"] == round(22 * 1191 * 0.25)
    assert by[-30]["profit_rs"] == round(22 * 1191 * -0.30) and by[-30]["value_rs"] == round(22 * 1191 * 0.7)
    assert ipo.tax_estimate(6550.0, 0.20) == pytest.approx(1310.0) and ipo.tax_estimate(-100.0, 0.20) == 0.0


def make_panel(tmp_path, n=40):
    """n large IPOs listed 2020-2024: the listing gain is +10% at the close, then the price drifts down 0.1% a day."""
    rows, ld = [], {}
    for k in range(n):
        isin = f"INE{k:09d}"
        first = pd.bdate_range("2020-01-02", periods=40 * n)[28 * k]          # always a trading day
        ld[isin] = first
        px = 100.0
        for j, d in enumerate(pd.bdate_range(first, periods=80)):
            close = 110.0 if j == 0 else px
            rows.append(dict(date=d, isin=isin, series="EQ", open=108.0 if j == 0 else px, close=close, prev_close=100.0 if j == 0 else px,
                             turnover=5e9, adj_close=close, symbol=f"S{k}"))
            px = close * 0.999
    p = tmp_path / "panel"
    p.mkdir()
    pd.DataFrame(rows).to_parquet(p / "prices.parquet", index=False)
    pd.DataFrame({"first_trade": pd.Series(ld)}).to_parquet(p / "listing_dates.parquet")
    return tmp_path


def test_base_rates_read_the_listing_gain_and_what_followed(tmp_path):
    root = make_panel(tmp_path)
    b = ipo.base_rates(root, since="2016-01-01", cache=False)
    assert b["n"] == 40
    assert b["listing_gain_at_open"]["median"] == pytest.approx(0.08) and b["listing_gain_at_close"]["median"] == pytest.approx(0.10)
    assert b["listing_gain_at_close"]["share_up"] == 1.0
    assert b["after_listing_day_20_sessions"]["median"] == pytest.approx(0.999 ** 20 - 1, abs=1e-3)
    assert b["after_listing_day_20_sessions"]["share_up"] == 0.0 and b["worst_fall_within_60_sessions"]["median"] < 0
    assert "not a forecast" in b["note"]


def test_small_or_odd_listings_are_left_out(tmp_path):
    root = make_panel(tmp_path, n=5)
    d = pd.read_parquet(root / "panel" / "prices.parquet")
    d.loc[d["isin"] == "INE000000000", "turnover"] = 1e6                       # a thin listing
    d.to_parquet(root / "panel" / "prices.parquet", index=False)
    assert ipo.base_rates(root, cache=False)["n"] == 4


def test_strategy_gives_facts_and_choices_and_predicts_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(ipo, "base_rates", lambda root: {"n": 1})
    monkeypatch.setattr(ipo, "group_exposure", lambda con, asof, syms, v: {"value_rs": 1000, "share_of_investable_pct": 1.0, "after_allotment_pct": 1.2})
    monkeypatch.setattr(ipo, "groups_config", lambda pm: {"reliance": ["AAA"]})
    monkeypatch.setattr(ipo, "remaining_plan", lambda con, asof, amount: {"left": amount})
    r = ipo.strategy(None, tmp_path, ASOF, "Co", 22, 1191.0, 150000.0, "reliance", tmp_path, stcg=0.20)
    assert r["allotment"] == {"shares": 22, "issue_price": 1191.0, "value_rs": 26202, "share_of_budget_pct": 17.5, "left_to_invest_rs": 123798}
    assert r["the_rest_under_the_standard_plan"] == {"left": 123798.0} and r["group_exposure"]["group"] == "reliance"
    assert r["tax_on_a_sale_within_a_year"]["on_a_25pct_listing_gain_rs"] == round(26202 * 0.25 * 0.20)
    assert len(r["choices_for_the_allotment"]) == 5 and "BEFORE the listing" in r["choices_for_the_allotment"][4]     # S67: hold is weighed as much as sell
    assert any("grey-market" in x for x in r["to_look_up_with_web_search"])
    assert "whether this goes up or down" in r["not_known"]


def test_no_group_file_says_the_overlap_cannot_be_measured(tmp_path, monkeypatch):
    monkeypatch.setattr(ipo, "base_rates", lambda root: {})
    monkeypatch.setattr(ipo, "remaining_plan", lambda con, asof, amount: {})
    r = ipo.strategy(None, tmp_path, ASOF, "Co", 1, 100.0, 1000.0, None, tmp_path, stcg=0.2, with_plan=False)
    assert "cannot be measured" in r["group_exposure"]["note"] and "the_rest_under_the_standard_plan" not in r


def test_an_allotment_bigger_than_the_budget_leaves_nothing_to_invest(tmp_path, monkeypatch):
    monkeypatch.setattr(ipo, "base_rates", lambda root: {})
    r = ipo.strategy(None, tmp_path, ASOF, "Co", 100, 1000.0, 50_000.0, None, tmp_path, stcg=0.2)
    assert r["allotment"]["left_to_invest_rs"] == -50000 and "the_rest_under_the_standard_plan" not in r
