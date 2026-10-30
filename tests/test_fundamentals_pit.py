"""S24: point-in-time quarterly results, ratios, reverse DCF. The eight Gadget Co quarters in
tests/fixtures are a REAL excerpt of BSE's endpoint (fetched 2026-10-06); dating and gap tests are
synthetic."""
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pflab.fundamentals import pit
from pflab.pm import estimate as est
from pflab.pm import store

FIX = json.loads((Path(__file__).parent / "fixtures" / "bse_results_599325_real_excerpt.json").read_text())
SCRIP = "599325"


def real_quarters() -> pd.DataFrame:
    rows = [pit.parse_quarter(lines, SCRIP, float(q)) for q, lines in sorted(FIX["quarters"].items(), key=lambda kv: int(kv[0]))]
    return pd.DataFrame([r for r in rows if r], columns=pit.COLUMNS)


def raw_of(lines_by_q) -> pd.DataFrame:
    return pd.DataFrame([{"scrip_code": SCRIP, "qtr": float(q), "fld_desc": x["fld_desc"], "Value": x["Value"]}
                         for q, lines in lines_by_q.items() for x in lines])


def val_of(q, desc):
    return float(next(x["Value"] for x in FIX["quarters"][str(q)] if x["fld_desc"] == desc))


# --- parsing real data ---------------------------------------------------------------------------

def test_parse_real_quarters():
    q = real_quarters()
    assert len(q) == 8
    ends = list(q["quarter_end"])
    assert ends[0] == date(2024, 9, 30) and ends[-1] == date(2026, 6, 30)
    assert all((pd.Timestamp(b) - pd.offsets.QuarterEnd(1)).date() == a for a, b in zip(ends, ends[1:]))   # consecutive
    last = q.iloc[-1]
    assert last["revenue"] == 1660130.0 and last["other_income"] == 41080.0 and last["total_income"] == 1701210.0
    assert not last["audited"] and bool(q[q["quarter_end"] == date(2026, 3, 31)]["audited"].iloc[0])
    for f in ("revenue", "pbt", "tax", "net_profit", "eps_basic"):
        assert q[f].notna().all(), f
    assert (q["tax"] < 0).all()                      # BSE shows tax as a negative line


def test_stored_raw_layout_gives_the_same_rows():
    q1 = real_quarters()
    q2 = pit.quarterly_frame(raw_of({int(k): v for k, v in FIX["quarters"].items()}))
    pd.testing.assert_frame_equal(q1.reset_index(drop=True), q2.reset_index(drop=True))


def test_error_and_empty_quarters_are_dropped():
    assert pit.parse_quarter([{"fld_desc": "__ERROR__", "Value": "x"}] * 5, "1", 100) is None
    assert pit.parse_quarter([{"fld_desc": "Type", "Value": "Audited"}], "1", 100) is None


def test_latest_qtr_id():
    assert pit.latest_qtr_id(date(2026, 9, 29)) == 130 and pit.latest_qtr_id(date(2026, 10, 6)) == 131
    assert pit.latest_qtr_id(date(2000, 6, 30)) == 26


# --- point in time -------------------------------------------------------------------------------------

def test_dating_rules_announcement_unmatched_and_first_seen():
    q = real_quarters()
    ann = pd.DataFrame([dict(scrip_code=SCRIP, t=pd.Timestamp("2026-08-20 16:30"), category="Result",
                             subcategory="Financial Results", headline="Q1 results June 2026")])
    dq = pit.date_quarters(q, ann)
    j26 = dq[dq["quarter_end"] == date(2026, 6, 30)].iloc[0]
    assert j26["date_source"] == "announcement" and j26["usable_from"] == date(2026, 8, 21)    # after 15:30: next day (past the 14-Aug floor)
    d25 = dq[dq["quarter_end"] == date(2025, 12, 31)].iloc[0]
    assert d25["date_source"] == "unmatched_90" and d25["usable_from"] == date(2025, 12, 31) + timedelta(days=90)
    dq2 = pit.date_quarters(q, ann, first_seen=date(2026, 10, 6))
    assert dq2[dq2["quarter_end"] == date(2025, 12, 31)].iloc[0]["date_source"] == "first_seen"
    assert dq2[dq2["quarter_end"] == date(2025, 12, 31)].iloc[0]["usable_from"] == date(2026, 10, 6)


