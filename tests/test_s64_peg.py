"""S64: PEG, the forward P/E (our estimate), five-year profit in words, and the multibagger study's fixed decision rule."""
import numpy as np
import pandas as pd
import pytest

from pflab.hq import plain, valuation as vl
from pflab.quant import peg_study


def test_peg_forward_pe_and_five_year_profit():
    v = vl.growth_view(px=200.0, eps=10.0, g=0.25)                  # P/E 20, growth 25%
    assert v["peg"] == 0.8
    assert v["forward_pe_our_estimate"] == pytest.approx(200 / 12.5, abs=0.05)
    assert v["next_5y_profit_pct_of_price"] == pytest.approx(sum(10 * 1.25 ** k for k in range(1, 6)) / 200 * 100, abs=0.1)
    capped = vl.growth_view(200.0, 10.0, 0.80)                       # 80% growth is carried as 30%
    assert capped["peg"] == pytest.approx(0.25) and capped["forward_pe_our_estimate"] == pytest.approx(200 / 13.0, abs=0.05)
    assert "analysts" in capped["forward_pe_basis"]


def test_no_peg_without_growth_and_nothing_without_positive_earnings():
    v = vl.growth_view(200.0, 10.0, -0.10)
    assert v["peg"] is None and v["forward_pe_our_estimate"] == 20.0         # a falling profit is not carried forward
    assert vl.growth_view(200.0, -3.0, 0.2) == {} and vl.growth_view(200.0, None, 0.2) == {}


def test_plain_words_for_peg_and_the_five_year_rule():
    lines = plain.growth_lines(vl.growth_view(200.0, 10.0, 0.25), {"label": "failed"})
    text = " ".join(lines)
    assert "PEG 0.80" in text and "tested 'PEG below 1" in text and "failed" in text and "weak power" in text
    assert "Forward P/E (our own estimate)" in text and "we hold none" in text
    assert "below that" in text                                                 # P/E 20 at 25% growth: 5 years of profit is 51% of the price
    cheap = " ".join(plain.growth_lines(vl.growth_view(50.0, 10.0, 0.25), None))       # P/E 5: 205%
    assert "clears it" in cheap and "has not been tested here" in cheap
    slow = " ".join(plain.growth_lines(vl.growth_view(400.0, 10.0, 0.05), None))
    assert "PEG 8.00" in slow and "Above 1" in slow and "below that" in slow
    nog = plain.growth_lines({"eps_growth_ttm_yoy_pct": -5.0})
    assert "PEG cannot be worked out" in nog[0]


def test_peg_frame_needs_both_years_and_no_split_between_them():
    idx = pd.bdate_range("2018-01-01", periods=600)
    cols = ["A", "B"]
    close = pd.DataFrame(100.0, index=idx, columns=cols)
    adj = close.copy()
    adj["B"] = np.where(np.arange(600) < 400, 50.0, 100.0)                  # B: a 2:1 split after session 400, adjusted back
    close["B"] = 100.0
    eps = pd.DataFrame(5.0, index=idx, columns=cols)
    eps.iloc[300:, :] = 6.0                                                 # profit up 20% from session 300 (P/E 100/6)
    w = {"close": close, "adj": adj}
    peg = peg_study.peg_frame(w, eps)
    assert peg["A"].iloc[500] == pytest.approx((100 / 6) / 20, abs=0.01)         # a year-ago EPS of 5 against 6 now: growth 20%
    assert np.isnan(peg["A"].iloc[100])                                           # no year-ago EPS yet
    assert np.isnan(peg["B"].iloc[500])                                           # adjustment factor moved: units differ


def rates(rows):
    return pd.DataFrame([{"year": y, "n_a": 20, "n_b": 100, "rate_a": a, "rate_b": b} for y, a, b in rows])


def test_decision_rule_needs_five_years_a_ratio_of_one_and_a_half_and_a_clear_interval():
    good = peg_study.decide(rates([(2010 + k, 0.10, 0.04) for k in range(7)]))
    assert good["decision"] == "pass" and good["years_a_beats_b"] == 7 and good["ratio"] == pytest.approx(2.5)
    noisy = peg_study.decide(rates([(2010, 0.30, 0.04), (2011, 0.02, 0.04), (2012, 0.02, 0.04), (2013, 0.02, 0.04),
                                    (2014, 0.02, 0.04), (2015, 0.30, 0.04), (2016, 0.30, 0.04)]))
    assert noisy["decision"] == "fail"                                          # beats B in only 3 of 7 years
    weak = peg_study.decide(rates([(2010 + k, 0.05, 0.04) for k in range(7)]))
    assert weak["decision"] == "fail" and "pooled ratio 1.25" in weak["why"]     # wins every year, but not 1.5x
    assert peg_study.decide(pd.DataFrame())["decision"] == "fail"


def test_status_reads_the_counter_row():
    import duckdb
    from pflab.learner import counter
    from pflab.pm import store
    from datetime import datetime
    con = duckdb.connect(":memory:")
    store.migrate(con)
    assert peg_study.status(con)["label"] == "not tested"
    counter.record(con, datetime(2026, 10, 27), "study", "peg_multibagger", {"x": 1}, passed=False, note="A beat B in 2 of 7 years")
    s = peg_study.status(con)
    assert s["label"] == "failed" and "2 of 7" in s["why"] and "weak power" in s["caveat"]