def test_statutory_floor_beats_an_early_announcement():
    q = real_quarters()
    early = pd.DataFrame([dict(scrip_code=SCRIP, t=pd.Timestamp("2026-07-02 10:00"), category="Result",
                               subcategory="Financial Results", headline="results june")])
    dq = pit.date_quarters(q, early)
    assert dq[dq["quarter_end"] == date(2026, 6, 30)].iloc[0]["usable_from"] == date(2026, 6, 30) + timedelta(days=45)


def test_nothing_after_asof_is_ever_used():
    dq = pit.date_quarters(real_quarters())             # all unmatched: quarter end + 90 days
    d = date(2024, 9, 1)
    while d < date(2027, 1, 1):
        u = pit.usable(dq, SCRIP, d)
        assert (u["usable_from"] <= d).all()
        got = pit.last_quarters(dq, SCRIP, d, 8)
        assert (got["usable_from"] <= d).all() and len(got) == len(u.head(8))
        d += timedelta(days=17)
    assert len(pit.last_quarters(dq, SCRIP, date(2026, 10, 6), 8)) == 8
    jun26 = date(2026, 6, 30) + timedelta(days=90)
    assert pit.last_quarters(dq, SCRIP, jun26 - timedelta(days=1), 8)["quarter_end"].iloc[-1] == date(2026, 3, 31)
    assert pit.last_quarters(dq, SCRIP, jun26, 8)["quarter_end"].iloc[-1] == date(2026, 6, 30)


def test_last_quarters_are_oldest_first_and_keep_gaps():
    dq = pit.date_quarters(real_quarters(), first_seen=date(2020, 1, 1))
    dq = dq[dq["quarter_end"] != date(2025, 9, 30)]
    got = pit.last_quarters(dq, SCRIP, date(2026, 10, 6), 8)
    assert len(got) == 7 and list(got["quarter_end"]) == sorted(got["quarter_end"])


# --- ratios ----------------------------------------------------------------------------------------------

def test_ratios_on_real_quarters_match_plain_arithmetic():
    q = real_quarters()
    r = pit.ratios(q)
    last4 = [127, 128, 129, 130]
    prev4 = [123, 124, 125, 126]
    rev = sum(val_of(k, "Net Sales/Revenue From Operations") for k in last4)
    np_ = sum(val_of(k, "Net Profit") for k in last4)
    rev_prev = sum(val_of(k, "Net Sales/Revenue From Operations") for k in prev4)
    assert r["revenue_ttm"] == pytest.approx(rev) and r["net_profit_ttm"] == pytest.approx(np_)
    assert r["net_margin_ttm"] == pytest.approx(np_ / rev)
    assert r["revenue_ttm_yoy"] == pytest.approx((rev - rev_prev) / rev_prev)
    assert r["revenue_yoy_q"] == pytest.approx(
        (val_of(130, "Net Sales/Revenue From Operations") - val_of(126, "Net Sales/Revenue From Operations"))
        / val_of(126, "Net Sales/Revenue From Operations"))
    pbt = sum(val_of(k, "Profit (+)/ Loss (-) from Ordinary Activities before Tax") for k in last4)
    tax = sum(val_of(k, "Tax") for k in last4)
    assert r["tax_rate_ttm"] == pytest.approx(-tax / pbt) and 0 < r["tax_rate_ttm"] < 0.5
    assert r["latest_quarter"] == date(2026, 6, 30)


def test_a_missing_quarter_makes_ttm_none_not_a_substitute():
    q = real_quarters()
    gap = q[q["quarter_end"] != date(2026, 3, 31)]
    r = pit.ratios(gap)
    assert r["revenue_ttm"] is None and r["eps_ttm"] is None and r["revenue_ttm_yoy"] is None
    assert r["revenue_yoy_q"] is not None                   # the single-quarter comparison does not need it
    only3 = pit.ratios(q.tail(3))
    assert only3["revenue_ttm"] is None and only3["revenue_yoy_q"] is None
    assert pit.ratios(q.iloc[0:0])["revenue_ttm"] is None


def test_ratios_with_a_missing_field_in_one_quarter():
    q = real_quarters()
    q.loc[q.index[-2], "net_profit"] = np.nan
    r = pit.ratios(q)
    assert r["net_profit_ttm"] is None and r["revenue_ttm"] is not None


def test_valuation_ratios():
    v = pit.valuation_ratios(100.0, 5.0, revenue_ttm_mn=2_000.0, shares_outstanding=50e6)
    assert v["pe_ttm"] == 20.0 and v["earnings_yield_ttm"] == 0.05
    assert v["ps_ttm"] == pytest.approx(100 * 50e6 / 2_000e6)
    assert pit.valuation_ratios(100.0, -2.0)["pe_ttm"] is None
    assert pit.valuation_ratios(100.0, None)["earnings_yield_ttm"] is None


# --- reverse DCF -------------------------------------------------------------------------------------------

def test_implied_growth_recovers_the_input_growth():
    for g in (-0.05, 0.0, 0.10, 0.25):
        price = pit._pv_from_growth(40.0, g, 0.12, 10, 0.05)
        e = pit.implied_growth(price, 40.0, date(2026, 10, 6))
        assert e.value == pytest.approx(g * 100, abs=1e-6)


def test_implied_growth_is_a_labelled_estimate_with_assumptions_and_moves_with_them():
    price = 900.0
    a = pit.implied_growth(price, 40.0, date(2026, 10, 6), discount_rate=0.12)
    b = pit.implied_growth(price, 40.0, date(2026, 10, 6), discount_rate=0.14)
    assert isinstance(a, est.Estimate) and b.value > a.value                 # higher hurdle needs more growth
    text = a.render()
    assert "estimate" in text and "discount rate 12.0%" in text and "assumptions, not forecasts" in text
    with pytest.raises(TypeError):
        float(a)


def test_implied_growth_input_errors():
    with pytest.raises(ValueError):
        pit.implied_growth(100.0, -1.0, date(2026, 1, 1))
    with pytest.raises(ValueError):
        pit.implied_growth(100.0, 5.0, date(2026, 1, 1), discount_rate=0.04, terminal_growth=0.05)
    with pytest.raises(ValueError, match="above the model value"):
        pit.implied_growth(1e9, 5.0, date(2026, 1, 1))


# --- store -----------------------------------------------------------------------------------------------------------

def test_store_round_trip_and_first_usable_date_sticks(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    q = real_quarters()
    first = pit.date_quarters(q, first_seen=date(2026, 10, 6))
    assert pit.save(con, first, "bse_results") == 8 and pit.save(con, first, "bse_results") == 0
    later = pit.date_quarters(q, first_seen=date(2026, 11, 1))
    assert pit.save(con, later, "bse_results") == 0                        # not replaced: usable_from does not move
    got = pit.load(con, SCRIP)
    assert len(got) == 8 and set(got["usable_from"]) == {date(2026, 10, 6)}
    r = pit.ratios(pit.last_quarters(got, SCRIP, date(2026, 10, 6), 8))
    assert r["revenue_ttm"] == pytest.approx(pit.ratios(q)["revenue_ttm"])


def test_the_same_quarter_twice_in_one_batch_is_stored_once_not_a_failed_commit(tmp_path):
    """Seen 2026-10-30: BSE listed a re-filed result twice in one fetch; DuckDB refused the whole commit and the guards job failed."""
    import pandas as pd
    con = store.connect(tmp_path / "l.duckdb")
    first = pit.date_quarters(real_quarters(), first_seen=date(2026, 10, 6))
    doubled = pd.concat([first, first.iloc[[0]]], ignore_index=True)
    assert pit.save(con, doubled, "bse_results") == len(first)
